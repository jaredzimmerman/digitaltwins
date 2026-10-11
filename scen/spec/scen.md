# `.scen`: a portable scene file

Status: **Draft 1.0**

A `.scen` file holds one place: a room, a street, a set, a landscape, real or fictional,
together with the props that belong to it. It keeps the photographs and captures the place
was recorded from, the geometry rebuilt from them, the lighting and dressing states it
appears in, and the generators built from it for any number of image models. Cast members
and the visual style are not copied in; they are referenced (`.prsn` and `.styl` files).

`.scen` is a member of the digitaltwins family. Its container, manifest, canonical JSON,
extension rules, derivations, provenance tiers, budgets, licences and security are the
shared rules of [digitaltwins core](../../core/spec/core.md), with these parameters:

| Parameter | Value |
|---|---|
| `manifest.format` | `"scen"` |
| Media type (provisional) | `application/vnd.scen+zip` |
| Subject record | `scene.json`, type `org.scen.scene`, named by `manifest.scene` |
| Type prefix | `org.scen.` |
| Modalities | `place` (the environment), `prop` (movable or signature objects) |
| Spatial modalities | `place`, `prop` (their `geometry/` and `generation/` entries carry `frame`) |
| State index | `manifest.states[]`; entry field `state` (`"*"` for state-independent entries) |
| `authored` tier | only when `scene.json` has `"kind": "fictional-place"` |
| Capture companion | `.scencap` (§9) |

The keywords MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are used as in RFC 2119.

## 1. Purpose and prior art

Keeping a location consistent across shots is the weakest part of current image
generation: training-free story methods hold characters better than sets, and every
storyboard tool keeps its locations in its own database. The robust anchors are the
photographs of the place and, where available, its geometry: a Gaussian splat or mesh
from which any camera angle can be rendered and then restyled. A `.scen` keeps both, plus
the states (time of day, weather, dressing) a location appears in.

