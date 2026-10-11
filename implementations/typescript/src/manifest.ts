// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//
// manifest.json parsing and validation: header rules, entry paths, per-entry
// rules (spec-fields, generation, type-fields), provenance-unrelated package
// rules (critical, person, capture-ref, looks/eras, entry order), hashes and
// the Ed25519 signature block. See spec/prsn.md.
//
// Rule ids match the conformance table in spec/prsn.md: container, version,
// paths, manifest-hash, signature, critical, person, spec-fields, looks-eras,
// capture-ref, generation, type-fields, entry-order.

import {
  JsonValue,
  JsonObject,
  isJObject,
  isJArray,
  asString,
  asBool,
  asInt,
  objGet,
  parseJson,
  JsonError,
  canonicalBytes,
  jsonClone,
} from "./json.js";
import { sha256Hex } from "./bytes.js";
import { decodePublicKey, keyIdOf, edVerify } from "./ed.js";

export const MIMETYPE_CURRENT = "application/vnd.prsn+zip";
export const MIMETYPE_LEGACY = "application/vnd.museli.prsn+zip";

/** Highest manifest `version` this reader implements. */
export const SUPPORTED_VERSION = 1;

export interface Issue {
  rule: string;
  message: string;
}

/** Legacy v1 namespace (Appendix A) maps to the current one for type checks. */
export function canonicalType(t: string): string {
  return t.startsWith("org.museli.") ? "org.prsn." + t.slice("org.museli.".length) : t;
}

/** Record types a full-spec reader understands (spec/prsn.md + spec/voice.md). */
export const KNOWN_TYPES: ReadonlySet<string> = new Set([
  "org.prsn.person",
  "org.prsn.face.capture-ref",
  "org.prsn.face.sample",
  "org.prsn.face.mesh",
  "org.prsn.face.landmarks",
  "org.prsn.face.params",
  "org.prsn.face.blendshapes",
  "org.prsn.face.expression-track",
  "org.prsn.face.expression-map",
  "org.prsn.face.splat",
  "org.prsn.face.coverage",
  "org.prsn.face.expression-clip",
  "org.prsn.face.avatar",
  "org.prsn.face.template",
  "org.prsn.image.lora",
  "org.prsn.image.embedding",
  "org.prsn.image.faceid",
  "org.prsn.avatar.vrm",
  "org.prsn.body.params",
  "org.prsn.body.mesh",
  "org.prsn.voice.template",
  "org.prsn.voice.sample",
  "org.prsn.voice.sample-index",
  "org.prsn.voice.training",
  "org.prsn.voice.training-set",
  "org.prsn.voice.seed",
  "org.prsn.voice.prompt",
  "org.prsn.voice.generation",
  "org.prsn.voice.lora",
  "org.prsn.voice.rvc",
  "org.prsn.voice.piper",
]);

