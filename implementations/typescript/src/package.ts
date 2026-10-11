// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//
// .prsn packages: opening ZIP or directory form, integrity verification,
// entry access, tier downgrade, and the builder. See spec/prsn.md.

import { readdir, readFile, stat, mkdir, writeFile } from "node:fs/promises";
import { join, relative, sep } from "node:path";
import {
  JsonValue,
  JsonObject,
  isJObject,
  asString,
  asInt,
  asBool,
  objGet,
  parseJson,
  JsonError,
  canonicalBytes,
} from "./json.js";
import { sha256Hex } from "./bytes.js";
import {
  parseZip,
  readMemberData,
  writeZip,
  ZIP_STORED,
  ZIP_DEFLATED,
  ZipError,
  ZipMember,
} from "./zip.js";
import {
  validateManifest,
  MIMETYPE_CURRENT,
  MIMETYPE_LEGACY,
  SUPPORTED_VERSION,
  Issue,
} from "./manifest.js";
import { applyTierDowngrade } from "./tiers.js";
import { generateKey, keyPairFromSeed, edSign, edVerify, decodePublicKey, keyIdOf, KeyPair } from "./ed.js";

export { generateKey, keyPairFromSeed };
export type { KeyPair };

const SIG_PATH = "signatures/manifest.sig";

export interface EntryView {
  path: string;
  type: string;
  media: string;
  sha256: string;
  bytes: number;
  raw: JsonObject;
}

export interface IntegrityReport {
  ok: boolean;
  issues: Issue[];
  notes: string[];
  /** Signature block present and structurally checked. */
  signed: boolean;
  /** key_id when signed, else null. */
  keyId: string | null;
  /** Whether the signer's key is in the trusted set. */
  trusted: boolean;
  /** Tier downgrade applied to the in-memory entry views. */
  downgradedOrigins: number;
  downgradedEvidence: number;
}

export interface OpenOptions {
  /** Trusted signers: key_ids (16 lowercase hex) or base64 public keys. Default: empty. */
  trustedKeys?: string[];
}

function hasDotSegment(p: string): boolean {
  return p.split("/").some((s) => s.startsWith("."));
}

async function readDirTree(root: string): Promise<Map<string, Uint8Array>> {
  const out = new Map<string, Uint8Array>();
  async function walk(dir: string): Promise<void> {
    for (const name of await readdir(dir)) {
      if (name.startsWith(".")) continue;
      const full = join(dir, name);
      const st = await stat(full);
      if (st.isDirectory()) {
        await walk(full);
      } else if (st.isFile()) {
        const rel = relative(root, full).split(sep).join("/");
        if (!hasDotSegment(rel)) out.set(rel, await readFile(full));
      }
    }
  }
  await walk(root);
  return out;
}

/**
 * An opened .prsn package (ZIP or directory form). `containerIssues` holds
 * container-rule violations found at open (rule `container`); the package is
 * still loaded so deeper validation can run.
 */
export class PrsnPackage {
  readonly kind: "zip" | "dir";
  readonly files: Map<string, Uint8Array>;
  readonly containerIssues: Issue[];
  readonly trustedKeys: string[];

  private constructor(
    kind: "zip" | "dir",
    files: Map<string, Uint8Array>,
    containerIssues: Issue[],
    trustedKeys: string[],
  ) {
    this.kind = kind;
    this.files = files;
    this.containerIssues = containerIssues;
    this.trustedKeys = trustedKeys;
  }

  /** Open a .prsn from a ZIP file or a directory package. */
  static async open(path: string, opts: OpenOptions = {}): Promise<PrsnPackage> {
    const trustedKeys = opts.trustedKeys ?? [];
    const st = await stat(path);
    if (st.isDirectory()) {
      return new PrsnPackage("dir", await readDirTree(path), [], trustedKeys);
    }
    const buf = new Uint8Array(await readFile(path));
    return PrsnPackage.fromZipBytes(buf, trustedKeys);
  }

