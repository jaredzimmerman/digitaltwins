// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//
// Conformance vector runner: every v1-relevant suite under
// prsn/conformance/ (canonical JSON, SHA-256, action_key, Ed25519, manifest
// build/sign, tier downgrade, ZIP container cases, .prsn package cases).
// Suites outside v1 scope (splits, imu, frames, eviction, recipes, prsncap)
// are not run.

import { readFile } from "node:fs/promises";
import { join } from "node:path";
import {
  parseJson,
  canonicalJson,
  canonicalBytes,
  jsonEqual,
  isJObject,
  isJArray,
  asString,
  objGet,
  toPlain,
  JsonError,
  JsonValue,
  JsonObject,
} from "./json.js";
import { sha256Hex, Sha256Stream } from "./bytes.js";
import { actionKeyPreimage, actionKey, ActionKeyError } from "./actionkey.js";
import {
  keyPairFromSeed,
  edSign,
  edVerify,
  decodePublicKey,
  keyIdOf,
} from "./ed.js";
import { applyTierDowngrade } from "./tiers.js";
import { PrsnPackage } from "./package.js";

export interface SuiteResult {
  name: string;
  passed: number;
  failed: number;
  failures: string[];
}

function suite(name: string): SuiteResult {
  return { name, passed: 0, failed: 0, failures: [] };
}

function ok(s: SuiteResult, cond: boolean, label: string, detail = ""): void {
  if (cond) s.passed++;
  else {
    s.failed++;
    s.failures.push(detail ? `${label}: ${detail}` : label);
  }
}

async function readDoc(path: string): Promise<unknown> {
  return toPlain(parseJson(new Uint8Array(await readFile(path))));
}

async function readAst(path: string): Promise<JsonValue> {
  return parseJson(new Uint8Array(await readFile(path)));
}

function hexBytes(hex: string): Uint8Array {
  return new Uint8Array(Buffer.from(hex, "hex"));
}

interface Named {
  name: string;
}

// ---------------------------------------------------------------------------
// json/canonical.json
// ---------------------------------------------------------------------------

async function runJsonSuite(dir: string): Promise<SuiteResult> {
  const s = suite("json/canonical");
  const doc = (await readDoc(join(dir, "json", "canonical.json"))) as {
    valid: Array<{ name: string; input: string; expected: string; expected_sha256: string }>;
    invalid: Array<{ name: string; input?: string; input_hex?: string }>;
  };
  for (const v of doc.valid) {
    let out: string;
    try {
      out = canonicalJson(parseJson(new TextEncoder().encode(v.input)));
    } catch (e) {
      ok(s, false, `valid/${v.name}`, `rejected: ${(e as Error).message}`);
      continue;
    }
    const bytes = new TextEncoder().encode(out);
    ok(
      s,
      out === v.expected && sha256Hex(bytes) === v.expected_sha256,
      `valid/${v.name}`,
      `got ${JSON.stringify(out.slice(0, 80))}`,
    );
  }
  for (const v of doc.invalid) {
    let rejected = false;
    try {
      if (v.input_hex !== undefined) parseJson(hexBytes(v.input_hex));
      else parseJson(v.input as string);
    } catch (e) {
      rejected = e instanceof JsonError;
    }
    ok(s, rejected, `invalid/${v.name}`, "parsed without error");
  }
  return s;
}

// ---------------------------------------------------------------------------
// hash/sha256.json
// ---------------------------------------------------------------------------

async function runSha256Suite(dir: string): Promise<SuiteResult> {
  const s = suite("hash/sha256");
  const doc = (await readDoc(join(dir, "hash", "sha256.json"))) as {
    vectors: Array<{
      name: string;
      input_utf8?: string;
      generator?: { kind: string; byte?: number; mul?: number; add?: number; length: number };
      sha256: string;
    }>;
  };
  for (const v of doc.vectors) {
    let data: Uint8Array;
    if (v.input_utf8 !== undefined) {
      data = new TextEncoder().encode(v.input_utf8);
    } else {
      const g = v.generator!;
      data = new Uint8Array(g.length);
      if (g.kind === "repeat") data.fill(g.byte!);
      else for (let i = 0; i < g.length; i++) data[i] = (i * g.mul! + g.add!) & 0xff;
    }
    const oneShot = sha256Hex(data);
    // uneven streaming chunks
    const st = new Sha256Stream();
    const sizes = [1, 7, 1024, 65536, 3];
    let p = 0;
    let si = 0;
    while (p < data.length) {
      const n = Math.min(sizes[si++ % sizes.length], data.length - p);
      st.update(data.subarray(p, p + n));
      p += n;
    }
    const streamed = st.hex();
    ok(s, oneShot === v.sha256 && streamed === v.sha256, v.name, `got ${oneShot}`);
  }
  return s;
}

