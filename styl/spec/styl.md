# `.styl`: a portable style file

Status: **Draft 1.0**

A `.styl` file holds one visual style: the exemplars that define it, the structured
attributes an author wrote down about it (palette, typography, rendering rules), the
embeddings used to measure it, and the generators built from it for any number of image
models. Like `.prsn`, it keeps the raw material its generators were made from, so when a new
image model ships the style is re-derived for it instead of being rebuilt by hand.

`.styl` is a member of the digitaltwins family. Its container, manifest, canonical JSON,
extension rules, derivations, provenance tiers, budgets, licences and security are the
shared rules of [digitaltwins core](../../core/spec/core.md), with these parameters:

| Parameter | Value |
|---|---|
| `manifest.format` | `"styl"` |
| Media type (provisional) | `application/vnd.styl+zip` |
| Subject record | `style.json`, type `org.styl.style`, named by `manifest.style` |
| Type prefix | `org.styl.` |
| Modalities | `style` (reserved: `type` for typography-only files, `motion`) |
| Spatial modalities | none (no entry carries `frame`) |
| State index | `manifest.variants[]`; entry field `variant` (`"*"` for the style as a whole) |
| `authored` tier | always allowed |
| Capture companion | none |

The keywords MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are used as in RFC 2119.

## 1. Purpose and prior art

No interchange standard describes a visual style. Each image service keeps its own handle:
a Midjourney style code is bound to the model version that minted it, a Recraft `style_id`
lives only on Recraft, and a style LoRA loads only into the base model it was trained on.
What survives every one of them is the exemplar images, plus the words that describe the
style. A `.styl` keeps those as the source and records every service-specific handle as a
derived, replaceable asset.