  /** Open from in-memory ZIP bytes (used by tests). */
  static fromZipBytes(buf: Uint8Array, trustedKeys: string[] = []): PrsnPackage {
    const issues: Issue[] = [];
    const members = parseZip(buf);
    const names = members.map((m) => m.name);
    if (names.length === 0 || names[0] !== "mimetype") {
      issues.push({ rule: "container", message: "the first member must be `mimetype`" });
    } else {
      const first = members[0];
      if (first.method !== ZIP_STORED) {
        issues.push({ rule: "container", message: "`mimetype` must be STORED" });
      }
      if (first.localExtraLen !== 0 || first.centralExtraLen !== 0) {
        issues.push({ rule: "container", message: "`mimetype` must have no extra field" });
      }
      const mt = new TextDecoder("ascii").decode(readMemberData(buf, first));
      if (mt !== MIMETYPE_CURRENT && mt !== MIMETYPE_LEGACY) {
        issues.push({ rule: "container", message: `mimetype ${JSON.stringify(mt)} is not a .prsn media type` });
      }
    }
    if (new Set(names).size !== names.length) {
      issues.push({ rule: "container", message: "a member name appears more than once" });
    }
    // Unlisted members are ignored; last occurrence wins for duplicates (container already refused).
    const files = new Map<string, Uint8Array>();
    for (const m of members) {
      if (m.name.endsWith("/")) continue;
      files.set(m.name, readMemberData(buf, m));
    }
    return new PrsnPackage("zip", files, issues, trustedKeys);
  }

  /** Parse manifest.json strictly; null when it cannot be parsed. */
  manifestObject(): JsonObject | null {
    const raw = this.files.get("manifest.json");
    if (raw === undefined) return null;
    try {
      const v = parseJson(raw);
      return isJObject(v) ? v : null;
    } catch {
      return null;
    }
  }

  /** The signature block, when present and well-formed. */
  signatureInfo(): { keyId: string; publicKey: Uint8Array; publicKeyB64: string; alg: string; path: string } | null {
    const m = this.manifestObject();
    if (!m) return null;
    const b = objGet(m, "signature");
    if (!isJObject(b)) return null;
    const keyId = asString(objGet(b, "key_id"));
    const publicKeyB64 = asString(objGet(b, "public_key"));
    if (keyId === undefined || publicKeyB64 === undefined) return null;
    try {
      const publicKey = decodePublicKey(publicKeyB64);
      return {
        keyId,
        publicKey,
        publicKeyB64,
        alg: asString(objGet(b, "alg")) ?? "",
        path: asString(objGet(b, "path")) ?? SIG_PATH,
      };
    } catch {
      return null;
    }
  }

  /** Is the signer's key trusted (signature present, verifies, key in the trusted set)? */
  isTrustedSigner(): boolean {
    const sig = this.signatureInfo();
    if (!sig || sig.alg !== "Ed25519") return false;
    const m = this.manifestObject();
    if (!m) return false;
    const sigBytes = this.files.get(sig.path);
    if (!sigBytes || !edVerify(sig.publicKey, canonicalBytes(m), sigBytes)) return false;
    return (
      this.trustedKeys.includes(sig.keyId) ||
      this.trustedKeys.includes(sig.publicKeyB64) ||
      this.trustedKeys.includes(Buffer.from(sig.publicKey).toString("base64"))
    );
  }