const ENTRY_PATH_RE = /^(?!.*(^|\/)\.\.?(\/|$))[a-z0-9._-]+(\/[a-z0-9._-]+)*$/;
const SPEC_RE = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;
const SHA256_RE = /^[0-9a-f]{64}$/;
const CONTENT_ID_RE = /^(sha256:)?[0-9a-f]{64}$/;
const MEDIA_RE = /^[a-z0-9!#$&^_.+-]+\/[a-z0-9!#$&^_.+-]+$/;
const PERSON_TYPE_RE = /^(org\.prsn|org\.museli)\.person$/;
const INDEX_TYPE_RE = /^(org\.prsn|org\.museli)\.[a-z0-9-]+\.(capture-ref|coverage)$/;
const SAMPLES_TRAINING_RE = /^[a-z0-9._-]+\/(samples|training)\//;
const DERIVED_ROLE_RE = /^[a-z0-9._-]+\/(geometry|generation|templates)\//;
const LOOK_ERA_ROLE_RE = /^[a-z0-9._-]+\/(samples|geometry|generation)\//;
const SPATIAL_FRAME_RE = /^(face|head|body)\/(geometry|generation)\//;
const GENERATION_RE = /^[a-z0-9._-]+\/generation\//;
const URN_UUID_RE = /^urn:uuid:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

export interface ParsedManifest {
  raw: JsonObject;
  spec11: boolean;
  entries: JsonObject[];
  personPath: string;
}

export interface ManifestReport {
  manifest: ParsedManifest | null;
  issues: Issue[];
  notes: string[];
}

/** Map a pre-1.1 person.json to the current shape (spec/prsn.md, person.json). */
export function mapLegacyPerson(p: JsonObject): { mapped: JsonObject; changed: boolean } {
  const out = jsonClone(p) as JsonObject;
  let changed = false;
  const get = (k: string) => objGet(out, k);
  const set = (k: string, v: JsonValue) => {
    const i = out.entries.findIndex(([ek]) => ek === k);
    if (i >= 0) out.entries[i][1] = v;
    else out.entries.push([k, v]);
  };
  const del = (k: string) => {
    const i = out.entries.findIndex(([ek]) => ek === k);
    if (i >= 0) out.entries.splice(i, 1);
  };
  if (get("display_name") === undefined && typeof get("name") === "string") {
    set("display_name", get("name") as string);
    del("name");
    changed = true;
  }
  const ids = get("ids");
  if (isJObject(ids)) {
    set(
      "ids",
      ids.entries.map(([scheme, value]) => ({
        ikind: "object",
        entries: [
          ["scheme", scheme],
          ["value", typeof value === "string" ? value : canonicalStringOf(value)],
        ] as Array<[string, JsonValue]>,
      })),
    );
    changed = true;
  }
  const links = get("links");
  if (isJObject(links)) {
    set(
      "links",
      links.entries.map(([rel, href]) => ({
        ikind: "object",
        entries: [
          ["rel", rel],
          ["href", typeof href === "string" ? href : canonicalStringOf(href)],
        ] as Array<[string, JsonValue]>,
      })),
    );
    changed = true;
  }
  return { mapped: out, changed };
}

function canonicalStringOf(v: JsonValue): string {
  return new TextDecoder().decode(canonicalBytes(v));
}

function isExpired(expires: JsonValue | undefined, today: string): boolean {
  return typeof expires === "string" && expires < today;
}

interface TypeRule {
  types: string[];
  required: string[];
  check?: (entry: JsonObject, missing: string[]) => string[];
}

const TYPE_RULES: TypeRule[] = [
  { types: ["org.prsn.face.mesh", "org.prsn.body.mesh"], required: ["topology", "coverage", "model"] },
  { types: ["org.prsn.face.landmarks"], required: ["topology"] },
  { types: ["org.prsn.face.params"], required: ["model", "kind"] },
  { types: ["org.prsn.body.params"], required: ["model", "coverage"] },
  { types: ["org.prsn.face.expression-track"], required: ["basis"] },
  { types: ["org.prsn.face.expression-map"], required: ["from", "to", "kind"] },
  { types: ["org.prsn.face.splat"], required: ["sh_degree", "kernel", "color_space", "coverage"] },
  { types: ["org.prsn.face.coverage"], required: ["look", "derivation"] },
  { types: ["org.prsn.face.avatar"], required: ["topology", "driver", "binding", "formulation", "coverage"] },
  { types: ["org.prsn.image.lora"], required: ["base_model", "trigger"] },
  { types: ["org.prsn.image.embedding"], required: ["base_model", "token"] },
  { types: ["org.prsn.image.faceid"], required: ["template"] },
  { types: ["org.prsn.avatar.vrm"], required: ["coverage"] },
  { types: ["org.prsn.face.template", "org.prsn.voice.template"], required: ["model"] },
  { types: ["org.prsn.voice.sample"], required: ["seconds", "sample_rate", "bits"] },
  { types: ["org.prsn.voice.seed"], required: ["text", "sample_rate", "bits"] },
  { types: ["org.prsn.voice.prompt"], required: ["engine"] },
  { types: ["org.prsn.voice.lora", "org.prsn.voice.rvc"], required: ["base_model"] },
];

function checkTypeRules(entry: JsonObject): string[] {
  const missing: string[] = [];
  const rawType = asString(objGet(entry, "type")) ?? "";
  const t = canonicalType(rawType);
  for (const rule of TYPE_RULES) {
    if (!rule.types.includes(t)) continue;
    for (const f of rule.required) {
      if (objGet(entry, f) === undefined) missing.push(`${t} requires ${f}`);
    }
    if (t === "org.prsn.face.mesh" || t === "org.prsn.body.mesh") {
      const model = objGet(entry, "model");
      if (isJObject(model) && objGet(model, "license") === undefined) {
        missing.push(`${t} requires model.license`);
      }
    }
    if (t === "org.prsn.face.params" || t === "org.prsn.body.params") {
      const model = objGet(entry, "model");
      if (isJObject(model) && objGet(model, "license") === undefined) {
        missing.push(`${t} requires model.license`);
      }
    }
    if (t === "org.prsn.face.splat" && asBool(objGet(entry, "critical")) === true) {
      missing.push("org.prsn.face.splat must not be critical");
    }
  }
  // Audio stored as integer FLAC from a floating-point capture records its source format.
  const captured = objGet(entry, "captured");
  if (isJObject(captured) && asBool(objGet(captured, "float")) === true) {
    if (objGet(entry, "source_format") === undefined) {
      missing.push("entry captured as float requires source_format");
    }
  }
  return missing;
}

/**
 * Full manifest/package validation, mirroring the reference validator's rule
 * mapping. `files` maps package-relative paths to bytes (manifest.json and
 * mimetype included where present). `today` is an ISO date (YYYY-MM-DD) used
 * for the expiry check.
 */
export function validateManifest(
  files: Map<string, Uint8Array>,
  today: string,
): ManifestReport {
  const issues: Issue[] = [];
  const notes: string[] = [];
  const err = (rule: string, message: string) => issues.push({ rule, message });

  const mt = files.get("mimetype");
  if (mt !== undefined) {
    const s = new TextDecoder("ascii").decode(mt);
    if (s !== MIMETYPE_CURRENT && s !== MIMETYPE_LEGACY) {
      err("container", `mimetype ${JSON.stringify(s)} is not a .prsn media type`);
    } else if (s === MIMETYPE_LEGACY) {
      notes.push("legacy v1 mimetype (accepted)");
    }
  }

  const rawManifest = files.get("manifest.json");
  if (rawManifest === undefined) {
    err("version", "no manifest.json");
    return { manifest: null, issues, notes };
  }
  let parsed: JsonValue;
  try {
    parsed = parseJson(rawManifest);
  } catch (e) {
    err("version", `manifest.json is not strict JSON: ${(e as Error).message}`);
    return { manifest: null, issues, notes };
  }
  if (!isJObject(parsed)) {
    err("version", "manifest.json is not an object");
    return { manifest: null, issues, notes };
  }
  const m = parsed;

  // --- header: format / version / spec (rule `version`) ---
  const format = objGet(m, "format");
  if (format !== "prsn") err("version", `format must be "prsn"`);
  const version = asInt(objGet(m, "version"));
  if (version === undefined || version < 1n) {
    err("version", "version must be an integer >= 1");
  } else if (version > BigInt(SUPPORTED_VERSION)) {
    err("version", `version ${version} is newer than this reader (${SUPPORTED_VERSION}): refuse and show it`);
  }
  const specRaw = objGet(m, "spec");
  let specMajor = 1;
  let specMinor = 0;
  if (specRaw !== undefined) {
    const sm = SPEC_RE.exec(asString(specRaw) ?? "");
    if (asString(specRaw) === undefined || !sm) {
      err("version", 'spec must be "<major>.<minor>"');
    } else {
      specMajor = parseInt(sm[1], 10);
      specMinor = parseInt(sm[2], 10);
    }
  }
  if (issues.some((i) => i.rule === "version")) {
    return { manifest: null, issues, notes };
  }
  const spec11 = specMajor > 1 || (specMajor === 1 && specMinor >= 1);

  const entriesRaw = objGet(m, "entries");
  const entries: JsonObject[] = isJArray(entriesRaw)
    ? entriesRaw.filter(isJObject)
    : [];

  // --- paths ---
  const seen = new Set<string>();
  for (const e of entries) {
    const p = asString(objGet(e, "path"));
    if (p === undefined || !ENTRY_PATH_RE.test(p)) {
      err("paths", `${JSON.stringify(p)}: not a valid entry path`);
      continue;
    }
    const depth = p.split("/").length;
    if (depth === 1) {
      const t = asString(objGet(e, "type")) ?? "";
      if (!PERSON_TYPE_RE.test(t)) err("paths", `${JSON.stringify(p)}: depth 1 is only for person.json`);
    } else if (depth === 2) {
      const t = asString(objGet(e, "type")) ?? "";
      if (!p.endsWith(".json") || !INDEX_TYPE_RE.test(t)) {
        err("paths", `${JSON.stringify(p)}: depth 2 is only for modality-level index records (<modality>/<name>.json)`);
      }
    }
    if (seen.has(p)) err("paths", `${p} is listed twice`);
    seen.add(p);
  }

  // --- entry order (writers sort by path in UTF-8 byte order; spec >= 1.1) ---
  const enc = new TextEncoder();
  const pathBytes = entries.map((e) => enc.encode(asString(objGet(e, "path")) ?? ""));
  const sorted = [...pathBytes].sort(Buffer.compare);
  if (!pathBytes.every((b, i) => Buffer.compare(b, sorted[i]) === 0)) {
    if (spec11) err("entry-order", "manifest entries are not sorted by path");
    else notes.push("entries not sorted by path (accepted in a pre-1.1 file; order is never relied on)");
  }

  // --- per-entry rules ---
  for (const e of entries) {
    const p = asString(objGet(e, "path")) ?? "<no path>";
    if (SAMPLES_TRAINING_RE.test(p) && objGet(e, "origin") === undefined) {
      err("spec-fields", `${p}: origin is required on samples/ and training/ entries`);
    }
    if (spec11) {
      if (DERIVED_ROLE_RE.test(p) && objGet(e, "derivation") === undefined) {
        err("spec-fields", `${p}: derivation is required (spec >= 1.1)`);
      }
      if (LOOK_ERA_ROLE_RE.test(p) && (objGet(e, "look") === undefined || objGet(e, "era") === undefined)) {
        err("spec-fields", `${p}: look and era are required (spec >= 1.1)`);
      }
      if (SPATIAL_FRAME_RE.test(p) && objGet(e, "frame") === undefined) {
        err("spec-fields", `${p}: frame is required for spatial modalities (spec >= 1.1)`);
      }
    }
    if (GENERATION_RE.test(p) && asBool(objGet(e, "synthetic_capable")) !== true) {
      err("generation", `${p}: generation/ entries carry synthetic_capable: true`);
    }
    if (SAMPLES_TRAINING_RE.test(p)) {
      const origin = objGet(e, "origin");
      if (isJObject(origin) && asBool(objGet(origin, "synthetic")) === true) {
        err("generation", `${p}: generated material in samples/ or training/`);
      }
    }
    for (const x of checkTypeRules(e)) {
      err("type-fields", `${p}: ${x}`);
    }
  }

  // --- critical / unknown types ---
  for (const e of entries) {
    const t = asString(objGet(e, "type")) ?? "";
    const ct = canonicalType(t);
    if (ct !== t) notes.push(`${asString(objGet(e, "path"))}: legacy type name ${t} read as ${ct}`);
    if (!KNOWN_TYPES.has(ct)) {
      if (asBool(objGet(e, "critical")) === true) {
        err("critical", `${asString(objGet(e, "path"))}: critical entry of unknown type ${t}: refuse the file`);
      } else {
        notes.push(`${asString(objGet(e, "path"))}: unknown type ${t}, carried through unread`);
      }
    }
    if (isExpired(objGet(e, "expires"), today)) {
      notes.push(`${asString(objGet(e, "path"))}: expired ${objGet(e, "expires")}; dropped on load, not written again`);
    }
  }

  // --- hashes ---
  const listed = new Set<string>();
  for (const e of entries) {
    const p = asString(objGet(e, "path"));
    if (p === undefined) continue;
    listed.add(p);
    const b = files.get(p);
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
  for (const p of [...files.keys()].sort()) {
    if (!listed.has(p) && p !== "mimetype" && p !== "manifest.json" && !p.startsWith("signatures/")) {
      notes.push(`${p}: not listed in the manifest; ignored, never written back`);
    }
  }
  if (objGet(m, "scopes") !== undefined) {
    notes.push("top-level `scopes` is retired: dropped on load");
  }

  // --- signature ---
  const sigBlock = objGet(m, "signature");
  if (sigBlock !== undefined && sigBlock !== null) {
    if (!isJObject(sigBlock)) {
      err("signature", "signature block must be an object");
    } else {
      const sigPath = asString(objGet(sigBlock, "path")) ?? "signatures/manifest.sig";
      const sigBytes = files.get(sigPath);
      if (sigBytes === undefined) {
        err("signature", `the manifest names ${sigPath} but the package does not carry it`);
      } else {
        let pub: Uint8Array;
        try {
          pub = decodePublicKey(asString(objGet(sigBlock, "public_key")) ?? "");
        } catch (e) {
          err("signature", `public_key is not valid base64: ${(e as Error).message}`);
          pub = new Uint8Array();
        }
        if (pub.length === 32) {
          if (keyIdOf(pub) !== (asString(objGet(sigBlock, "key_id")) ?? "")) {
            err("signature", "key_id is not the first 16 hex digits of SHA-256(public_key)");
          }
          if (asString(objGet(sigBlock, "alg")) !== "Ed25519") {
            notes.push(
              `signature algorithm ${JSON.stringify(objGet(sigBlock, "alg"))} not implemented: present but unverified`,
            );
          } else if (!edVerify(pub, canonicalBytes(m), sigBytes)) {
            err("signature", "Ed25519 signature does not verify over the canonical manifest");
          }
        }
      }
    }
  } else {
    notes.push("unsigned: integrity unproven; top tiers are not vouched for");
  }

  // --- person.json ---
  const personPath = asString(objGet(m, "person")) ?? "person.json";
  const personListed = listed.has(personPath);
  const personBytes = files.get(personPath);
  if (!personListed || personBytes === undefined) {
    err("person", `${personPath} is not a listed entry`);
  } else if (asBool(objGet(m, "redact")) === true) {
    notes.push("redact: person.json is encrypted");
  } else {
    let person: JsonValue;
    try {
      person = parseJson(personBytes);
    } catch (e) {
      err("person", `person.json is not strict JSON: ${(e as Error).message}`);
      person = null;
    }
    if (isJObject(person)) {
      let p = person;
      if (!spec11) {
        const { mapped, changed } = mapLegacyPerson(person);
        if (changed) notes.push("legacy person.json shape mapped (name -> display_name, ids/links objects -> arrays)");
        p = mapped;
      }
      const id = asString(objGet(p, "id"));
      const displayName = asString(objGet(p, "display_name"));
      if (id === undefined || !URN_UUID_RE.test(id)) err("person", "person.json needs an id (urn:uuid:…)");
      if (displayName === undefined || displayName.length === 0) {
        err("person", "person.json needs a display_name");
      }
    } else if (person !== null) {
      err("person", "person.json is not an object");
    }
  }

  // --- capture refs ---
  const refs: JsonObject[] = [];
  for (const e of entries) {
    const t = canonicalType(asString(objGet(e, "type")) ?? "");
    const p = asString(objGet(e, "path")) ?? "";
    if (t !== "org.prsn.face.capture-ref" || !files.has(p)) continue;
    let payload: JsonValue;
    try {
      payload = parseJson(files.get(p)!);
    } catch (ex) {
      err("capture-ref", `${p}: not strict JSON: ${(ex as Error).message}`);
      continue;
    }
    let list: JsonValue[] = [];
    if (isJArray(payload)) list = payload;
    else if (isJObject(payload)) {
      notes.push(`${p}: single-object capture-ref read as a one-item list`);
      list = [payload];
    } else {
      err("capture-ref", `${p}: payload must be a list`);
      continue;
    }
    for (const item of list) {
      if (!isJObject(item)) {
        err("capture-ref", `${p}: ref must be an object`);
        continue;
      }
      const h = asString(objGet(item, "manifest_sha256"));
      if (h === undefined || !CONTENT_ID_RE.test(h)) {
        err("capture-ref", `${p}: manifest_sha256 is not a SHA-256`);
      }
      refs.push(item);
    }
  }

  // --- looks and eras ---
  const looksRaw = objGet(m, "looks");
  const erasRaw = objGet(m, "eras");
  const looks = new Map<string, JsonObject>();
  const eras = new Map<string, JsonObject>();
  if (isJArray(looksRaw)) for (const l of looksRaw) if (isJObject(l)) {
    const id = asString(objGet(l, "id"));
    if (id !== undefined) looks.set(id, l);
  }
  if (isJArray(erasRaw)) for (const er of erasRaw) if (isJObject(er)) {
    const id = asString(objGet(er, "id"));
    if (id !== undefined) eras.set(id, er);
  }
  for (const [lid, lk] of looks) {
    const eraId = asString(objGet(lk, "era"));
    const owners: string[] = [];
    for (const [eid, er] of eras) {
      const erLooks = objGet(er, "looks");
      if (isJArray(erLooks) && erLooks.some((x) => x === lid)) owners.push(eid);
    }
    if (eraId === undefined || !eras.has(eraId) || owners.length !== 1 || owners[0] !== eraId) {
      err("looks-eras", `look ${lid} must belong to exactly one declared era`);
    }
  }
  const checkLookEra = (kind: string, name: string, look: JsonValue | undefined, era: JsonValue | undefined) => {
    if (typeof look === "string" && look !== "*" && !looks.has(look)) {
      err("looks-eras", `${kind} ${name}: look ${JSON.stringify(look)} is not in manifest.looks`);
    }
    if (typeof era === "string" && !eras.has(era)) {
      err("looks-eras", `${kind} ${name}: era ${JSON.stringify(era)} is not in manifest.eras`);
    }
  };
  for (const e of entries) {
    checkLookEra(
      "entry",
      asString(objGet(e, "path")) ?? "",
      objGet(e, "look"),
      objGet(e, "era"),
    );
  }
  for (const r of refs) {
    checkLookEra("capture-ref", asString(objGet(r, "file")) ?? "", objGet(r, "look"), objGet(r, "era"));
  }

  // --- structural schema checks (only when nothing else failed) ---
  if (issues.length === 0) {
    if (typeof objGet(m, "created") !== "string") err("schema", "manifest.created is required");
    if (typeof objGet(m, "person") !== "string") err("schema", "manifest.person is required");
    if (!isJArray(entriesRaw)) err("schema", "manifest.entries is required");
    for (const e of entries) {
      const p = asString(objGet(e, "path")) ?? "<no path>";
      for (const f of ["path", "type", "media", "sha256", "bytes"]) {
        if (objGet(e, f) === undefined) err("schema", `${p}: entry field ${f} is required`);
      }
      const h = asString(objGet(e, "sha256"));
      if (h !== undefined && !SHA256_RE.test(h)) err("schema", `${p}: sha256 must be 64 lowercase hex digits`);
      const nb = asInt(objGet(e, "bytes"));
      if (nb !== undefined && nb < 0n) err("schema", `${p}: bytes must be >= 0`);
      const media = asString(objGet(e, "media"));
      if (media !== undefined && !MEDIA_RE.test(media)) err("schema", `${p}: media is not a media type`);
    }
  }

  const parsedManifest: ParsedManifest = {
    raw: m,
    spec11,
    entries,
    personPath,
  };
  return { manifest: parsedManifest, issues, notes };
}