| Standard | Covers | Use in `.scen` |
|---|---|---|
| ISO/IEC 12113 (glTF 2.0) | Meshes, scenes, cameras | Place and prop meshes; splats via `KHR_gaussian_splatting`; camera rigs |
| W3C DTCG | Colour tokens | `attributes/palette.json` |
| OpenEXR | HDR images | Light probes |
| safetensors + ModelSpec | Adapters | `generation/` ([core §6.1](../../core/spec/core.md#61-image-adapters)) |
| C2PA | Provenance | Imported photographs that carry credentials; everything generated |
| ZIP + `mimetype` first | Container | The wrapper |

## 2. Container

```
north-pier-kitchen.scen
├── mimetype                       application/vnd.scen+zip
├── manifest.json
├── scene.json                     name, kind, coarse location, rights (no images)
├── place/
│   ├── capture-refs.json          the .scencap sessions it was built from
│   ├── coverage-<state>.json      viewpoints and zones seen, per state
│   ├── captions-<conv>.json  refset-<target>.json  descriptor.json  holdout.json
│   ├── samples/                   photographs of the place
│   ├── geometry/                  splat, mesh, layout, camera rigs
│   ├── attributes/                lighting per state, palette, bible
│   ├── templates/                 place embeddings
│   ├── training/                  curated sets and renders of captured geometry
│   └── generation/                LoRAs, adapter and vendor references
├── prop/
│   ├── samples/  geometry/  attributes/  generation/   (each entry names its `prop`)
└── signatures/
    └── manifest.sig
```

Path depths follow the core: depth 1 is `scene.json` only; depth 2 is
`<modality>/<name>.json` index records only; everything else is `<modality>/<role>/<name>`
or deeper. Prop entries put the prop id first in the file name
(`prop/samples/kettle-0001.heic`) and carry a `prop` field.

## 3. `manifest.json`

```json
{
  "format": "scen", "version": 1, "spec": "1.0",
  "created": "2026-10-10T18:00:00Z", "generator": "example-writer 1.0.0",
  "scene": "scene.json",
  "states": [
    {"id": "st-morning", "label": "Morning, clear", "default": true,
     "state": {"time_of_day": "morning", "weather": "clear", "season": "autumn", "dressing": "breakfast"}},
    {"id": "st-night", "label": "Night, rain", "state": {"time_of_day": "night", "weather": "rain"}}
  ],
  "props": [{"id": "kettle", "label": "Copper kettle", "fixed": false}],
  "refs": [
    {"format": "prsn", "id": "urn:uuid:…", "role": "cast", "label": "Mira"},
    {"format": "styl", "id": "urn:uuid:…", "role": "style"}
  ],
  "budgets": {"place.samples": {"per_state": {"count": 80, "bytes": 400000000},
                                "floors": {"per_zone_min": 2, "per_viewpoint_bin_min": 1}}},
  "entries": [ … ], "signature": { … }
}
```

| Field | Required | Meaning |
|---|---|---|
| `format`, `version`, `spec`, `created`, `generator` | as in the core | `format` is `"scen"` |
| `scene` | yes | Path of the `scene.json` entry |
| `states` | when entries use them | Named states ([`state.schema.json`](../../core/schemas/state.schema.json)); `state` keys SHOULD use `time_of_day`, `weather`, `season`, `dressing` |
| `props` | when `prop/` entries exist | `{"id", "label", "fixed"}`; `fixed: true` means the prop never moves (it is part of the layout) |
| `refs` | no | Cast (`role: "cast"`), style (`role: "style"`) and related scenes ([core §7](../../core/spec/core.md#7-references-between-files)) |
| `budgets` | no | §8 |
| `entries`, `signature`, `redact` | `entries` yes | As in the core |

Every `samples/`, `geometry/`, `attributes/`, `templates/`, `generation/` and `training/`
entry carries `state`: a declared state id, or `"*"` for what does not depend on state (geometry of the
architecture, the layout, the place template). Prop entries also carry `prop`, a declared
prop id.

What pools across states and what is per state:

| Pools across every state (identity of the place) | Per state |
|---|---|
| Architecture geometry, layout, fixed props | Lighting, weather, dressing (movable props, table settings) |
| Place template | Samples, light probes, the appearance layer of a splat |
| Palette core | Palette accents |

## 4. `scene.json`

```json
{"id": "urn:uuid:…", "display_name": "North Pier kitchen", "kind": "real-place",
 "description": "A narrow galley kitchen with a window over the sink.",
 "location": {"precision": "city", "label": "San Francisco"},
 "rights": {"holder": "Example Owner", "license": "LicenseRef-example-location"},
 "consent": {"vendors": [], "exact_location": false},
 "aliases": [], "links": []}
```

- `id`, `display_name` and `kind` are required. `kind` is `real-place` or
  `fictional-place`.
- `location.precision` is `none`, `region`, `city` or `exact`. Coordinates (`lat`, `lon`)
  are allowed only with `exact`, and `exact` only when `consent.exact_location` is `true`.
  The default is `city`. A file describing a private home MUST NOT carry exact
  coordinates without that consent.
- `rights` names who controls the place's likeness (a property owner, a production) or the
  fictional set's design. It propagates (R6).
- `consent.vendors` lists vendors allowed to receive samples.

## 5. Frames and units

[frames-and-units.md](../../prsn/spec/frames-and-units.md) applies, with two frames
added:

- **`scene-canonical`**: metres, right-handed, +Y up, as glTF. The origin and the
  horizontal axes are fixed by the layout's `anchor` (a named point, for example a floor
  corner or a fixed fixture), so re-registered captures land in the same frame. Every
  `place` geometry and generation entry uses it.
- **`prop-canonical`**: per prop, metres, +Y up, origin at the prop's base centre. A prop's
  placement in the scene is `T_scene_from_prop` in the layout (per state, for movable props).

Camera poses are `T_scene_from_camera` with the camera-axis convention of
frames-and-units.md (the OpenCV convention for capture data; conversions to the glTF camera
convention are given there).

## 6. Records

**MUST** fields are schema-enforced; **SHOULD** fields are recommended.

### 6.1 Samples

| Type | Payload | MUST | SHOULD |
|---|---|---|---|
| `org.scen.place.sample` | A photograph or a still cut from a capture: HEIC, PNG, JPEG-XL, JPEG, or EXR for HDR | `origin`, `people` (`none`, `masked`, `removed`, or in a fictional place `fictional`) | `camera` (`T_scene_from_camera`, intrinsics or field of view, device), `viewpoint` (a camera rig id from `cameras`), `zone` (a layout zone id), `condition`, `quality` |
| `org.scen.prop.sample` | A photograph of one prop | `origin`, `prop` | `camera` (`T_prop_from_camera`), `quality` |

A scene file must not become a file about the people who happened to be in the place.
Every place sample MUST say whether people appear in it. In a real place, identifiable
people MUST be masked or removed before the sample is admitted (`people: "masked"` or
`"removed"`), and the sample then carries a `derivation` naming the masking method. In a
fictional place, invented figures in concept art are `people: "fictional"`. Cast belong in their own
`.prsn` files, referenced from `manifest.refs`.

### 6.2 Geometry

| Type | Payload | MUST | SHOULD |
|---|---|---|---|
| `org.scen.place.splat` | 3D Gaussian splat, canonical glTF 2.0 `.glb` with `KHR_gaussian_splatting`, float32 attributes, `kernel: "ellipse"`, metres, `scene-canonical`. Display copy `.spz` (derived, disposable) | `sh_degree`, `kernel`, `color_space`, `zones` (the layout zones it covers) | `gaussian_count`, `antialiased` |
| `org.scen.place.mesh` | glTF 2.0 `.glb`, metres, +Y up | `zones` | `collider` (a separate simplified mesh), texture colour space |
| `org.scen.place.layout` | JSON: `anchor`, `zones` (id, label, polygon on the floor plane), fixed fixtures and props with `T_scene_from_prop`, doors and windows, and signage text that must render exactly | | units (`m`), floor height |
| `org.scen.place.cameras` | JSON: named camera rigs: id, label, `T_scene_from_camera`, field of view or focal length and sensor, aspect | | which zone each looks at |
| `org.scen.prop.mesh` / `org.scen.prop.splat` | As the place types, in `prop-canonical` | `prop` (and the splat's MUST fields; a splat is never `critical`) | |

Geometry is derived from samples or captures and carries a `derivation`. A fictional
place's geometry MAY be authored (modelled by hand); it then carries `origin.tier:
"authored"` in place of a derivation. It is authored source, like attributes: `admit` MAY
register candidates against it, but anchors are always samples (core §4.3).

`frame` is `scene-canonical` on every `place` geometry and generation entry and
`prop-canonical` on every `prop` one. Zones named by samples and geometry, and viewpoints
named by samples, MUST exist in the layout and camera rigs when the file holds them.

### 6.3 Attributes

| Type | Payload | MUST | SHOULD |
|---|---|---|---|
| `org.scen.place.lighting` | JSON per state: key light direction in `scene-canonical`, colour temperature, intensity ratios, practical lights, window light; optional light probe (an EXR entry) by hash | `origin`, `state` (not `"*"`) | `probe` |
| `org.scen.place.palette` | DTCG colour tokens | `origin`, `color_space` | `weights` |
| `org.scen.place.bible` | Markdown: what never changes (fixtures, signage, era), what may change per state, and continuity notes | `origin` | |

### 6.4 Templates

`org.scen.place.template`: a place embedding (DINOv2, CLIP or a place-recognition model)
of the retained samples, per state or pooled. MUST: `model` with `key`, `sha256`, `dim`,
`license`. Used by `admit` and by the `dino-cos` consistency metric. As with style scores,
thresholds come from the file's own sample spread.

### 6.5 Training

| Type | Payload | MUST | SHOULD |
|---|---|---|---|
| `org.scen.place.render` | A view rendered from captured geometry (core §4.4) | `origin` with `render: true`, `derivation` naming the geometry, `camera` | `viewpoint` |
| `org.scen.place.training-set` | JSON: samples and renders (by hash), captions record, state, purpose | | |

Renders teach a generator the place from angles nobody photographed. They are never
samples and never count as evidence: `admit`, templates and coverage use samples only.

### 6.6 Generation

| Type | Payload | MUST | SHOULD |
|---|---|---|---|
| `org.scen.image.lora` | safetensors location LoRA | `base_model`, `trigger` | `rank`, `training_samples`, `training_captions`, ModelSpec header |
| `org.scen.image.adapter-ref` | JSON: zero-shot use of samples or renders by an adapter | `adapter`, `refset` | `weights` |
| `org.scen.image.vendor-ref` | JSON or none: a vendor's world or location id (for example a hosted world model's world id) | `vendor`, `kind`, `value`, `portable: false`, `created_from` | `vendor_model` |

Every `generation/` entry carries `synthetic_capable: true`, a `derivation` and, for
`place`, `frame: "scene-canonical"`. Novel-view generators that are not specific to this
place (a general multi-angle adapter) are models named in `derivation.models`, not entries.

### 6.7 Index records

As in [core §5](../../core/spec/core.md#5-index-records), with these `.scen` rules:

- Captions use `"excludes": ["place"]` and describe camera, framing, state and what is in
  frame, never the place's identifying features.
- A reference set ranks samples by viewpoint and zone coverage for its target: the widest
  establishing view first, then one per zone. Renders MAY be included only when the target
  needs a viewpoint no sample has, marked `"render": true` on the item.
- `org.scen.place.coverage` (`place/coverage-<state>.json`): zones × viewpoint bins seen
  in samples, per state; derived.
- The held-out split is stratified by zone.

## 7. Provenance

- `real-place`: tiers `professional` (location scout or production photography the owner
  supplies), `enrolled` (the producing application's guided capture), `imported`,
  `observed`. `authored` is refused.
- `fictional-place`: `authored` is allowed, for concept art, set designs, and approved
  generated views. Anchors are the concept art;
  generated views pass `admit` against them (`dino-cos` or `vlm-judge`), record `lineage`,
  and are refused above lineage 2 by default (core §4.3).
- Renders of captured geometry are `imported` with `render: true` (core §4.4) and live in
  `training/` only.

## 8. Enrichment, budgets and eviction

The generic procedure applies, per state, with `.scen` functions:

| Function | `.scen` |
|---|---|
| `admit(candidate)` | Registers to the place (pose recovered against geometry, or place similarity to the template above threshold); people masked or removed; for a real place, PAD-style check that it is not a photo of a screen |
| `quality(entry)` | Sharpness, exposure, registration residual, resolution |
| `condition(entry)` | The `zone`, plus a viewpoint bin (azimuth around the zone centre in 45° bins) |
| `derive(samples)` | Re-register, refit geometry and the template from the whole retained set; re-render training views |
| `generate(samples, current)` | Retrain or re-register generators; adopt only if better on the held-out split (R4), scored with `dino-cos` or `vlm-judge` |

Budgets: `place.samples.per_state` with `count` and `bytes`, and floors
`per_zone_min` and `per_viewpoint_bin_min`. `prop.samples` with `per_prop` count.
Eviction never removes the last sample of a zone or the last establishing view.

## 9. Companion capture file (`.scencap`)

A `.scencap` uses the [`.prsncap`](../../prsn/spec/prsncap.md) layout, rules and schemas
unchanged, with media type `application/vnd.scen.capture+zip`, and `session.json`
`subject_format: "scen"`. Its capture script phases are scene phases: `establish`
(wide views from the entrances), `orbit` (each zone), `walkthrough` (continuous video),
`detail` (fixtures, signage, props) and `probe` (HDR light probe per state). Splits,
storage tiers, IMU records and calibration are as in `.prsncap`. Capture references live at
`place/capture-refs.json`, with `state` in place of `look` and no `era`. (A schema for the
`.scen` capture reference is not yet in this draft; validators currently accept the
payload unread.)

## 10. Security, licences, expiry, synthetic output

As in the core. Licence propagation (R6) includes `scene.json` `rights` and the rights of
referenced cast and style files. Everything rendered from a `generation/` asset carries a
C2PA content credential naming the asset's `action_key` and, when cast appear, the cast
files' ids.

## 11. Conformance

Rule ids as in `.styl` (`container`, `version`, `paths`, `manifest-hash`, `signature`,
`critical`, `subject`, `spec-fields`, `states`, `authored`, `index`, `generation`,
`type-fields`, `entry-order`), plus:

| Rule | Meaning |
|---|---|
| `people` | every place sample says `people`; `fictional` only in a fictional place; `masked` or `removed` samples carry a `derivation` |
| `props` | every `prop` field names a declared prop |
| `location` | `precision: "exact"` only with `consent.exact_location: true`; coordinates only with `exact` |
| `consent` | every vendor reference's `vendor` is in `scene.json` `consent.vendors` |

`spec-fields` also covers `frame` (present and correct on `place` and `prop` geometry and
generation); `type-fields` also covers zones and viewpoints that the layout or camera rigs
do not define.

Examples, conformance cases and the validator are described in [`../README.md`](../README.md).

## Decisions (draft 1.0)

1. **Two modalities.** `place` for the environment, `prop` for objects that carry their own
   continuity; cast stay in `.prsn` files.
2. **States, not looks.** Time of day, weather, season and dressing are states; geometry and
   layout pool across them.
3. **Renders allowed in `training/` only**, never as evidence.
4. **People are masked** before a sample of a real place is admitted.
5. **Coarse location by default**; exact coordinates need explicit consent.
6. **`.scencap` reuses `.prsncap`** rather than defining a second capture container.