  /**
   * Integrity verification: container rules, manifest header (format/version),
   * every listed entry present with matching size and SHA-256, and the
   * signature via the embedded key. The tier downgrade is applied to the
   * in-memory entry views (counts reported).
   */
  verifyIntegrity(): IntegrityReport {
    const issues: Issue[] = [...this.containerIssues];
    const notes: string[] = [];
    const err = (rule: string, message: string) => issues.push({ rule, message });

    const rawManifest = this.files.get("manifest.json");
    let m: JsonObject | null = null;
    if (rawManifest === undefined) {
      err("version", "no manifest.json");
    } else {
      try {
        const v = parseJson(rawManifest);
        if (!isJObject(v)) err("version", "manifest.json is not an object");
        else m = v;
      } catch (e) {
        err("version", `manifest.json is not strict JSON: ${(e as Error).message}`);
      }
    }

    if (m) {
      if (objGet(m, "format") !== "prsn") err("version", 'format must be "prsn"');
      const version = asInt(objGet(m, "version"));
      if (version === undefined || version < 1n) {
        err("version", "version must be an integer >= 1");
      } else if (version > BigInt(SUPPORTED_VERSION)) {
        err("version", `version ${version} is newer than this reader (${SUPPORTED_VERSION}): refuse and show it`);
      }
    }

    let signed = false;
    let keyId: string | null = null;
    if (m && !issues.some((i) => i.rule === "version")) {
      const entriesRaw = objGet(m, "entries");
      const entries: JsonObject[] = Array.isArray(entriesRaw) ? entriesRaw.filter(isJObject) : [];
      for (const e of entries) {
        const p = asString(objGet(e, "path"));
        if (p === undefined) continue;
        const b = this.files.get(p);
        if (b === undefined) {
          err("manifest-hash", `${p} is listed but not in the package`);
          continue;
        }
        const wantBytes = asInt(objGet(e, "bytes"));
        const wantHash = asString(objGet(e, "sha256"));
        if (wantBytes === undefined || BigInt(b.length) !== wantBytes || sha256Hex(b) !== (wantHash ?? "")) {
          err("manifest-hash", `${p}: size or sha256 does not match the manifest`);
        }
      }

      const sigBlock = objGet(m, "signature");
      if (sigBlock !== undefined && sigBlock !== null && isJObject(sigBlock)) {
        signed = true;
        const sigPath = asString(objGet(sigBlock, "path")) ?? SIG_PATH;
        const sigBytes = this.files.get(sigPath);
        if (sigBytes === undefined) {
          err("signature", `the manifest names ${sigPath} but the package does not carry it`);
        } else {
          const publicKeyB64 = asString(objGet(sigBlock, "public_key")) ?? "";
          let pub: Uint8Array | null = null;
          try {
            pub = decodePublicKey(publicKeyB64);
          } catch (e) {
            err("signature", `public_key is not valid base64: ${(e as Error).message}`);
          }
          if (pub) {
            keyId = keyIdOf(pub);
            if (keyId !== (asString(objGet(sigBlock, "key_id")) ?? "")) {
              err("signature", "key_id is not the first 16 hex digits of SHA-256(public_key)");
            }
            if (asString(objGet(sigBlock, "alg")) !== "Ed25519") {
              notes.push("signature algorithm not implemented: present but unverified");
            } else if (!edVerify(pub, canonicalBytes(m), sigBytes)) {
              err("signature", "Ed25519 signature does not verify over the canonical manifest");
            }
          }
        }
      } else {
        notes.push("unsigned: integrity unproven; top tiers are not vouched for");
      }
    }

    const trusted = this.isTrustedSigner();
    // Tier downgrade applied to the in-memory views (unsigned or untrusted signer).
    let downgradedOrigins = 0;
    let downgradedEvidence = 0;
    if (m) {
      const entriesRaw = objGet(m, "entries");
      const entries: JsonObject[] = Array.isArray(entriesRaw) ? entriesRaw.filter(isJObject) : [];
      if (!trusted) {
        for (const e of entries) {
          const origin = objGet(e, "origin");
          if (isJObject(origin)) {
            const t = asString(objGet(origin, "tier"));
            if (t === "enrolled" || t === "professional") downgradedOrigins++;
          }
          const ev = objGet(e, "evidence");
          if (isJObject(ev) && (objGet(ev, "enrolled") !== undefined || objGet(ev, "professional") !== undefined)) {
            downgradedEvidence++;
          }
        }
      }
    }

    return {
      ok: issues.length === 0,
      issues,
      notes,
      signed,
      keyId,
      trusted,
      downgradedOrigins,
      downgradedEvidence,
    };
  }

