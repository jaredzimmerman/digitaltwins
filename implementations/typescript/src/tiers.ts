// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//
// Provenance tier downgrade: for a file that is unsigned or signed by a key
// the reader does not trust, `enrolled` and `professional` origins become
// `imported` (the claimed tier is kept as `origin.was`), and a template's
// `evidence` seconds for those tiers move to `imported` (sum, rounded to 0.1).
// See spec/prsn.md, "Provenance tiers".

import { JsonValue, JsonObject, isJObject, isJFloat, isJInt, objGet, jsonClone } from "./json.js";

const TOP_TIERS = new Set(["enrolled", "professional"]);

/** Round to 0.1 with half-to-even, matching the reference implementation. */
function round1(x: number): number {
  const n = x * 10;
  const floor = Math.floor(n);
  const frac = n - floor;
  let r: number;
  if (frac < 0.5) r = floor;
  else if (frac > 0.5) r = floor + 1;
  else r = floor % 2 === 0 ? floor : floor + 1; // half to even
  // Guard against float error extremely close to the tie (e.g. 44.199999999999996).
  if (Math.abs(frac - 0.5) < 1e-9) r = floor % 2 === 0 ? floor : floor + 1;
  return r / 10;
}

/**
 * Apply the tier downgrade to manifest entry objects (in the JsonObject AST
 * form). Returns new objects; the input is not modified. When `trusted` is
 * true the entries are returned unchanged.
 */
export function applyTierDowngrade(entries: JsonObject[], trusted: boolean): JsonObject[] {
  if (trusted) return entries;
  return entries.map((entry) => {
    const out = jsonClone(entry) as JsonObject;
    const origin = objGet(out, "origin");
    if (isJObject(origin)) {
      const tier = objGet(origin, "tier");
      if (typeof tier === "string" && TOP_TIERS.has(tier)) {
        const idx = origin.entries.findIndex(([k]) => k === "tier");
        origin.entries[idx][1] = "imported"; // `tier` keeps its position
        origin.entries.push(["was", tier]); // `was` is appended
      }
    }
    const evidence = objGet(out, "evidence");
    if (isJObject(evidence)) {
      const topKeys = evidence.entries.filter(
        ([k]) => TOP_TIERS.has(k),
      );
      if (topKeys.length > 0) {
        let moved = 0;
        const keep: Array<[string, JsonValue]> = [];
        for (const [k, v] of evidence.entries) {
          if (TOP_TIERS.has(k)) {
            if (isJFloat(v)) moved += v.value;
            else if (isJInt(v)) moved += Number(v.value);
            // non-numeric evidence values: dropped with the tier, like the reference
          } else {
            keep.push([k, v]);
          }
        }
        evidence.entries.length = 0;
        evidence.entries.push(...keep);
        const importedEntry = keep.find(([k]) => k === "imported");
        const importedVal = importedEntry?.[1];
        const base = isJFloat(importedVal) ? importedVal.value : isJInt(importedVal) ? Number(importedVal.value) : 0;
        const idx = evidence.entries.findIndex(([k]) => k === "imported");
        const nv: JsonValue = { ikind: "float", value: round1(base + moved) };
        if (idx >= 0) evidence.entries[idx][1] = nv;
        else evidence.entries.push(["imported", nv]);
      }
    }
    return out;
  });
}