| Standard | Covers | Use in `.styl` |
|---|---|---|
| W3C Design Tokens Community Group format (DTCG) | Colour, typography and dimension tokens as JSON | `attributes/palette.json`, `attributes/typography.json` |
| ICC colour spaces (sRGB, Display P3) | Colour meaning | `color_space` on exemplars and palettes |
| safetensors + Stability AI ModelSpec | Adapter weights and their header metadata | `generation/` LoRAs and embeddings ([core §6.1](../../core/spec/core.md#61-image-adapters)) |
| CSD (Contrastive Style Descriptors) | Style embeddings | `templates/` (model-specific, like a voice template) |
| C2PA | Content provenance | Imported exemplars that carry credentials; everything generated |
| ZIP + `mimetype` first | Container | The wrapper |

## 2. Container

```
harbor-ink.styl
├── mimetype                     application/vnd.styl+zip
├── manifest.json                every entry with its SHA-256, size, media type, record type
├── style.json                   what the style is called, who owns it (no images)
├── style/
│   ├── captions-<conv>.json     index records (core §5)
│   ├── refset-<target>.json
│   ├── descriptor.json
│   ├── holdout.json
│   ├── samples/                 exemplars: the definition of the style
│   ├── attributes/              palette, typography, rendering rules, bible
│   ├── templates/               style embeddings, one per model
│   ├── training/                curated training sets
│   └── generation/              LoRAs, embeddings, adapter and vendor references, prompts
└── signatures/
    └── manifest.sig
```

Path depths follow the core: depth 1 is `style.json` only; depth 2 is
`style/<name>.json` index records only (captions, reference sets, descriptors, held-out
splits, coverage); everything else is `style/<role>/<name>` or deeper.

## 3. `manifest.json`

```json
{
  "format": "styl", "version": 1, "spec": "1.0",
  "created": "2026-10-10T18:00:00Z", "generator": "example-writer 1.0.0",
  "style": "style.json",
  "budgets": {"style.samples": {"count": 64, "bytes": 200000000,
                                "floors": {"per_content_class_min": 3}}},
  "variants": [
    {"id": "var-day", "label": "Daylight palette", "default": true, "state": {"palette": "day"}},
    {"id": "var-night", "label": "Night palette", "state": {"palette": "night"}}
  ],
  "refs": [],
  "entries": [ … ],
  "signature": { … }
}
```

| Field | Required | Meaning |
|---|---|---|
| `format` | yes | `"styl"` |
| `version` | yes | Integer; 1 for this document |
| `spec` | no | `"1.0"` for this document |
| `created`, `generator` | `created` yes | As in `.prsn` |
| `style` | yes | Path of the `style.json` entry |
| `budgets` | no | Per `style.<role>` budgets (§7) |
| `variants` | when entries use them | Named states of the style ([`state.schema.json`](../../core/schemas/state.schema.json)) |
| `refs` | no | Other files ([core §7](../../core/spec/core.md#7-references-between-files)) |
| `entries`, `signature`, `redact` | `entries` yes | As in `.prsn` |

Every `samples/`, `attributes/`, `templates/`, `training/` and `generation/` entry
carries `variant`: a declared variant id, or `"*"` when it belongs to the style as a whole.
A variant is a controlled departure from the core style (a night palette, a monochrome
print version, a different medium); the core look is what every variant shares.

## 4. `style.json`

Contains no images:

```json
{"id": "urn:uuid:…", "display_name": "Harbor Ink", "kind": "original",
 "description": "Loose ink line with flat watercolour washes and a muted harbour palette.",
 "rights": {"holder": "Example Studio", "license": "LicenseRef-example-style"},
 "authors": ["Example Studio"], "influences": [],
 "consent": {"vendors": ["example-vendor"]},
 "aliases": [], "links": []}
```

- `id` (`urn:uuid`), `display_name` and `kind` are required.
- `kind`: `original` (made by its authors) or `derived` (assembled from imported works).
  A derived style lists its sources' rights on each exemplar (§5.1).
- `rights` names who owns the style definition. Exporters treat it like a model licence:
  it propagates into everything derived (R6).
- `consent.vendors` lists the vendors allowed to receive exemplars (for vendor references,
  core §6.3). Absent means none; a vendor reference to an unlisted vendor breaks the rule
  `consent`.

## 5. Records

In the tables, **MUST** lists the fields a reader needs; the schemas enforce them.
**SHOULD** lists fields a writer includes when it has them.

### 5.1 Exemplars (`style/samples/`)

`org.styl.style.exemplar`: one image showing the style, at native resolution (PNG, HEIC,
JPEG-XL, JPEG, WebP).

- MUST: `origin`, `content_class`, `rights`.
- SHOULD: `subject` (a short phrase naming what is depicted, never the style), `medium`
  (`ink`, `watercolour`, `oil`, `vector`, `3d-render`, `photo`, …), `color_space`,
  `quality`, `depicts_real_person` (boolean).

`content_class` is one of `person`, `animal`, `object`, `vehicle`, `architecture`,
`interior`, `landscape`, `food`, `text`, `abstract`, `other`. A style is what stays the same
when the content changes, so the bank must span content: eviction keeps a floor of
exemplars per class (§7), reference sets and training sets draw across classes, and
captions describe content only.

`rights` is `{"holder", "license"}`, or `"unknown"`. Rights propagate into
`license_constraints` as `rights:<license>` ([core §7.1](../../core/spec/core.md#71-rights)):
an exporter MUST NOT give anything derived from an exemplar with unknown rights to anyone
other than the rights holder of the file.

An exemplar that reproduces one specific protected work is evidence of that work, not of a
style: `admit` SHOULD refuse it (near-duplicate check against the rest of the bank and
against `influences`).

### 5.2 Attributes (`style/attributes/`)

The written definition of the style, editable by people:

| Type | Payload | MUST | SHOULD |
|---|---|---|---|
| `org.styl.style.palette` | DTCG JSON: colour tokens with `$type: "color"` and `$value` (hex or a colour object), grouped by role (`ink`, `paper`, `accent`, `shadow`, …) | `origin`, `color_space` | `weights` (share of image area per token, from the exemplars) |
| `org.styl.style.typography` | DTCG JSON: font family, weight, size and spacing tokens | `origin` | font licences |
| `org.styl.style.rendering` | JSON: `medium`, `line` (weight, variation, closure), `shading` (`flat`, `cel`, `soft`, …), `texture`, `lighting`, `lens` (focal length, depth of field), `composition` rules | `origin` | |
| `org.styl.style.bible` | Markdown: the author's description, do and don't, examples by hash | `origin` | |

Attributes carry `origin` (usually `authored`). A palette extracted from the exemplars by a
method carries a `derivation` and `origin.confirmed_by: "user"` once the author accepts it.

### 5.3 Templates (`style/templates/`)

`org.styl.style.template`: a style embedding of the bank (safetensors or `.npz` holding a
centroid and, optionally, per-exemplar vectors).

- MUST: `model` with `key`, `sha256`, `dim`, `license`; `readout` (`raw-cosine` or `csls`).
- SHOULD: `spread`, the distribution of anchor-to-centroid similarity
  (`{"mean", "sd", "min"}`), used to calibrate `admit` thresholds for this file.

Style embedding scores are relative. A raw CSD cosine is not a calibrated absolute score,
and the same failure has been reported for CLIP, SigLIP and DINOv2 backbones, so a writer
compares scores only within one model, one readout and one file, and sets thresholds from
`spread`, never from a constant.

### 5.4 Training (`style/training/`)

`org.styl.style.training-set`: a JSON record naming the exemplars (by hash), the captions
record and the variant a generator is trained on, and why that selection was made (content
balance, held-out exclusions). Exemplars themselves stay in `samples/`; a training set
never copies them.

### 5.5 Generation (`style/generation/`)

| Type | Payload | MUST | SHOULD |
|---|---|---|---|
| `org.styl.image.lora` | safetensors style LoRA | `base_model` (`{"key", "sha256"}`) | `trigger` (style LoRAs are often triggerless), `rank`, `strength` (recommended weight), `training_samples`, `training_captions`, ModelSpec header |
| `org.styl.image.embedding` | safetensors textual-inversion vector | `base_model`, `token` | |
| `org.styl.image.adapter-ref` | JSON: zero-shot adapter use of the exemplars | `adapter` (`key`, `license`), `refset` | `weights` |
| `org.styl.image.vendor-ref` | JSON or none: Midjourney style code, Recraft `style_id`, Krea style | `vendor`, `kind`, `value`, `portable: false`, `created_from` | `vendor_model` (Midjourney codes need their `--sv` interpreter version) |
| `org.styl.image.prompt` | JSON: an engine-specific prompt fragment (`engine`, `positive`, `negative`) built from the descriptor and attributes. Disposable | `engine` (`{"name", "version"}`) | |

Every `generation/` entry carries `synthetic_capable: true` and a `derivation`.

### 5.6 Index records (`style/<name>.json`)

As defined in [core §5](../../core/spec/core.md#5-index-records), with these `.styl`
rules:

- Captions use `"excludes": ["style"]`: each caption names the content (subject, setting,
  composition) and never the medium, palette or technique, so the trainer binds the style
  to the trigger or to the adapter itself.
- A reference set draws its items across content classes (at most one per class until
  every class present is used), so the target sees the style on varied content. Targets
  with style slots (for example a model with 3 style slots) fill those; targets that take
  only style-reference URLs take the ranks in order.
- The descriptor's `invariants` are the style's words to repeat verbatim (medium, line,
  palette names); `palette` holds the core hex colours.
- The held-out split is stratified by content class.

`org.styl.style.coverage` (`style/coverage[-<variant>].json`): which content classes and
media the bank covers, derived.

## 6. Provenance

The tiers are the core's. In a `.styl`:

- `authored`: exemplars the style's authors made, by hand or with tools, including
  generated images the author approved (core §4.2). The author's founding set is the
  anchors.
- `imported`: works added from elsewhere, with their `rights`.
- `professional` and `enrolled` are unused; `observed` is allowed (exemplars collected
  incidentally) but never generates anything alone.

Anchors define the style. Every non-anchor authored synthetic exemplar passes `admit`
against them (`csd-csls` or another style metric, threshold from the template's `spread`),
records `lineage`, and writers refuse `lineage` above 2 by default. Generated output of this
file's own generators MAY return as exemplars only through that path, never automatically.

## 7. Enrichment, budgets and eviction

The generic procedure of [`.prsn`](../../prsn/spec/prsn.md#enrichment-budgets-and-eviction)
applies, with `.styl` functions:

| Function | `.styl` |
|---|---|
| `admit(candidate)` | Style similarity to the anchors above the file's threshold; not a near-duplicate of an existing exemplar; not a reproduction of one protected work; rights recorded |
| `quality(entry)` | Resolution, compression artefacts, and agreement with the template centroid, labelled as the writer's own score |
| `condition(entry)` | The `content_class` |
| `derive(samples)` | Recompute templates, palette weights and coverage from the whole retained bank |
| `generate(samples, current)` | Retrain or re-register generators; adopt only if better on the held-out split (R4) |

Budgets: `style.samples` with `count`, `bytes` and `floors.per_content_class_min`.
Eviction compares tier first (anchors are pinned), then effective quality, and never takes
the last exemplar of a content class while the floor holds. `style.generation` MAY set
`per_base_model: 1` to keep one current adapter per base model.

## 8. Using a `.styl` with other files

- A `.prsn` and a `.styl` combine at generation time: identity from the person, look from
  the style. Neither file copies the other's samples. A `.scen` names its style in
  `manifest.refs` with `role: "style"`.
- A style is not a person. Exemplars that depict an identifiable real person SHOULD carry
  `depicts_real_person: true`; exporters and generators treat them as the person's data
  too, and SHOULD exclude them from anything shared.

## 9. Security, licences, expiry, synthetic output

As in the core: Ed25519 signing over the canonical manifest, per-entry encryption,
`expires`, licence propagation (R6, including exemplar `rights` and `style.json`
`rights`), and a C2PA content credential on everything rendered from a `generation/`
asset, naming the asset's `action_key`.

## 10. Conformance

Rule ids, as in `.prsn` where the names match:

| Rule | Meaning |
|---|---|
| `container` | ZIP: `mimetype` first, STORED, holding `application/vnd.styl+zip` |
| `version` | `format: "styl"`, integer `version` ≤ 1 |
| `paths` | path rule, the three depths, each path listed once |
| `manifest-hash` | every listed entry present with matching size and SHA-256 |
| `signature` | signature file present, `key_id` matches, Ed25519 verifies |
| `critical` | no `critical: true` entry of an unknown type |
| `subject` | `style.json` is a listed entry matching its schema |
| `spec-fields` | `origin` on `samples/`, `training/`, `attributes/`; `variant` on every role entry; `derivation` on `templates/` and `generation/`; no entry carries `frame` |
| `states` | every `variant` is `"*"` or declared |
| `authored` | core §4 rules on authored, synthetic, anchors and lineage |
| `index` | core §5 index records are valid and resolve; held-out exemplars feed no generator |
| `consent` | every vendor reference's `vendor` is in `style.json` `consent.vendors` |
| `generation` | `synthetic_capable: true` in `generation/`; no non-authored synthetic material in `samples/` or `training/` |
| `type-fields` | MUST fields per record type |
| `entry-order` | entries sorted by path |

Examples, conformance cases and the validator are described in [`../README.md`](../README.md).

## Decisions (draft 1.0)

1. **One modality.** `style/` holds the visual style; typography-only and motion styles get
   their own modalities later without a version bump.
2. **Exemplars are the source.** Vendor handles and adapters are derived and replaceable;
   a vendor reference names the exemplars it was made from, and they stay in the file
   (core §6.3).
3. **Content-class floors** replace angle bins: the bank must show the style on varied
   content, which is also the main defence against content leaking into style adapters.
4. **DTCG tokens** for palette and typography, so design tools read them without a
   converter.
5. **Relative style scores.** Thresholds come from each file's anchor spread.