// ---------------------------------------------------------------------------
// hash/action_key.json
// ---------------------------------------------------------------------------

async function runActionKeySuite(dir: string): Promise<SuiteResult> {
  const s = suite("hash/action_key");
  const root = await readAst(join(dir, "hash", "action_key.json"));
  const getCases = (key: string): JsonObject[] => {
    const arr = isJObject(root) ? objGet(root, key) : undefined;
    return isJArray(arr) ? arr.filter(isJObject) : [];
  };
  for (const v of getCases("valid")) {
    const name = asString(objGet(v, "name")) ?? "?";
    const derivation = objGet(v, "derivation") as JsonValue;
    const wantPreimage = asString(objGet(v, "preimage"));
    const wantKey = asString(objGet(v, "action_key"));
    let pre: string;
    let key: string;
    try {
      pre = new TextDecoder().decode(actionKeyPreimage(derivation));
      key = actionKey(derivation);
    } catch (e) {
      ok(s, false, `valid/${name}`, `threw: ${(e as Error).message}`);
      continue;
    }
    ok(s, pre === wantPreimage && key === wantKey, `valid/${name}`, `key got ${key}`);
  }
  for (const v of getCases("invalid")) {
    const name = asString(objGet(v, "name")) ?? "?";
    const derivation = objGet(v, "derivation") as JsonValue;
    let threw = false;
    try {
      actionKey(derivation);
    } catch (e) {
      threw = e instanceof ActionKeyError;
    }
    ok(s, threw, `invalid/${name}`, "produced a key");
  }
  return s;
}

// ---------------------------------------------------------------------------
// hash/ed25519.json
// ---------------------------------------------------------------------------

async function runEd25519Suite(dir: string): Promise<SuiteResult> {
  const s = suite("hash/ed25519");
  const doc = (await readDoc(join(dir, "hash", "ed25519.json"))) as {
    vectors: Array<{
      name: string;
      seed: string;
      public_key: string;
      public_key_b64: string;
      key_id: string;
      message: string;
      signature: string;
    }>;
  };
  for (const v of doc.vectors) {
    const seed = hexBytes(v.seed);
    const pub = hexBytes(v.public_key);
    const msg = hexBytes(v.message);
    const sig = hexBytes(v.signature);
    const derived = keyPairFromSeed(seed);
    const flipped = new Uint8Array(sig);
    flipped[0] ^= 1;
    const longer = new Uint8Array(msg.length + 1);
    longer.set(msg);
    longer[msg.length] = 0x78; // "x"
    const reproduced = Buffer.from(edSign(seed, msg)).toString("hex");
    const checks: Array<[boolean, string]> = [
      [Buffer.from(derived.publicKey).toString("hex") === v.public_key, "derive public_key"],
      [derived.publicKeyB64 === v.public_key_b64, "public_key_b64"],
      [derived.keyId === v.key_id, "key_id"],
      [keyIdOf(pub) === v.key_id, "key_id recomputed"],
      [edVerify(pub, msg, sig), "verify signature"],
      [reproduced === v.signature, "reproduce signature (deterministic RFC 8032)"],
      [!edVerify(pub, msg, flipped), "reject bit-flipped signature"],
      [!edVerify(pub, longer, sig), "reject modified message"],
    ];
    const bad = checks.filter(([c]) => !c).map(([, w]) => w);
    ok(s, bad.length === 0, v.name, bad.join("; "));
  }
  return s;
}

// ---------------------------------------------------------------------------
// hash/manifest.json — rebuild the manifest from files + top_level + seed
// ---------------------------------------------------------------------------

interface ManifestVectorFile {
  path: string;
  content: string;
  type: string;
  media: string;
  extra: JsonObject;
}

