// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//
// prsn-ts: a reader/writer library for the .prsn digital-twin file format (v1).
// See README.md for scope and the spec in prsn/spec/prsn.md.

export {
  parseJson,
  canonicalJson,
  canonicalBytes,
  compareCodePoints,
  jsonEqual,
  jsonClone,
  objGet,
  asString,
  asBool,
  asInt,
  asFloat,
  isJInt,
  isJFloat,
  isJObject,
  isJArray,
  jInt,
  jFloat,
  jStr,
  jArr,
  jObj,
  JsonError,
} from "./json.js";
export type { JsonValue, JsonInt, JsonFloat, JsonObject } from "./json.js";

export { sha256Hex, sha256Bytes, Sha256Stream } from "./bytes.js";

export { generateKey, keyPairFromSeed, keyIdOf, edSign, edVerify, decodePublicKey } from "./ed.js";
export type { KeyPair } from "./ed.js";

export { actionKey, actionKeyPreimage, ActionKeyError } from "./actionkey.js";

export { applyTierDowngrade } from "./tiers.js";

export {
  PrsnPackage,
  PrsnBuilder,
  todayISO,
  buildInteropPackage,
  INTEROP_CREATED,
} from "./package.js";
export type { EntryView, IntegrityReport, OpenOptions, AddEntryOptions, BuiltManifest } from "./package.js";
export {
  validateManifest,
  mapLegacyPerson,
  canonicalType,
  KNOWN_TYPES,
  MIMETYPE_CURRENT,
  MIMETYPE_LEGACY,
  SUPPORTED_VERSION,
} from "./manifest.js";
export type { Issue, ParsedManifest, ManifestReport } from "./manifest.js";

export { runVectors } from "./vectors.js";
export type { SuiteResult } from "./vectors.js";