  /** Full rule validation (every conformance rule id). Used by the vectors runner. */
  validate(): { issues: Issue[]; notes: string[] } {
    const { issues, notes } = validateManifest(this.files, todayISO());
    return { issues: [...this.containerIssues, ...issues], notes };
  }

  /** Listed entries with expired entries dropped ("readers drop expired entries on load"). */
  listEntries(): EntryView[] {
    const m = this.manifestObject();
    if (!m) return [];
    const today = todayISO();
    const entriesRaw = objGet(m, "entries");
    if (!Array.isArray(entriesRaw)) return [];
    const out: EntryView[] = [];
    for (const e of entriesRaw) {
      if (!isJObject(e)) continue;
      const expires = objGet(e, "expires");
      if (typeof expires === "string" && expires < today) continue; // dropped on load
      const path = asString(objGet(e, "path"));
      if (path === undefined) continue;
      out.push({
        path,
        type: asString(objGet(e, "type")) ?? "",
        media: asString(objGet(e, "media")) ?? "",
        sha256: asString(objGet(e, "sha256")) ?? "",
        bytes: Number(asInt(objGet(e, "bytes")) ?? 0n),
        raw: e,
      });
    }
    return out;
  }

  /** Raw bytes of a listed, present, non-expired entry. */
  readEntryBytes(path: string): Uint8Array {
    const entry = this.listEntries().find((e) => e.path === path);
    if (!entry) throw new Error(`${path}: not a listed entry of this package`);
    const b = this.files.get(path);
    if (b === undefined) throw new Error(`${path}: listed but not in the package`);
    return b;
  }

  /** person.json with the legacy shape mapped (pre-1.1 files), or null. */
  person(): JsonValue | null {
    const m = this.manifestObject();
    if (!m) return null;
    const personPath = asString(objGet(m, "person")) ?? "person.json";
    const b = this.files.get(personPath);
    if (b === undefined) return null;
    try {
      return parseJson(b);
    } catch {
      return null;
    }
  }

  /** Manifest entries with the provenance tier downgrade applied per trust. */
  downgradedEntries(): JsonObject[] {
    const m = this.manifestObject();
    if (!m) return [];
    const entriesRaw = objGet(m, "entries");
    const entries: JsonObject[] = Array.isArray(entriesRaw) ? entriesRaw.filter(isJObject) : [];
    return applyTierDowngrade(entries, this.isTrustedSigner());
  }
}

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// builder
// ---------------------------------------------------------------------------

function zipMethodFor(media: string, path: string): typeof ZIP_STORED | typeof ZIP_DEFLATED {
  const t = media.toLowerCase();
  if (
    t.startsWith("audio/") ||
    t.startsWith("image/") ||
    t.startsWith("video/") ||
    t === "application/zip" ||
    path === SIG_PATH
  ) {
    return ZIP_STORED;
  }
  return ZIP_DEFLATED;
}

export interface AddEntryOptions {
  type: string;
  media: string;
  /** Extra entry fields (origin, …) as JSON values. */
  fields?: Record<string, JsonValue>;
}

export interface BuiltManifest {
  manifest: JsonObject;
  manifestBytes: Uint8Array;
  signature: Uint8Array | null;
}

export const INTEROP_CREATED = "2026-10-10T00:00:00Z";