async function runManifestSuite(dir: string): Promise<SuiteResult> {
  const s = suite("hash/manifest");
  const root = await readAst(join(dir, "hash", "manifest.json"));
  if (!isJObject(root)) {
    ok(s, false, "vector", "not an object");
    return s;
  }
  const seed = hexBytes(asString(objGet(root, "seed")) ?? "");
  const kp = keyPairFromSeed(seed);
  const topLevel = objGet(root, "top_level");
  const filesRaw = objGet(root, "files");
  const wantManifest = asString(objGet(root, "canonical_manifest"));
  const wantSha = asString(objGet(root, "manifest_sha256"));
  const wantSig = asString(objGet(root, "signature"));
  if (!isJObject(topLevel) || !isJArray(filesRaw) || !wantManifest || !wantSha || !wantSig) {
    ok(s, false, "vector", "malformed vector file");
    return s;
  }

  const files: ManifestVectorFile[] = filesRaw.filter(isJObject).map((f) => ({
    path: asString(objGet(f, "path")) ?? "",
    content: asString(objGet(f, "content")) ?? "",
    type: asString(objGet(f, "type")) ?? "",
    media: asString(objGet(f, "media")) ?? "",
    extra: (objGet(f, "extra") as JsonObject) ?? { ikind: "object", entries: [] },
  }));

  const entries: JsonValue[] = files
    .map((f) => {
      const bytes = new TextEncoder().encode(f.content);
      const pairs: Array<[string, JsonValue]> = [
        ["path", f.path],
        ["type", f.type],
        ["media", f.media],
        ["sha256", sha256Hex(bytes)],
        ["bytes", { ikind: "int", value: BigInt(bytes.length) }],
      ];
      for (const [k, v] of (isJObject(f.extra) ? f.extra.entries : []) as Array<[string, JsonValue]>) {
        pairs.push([k, v]);
      }
      return { path: f.path, obj: { ikind: "object", entries: pairs } as JsonValue };
    })
    .sort((a, b) => Buffer.compare(Buffer.from(a.path, "utf8"), Buffer.from(b.path, "utf8")))
    .map((e) => e.obj);

  const topPairs: Array<[string, JsonValue]> = [...topLevel.entries];
  topPairs.push(["entries", entries]);
  const sigEntries: Array<[string, JsonValue]> = [
    ["path", "signatures/manifest.sig"],
    ["alg", "Ed25519"],
    ["key_id", kp.keyId],
    ["public_key", kp.publicKeyB64],
  ];
  const sigBlockObj: JsonObject = { ikind: "object", entries: sigEntries };
  topPairs.push(["signature", sigBlockObj]);
  const manifest: JsonObject = { ikind: "object", entries: topPairs };
  const body = canonicalBytes(manifest);
  const bodyText = new TextDecoder().decode(body);
  const sigBytes = hexBytes(wantSig);

  const parsed = parseJson(body);
  const sigBlock = isJObject(parsed) ? objGet(parsed, "signature") : undefined;
  const pubB64 = sigBlock && isJObject(sigBlock) ? asString(objGet(sigBlock, "public_key")) : undefined;
  const pub = pubB64 !== undefined ? decodePublicKey(pubB64) : new Uint8Array();

  const filesOk = files.every((f) => {
    const bytes = new TextEncoder().encode(f.content);
    if (!isJObject(parsed)) return false;
    const ents = objGet(parsed, "entries");
    return (
      isJArray(ents) &&
      ents.some(
        (e) =>
          isJObject(e) &&
          objGet(e, "path") === f.path &&
          objGet(e, "sha256") === sha256Hex(bytes),
      )
    );
  });

  ok(s, bodyText === wantManifest, "canonical bytes", "manifest bytes differ");
  ok(s, sha256Hex(body) === wantSha, "manifest_sha256", `got ${sha256Hex(body)}`);
  ok(s, filesOk, "entry hashes", "entry sha256 mismatch");
  ok(s, edVerify(pub, body, sigBytes), "signature verifies", "ed25519 verify failed");
  ok(
    s,
    Buffer.from(edSign(seed, body)).toString("hex") === wantSig,
    "signature reproduces",
    "deterministic signature differs",
  );
  return s;
}

// ---------------------------------------------------------------------------
// tiers/downgrade.json
// ---------------------------------------------------------------------------

