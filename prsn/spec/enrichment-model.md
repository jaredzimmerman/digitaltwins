# Enrichment data model: sessions, looks, eras, coverage, budgets

Status: **Draft v1.1**. Part of the [`.prsn` specification](prsn.md), which states the
enrichment rules; this document gives the data model behind them. Rescans enrich; they
never replace.

## 1. Objects

| Object | Identity | Lives in | Meaning |
|---|---|---|---|
| **Person** | `person.id` (`urn:uuid`) | `person.json` | One `.prsn` |
| **Session / capture** | `.prsncap` manifest SHA-256 | `org.prsn.face.capture-ref` list | One recording |
| **Look** | `look-<id>` | `manifest.looks[]` | A named group of sessions sharing a state (hair, glasses, facial hair, makeup, clothing). Each session belongs to exactly one look |
| **Era** | `era-<id>` | `manifest.eras[]` | A period within which identity pools. Each look belongs to exactly one era |
| **Coverage record** | cache item (`family: coverage`) per look | cache; summary copied into the `.prsn` as `org.prsn.face.coverage` at `face/coverage-<look>.json` (non-critical) | What has been seen |

Manifest additions ([`look.schema.json`](../schemas/look.schema.json),
[`era.schema.json`](../schemas/era.schema.json)):

```json
"looks": [
  {"id": "look-2026-10a", "label": "Oct 2026, short hair", "era": "era-1", "default": true,
   "sessions": ["sha256:…", "sha256:…"],
   "state": {"hair_length": "short", "hair_colour": "dark", "facial_hair": "none", "glasses": false, "makeup": false, "clothing": "navy patterned shirt"},
   "created": "2026-10-02T…Z"}
],
"eras": [
  {"id": "era-1", "label": "2026", "looks": ["look-2026-10a"], "identity_ref": "face/geometry/gnm-head.identity.era-1.npz", "started": "2026-10-02", "ended": null, "linked_from": null}
]
```

Entry fields: every `samples/`, `geometry/` and `generation/` entry carries `look` (a look
id, or `"*"` for identity-level entries) and `era`. Identity-level entries (head-model
identity, expression maps, per-person expression mappings) say `look: "*"`. A look's
`era` names the era whose `looks` list contains it.

## 2. What pools and what is per look

| Pools across every session in the era (identity) | Per look (state) |
|---|---|
| Head-model identity parameters (GNM; FLAME/ICT secondary fits) | Hair, facial hair, glasses, makeup, clothing |
| Expression model: per-person expression mapping, avatar expression basis | Appearance layer of splat and avatar (hair, clothing, shoulders) |
| Teeth, eyes, ears geometry | Stills bank (`samples/`) |
| Voice | Lighting (per session, never pooled) |

Which captures each asset family may select:

| Asset family | Captures | Regions / streams |
|---|---|---|
| `head-fit` identity | every session in the era, weighted by quality | all tracking + depth + stills |
| `expression-map`, `expression-track` | every session with an `expr`/`speech` phase | face tracking |
| `static-splat` | face/skin from all sessions in the era; hair, clothing, shoulders from the look's sessions only; weights by quality × recency | orbit, face, neck, hair-up, raised |
| `avatar` | identity + expression from the era; per-look appearance layer | all |
| `stills-bank` / `lora-export` | the look's sessions; optional identity-only face crops from other looks, captioned as such | stills + sharp video frames |
| `probe-hdr`, `colour-ccm` | per session, never pooled | probe, chart |

Recency weight: `w = q · 0.5^(age_days / 180)` for appearance; identity uses `w = q`.

## 3. Head-centred alignment

Every session gets a rigid `T_headcanon_from_sessionworld` from its head-model fit against
the era's identity ([frames-and-units.md](frames-and-units.md)). All multi-session assets
are built in `head-canonical`. A session whose alignment residual exceeds 3 mm RMS on the
face region is flagged and excluded from pooled assets until refit.

## 4. Admit gate (per session, before anything changes)

A new capture is admitted to a person only if all pass; otherwise nothing changes and the
writer says which check failed:

1. **Same person:** head-model identity distance (Mahalanobis in the identity space, fit
   on the new session alone) to the era identity ≤ `τ_id`, **and** face-embedding cosine
   similarity between the new session's frontal stills and the era's reference crops ≥
   `τ_face`. Embeddings are computed on the fly and **not stored** (no face template is
   written; [prsn.md, Templates](prsn.md#templates-facetemplates)).
2. **Liveness:** depth present on the face with a plausible nose-to-cheek relief (not a
   flat image) in ≥ 90 % of face-phase frames.
3. **Tracking quality:** ≥ 80 % of face-tracking frames tracked, ≥ 70 % of orbit frames
   with a pose.
4. **Provenance:** `origin.tier` is `enrolled` for the application's own capture path;
   imported captures are admitted at `imported`.

The thresholds `τ_id` and `τ_face` are params of the `admit` recipe and recorded in its
derivation.

## 5. Look and era assignment

- After admission the writer proposes a look: it compares hair, facial-hair and glasses
  masks and colour statistics against each existing look in the current era and asks
  "same look as *<label>*?", defaulting to the best match if its distance is under the
  recipe threshold, otherwise "new look". The user confirms; the answer is recorded in
  `looks[].sessions`.
- An **era** boundary is proposed when the identity fit of the new session, pooled with the
  era, worsens the per-session identity residual on earlier sessions by more than `τ_era`
  (ageing, large weight change). The user confirms; the new era links to the old
  (`linked_from`) and identity stops pooling across the boundary.
- **Default look** = most recent, unless the user pins one (`default: true`). Exports
  choose a look.

## 6. Coverage record (`family: coverage`, per look)

Schema: [`coverage.schema.json`](../schemas/coverage.schema.json).

```json
{"look": "look-2026-10a", "regions": {
   "face": {"bins": {"yaw:12|pitch:6": {"views": 143, "sharp": 0.91, "best_px_per_mm": 6.2}}, "fraction": 0.98},
   "scalp-top": {…}, "scalp-back": {…}, "ears": {…}, "neck-front": {…}, "neck-back": {…}, "chin-under": {…}, "shoulders": {…}},
 "expressions": {"jawOpen": {"peak": 0.93, "frames": 88}, "cheekPuff": {"peak": 0.21, "frames": 12}, …},
 "phonemes": {"AA": 41, "TH": 0, …},
 "lighting": {"sessions": 2, "distinct_environments": 1},
 "gaps": [{"kind": "region", "region": "scalp-top", "severity": 0.8, "suggest": "raised"},
          {"kind": "expression", "names": ["cheekPuff", "tongueOut"], "suggest": "expression-topup"}]}
```

Regions are vertex sets on the head-model template. Bins are the 15° yaw × 15° pitch bins
of [frames-and-units.md](frames-and-units.md) §3, keyed `yaw:<id>|pitch:<id>`. A gap's
`suggest` names a capture script kind or phase ([prsncap.md](prsncap.md) §7) that would
fill it.

## 7. Budgets and eviction (stills bank `samples/`)

`budgets["face.samples"]` is per look
([`budgets.schema.json`](../schemas/budgets.schema.json)):

```json
"budgets": {"face.samples": {"per_look": {"count": 48, "bytes": 160000000},
            "floors": {"per_angle_bin_min": 2, "per_expression_class_min": 3},
            "angle_bins": "yaw15", "expression_classes": ["neutral", "smile-closed", "smile-open", "laugh", "speaking", "serious", "surprised"]}}
```

Eviction is the generic [eviction procedure](prsn.md#eviction-procedure) run separately for
each look, counting entries: the cap is `per_look.count` and `per_look.bytes`; each still
belongs to an angle bin (from its `pose`) and an expression class, with floors
`per_angle_bin_min` and `per_expression_class_min`; the sources of the current
`generation/` assets of that look are pinned. A new session can't remove the only good
left-profile shot of an older look. Vectors with `role: "face.samples"`:
[`conformance/eviction/vectors.json`](../conformance/eviction/vectors.json).

## 8. Adopt only if better, across sessions

A re-derived asset for a look is scored on the **union of every input session's
`splits.json` holdout**. It is adopted only if the total improves by the family's
`min_improvement` and no session's score drops by more than `no_regression_per_capture`
([derivation-recipes.md](derivation-recipes.md) §3). The previous asset stays in the
`supersedes` chain.

## 9. Non-destructive rules

Captures are never deleted or demoted automatically. Every asset version is restorable
through `supersedes`. Guided `enrolled` sessions outrank imports. Recency is a weight,
never a replacement.