/**
 * The fixed interop test package: byte-identical semantics in every
 * implementation. person.json is the canonical JSON of
 * {"id":"urn:uuid:3b1f2a4c-9d5e-4f6a-8b7c-1d2e3f4a5b6c","display_name":"Interop Test",
 *  "aliases":[],"ids":[],"links":[]}; two sample entries; signed with a fresh key.
 *
 * ZIP member order is exactly: mimetype, manifest.json, person.json,
 * face/samples/f-0001.bin, voice/samples/s-0001.bin, signatures/manifest.sig.
 * (Manifest *entry* order is UTF-8 byte order by path: face/…, person.json,
 * voice/… — the member order is the fixed interop order, not the entry order.)
 */
export function buildInteropPackage(): { zip: Uint8Array; publicKeyB64: string; keyId: string } {
  const enc = new TextEncoder();
  const person: JsonObject = {
    ikind: "object",
    entries: [
      ["id", "urn:uuid:3b1f2a4c-9d5e-4f6a-8b7c-1d2e3f4a5b6c"],
      ["display_name", "Interop Test"],
      ["aliases", []],
      ["ids", []],
      ["links", []],
    ],
  };
  const origin: JsonObject = {
    ikind: "object",
    entries: [
      ["tier", "imported"],
      ["how", "interop-fixture"],
      ["at", INTEROP_CREATED],
    ],
  };
  const faceData = enc.encode("hello prsn");
  const voiceData = enc.encode("voice sample");
  const personData = canonicalBytes(person);
  const builder = new PrsnBuilder({ generator: "prsn-ts 0.1.0", created: INTEROP_CREATED });
  builder.setPerson(person);
  builder.addEntry("face/samples/f-0001.bin", faceData, {
    type: "org.prsn.face.sample",
    media: "application/octet-stream",
    fields: { origin },
  });
  builder.addEntry("voice/samples/s-0001.bin", voiceData, {
    type: "org.prsn.voice.sample",
    media: "application/octet-stream",
    fields: { origin },
  });
  const kp = generateKey();
  const { manifestBytes, signature } = builder.buildManifest(kp.seed);
  if (!signature) throw new Error("interop package must be signed");
  const zip = writeZip([
    { name: "mimetype", data: enc.encode(MIMETYPE_CURRENT), method: ZIP_STORED },
    { name: "manifest.json", data: manifestBytes, method: ZIP_DEFLATED },
    { name: "person.json", data: personData, method: ZIP_DEFLATED },
    { name: "face/samples/f-0001.bin", data: faceData, method: ZIP_DEFLATED },
    { name: "voice/samples/s-0001.bin", data: voiceData, method: ZIP_DEFLATED },
    { name: SIG_PATH, data: signature, method: ZIP_STORED },
  ]);
  return { zip, publicKeyB64: kp.publicKeyB64, keyId: kp.keyId };
}

/** Build a new .prsn package: add entries, then write a ZIP (or directory). */
export class PrsnBuilder {
  private personDoc: JsonValue | null = null;
  private readonly entryList: Array<{ path: string; data: Uint8Array; type: string; media: string; fields: Record<string, JsonValue> }> = [];
  private readonly generator: string;
  private readonly created: string;

  constructor(opts: { generator?: string; created?: string } = {}) {
    this.generator = opts.generator ?? "prsn-ts 0.1.0";
    this.created = opts.created ?? new Date().toISOString().replace(/\.\d+Z$/, "Z");
  }

  setPerson(person: JsonValue): this {
    this.personDoc = person;
    return this;
  }

  addEntry(path: string, data: Uint8Array, opts: AddEntryOptions): this {
    this.entryList.push({ path, data, type: opts.type, media: opts.media, fields: opts.fields ?? {} });
    return this;
  }