async function runTiersSuite(dir: string): Promise<SuiteResult> {
  const s = suite("tiers/downgrade");
  const root = await readAst(join(dir, "tiers", "downgrade.json"));
  const casesRaw = isJObject(root) ? objGet(root, "cases") : undefined;
  const cases = isJArray(casesRaw) ? casesRaw.filter(isJObject) : [];
  for (const c of cases) {
    const name = asString(objGet(c, "name")) ?? "?";
    const trusted = objGet(c, "trusted") === true;
    const entriesRaw = objGet(c, "entries");
    const expectedRaw = objGet(c, "expected");
    if (!isJArray(entriesRaw) || !isJArray(expectedRaw)) {
      ok(s, false, name, "case entries must be arrays");
      continue;
    }
    const objs = entriesRaw.filter(isJObject);
    const got = applyTierDowngrade(objs, trusted);
    const exp = expectedRaw.filter(isJObject);
    const equal = got.length === exp.length && got.every((g, i) => jsonEqual(g, exp[i]));
    ok(s, equal, name, `got ${canonicalJson(got)}`);
  }
  return s;
}

// ---------------------------------------------------------------------------
// container/cases.json + container/*.prsn
// ---------------------------------------------------------------------------

async function runContainerSuite(dir: string): Promise<SuiteResult> {
  const s = suite("container");
  const cases = (await readDoc(join(dir, "container", "cases.json"))) as {
    cases: Array<{ file: string; rule: string | null; outcome: "valid" | "refuse"; why: string }>;
  };
  for (const c of cases.cases) {
    const buf = new Uint8Array(await readFile(join(dir, "container", c.file)));
    let pkg: PrsnPackage | null = null;
    let openErr = "";
    try {
      pkg = PrsnPackage.fromZipBytes(buf);
    } catch (e) {
      openErr = (e as Error).message;
    }
    if (c.outcome === "valid") {
      if (!pkg) {
        ok(s, false, c.file, `open threw: ${openErr}`);
        continue;
      }
      const { issues } = pkg.validate();
      ok(s, issues.length === 0, c.file, issues.map((i) => `[${i.rule}] ${i.message}`).join("; "));
    } else {
      const onlyContainer =
        pkg !== null &&
        pkg.containerIssues.length > 0 &&
        pkg.containerIssues.every((i) => i.rule === "container");
      ok(
        s,
        onlyContainer || openErr !== "",
        `${c.file} refused by rule \`${c.rule}\``,
        openErr || `rules: ${pkg?.containerIssues.map((i) => i.rule).join(",")}`,
      );
    }
  }
  return s;
}

// ---------------------------------------------------------------------------
// prsn/rules.json + prsn/<case>/ directory fixtures
// ---------------------------------------------------------------------------

async function runPrsnSuite(dir: string, repoRoot: string): Promise<SuiteResult> {
  const s = suite("prsn");
  const rules = (await readDoc(join(dir, "prsn", "rules.json"))) as {
    valid: Array<{ id: string; path: string; spec: string | null }>;
    cases: Array<{ id: string; rule: string | null; outcome: "refuse" | "invalid" | "valid"; why: string }>;
  };
  for (const v of rules.valid) {
    const pkg = await PrsnPackage.open(join(repoRoot, v.path));
    const { issues } = pkg.validate();
    ok(s, issues.length === 0, `valid/${v.id}`, issues.map((i) => `[${i.rule}] ${i.message}`).join("; "));
  }
  for (const c of rules.cases) {
    const pkg = await PrsnPackage.open(join(dir, "prsn", c.id));
    const { issues } = pkg.validate();
    const ruleSet = new Set(issues.map((i) => i.rule));
    const detail = issues.map((i) => `[${i.rule}] ${i.message}`).join("; ");
    if (c.outcome === "valid") {
      ok(s, issues.length === 0, `${c.id}: valid`, detail);
    } else {
      // refuse: must fail and include the stated rule; invalid: must report the rule.
      ok(s, ruleSet.has(c.rule as string), `${c.id}: ${c.outcome} by rule \`${c.rule}\``, `rules: ${[...ruleSet].join(",")}; ${detail}`);
    }
  }
  return s;
}

/** Run every v1-relevant conformance suite. `conformanceDir` holds the suite dirs. */
export async function runVectors(conformanceDir: string): Promise<SuiteResult[]> {
  // prsn/rules.json "valid" entries live under the repo root (examples/prsn/…).
  const repoRoot = join(conformanceDir, "..");
  return [
    await runJsonSuite(conformanceDir),
    await runSha256Suite(conformanceDir),
    await runActionKeySuite(conformanceDir),
    await runEd25519Suite(conformanceDir),
    await runManifestSuite(conformanceDir),
    await runTiersSuite(conformanceDir),
    await runContainerSuite(conformanceDir),
    await runPrsnSuite(conformanceDir, repoRoot),
  ];
}
