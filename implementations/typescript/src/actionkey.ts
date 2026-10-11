// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//
// R1 `action_key`: "sha256:" + hex(SHA-256(canonical JSON of the preimage)).
// See spec/derivation-recipes.md, R1.

import {
  JsonValue,
  JsonObject,
  isJObject,
  isJArray,
  asString,
  objGet,
  canonicalBytes,
  compareCodePoints,
} from "./json.js";
import { sha256Hex } from "./bytes.js";

export class ActionKeyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ActionKeyError";
  }
}

const CONTENT_HASH_KEYS = ["capture", "cache", "sha256"] as const;
const KEPT_INPUT_KEYS = new Set(["capture", "cache", "sha256", "role", "select"]);

/** Build the canonical preimage bytes for a derivation block. Throws ActionKeyError when the derivation has no key. */
export function actionKeyPreimage(derivation: JsonValue): Uint8Array {
  if (!isJObject(derivation)) throw new ActionKeyError("derivation must be an object");

  const family = asString(objGet(derivation, "family"));
  if (family === undefined) throw new ActionKeyError("derivation.family is required");

  const recipe = objGet(derivation, "recipe");
  if (!isJObject(recipe)) throw new ActionKeyError("derivation.recipe is required");
  const recipeId = asString(objGet(recipe, "id"));
  const recipeVersion = asString(objGet(recipe, "version"));
  if (recipeId === undefined || recipeVersion === undefined) {
    throw new ActionKeyError("derivation.recipe.id and derivation.recipe.version are required");
  }

  const modelsRaw = objGet(derivation, "models");
  const modelHashes: string[] = [];
  if (modelsRaw !== undefined && modelsRaw !== null) {
    if (!isJArray(modelsRaw)) throw new ActionKeyError("derivation.models must be an array");
    for (const m of modelsRaw) {
      if (!isJObject(m)) throw new ActionKeyError("derivation model without sha256");
      const h = asString(objGet(m, "sha256"));
      if (h === undefined) throw new ActionKeyError("derivation model without sha256");
      modelHashes.push(h);
    }
  }
  modelHashes.sort(compareCodePoints); // UTF-8 byte order == code-point order

  const paramsRaw = objGet(derivation, "params");
  let params: JsonObject;
  if (paramsRaw === undefined || paramsRaw === null) {
    params = { ikind: "object", entries: [] };
  } else if (isJObject(paramsRaw)) {
    params = paramsRaw;
  } else {
    throw new ActionKeyError("derivation.params must be an object");
  }

  const inputsRaw = objGet(derivation, "inputs");
  const resolved: JsonObject[] = [];
  if (inputsRaw !== undefined && inputsRaw !== null) {
    if (!isJArray(inputsRaw)) throw new ActionKeyError("derivation.inputs must be an array");
    for (const input of inputsRaw) {
      if (!isJObject(input)) throw new ActionKeyError("derivation input must be an object");
      const present = CONTENT_HASH_KEYS.filter((k) => objGet(input, k) !== undefined);
      if (present.length !== 1) {
        throw new ActionKeyError("a derivation input needs exactly one content hash");
      }
      const hashValue = objGet(input, present[0]);
      if (typeof hashValue !== "string") {
        throw new ActionKeyError("a derivation input's content hash must be a string");
      }
      // Keep only capture/cache/sha256/role/select; drop look, era, entry paths, unknown keys.
      const kept: Array<[string, JsonValue]> = [];
      for (const [k, v] of input.entries) {
        if (KEPT_INPUT_KEYS.has(k)) kept.push([k, v]);
      }
      resolved.push({ ikind: "object", entries: kept });
    }
  }
  // Sort by the UTF-8 bytes of each input's canonical JSON.
  const serialized = resolved.map((r) => canonicalBytes(r));
  const order = serialized.map((_, i) => i);
  order.sort((a, b) => {
    const sa = serialized[a];
    const sb = serialized[b];
    const n = Math.min(sa.length, sb.length);
    for (let i = 0; i < n; i++) {
      if (sa[i] !== sb[i]) return sa[i] - sb[i];
    }
    return sa.length - sb.length;
  });
  const sortedInputs = order.map((i) => resolved[i]);

  const preimage: JsonObject = {
    ikind: "object",
    entries: [
      ["family", family],
      ["recipe", { ikind: "object", entries: [["id", recipeId], ["version", recipeVersion]] }],
      ["models", modelHashes],
      ["params", params],
      ["inputs", sortedInputs],
    ],
  };
  return canonicalBytes(preimage);
}

/** R1 action_key for a derivation block, or throws ActionKeyError when it has no key. */
export function actionKey(derivation: JsonValue): string {
  return "sha256:" + sha256Hex(actionKeyPreimage(derivation));
}
