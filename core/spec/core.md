# digitaltwins core: rules shared by `.prsn`, `.styl` and `.scen`

Status: **Draft 1.0**

The three formats in this repository describe three kinds of subject:

| Format | Subject | Subject record | Media type (provisional) |
|---|---|---|---|
| `.prsn` | One person, real or fictional | `person.json` | `application/vnd.prsn+zip` |
| `.styl` | One visual style | `style.json` | `application/vnd.styl+zip` |
| `.scen` | One place or set, with its props | `scene.json` | `application/vnd.scen+zip` |

They share one architecture. This document states which rules are shared, how each
format parameterises them, and the cross-format additions that let the three be used
together: index records for captions, reference sets, descriptors and held-out splits,
the `authored` provenance tier, vendor-bound generation records, and references between
files.

The keywords MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are used as in RFC 2119.

## 1. Shared rules

The normative text of the shared rules is in [`../../prsn/spec/prsn.md`](../../prsn/spec/prsn.md)
and its companion documents. A `.styl` or `.scen` applies each of them with the
substitutions in §2:

| Rule | Normative text |
|---|---|
| Container (ZIP, `mimetype` first, directory working form, unique members, compression, size) | prsn.md, [Container](../../prsn/spec/prsn.md#container) |
| Canonical JSON | prsn.md, [Canonical JSON](../../prsn/spec/prsn.md#canonical-json) |
| `manifest.json`: single index, entries sorted by path, unknown top-level keys kept | prsn.md, [`manifest.json`](../../prsn/spec/prsn.md#manifestjson) |
| Fields common to all entries | prsn.md, [Fields common to all entries](../../prsn/spec/prsn.md#fields-common-to-all-entries) |
| Extension: reverse-DNS types, ignore and keep unknown types, `critical`, `version` | prsn.md, [How it extends](../../prsn/spec/prsn.md#how-it-extends) |
| `derivation` block, `action_key`, recipes, R1 to R8 | [derivation-recipes.md](../../prsn/spec/derivation-recipes.md) |
| Provenance tiers, tier downgrade for untrusted signers | prsn.md, [Provenance tiers](../../prsn/spec/prsn.md#provenance-tiers), extended by §4 |
| Budgets, eviction order and procedure | prsn.md, [Enrichment, budgets and eviction](../../prsn/spec/prsn.md#enrichment-budgets-and-eviction) |
| Licences and their propagation | prsn.md, [Licences](../../prsn/spec/prsn.md#licences) |
| Synthetic output and acceptable use | prsn.md, [Synthetic output](../../prsn/spec/prsn.md#synthetic-output-and-acceptable-use), extended by §4 |
| Security: signing, per-entry encryption, protected templates | prsn.md, [Security](../../prsn/spec/prsn.md#security) |
| Expiry | prsn.md, [Expiry](../../prsn/spec/prsn.md#expiry) |
| Coordinate frames, units, clocks | [frames-and-units.md](../../prsn/spec/frames-and-units.md), extended by `.scen` |
| Companion capture file | [prsncap.md](../../prsn/spec/prsncap.md); `.scen` uses the same layout as `.scencap` |

A rule's text uses `.prsn` words; read them through §2. Where a format document says
otherwise, the format document wins for that format.

## 2. Parameters per format

| Parameter | `.prsn` | `.styl` | `.scen` |
|---|---|---|---|
| `manifest.format` | `"prsn"` | `"styl"` | `"scen"` |
| Subject pointer (manifest key) | `person` | `style` | `scene` |
| Subject record type | `org.prsn.person` | `org.styl.style` | `org.scen.scene` |
| Type prefix | `org.prsn.` | `org.styl.` | `org.scen.` |
| Modalities | `face`, `voice`, `body` (+ reserved) | `style` | `place`, `prop` |
| Spatial modalities (entries carry `frame`) | `face`, `head`, `body` | none | `place`, `prop` |
| State index (groups of material sharing a state) | `looks` (with `eras`) | `variants` | `states` |
| Entry field naming the state | `look` (+ `era`) | `variant` | `state` |
| Identity-level value of that field | `"*"` | `"*"` | `"*"` |
| `authored` tier allowed | only when `person.json` has `"kind": "fictional"` | always | only when `scene.json` has `"kind": "fictional-place"` |
| Capture companion | `.prsncap` | none | `.scencap` |

Each format's `version` and `spec` fields are independent. A `.styl` at `"version": 1,
"spec": "1.0"` follows this document and the `.styl` specification at those numbers.

## 3. Roles

Every modality uses the same roles, and only the ones it needs:

| Role | Holds | Evidence of the subject? |
|---|---|---|
| `samples/` | Raw material any future method can re-derive from | Yes |
| `templates/` | Model-specific comparison data (embeddings), one per model | No (derived) |
| `geometry/` | Shape that is neither a template nor a sample: meshes, splats, layouts, coefficients | No (derived) |
| `attributes/` | **New.** Structured, human-editable parameters of the subject: palettes, lighting setups, rendering rules, written bibles | Authored source, not evidence |
| `training/` | Material whose purpose is to train a generator | Yes, except `.scen` renders (§4.4) |
| `generation/` | Assets that reproduce the subject: LoRAs, embeddings, adapters, vendor references | No (generated) |

`attributes/` entries are JSON or Markdown. They carry `origin` (usually `authored` or
`imported`) and MAY carry `derivation` when a method proposed them (for example a palette
extracted from exemplars and then confirmed by the author, `origin.confirmed_by`).
Derivations MAY take attributes as inputs; attributes are never generated output.

## 4. Provenance additions

### 4.1 The `authored` tier

| Tier | Rank | What it is | Who sets it |
|---|---|---|---|
| `professional` | 4 | (unchanged) | |
| `enrolled` | 3 | (unchanged) | |
| `authored` | 3 | Material the subject's author made deliberately as canonical: a fictional character's model sheet, a style's exemplars, a fictional set's concept art. Hand-made, tool-assisted or generated, then approved | The author, through the writer's authoring path (`"set_by": "user"`) |
| `imported` | 2 | (unchanged) | |
| `observed` | 1 | (unchanged) | |

- `authored` is valid only where §2 allows it. A writer MUST refuse it elsewhere: a real
  person's or real place's evidence is captured, never authored.
- `authored` is a top tier. The tier-downgrade rule applies to it as to `enrolled` and
  `professional`: in a file that is unsigned or signed by an untrusted key, a reader treats
  `authored` entries as `imported` and keeps `origin.was: "authored"`. The rules below that
  depend on the tier (the synthetic exception, anchors, lineage) judge `origin.was` when it
  is present, so a downgraded file stays valid.
- Eviction ranks `authored` equal to `enrolled`.

### 4.2 Synthetic material in `samples/` and `training/`

The rule that generated output never enters `samples/` or `training/` stays, with one
exception: an entry whose `origin.tier` is `authored` MAY set `origin.synthetic: true`.
Such an entry MUST also carry:

- `origin.approved`: `{"by": "user", "at": <date-time>}`, the author's acceptance of this
  exact item;
- `origin.lineage`: an integer ≥ 0, the number of generation steps between this item and
  the subject's anchors. Anchors are 0; any other item is 1 + the highest `lineage` among
  the authored samples its `derivation` takes as inputs;
- `origin.anchor`: `true` on the items that define the subject (see 4.3), else absent or
  `false`;
- a `derivation` when `lineage` ≥ 1, whose inputs name the generator assets and the
  authored samples used;
- `origin.admit` unless it is an anchor (4.3).

### 4.3 Anchors and drift

A file whose subject has no physical referent (a fictional person, a style, a fictional
place) is defined by its **anchors**: `samples/` entries with `origin.anchor: true`.

- Anchors are pinned: eviction never removes them. An anchor has `lineage: 0`. A file that
  holds any `authored` material MUST hold at least one anchor.
- Every non-anchor authored synthetic entry MUST pass the modality's `admit` against the
  anchors (identity similarity for a person, style similarity for a style, place similarity
  for a scene), with the scores recorded in `origin.admit`
  (`{"metric": "...", "value": ..., "threshold": ...}`).
- Writers SHOULD refuse `lineage` above 2 by default. Each generation step away from the
  anchors compounds drift; the limit keeps a bootstrap loop (generate, curate, train,
  generate again) tied to the definition.
- `derive` and `generate` weight anchors above lineage material, the same way they prefer
  higher tiers.

### 4.4 Renders of captured geometry (`.scen` only)

A view rendered from geometry that was itself derived from captured samples is a
re-projection of evidence, not an invention. `origin.render` is valid only in a `.scen`;
validators of other formats refuse it. In a `.scen` a render MAY go into `training/`
(never `samples/`) with `origin: {"tier": "imported", "render": true, ...}` and a
`derivation` naming the geometry entry. It is never counted as evidence by `admit`,
`derive` or templates.

## 5. Index records

Depth-2 paths (`<modality>/<name>.json`) hold modality-level index records. Besides the
existing capture references and coverage records, every format MAY use four new kinds. All
four are JSON, never `critical`, and either carry a `derivation` (they are re-derivable
from the retained samples) or, for an author-written descriptor, an `origin` with
`tier: "authored"`.

| Kind | Path | Record type | Payload schema |
|---|---|---|---|
| Captions | `<modality>/captions-<convention>[-<state>].json` | `<prefix><modality>.captions` | [`captions.schema.json`](../schemas/captions.schema.json) |
| Reference set | `<modality>/refset-<target>[-<state>].json` | `<prefix><modality>.refset` | [`refset.schema.json`](../schemas/refset.schema.json) |
| Descriptor | `<modality>/descriptor[-<state>].json` | `<prefix><modality>.descriptor` | [`descriptor.schema.json`](../schemas/descriptor.schema.json) |
| Held-out split | `<modality>/holdout.json` | `<prefix><modality>.holdout` | [`holdout.schema.json`](../schemas/holdout.schema.json) |

Their method families are shared: `org.dtwin.method.captions`, `org.dtwin.method.refset`,
`org.dtwin.method.descriptor`, `org.dtwin.method.holdout`. The `org.dtwin` namespace is
provisional, like `org.prsn`.

- File names are for people. The payload's `convention`, `target` and `state` are
  authoritative; readers never parse them out of the path.
- Index records name samples by hash, so they go stale when a sample is evicted. A writer
  that evicts a sample re-derives or drops, in the same write, every index record that
  names it.
- Budget floors (a minimum per angle bin, content class or zone) only limit eviction. A
  bank smaller than its floors is valid; it just never shrinks below them.

### 5.1 Captions

Per-sample text for training a generator, in one convention:

```json
{"convention": "natural", "state": "look-2026-10a", "trigger": "mira_zx",
 "excludes": ["identity"],
 "items": [{"sha256": "…", "text": "mira_zx, three-quarter view, laughing, red jacket, night street"}]}
```

- `convention`: `natural` (sentences), `tags` (comma-separated tags), or a reverse-DNS
  name for anything else. Each convention gets its own record.
- `excludes` names what the captions deliberately leave out, so a trainer binds it to the
  trigger: `identity` (`.prsn`), `style` (`.styl`), `place` or `prop` (`.scen`). A caption MUST NOT
  describe what `excludes` names; it describes everything that should stay changeable.
- `items[].sha256` names a `samples/` or `training/` entry in the same file. Every item
  MUST resolve.
- A writer SHOULD derive captions from structured entry metadata first (pose, condition,
  expression, state fields, content class), using a vision-language model only for what
  metadata does not say, and name that model in `derivation.models`.
- Captions are disposable: a trainer's convention changes, the record is re-derived.

### 5.2 Reference sets

A ranked selection of samples for one target model that takes reference images at
generation time:

```json
{"target": {"key": "gemini-nano-banana-2.1", "slots": {"character": 4}},
 "state": "look-2026-10a",
 "items": [{"sha256": "…", "slot": "character", "rank": 1}],
 "composite": {"cache": "sha256:<action_key>", "layout": "turnaround-4x2"}}
```

- `target.key` names the model or product; `target.slots` maps the target's slot names to
  its limits (`character`, `object`, `style`, `image`, or the target's own names).
- `rank` is global across the record (1 first). A caller takes items in ascending rank,
  skipping items whose `slot` it lacks, until its slots are full. Every item's `slot` MUST
  be a key of `target.slots`.
- Every `sha256` MUST resolve to a `samples/` entry in the same file. The one exception is
  a `.scen` item marked `"render": true`, which resolves to a `training/` render.
- Selection prefers top tiers and anchors, then quality, then coverage (angle bins for
  faces, content classes for styles, viewpoints for places), per the family's recipe.
- `composite` optionally names a cache item: a single image laying several samples out
  together (a turnaround sheet) for targets with one or two slots. It is reproducible from
  the samples, so it lives in the cache, not the file.
- A reference set holds hashes only. It never copies images.

### 5.3 Descriptors

Text for targets that take no reference images, and the source of the invariant part of
every prompt:

```json
{"state": "*", "text": "…", "invariants": ["…"], "avoid": ["…"],
 "fields": {"hair_colour": "dark"}, "palette": ["#1b2a41", "#c9a227"]}
```

- `invariants` are short phrases to repeat verbatim in every prompt; `avoid` lists what
  must not drift in (anachronisms, wrong colours, off-model features).
- A derived descriptor names its vision-language model in `derivation.models`. An
  author-written one carries `origin: {"tier": "authored", ...}` instead; for a real
  person, `authored` is not available, and the descriptor is derived and confirmed
  (`origin: {"tier": "imported", "confirmed_by": "user"}` with a `derivation`).
- A descriptor never holds biometric measurements.

### 5.4 Held-out splits

A file without a capture companion (most `.styl` files, fictional `.prsn` and `.scen`
files) still needs held-out material for R4 upgrades and R5 verification:

```json
{"seed": 1234, "fraction": 0.2, "items": ["<sha256>", "…"], "method": "stratified", "strata": "content_class"}
```

- `items` are `samples/` hashes held out from everything a generator learns from or is
  conditioned on: captions items, reference-set items, training sets, `training_samples`
  and the derivation inputs of `generation/` entries. Templates and geometry used only to
  score MAY include them. (`derivation.inputs[].select.exclude_split: "holdout"` refers to
  this record when the inputs are entries rather than captures.)
- Anchors are never held out.
- Existing held-out items stay held out. A sample added later is held out when the first 8
  bytes of SHA-256(`"<seed>:<sha256>"`), read as a big-endian unsigned integer and divided
  by 2^64, are below `fraction`. `method` and `strata` describe how the initial split was
  drawn; they are informative.

## 6. Generation records shared by all formats

### 6.1 Image adapters

`<prefix>image.lora` and `<prefix>image.embedding` follow `org.prsn.image.lora` and
`org.prsn.image.embedding` (MUST: `base_model`; `trigger` is MUST in `.prsn` and `.scen`,
SHOULD in `.styl`, where adapters are often triggerless; `token` is MUST on embeddings),
plus:

- SHOULD: `training_captions`, the `sha256` of the captions record used;
- SHOULD: the safetensors header carries the Stability AI ModelSpec keys
  `modelspec.sai_model_spec`, `modelspec.architecture`, `modelspec.implementation`,
  `modelspec.title`, and where they apply `modelspec.trigger_phrase`,
  `modelspec.license` and `modelspec.date`, together with `org.dtwin.action_key` (the
  entry's `derivation.action_key`) and `org.dtwin.subject` (the subject record's `id`).
  A tool that sees only the `.safetensors` can then identify its base, trigger, licence
  and the file it came from. The manifest stays the source of truth when they disagree.

### 6.2 Adapter recipes

`<prefix>image.adapter-ref`: a JSON record telling a zero-shot adapter how to use this
file's samples (which samples, at which weights, with which adapter):

```json
{"adapter": {"key": "uso-flux1-dev", "sha256": "…", "license": "Apache-2.0"},
 "refset": "<sha256 of a refset record>", "weights": {"style": 0.8}}
```

MUST: `adapter` (`key`, `license`), `refset`. It is in `generation/` and carries
`synthetic_capable: true`.

### 6.3 Vendor references

`<prefix>image.vendor-ref`: an identifier that only a vendor's service can use (a
Midjourney style code, a Recraft `style_id`, a vendor-trained identity):

```json
{"vendor": "recraft", "kind": "style_id", "value": "…", "vendor_model": "recraft-v4",
 "portable": false, "created_from": ["<sha256>", "…"]}
```

These fields live on the manifest entry. The entry's payload is a small JSON file repeating
them, for tools that read files without the manifest; the manifest wins when they differ.
Expiry uses the entry's ordinary `expires` date.

- MUST: `vendor`, `kind`, `value`, `portable` (always `false`), `created_from` (the hashes of
  the samples sent to the vendor; each MUST resolve to a `samples/` entry of the file).
- SHOULD: `vendor_model` (the vendor model version it is bound to; Midjourney codes are
  version-bound; not `model`, which every format reserves for a model object).
- Vendor references are conveniences. A file never holds one without the samples it was
  made from, because the samples are what survive the vendor: when the vendor or its model
  version goes away, the reference is re-created elsewhere from `created_from`.
- The vendor's terms are the entry's `license`. Sending samples to a vendor is a
  remote-processing step: `vendor` MUST be listed in the subject record's
  `consent.vendors` (absent means no vendor). Validators report a missing consent under
  the rule `consent`.

## 7. References between files

A `.scen` names its cast and its style; a `.prsn` can name the styles it was rendered in.
`manifest.refs` lists other files without embedding them:

```json
"refs": [
  {"format": "prsn", "id": "urn:uuid:…", "manifest": "sha256:…", "role": "cast", "label": "Mira"},
  {"format": "styl", "id": "urn:uuid:…", "manifest": "sha256:…", "role": "style"}
]
```

- `format` and `id` (the other file's subject record `id`) are required. `manifest` (the
  other file's canonical manifest hash) pins a version; absent means any version.
- A reader MUST NOT require a referenced file to be present. A missing reference is
  reported, never fatal.
- A derivation input from another file is `{"sha256": "<entry hash>", "file": "sha256:<its
  manifest hash>", "role": "…"}`. `file` is not part of the `action_key` preimage (R1
  keeps only `capture`, `cache`, `sha256`, `role` and `select`), so the key depends only on
  the content used.
- Licence constraints of referenced entries propagate into derivations that use them
  (R6). A real person's `.prsn` referenced by a `.scen` does not license the scene's
  writer to copy that person's samples into the scene.

Schema: [`refs.schema.json`](../schemas/refs.schema.json).

### 7.1 Rights

Subject records (`person.json` for a fictional person, `style.json`, `scene.json`) and
`.styl` exemplars carry `rights` (`{"holder", "license"}`). R6 treats them like model
licences: a derivation whose inputs include an entry with rights, or whose subject record
has rights, adds `"rights:<license>"` to `license_constraints`, and so does every
derivation downstream. An exporter checks those constraints before giving the result to
anyone other than the rights holder. Rights `"unknown"` adds `"rights:unknown"`, which no
export to a third party satisfies.

## 8. Cross-format consistency checks

Consistency across target models is measured, not assumed. A derivation that produces a
generator (`generation/`) SHOULD report `eval` on the held-out split with a metric from
this list, named exactly:

| Metric | Measures | Notes |
|---|---|---|
| `arcface-cos` | Face identity, cosine to the subject's face template | Pretrained ArcFace weights are non-commercial; record the model licence |
| `csd-csls` | Style, CSD embedding with a CSLS readout | Raw CSD cosine is not calibrated; compare only within one model and readout |
| `dino-cos` | Place or object similarity | |
| `vlm-judge` | Rubric score from a named vision-language model | Name the model and rubric in `eval.extra` |

Scores are relative: a writer adopts a re-derivation only when it beats the current entry
on the same metric, model and split (R4). Thresholds in `origin.admit` are calibrated per
file against the anchors' own spread, never copied between files.

## 9. Rule ids

Validators of every format use the same rule ids where a rule is shared: `container`,
`version`, `paths`, `manifest-hash`, `signature`, `critical`, `spec-fields`,
`entry-order`, `generation`, `type-fields`, `authored` (§4), `index` (§5) and `consent`
(§6.3). Each format adds its own (the subject record's rule, state references, and for
`.scen` `people`, `props` and `location`).

## 10. Schemas

[`../schemas/`](../schemas/) holds the payload schemas for §5 to §7. Each format's own
schemas reference them by absolute `$id`; validators load the core schemas and the
format's schemas into one registry.