  /** Assemble the manifest (canonical bytes); sign when a seed is given. */
  buildManifest(signSeed?: Uint8Array): BuiltManifest {
    if (!this.personDoc) throw new Error("builder: person.json not set");
    const all = [...this.entryList];
    if (!all.some((e) => e.path === "person.json")) {
      all.push({
        path: "person.json",
        data: canonicalBytes(this.personDoc),
        type: "org.prsn.person",
        media: "application/json",
        fields: {},
      });
    }
    const sorted = all.sort((a, b) =>
      Buffer.compare(Buffer.from(a.path, "utf8"), Buffer.from(b.path, "utf8")),
    );
    const entryObjs: JsonObject[] = sorted.map((e) => ({
      ikind: "object",
      entries: [
        ["path", e.path],
        ["type", e.type],
        ["media", e.media],
        ["sha256", sha256Hex(e.data)],
        ["bytes", { ikind: "int", value: BigInt(e.data.length) }],
        ...Object.entries(e.fields),
      ] as Array<[string, JsonValue]>,
    }));
    const manifest: JsonObject = {
      ikind: "object",
      entries: [
        ["format", "prsn"],
        ["version", { ikind: "int", value: 1n }],
        ["spec", "1.1"],
        ["created", this.created],
        ["generator", this.generator],
        ["person", "person.json"],
        ["entries", entryObjs],
      ],
    };
    let signature: Uint8Array | null = null;
    if (signSeed) {
      const kp = keyPairFromSeed(signSeed);
      manifest.entries.push([
        "signature",
        {
          ikind: "object",
          entries: [
            ["path", SIG_PATH],
            ["alg", "Ed25519"],
            ["key_id", kp.keyId],
            ["public_key", kp.publicKeyB64],
          ],
        },
      ]);
      const manifestBytes = canonicalBytes(manifest);
      signature = edSign(signSeed, manifestBytes);
      return { manifest, manifestBytes, signature };
    }
    return { manifest, manifestBytes: canonicalBytes(manifest), signature };
  }

  /** Write the interchange ZIP. Member order: mimetype, manifest.json, entries…, signature. */
  buildZip(signSeed?: Uint8Array): Uint8Array {
    const { manifestBytes, signature } = this.buildManifest(signSeed);
    const personEntry = !this.entryList.some((e) => e.path === "person.json")
      ? [
          {
            path: "person.json",
            data: canonicalBytes(this.personDoc!),
            type: "org.prsn.person",
            media: "application/json",
          },
        ]
      : [];
    const sorted = [...this.entryList, ...personEntry].sort((a, b) =>
      Buffer.compare(Buffer.from(a.path, "utf8"), Buffer.from(b.path, "utf8")),
    );
    const members: Array<{ name: string; data: Uint8Array; method: typeof ZIP_STORED | typeof ZIP_DEFLATED }> = [
      { name: "mimetype", data: new TextEncoder().encode(MIMETYPE_CURRENT), method: ZIP_STORED },
      { name: "manifest.json", data: manifestBytes, method: ZIP_DEFLATED },
    ];
    for (const e of sorted) {
      members.push({ name: e.path, data: e.data, method: zipMethodFor(e.media, e.path) });
    }
    if (signature) members.push({ name: SIG_PATH, data: signature, method: ZIP_STORED });
    return writeZip(members);
  }

  /** Write a directory package (same tree, same manifest bytes). */
  async writeDir(dir: string, signSeed?: Uint8Array): Promise<void> {
    const { manifestBytes, signature } = this.buildManifest(signSeed);
    await mkdir(dir, { recursive: true });
    await writeFile(join(dir, "mimetype"), MIMETYPE_CURRENT, "ascii");
    await writeFile(join(dir, "manifest.json"), manifestBytes);
    for (const e of this.entryList) {
      const full = join(dir, e.path);
      await mkdir(join(dir, e.path.split("/").slice(0, -1).join("/")), { recursive: true });
      await writeFile(full, e.data);
    }
    if (!this.entryList.some((e) => e.path === "person.json")) {
      await writeFile(join(dir, "person.json"), canonicalBytes(this.personDoc!));
    }
    if (signature) {
      await mkdir(join(dir, "signatures"), { recursive: true });
      await writeFile(join(dir, SIG_PATH), signature);
    }
  }
}
