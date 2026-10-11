# `.prsn`: a portable person file

Status: **Draft v1.1**

A `.prsn` file holds one person: several modalities (voice, face, head, body), several
models' data for each, the raw material that data came from, and generative assets built
from it. It is application-independent: any reader that follows this document can open,
update and save a file another application wrote without losing anything.

Companion documents:

- [prsncap.md](prsncap.md): the companion raw-capture file `.prsncap`.
- [frames-and-units.md](frames-and-units.md): coordinate frames, transforms, units, clocks.
- [derivation-recipes.md](derivation-recipes.md): the `derivation` block, `action_key`, recipe descriptors.
- [enrichment-model.md](enrichment-model.md): sessions, looks, eras, coverage, per-look budgets.
- [voice.md](voice.md): the voice modality in detail, including its eviction procedure.
- JSON Schemas for every record: [`../schemas/`](../schemas/).
- Test vectors and invalid files: [`../conformance/`](../conformance/).

The keywords MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are used as in RFC 2119.

### Revision 1.1

Revision 1.1 is additive: `manifest.version` stays `1` because no rule from 1.0 changes
meaning. A writer signals the revision with `manifest.spec: "1.1"` (see
[Spec revision](#spec-revision-within-version-1)). It adds:

- the `derivation` block and recipe rules ([Derivations and recipes](#derivations-and-recipes));
- `org.prsn.face.capture-ref` as a **list** of sessions;
- `looks` and `eras` indexes, with `look` and `era` fields on entries;
- per-look budgets and coverage records ([Enrichment](#enrichment-budgets-and-eviction));
- the full `.prsncap` layout with `session.json`, `splits.json` and storage tiers;
- licence propagation, GNM Head as a first-class head model, the `geometry/` and
  `training/` roles for every modality, the `body` modality, and the glTF
  `KHR_gaussian_splatting` splat payload.

## Purpose and prior art

No existing standard covers a whole person. Several cover parts, and `.prsn` uses them
wherever one applies:

| Standard | Covers | Use in `.prsn` |
|---|---|---|
| ISO/IEC 19785 (CBEFF) | Envelope for one biometric record: header, data block, security block | Recognition templates and sample indexes are CBEFF BIRs |
| ISO/IEC 19794-13 | Voice *sample* interchange (explicitly excludes feature and model data) | Voice sample metadata is aligned to it |
| ISO/IEC 39794-1/-4/-5 | Extensible formats for finger and face images (no voice part published) | Face samples MAY be 39794-5 records |
| ISO/IEC 29794 | Sample quality | The `quality` field, where the modality has a standard measure |
| ISO/IEC 30107 | Presentation-attack detection (liveness) | The `pad` field |
| ISO/IEC 24745 | Biometric template protection | The `protected` block |
| ISO/IEC 12113 (glTF 2.0) | 3D meshes | Face, head and body meshes; splats via `KHR_gaussian_splatting` |
| ZIP + `mimetype` first (EPUB OCF, ODF, OOXML) | Container conventions | The wrapper |
| C2PA | Content provenance | Imported professional material, and everything generated |

None of these holds a person: several modalities, several models' templates for each, the
raw samples behind them, and generative assets such as a voice clone or an avatar. So the
container has its own name, and every record inside it uses an existing standard wherever
one applies.

## Container

A ZIP file that follows EPUB OCF:

```
alex-chen.prsn
├── mimetype                 "application/vnd.prsn+zip" (first member, STORED, no extra field)
├── manifest.json            the index; the only file a reader must understand
├── person.json              who: name, aliases, ids, links (no biometrics)
├── face/
│   ├── capture-refs.json    the captures this file was derived from
│   ├── samples/             guided-capture stills
│   ├── geometry/            meshes, landmarks, model coefficients, splats
│   ├── training/            expression clips and other material that trains a generator
│   ├── generation/          avatar, LoRA and other generative assets
│   └── templates/           recognition data (optional; see Templates)
├── voice/
│   └── templates/ samples/ training/ generation/
├── body/
│   └── geometry/ …
└── signatures/
    └── manifest.sig         detached signature over manifest.json
```

Rules:

- **Single source of truth.** `manifest.json` lists every other entry with its SHA-256,
  size, media type and record type. An entry the manifest does not list is ignored: a
  reader MUST NOT treat it as part of the file and MUST NOT write it back. A listed entry
  that is missing, or whose size or hash does not match, is an error.
- **Not entries.** `mimetype`, `manifest.json`, anything under the top-level
  `signatures/`, and any path with a segment starting with `.` are never manifest entries.
- **Unique members.** A ZIP member name MUST NOT appear more than once (two readers could
  each see different bytes). A reader MUST refuse such a file.
- **The `mimetype` member** is the first member, STORED, with no extra field, and holds
  exactly `application/vnd.prsn+zip` (ASCII, no newline). A reader MUST refuse a ZIP
  whose first member is not a `mimetype` meeting these rules. Readers SHOULD also accept
  the legacy value in [Appendix A](#appendix-a-legacy-v1-namespace). The media types, the
  `org.prsn` namespace and the CBEFF format owner/type codes are **provisional**; they
  will be registered (the media types in the IANA vendor tree) at format version 1.0.
- **Compression.** Audio, images, video, CBEFF BIRs and nested ZIPs are STORED, because
  they are already compressed. JSON, PLY and binary arrays are DEFLATE. Writers use ZIP64
  only when the file needs it; readers MUST support ZIP64. ZIP's own encryption is never used: it is weak, and readers
  handle it inconsistently (see [Security](#security)).
- **Paths.** Segments are ASCII `[a-z0-9._-]`; `.` and `..` are forbidden; nothing may
  climb out of the package. Modality and role names are reserved. Three depths exist, and
  no others:
  - depth 1: only `person.json` (the entry `manifest.person` names);
  - depth 2: only **modality-level index records**, `<modality>/<name>.json`: capture
    references (`face/capture-refs.json`) and coverage records
    (`face/coverage-<look>.json`);
  - depth 3 or more: every other entry, `<modality>/<role>/<name>`, with deeper paths
    allowed below a role (for example `face/generation/avatar/gaussians.ply`).
- **Size.** A `.prsn` is meant to be shared. Bulky raw capture data goes in a companion
  `.prsncap` file, not in the `.prsn`. A reader MUST accept archives up to at least 4 GiB
  total uncompressed size (which requires ZIP64) and MAY refuse larger ones, to guard
  against decompression bombs.
- **Working form.** An application MAY keep a `.prsn` as a directory package with the
  same tree and the same `manifest.json`; the ZIP is the interchange form. Converting
  between the two is lossless and leaves the manifest bytes, and so its hash and
  signature, unchanged.

## Canonical JSON

`manifest.json` is hashed and signed, and `action_key`s are hashed, in one byte form.
Writers store `manifest.json` in this form; a verifier re-canonicalises what it reads, so a
package's identity is the SHA-256 of the canonical bytes even if another tool
pretty-printed the file.

**Parsing** is strict RFC 8259. A reader rejects: invalid UTF-8 (overlong forms, encoded
surrogates, truncation), a leading byte-order mark, raw U+0000 to U+001F inside strings,
unknown escapes, lone or mis-paired surrogate escapes, duplicate object keys at any depth,
comments, `NaN`/`Infinity`, a leading `+`, leading zeros, `.5`, `1.`, `1e`, trailing
commas, trailing content, empty input, and number tokens whose value overflows a double.
An integer token (no `.`, no exponent) that fits a signed 64-bit integer is an exact
integer; any other number token is read as an IEEE-754 double (correctly rounded; underflow
reads as zero).

**Serialising:**

- No whitespace between tokens. UTF-8 output.
- Object keys sorted by Unicode code point, which equals UTF-8 byte order (**not**
  RFC 8785's UTF-16 order). Arrays keep their order.
- Strings escape `"` as `\"`, `\` as `\\`, U+0008 `\b`, U+0009 `\t`, U+000A `\n`, U+000C
  `\f`, U+000D `\r`, and other U+0000 to U+001F as `\u00xx` (lowercase hex). Everything
  else, including `/`, U+007F, U+2028/2029 and all non-ASCII, is written literally.
- `true`, `false`, `null`. Integers in exact decimal (`-0` becomes `0`).
- Doubles: the shortest digits that round-trip, laid out like ECMAScript
  `Number.prototype.toString` (RFC 8785 §3.2.2.3). With digits d₁…dₖ and value
  `0.d₁…dₖ × 10ⁿ`: if `k ≤ n ≤ 21`, the digits then `n−k` zeros (`1.0` → `1`); if
  `0 < n ≤ 21`, a point inside the digits (`12.5`); if `−6 < n ≤ 0`, `0.` then `−n` zeros
  then the digits (`0.000001`); otherwise exponent form `d₁[.d₂…dₖ]e±(n−1)` (`1e+21`,
  `1e-7`, `1.5e-9`). `-0.0` is written `0`; NaN and infinities cannot be serialised.

Vectors: [`conformance/json/`](../conformance/json/).

## `manifest.json`

```json
{
  "format": "prsn",
  "version": 1,
  "spec": "1.1",
  "created": "2026-10-02T18:04:11Z",
  "generator": "example-writer 1.0.0",
  "person": "person.json",
  "budgets": {"face.samples": {"count": 48, "bytes": 120000000, "per_condition_min_count": 3,
                               "per_look": {"count": 48, "bytes": 160000000},
                               "floors": {"per_angle_bin_min": 2, "per_expression_class_min": 3}}},
  "looks": [
    {"id": "look-2026-10a", "label": "Oct 2026, short hair", "era": "era-1", "default": true,
     "sessions": ["sha256:…"], "state": {"hair_length": "short", "facial_hair": "none", "glasses": false},
     "created": "2026-10-02T18:30:00Z"}
  ],
  "eras": [
    {"id": "era-1", "label": "2026", "looks": ["look-2026-10a"],
     "identity_ref": "face/geometry/gnm-head.identity.era-1.npz", "started": "2026-10-02", "ended": null, "linked_from": null}
  ],
  "entries": [
    {
      "path": "face/capture-refs.json",
      "type": "org.prsn.face.capture-ref",
      "media": "application/json",
      "sha256": "…", "bytes": 912
    },
    {
      "path": "face/samples/f-0001.heic",
      "type": "org.prsn.face.sample",
      "media": "image/heic",
      "sha256": "…", "bytes": 2841122,
      "pose": {"yaw": -32.5, "pitch": 4.1, "roll": 1.0},
      "condition": "profile",
      "expression": "neutral",
      "camera": {"device": "iPhone18,1", "lens": "front-truedepth", "width": 4032, "height": 3024},
      "quality": {"score": 0.86, "standard": "ISO/IEC 29794-5", "by": "ofiq@1.0.0"},
      "pad": {"method": "truedepth-depth-3d", "score": 0.99},
      "origin": {"tier": "enrolled", "how": "example-guided-v1", "at": "2026-10-02T17:58:00Z"},
      "look": "look-2026-10a", "era": "era-1",
      "derivation": {"family": "org.prsn.method.stills-bank", "recipe": {"id": "…", "version": "1.0.0", "rank": 10}, "…": "…"}
    },
    {
      "path": "face/geometry/head.glb",
      "type": "org.prsn.face.mesh",
      "media": "model/gltf-binary",
      "sha256": "…", "bytes": 1840022,
      "topology": "gnm-head-v3",
      "frame": "head-canonical",
      "coverage": ["face", "scalp", "ears", "neck"],
      "model": {"key": "gnm-head-v3", "sha256": "…", "license": "Apache-2.0"},
      "look": "*", "era": "era-1",
      "derivation": {"family": "org.prsn.method.head-fit", "…": "…"}
    }
  ],
  "signature": {"path": "signatures/manifest.sig", "alg": "Ed25519", "key_id": "…", "public_key": "…"}
}
```

Top-level fields:

| Field | Required | Meaning |
|---|---|---|
| `format` | yes | Always `"prsn"` |
| `version` | yes | Integer; see [How it extends](#how-it-extends) rule 5 |
| `spec` | no | Revision followed, `"<major>.<minor>"`; absent means `"1.0"` |
| `created` | yes | When this manifest was written (ISO 8601, UTC) |
| `generator` | no | Name and version of the writing software |
| `person` | yes | Path of the `person.json` entry |
| `budgets` | no | Per `<modality>.<role>` budgets ([Budgets](#budgets)) |
| `looks`, `eras` | spec ≥ 1.1 when entries use them | [Looks and eras](#looks-and-eras) |
| `entries` | yes | One row per entry |
| `signature` | no | The signature block ([Security](#security)) |
| `redact` | no | `true`: `person.json` is encrypted too |

A reader keeps top-level keys it does not know and writes them back unchanged. One key is
retired: `scopes` (an early draft's consent object) is dropped on load and not written
back. Writers MUST list entries sorted by path in UTF-8 byte order. Readers MUST NOT
depend on the order and MUST accept unsorted files written before revision 1.1.

### Fields common to all entries

| Field | Required | Meaning |
|---|---|---|
| `path`, `type`, `media`, `sha256`, `bytes` | yes | Container fields. `sha256` is 64 lowercase hex digits |
| `critical` | no (default `false`) | The file can't be used without understanding this entry |
| `origin` | yes for `samples/` and `training/` | Provenance tier and capture path ([Provenance tiers](#provenance-tiers)) |
| `quality` | where scored | Score in [0, 1], its components, which scorer and when, and a `standard` if one applies |
| `model` | yes for model-bound entries | `key`, `sha256` and `license` of the model the entry belongs to |
| `license` | where the entry itself is licensed | SPDX id or URL ([Licences](#licences)) |
| `coverage` | for geometry and generation | Body regions present (below) |
| `synthetic_capable` | yes in `generation/` | Always `true` there |
| `expires` | no | ISO date; readers drop the entry after it ([Expiry](#expiry)) |
| `enc`, `protected` | no | [Security](#security) |
| `derivation` | yes (`spec` ≥ 1.1) for `geometry/`, `generation/`, `templates/`; recommended for derived `samples/` | How the entry was made: family, recipe, tool, models, inputs by content hash, params, `action_key`, determinism, eval, `supersedes` ([Derivations and recipes](#derivations-and-recipes)) |
| `look` | yes (`spec` ≥ 1.1) for `samples/`, `geometry/`, `generation/` | A look id from `manifest.looks`, or `"*"` for identity-level entries |
| `era` | yes (`spec` ≥ 1.1) where `look` is | An era id from `manifest.eras` |
| `frame` | yes (`spec` ≥ 1.1) for `geometry/` and `generation/` of spatial modalities (`face`, `head`, `body`); omitted for non-spatial modalities such as `voice` | A named coordinate frame (`head-canonical`, `arkit-face`, `flame-canonical`, …; [frames-and-units.md](frames-and-units.md)) |

Every other field on an entry is the record's own metadata. A reader keeps fields it does
not know and writes them back unchanged.

`coverage` values: `face`, `scalp`, `hair`, `ears`, `neck`, `shoulders`, `upper-torso`.

### Looks and eras

A **look** (`manifest.looks[]`) is a named group of sessions sharing a state (hair, facial
hair, glasses, makeup, clothing); every session belongs to exactly one look. An **era**
(`manifest.eras[]`) is a period within which identity pools; every look belongs to exactly
one era, and eras are linked (`linked_from`). An entry's or capture reference's `look` is
`"*"` or a declared look id, and its `era` is a declared era id. Readers that predate 1.1
ignore both indexes and the `look`/`era` fields without harm. The data model is in
[enrichment-model.md](enrichment-model.md).

### Spec revision within version 1

`manifest.spec` names the revision of this document the writer followed: `"1.1"` for this
draft. Absent means `"1.0"`. It never changes how a file is read; it only decides what a
validator requires:

- `spec` ≥ 1.1: `derivation`, `look`, `era` and `frame` are **required** where the table
  above says "yes (`spec` ≥ 1.1)". A validator refuses a 1.1 file that lacks them.
- `spec` absent or 1.0: the same fields are SHOULD. A 1.1 reader fills in defaults in
  memory and flags the entry `legacy`: `look: "*"`, `era: "era-0"` (one implicit era
  holding every session), `frame` from the entry's `topology` where it is determined
  (`arkit-1220` → `arkit-face`, `flame-*` → `flame-canonical`, `gnm-head-v3` →
  `head-canonical`), else `unknown`; no `derivation`, so the entry can't be rebuilt and is
  never auto-superseded (R3 treats it as stale but usable).
- A writer that rewrites a 1.0 file emits `spec: "1.1"` only after it has supplied the
  required fields for every entry it wrote; entries it copied through keep their `legacy`
  state and the file keeps `spec` absent.

## `person.json`

Contains no biometrics. Writers always write this shape:

```json
{"id": "urn:uuid:…", "display_name": "Alex Chen", "aliases": [],
 "ids": [{"scheme": "example", "value": "abc123"}],
 "links": [{"rel": "homepage", "href": "https://example.org/"}]}
```

`id` (a `urn:uuid`) and `display_name` are required; `aliases`, `ids` and `links` are
arrays; other fields are allowed and kept on rewrite. Files from before revision 1.1 may
use a legacy shape; readers MUST map it before use:

- `name` → `display_name` (when `display_name` is absent);
- an `ids` object `{scheme: value}` → `[{"scheme": scheme, "value": value}]`;
- a `links` object `{rel: href}` → `[{"rel": rel, "href": href}]`.

`person.json` and the manifest stay plaintext unless the manifest sets `"redact": true`,
so a file can be inspected without revealing biometrics.

## How it extends

New data is added under these rules, without a version bump:

1. **Record types are reverse-DNS strings**, written `<org>.<modality>.<role-or-kind>`.
   `org.prsn.*` is defined by this document (provisionally; see [Container](#container)).
   Anyone else uses their own prefix (for example `com.vendor.face.template`). A type name
   is never reused for something else.
2. **Readers ignore what they don't understand, and keep it.** An unknown type is skipped
   when reading. On rewrite it is copied through byte for byte and stays in the manifest,
   with all its fields. So a voice-only reader can open, update and save a file holding
   face data without losing anything.
3. **`critical: true`** marks an entry the file can't be used without (like PNG's critical
   chunks). A reader that doesn't understand a critical entry MUST refuse the file, not
   half-load it. A known type marked critical is fine.
4. **Every modality has the same roles**, and uses only the ones it needs:
   - `templates/`: model-specific comparison data, one per model, each naming its model by hash.
   - `samples/`: raw captures that any future model can re-derive templates or geometry from.
   - `geometry/`: shape that is neither a template nor a sample (meshes, landmarks, model
     coefficients, splats).
   - `training/`: material whose purpose is to train a generator (voice-clone corpus,
     expression clips). It is evidence of the person, just like `samples/`.
   - `generation/`: assets that reproduce the trait (voice-clone seed, avatar, LoRA).

   A new modality (face, gait, signature, typing rhythm) adds a directory. It doesn't
   change the format.
5. **`version`** increases only when an existing rule changes meaning. Readers accept any
   version up to the one they know. A file with a higher version is refused, and its
   version is shown. `version` is an integer ≥ 1.

## Face and head

In the tables below, **MUST** lists the fields a reader needs to use the entry; a writer
MUST include them and the schemas enforce them. **SHOULD** lists fields a writer includes
when it has them. Fields required by the spec revision (`derivation`, `look`, `era`,
`frame`) and by the role (`origin`, `synthetic_capable`) apply on top.

### Samples (`face/samples/`)

`org.prsn.face.sample`: stills from a guided capture at native resolution: HEIC, PNG or
JPEG-XL, or an ISO/IEC 39794-5 record.

- MUST: `origin`.
- SHOULD: `pose` (yaw, pitch, roll in degrees, display-upright;
  [frames-and-units.md](frames-and-units.md) §3), `condition` (`frontal` / `profile` /
  `three-quarter` / `up` / `down` / `low-light` / `glasses`), `expression` (`neutral`, or
  an ARKit blendshape name or short label), `camera`, `quality` (ISO/IEC 29794-5 where
  available), `pad`. Eviction uses the angle bin (from `pose`) and the expression class;
  a sample without them counts in no bin or class floor.

The same stills serve as the training images for an image LoRA, which refers to them by
hash. A stills bank is evidence of the person; renders made from a generator never are.

### Geometry (`face/geometry/`)

| Type | Payload | MUST | SHOULD |
|---|---|---|---|
| `org.prsn.face.mesh` | glTF 2.0 `.glb`, metres, right-handed, +Y up. Optional morph targets, named with ARKit's 52 names where the topology supports them | `topology` (`gnm-head-v3`, `arkit-1220`, `mediapipe-478`, `flame-2023-open`, `flame-2020`, `ict-facekit`, `mhr`, …), `coverage`, `model` with `license` | |
| `org.prsn.face.landmarks` | JSON landmark arrays | `topology` | coordinate space, capture pose |
| `org.prsn.face.params` | safetensors or `.npz` of model coefficients: identity (for example GNM 253, FLAME 300) and, where present, per-frame expression and pose tracks | `model` with `license` ([Licences](#licences)); `kind` (`identity` or `track`) | for tracks, the capture and stream the frames come from (via `derivation.inputs`) |
| `org.prsn.face.blendshapes` | JSON, the 52 ARKit-named coefficients (MediaPipe emits the same names). A neutral rest pose only; expression over time is a track | | |
| `org.prsn.face.expression-track` | JSONL or `.npz`: per-frame ARKit-52 coefficients (the canonical driver), plus optional per-frame mapped coefficients for other bases | `basis` (`arkit-52`, `gnm-expr-383`, `flame-expr-100+jaw`) | fps, frame count |
| `org.prsn.face.expression-map` | `.npz`: mapping from one expression basis to another (generic or per-person) | `from`, `to`, `kind` (`generic-linear`, `per-user-linear`, `per-user-mlp`) | fit residual |
| `org.prsn.face.splat` | 3D Gaussian splat. **Canonical: glTF 2.0 `.glb` with `KHR_gaussian_splatting`**, all attributes float32, `kernel: "ellipse"`, truthful `colorSpace`, metres, in `head-canonical`. Display copy: `.spz` (derived, disposable). 2DGS or non-ellipse kernels: float32 `.ply` with a `kernel` field until a KHR extension exists | `sh_degree`, `kernel`, `color_space`, `coverage`; `critical` absent or `false` | `antialiased` (bool), `gaussian_count` |

### Coverage records (`face/coverage-<look>.json`)

`org.prsn.face.coverage`: a modality-level index record, one per look
([`coverage.schema.json`](../schemas/coverage.schema.json)). MUST: `look`, `derivation`;
`critical` absent or `false` (it is a cache item copied in for readers).

### Training (`face/training/`)

| Type | Payload | MUST | SHOULD |
|---|---|---|---|
| `org.prsn.face.expression-clip` | HEVC or ProRes video plus a JSONL sidecar of per-frame ARKit blendshapes and head pose | `origin` | duration, fps, camera, the prompt the person was following |

### Generation (`face/generation/`)

| Type | Payload | MUST | SHOULD |
|---|---|---|---|
| `org.prsn.face.avatar` | A directory: `avatar.json`, the bound mesh (`.glb`), and `gaussians.ply` with per-Gaussian binding attributes; optionally per-basis Gaussian blendshape deltas (`deltas/<basis-name>.ply`) | `topology` (`gnm-head-v3` by default), `driver` (`arkit-52`, `gnm-expr-383` or `flame-expr-100`), `binding`, `formulation` (`lbs-bound` or `gaussian-blendshapes`), `coverage` | the bound mesh's hash (`mesh_sha256`), trainer, version and training clips via `derivation`, `look` (the appearance layer's look; identity and expression basis are per era) |
| `org.prsn.image.lora` | safetensors LoRA (kohya/diffusers keys) | `base_model` (`{"key", "sha256"}`), `trigger` | `rank`, `training_samples` (hashes of the training images in `face/samples/`) |
| `org.prsn.image.embedding` | safetensors textual-inversion vector | `base_model`, `token` | |
| `org.prsn.image.faceid` | none: reuses a `face.template` | `template` (the template entry's path) | |
| `org.prsn.avatar.vrm` | VRM 1.0 (glTF-based humanoid avatar) | `coverage` | source mesh hash |

**Avatar binding.** The per-Gaussian binding attributes in `gaussians.ply` (parent
triangle, local offset, local rotation and scale) are trainer-defined and identified by
the `binding` name (for example `triangle-local` as in GaussianAvatars, `mesh-embedded` as
in SplattingAvatar), together with `formulation` and the per-basis delta files. A reader
uses an avatar only if it implements that `binding`. A standard attribute layout is
planned for a later revision.

### Templates (`face/templates/`)

`org.prsn.face.template` (a CBEFF BIR holding a face embedding, for example ArcFace
512-d) is defined for completeness. MUST: `model` with `key`, `sha256`, `dim` and
`license`. No standard exists for the embedding itself; it is vendor-specific, like a voice
template. A writer SHOULD NOT produce one unless recognition is the explicit purpose of
the file. A face template is a face print. The common pretrained models (for example
InsightFace's ArcFace weights) are licensed for non-commercial use only, which
`model.license` must state.

## Body (`body/`)

A `body` modality with the same roles, used for the neck, shoulders and upper torso:

| Type | Payload | MUST | SHOULD |
|---|---|---|---|
| `org.prsn.body.params` | `.npz` of body-model coefficients (MHR identity and pose by default) | `model` with `license`, `coverage` (`neck`, `shoulders`, `upper-torso`) | the stitch transform to the head model's neck joint (`T_headcanon_from_body`) |
| `org.prsn.body.mesh` | glTF 2.0 `.glb` | `topology` (`mhr`, `anny`), `coverage`, `model` with `license` | |

## Voice

Voice is a non-spatial modality: its entries carry no `frame`. Summary; the full rules are
in [voice.md](voice.md).

| Type | Role | Payload | MUST | SHOULD |
|---|---|---|---|---|
| `org.prsn.voice.template` | `templates/` | CBEFF BIR (speaker vector) | `model` with `key`, `sha256`, `dim`, `license` | `evidence_seconds`, `evidence` by tier |
| `org.prsn.voice.sample` | `samples/` | FLAC at the captured rate and bit depth, metadata aligned to ISO/IEC 19794-13, 3–15 s, one speaker | `seconds`, `sample_rate`, `bits`; `source_format` when the capture was floating point | `channels`, `captured`, `condition`, `overlap`, `quality` |
| `org.prsn.voice.sample-index` | `samples/` | CBEFF BIR with one 19794-13-aligned block per sample (hash, not audio), rebuilt on every write | | |
| `org.prsn.voice.training` | `training/` | One clone-training clip per entry, lossless at native rate | | the words it carries |
| `org.prsn.voice.training-set` | `training/` | JSON record of the training set | | why it was staged, its sources, clip order |
| `org.prsn.voice.seed` | `generation/` | FLAC reference line | `text`, `sample_rate`, `bits` | `source_sample`, verification scores |
| `org.prsn.voice.generation` | `generation/` | JSON: which seed, which engines, verification scores, history | | |
| `org.prsn.voice.prompt` | `generation/` | Engine-specific speaker prompt (safetensors). Disposable | `engine` (`{"name", "version"}`) | |
| `org.prsn.voice.lora` | `generation/` | safetensors adapter for a TTS model | `base_model` | `rank`, `training_samples` |
| `org.prsn.voice.rvc` | `generation/` | RVC voice-conversion `.pth` + `.index` | `base_model` | sample rate |
| `org.prsn.voice.piper` | `generation/` | Piper `.onnx` + `.json` (trained single-speaker TTS) | | the training set's hashes |

## Other modalities

These record types are reserved for modalities that already have interchange standards.
They follow the same roles and rules:

| Type | Payload standard | SHOULD |
|---|---|---|
| `org.prsn.finger.*`, `org.prsn.iris.*`, `org.prsn.vein.*` | ISO/IEC 39794-4 / -6 / -9, or the 19794 equivalents | quality (NFIQ 2 for fingerprints) |
| `org.prsn.signature.sample` | W3C InkML, or ISO/IEC 19794-7 time series | device, sampling rate |
| `org.prsn.gait.*` | ISO/IEC 39794-16 / -17 where published | sensor, rate |

### Cross-cutting standards

- **ISO/IEC 29794** (sample quality): when a modality has a standard quality measure, it
  fills the `quality` field and names it in `quality.standard` (29794-5 for faces, NFIQ 2
  for fingerprints). Voice has none, so a writer's own score is used and labelled as such
  (its own `standard` string, never a standard's name).
- **ISO/IEC 30107** (presentation-attack detection): when a sample passed a liveness
  check, `pad` records which one and its score. A replayed recording or a photo of a photo
  must not enrich anyone's file.
- **ISO/IEC 24745** (template protection): the `protected` block ([Security](#security)).
- **C2PA**: provenance for imported `professional` material (when the source carries
  credentials) and for everything generated.

## Companion capture file (`.prsncap`)

Raw capture sessions (video, depth, stills, calibration, per-frame tracking, IMU, audio,
environment) let future pipelines rebuild everything in `geometry/` and `generation/`.
They are gigabytes, so they go in a companion package that follows the same container
rules. The full layout, `session.json`, `splits.json`, the capture script and the
per-stream formats are in [prsncap.md](prsncap.md). The principles:

- **P1 Write-once.** A `.prsncap` holds only what sensors and the capture application
  observed during the session. Nothing computed afterwards goes in. Its identity is the
  SHA-256 of its canonical `manifest.json`.
- **P2 Everything else is a re-derivable cache:** masks, poses, fits, undistorted frames,
  HDR merges, splats, avatars, LoRA sets. Each cache item carries a `derivation` and may be
  deleted at any time.
- **P3 One clock per session** (`d0.host`), with a per-device clock model.
- **P4 Sensor-native first.** Depth, IMU, tracker output and calibration tables are stored
  in the type and units the OS delivered. Conversions are derived.
- **P5 Tiers are derivations.** A smaller tier made from a larger one is a new `.prsncap`
  with its own manifest and a `derived_from` recipe. Captures are never promoted, and
  demotion is recorded and confirmed by the user, never silent.
- **P6 The assembler signs.**

**Capture references.** The `.prsn` refers to its captures with one
`org.prsn.face.capture-ref` entry whose payload is a **list** (1.1; a single object is
still accepted and read as a one-item list):

```json
[{"file": "alex-chen-20261002T1804Z.prsncap", "manifest_sha256": "…", "tier": "archival",
  "capabilities": ["rgb.log2", "depth.truedepth.30", "tracking.arkit-face", "…"],
  "look": "look-2026-10a", "era": "era-1", "captured_at": "2026-10-02T18:04:11Z",
  "script": {"id": "example-guided", "version": "1.0.0", "kind": "full"}}]
```

`manifest_sha256` is required: a SHA-256, bare hex or `sha256:`-prefixed. Because the
capture manifest hashes every entry, it fixes the whole capture. A reader that lacks the
`.prsncap` still has a complete `.prsn`.

## Derivations and recipes

Every derived entry (and every cache item) carries a `derivation` block. The schema and
the recipe descriptor format are in [derivation-recipes.md](derivation-recipes.md):

```json
"derivation": {
  "family": "org.prsn.method.static-splat",
  "recipe": {"id": "org.example.recipe.splat.mcmc", "version": "1.2.0", "rank": 40},
  "tool": {"name": "example-writer", "version": "1.0.0", "build": "git:3f9c2e1", "platform": "macOS 27.0 / Apple M3"},
  "models": [{"role": "head-model", "key": "gnm-head-v3", "sha256": "…", "license": "Apache-2.0", "use_restrictions": []}],
  "inputs": [{"capture": "sha256:…", "look": "look-2026-10a", "era": "era-1",
              "select": {"streams": ["d0/rgb.front", "d0/depth.front"], "phases": ["orbit", "face"], "exclude_split": "holdout"}},
             {"cache": "sha256:<action_key>", "role": "masks"}],
  "params": {"iterations": 30000, "sh_degree": 3, "seed": 1234},
  "action_key": "sha256:…", "determinism": "seeded-nonbitwise",
  "eval": {"split": "holdout", "metric": "psnr", "value": 31.8, "per_capture": [{"capture": "sha256:…", "value": 31.8}]},
  "supersedes": null, "created": "2026-11-14T03:12:09Z", "duration_s": 1840,
  "license_constraints": []
}
```

- **R1 `action_key`** is the SHA-256 of the canonical JSON of `{family, recipe.id,
  recipe.version, models[].sha256 sorted, params, inputs resolved to content hashes and
  selections, sorted}` (exact preimage in [derivation-recipes.md](derivation-recipes.md)).
  `tool.build` is recorded for provenance but is **not** part of the key: a recipe whose
  output changes with the tool bumps `recipe.version`. Two derivations with the same key
  are interchangeable.
- **R2 Inputs are content hashes, never paths.** A capture is its manifest hash; a
  selection (`select`) is part of the input; a cache item is its `action_key`; an entry is
  its `sha256`.
- **R3 Staleness.** An entry is stale when an input hash cannot be resolved or an input
  cache item was recomputed with a different output. Staleness propagates down the input
  graph. Stale entries stay usable but are flagged and are never auto-superseded.
- **R4 Upgrade.** When a better recipe of the same family becomes available and its
  `requires` are met by the referenced captures' `capabilities`, a writer may re-derive the
  entry, score it on the captures' `splits.json` held-out set, and **adopt it only if it
  is better**; it then sets `supersedes` and keeps the previous entry until the user
  confirms.
- **R5 Determinism is declared** (`bitwise`, `seeded-nonbitwise`, `none`), never assumed.
  Re-derivation is verified by `eval` unless `bitwise`.
- **R6 Licences and restrictions propagate.** `license_constraints` is the union of the
  models' and inputs' constraints. Exporters MUST check the union.
- **R7 Live-session outputs** made on the capture device are derived too; `tool.platform`
  names the device.
- **R8 Generated media** rendered from a `generation/` asset carry a C2PA manifest whose
  ingredients include the asset's `action_key` and the source capture hashes.

## Provenance tiers

Every sample and training entry records where it came from, and its origin outranks its
quality score: one sample captured on purpose is worth more than several overheard ones.

```json
"origin": {"tier": "enrolled", "how": "example-guided-v1", "device": "…",
           "at": "2026-10-01T09:12:00Z", "set_by": "example-writer"}
```

| Tier | Rank | What it is | Who sets it |
|---|---|---|---|
| `professional` | 4 | Studio or broadcast capture, or a dataset recorded for the purpose (a podcast master, a voiceover session) | The person, on material they add (`"set_by": "user"`) |
| `enrolled` | 3 | The producing application's own guided capture | Only that application's capture path |
| `imported` | 2 | Files the person chose to add | The application, on import |
| `observed` | 1 | Material collected incidentally | The application |

- **The tier comes from the path the data took, never from its content.** A tier says how
  much to trust the capture. It never decides whose data it is: `professional` material
  still has to pass the modality's admission check.
- **The top tiers hold only within the signer's trust.** For a file that is unsigned or
  signed by a key the reader does not trust, the reader MUST treat `enrolled` **and**
  `professional` entries as `imported`, keeping the claimed tier as `origin.was`, and MUST
  move the seconds a template's `evidence` attributes to those tiers to `imported` (sum
  rounded to 0.1). Lower tiers are unchanged. Vectors:
  [`conformance/tiers/`](../conformance/tiers/).
- **Eviction compares tier first, then effective quality.** Lower-tier material never
  displaces higher-tier material.
- **Generation prefers the top tiers.** Generators choose `professional` and `enrolled`
  material first; lower-tier material replaces it only when it scores measurably better.
- **Templates record their mix**, for example `"evidence": {"enrolled": 44.8, "observed":
  15.2}` (seconds for voice), so recognition can tell a template built from deliberate
  capture from one assembled from incidental material.
- `origin.synthetic: true` marks generated material. It is never valid in `samples/` or
  `training/` ([Synthetic output](#synthetic-output-and-acceptable-use)).

## Enrichment, budgets and eviction

A `.prsn` file is never final. When new material beats something already in the file, the
file improves. Every role has a budget, and the lowest-value data goes first when a budget
is exceeded. One mechanism serves every modality: each modality supplies five functions,
and the generic procedure never looks inside the data.

| Function | Voice | Face |
|---|---|---|
| `admit(candidate, person) → bool` | Matches the person's template at threshold + margin, overlap 0, single speaker, mono, 3–15 s, unclipped, level above a floor | A single face, unoccluded, PAD passed, pose within capture limits; for a rescan, the session-level admit gate ([enrichment-model.md](enrichment-model.md) §4) |
| `quality(entry) → 0..1` + components | SNR, speech ratio, length (saturates at about 10 s), agreement with the person's template | ISO/IEC 29794-5 (OFIQ) where available; otherwise sharpness, pose, illumination and resolution, labelled as the writer's own score |
| `condition(entry) → str` | `quiet` / `noisy` / `headset` / `far-field` | `frontal` / `profile` / `three-quarter` / `up` / `down` / `low-light` / `glasses` |
| `derive(samples) → templates/geometry` | Re-embed the whole bank with each model present | Refit mesh and params from all samples and captures |
| `generate(samples, current) → generation` | Choose a new seed only if its clones score higher | Retrain the avatar or LoRA; adopt only if it scores better on held-out views |

`derive` always recomputes from the whole retained set, never from a running average, so
evicting a sample really removes its influence. Generated output never goes back into
`samples/` or `training/`.

### Writer behaviour on each encounter (informative)

1. **Collect** candidates for each recognised person. Cap how many one encounter may
   propose, so one long encounter can't take over the bank.
2. **Admit.** A candidate that fails `admit` is dropped. If nothing is admitted, nothing
   changes: this gate keeps mis-attributed material out of the file.
3. **Score.** Write `quality` (score, components, the scorer and its model hash, the time)
   to the entry.
4. **Insert, then evict until within budget** ([Eviction order](#eviction-order)). A
   candidate that the full bank would evict on arrival is refused instead, so running the
   same encounter twice changes nothing.
5. **Re-derive** templates and geometry if the retained set changed.
6. **Regenerate** if new material beats the current generator's source; adopt only if
   better, and record rejected attempts so the same material isn't retried.
7. **Write atomically**: write beside the old file, sync, rename over it, and keep the
   previous version until the next successful write.

### Budgets

Budgets live in `manifest.budgets`, keyed `<modality>.<role>`, each with a size cap and a
coverage floor ([`budgets.schema.json`](../schemas/budgets.schema.json)):

```json
"budgets": {
  "voice.samples":    {"seconds": 60, "bytes": 8000000, "per_condition_min_seconds": 8, "reserve_seconds": 45},
  "voice.generation": {"candidates": 0},
  "voice.templates":  {"models": 3},
  "face.samples":     {"per_look": {"count": 48, "bytes": 160000000},
                       "floors": {"per_angle_bin_min": 2, "per_expression_class_min": 3}}
}
```

A reader fills budgets the file does not give from its defaults and keeps keys it does not
know. Voice defaults and the protected reserve are in [voice.md](voice.md); per-look face
budgets in [enrichment-model.md](enrichment-model.md) §7.

### Eviction order

While a budget is exceeded:

1. Remove expired entries (`expires`).
2. Consider the lowest provenance tier present first. Within that tier, among groups
   *above* their floor, remove the entry with the lowest **effective quality** =
   `score × (1 − redundancy)`. Redundancy is how close the entry is to its nearest
   neighbour in the same group (for example by template cosine), so a near-duplicate of a
   better entry goes before a worse but distinct one.
3. If every group in that tier is at its floor, move up to the next tier.
4. Never remove the last entry of a group, or the sources of the current generation
   assets. Nothing else is pinned.

Ties go to the older entry. When the scoring model changes, every entry is re-scored before
the next eviction, so scores from different models are never compared.

### Eviction procedure

The exact procedure, used by every role with a budget. Parameters per role:

| Role | Measure | Cap | Groups and floors | Reserve |
|---|---|---|---|---|
| `voice.samples` | seconds (`seconds` of each entry) | `seconds`, `bytes` | `condition`, floor `per_condition_min_seconds` | `reserve_seconds` (default: `seconds`) |
| `face.samples` | count (1 per entry), run separately **per look** | `per_look.count`, `per_look.bytes` | angle bin (15° yaw × 15° pitch, [frames-and-units.md](frames-and-units.md) §3), floor `floors.per_angle_bin_min`; and expression class, floor `floors.per_expression_class_min` | none (the whole cap) |

Inputs: the role's entries (for faces, one look's), its budget, the pinned entries (sources
of current generation assets), each entry's redundancy (default 0), and optionally a
**newcomer**: a top-tier entry that was just inserted.

Definitions: an entry's rank is its tier's rank (professional 4, enrolled 3, imported 2,
observed 1; top tiers are ranks 3 and 4). Effective quality `eq = score × (1 − r)` with
redundancy `r` clamped to [0, 1]. The **worst** of a set is the entry with the lowest
`eq`, ties going to the older (`origin.at`) entry. An entry belongs to one group per
grouping (voice: its condition; face: its angle bin and its expression class).

1. Remove every entry whose `expires` is before today, whatever the budget.
2. While the total measure exceeds the cap, or the total entry size exceeds `bytes`:
   1. **Removable** entries are those that are not pinned and are not the last entry of
      any of their groups. If there are none, stop.
   2. **Floor-protected** entries: for each group, order its entries by (rank, `eq`, age)
      best first, and protect them from the top until the protected measure reaches the
      group's floor; the first entry of every group is always protected. An entry
      protected in any of its groups is protected.
   3. **Lower tiers first.** Among removable lower-tier (`imported`, `observed`) entries,
      take the lowest rank that has an entry that is not floor-protected, and remove the
      worst such entry.
   4. Otherwise, if the top tiers hold more than the reserve, the reserve gives:
      - if there is a newcomer that is not pinned, remove the worst top-tier removable
        entry in the newcomer's group(s) whose rank is not above the newcomer's and whose
        `eq` is below the newcomer's; if there is none, remove the newcomer itself (so a
        deliberately captured entry only displaces a worse one of its own kind);
      - otherwise, starting from the lowest top rank, remove the worst entry that is not
        floor-protected, or the worst entry of that rank if all are protected.
   5. Otherwise, if any removable lower-tier entry remains, remove the worst entry of the
      lowest lower-tier rank (lower-tier floors yield before the reserve does).
   6. Otherwise stop.

A writer that inserted a candidate and sees the procedure remove that same candidate
refuses the candidate and leaves the bank as it was. Vectors (voice and face):
[`conformance/eviction/`](../conformance/eviction/).

### Rescans enrich, never replace

A person can capture again at any time; each session adds to the file. The data model is
in [enrichment-model.md](enrichment-model.md). Rules:

1. **Identity pools; state belongs to a look.** Skull and face shape, the expression model,
   teeth, eyes, ears, voice and fine skin detail pool across every session in an **era**.
   Hair, facial hair, glasses, makeup, clothing, lighting and room belong to a **look**.
   Identity-level entries carry `look: "*"`; appearance entries carry a look id. Lighting
   records (probes) are per session and never pooled.
2. **Admit gate per session.** A new capture is admitted only if it is the same person
   (identity distance and a face-similarity check computed on the fly and **not stored**
   as a template), passes liveness, and has adequate tracking. If it fails, nothing
   changes and the writer says why.
3. **Looks and eras are proposed, then confirmed** by the user.
4. **Multi-session assets** list every capture they used in `derivation.inputs`, with the
   streams, phases and regions taken from each.
5. **Adopt only if better on all held-out data**: scored on the **union** of every input
   session's `splits.json` held-out frames; adopted only if the total improves and no
   earlier session's score drops noticeably.
6. **Budgets per look.** `face.samples` floors apply per look × angle bin × expression
   class, so a new session cannot evict the only good left-profile shot of an older look.
7. **Nothing is destructive.** Captures are never deleted or demoted automatically. Assets
   keep their `supersedes` chain and any version can be restored. Recency is a weight, not
   a replacement.
8. **Coverage records** (`org.prsn.face.coverage`, one per look) say which regions, view
   angles, expressions and phonemes have been captured, and drive targeted rescan
   suggestions.

## Licences

Every model-bound entry names its model and that model's licence, because a template,
mesh, coefficient set or adapter can be useless, misleading or restricted without it.
Writers MUST record the licence of the specific version used. Exporters MUST NOT include
an entry whose licence forbids the intended use. For head and body models:

| Model | Licence | Commercial use |
|---|---|---|
| GNM Head v3 (Google) | Apache-2.0 (tongue meshes MIT) | Yes, no field-of-use restriction. The default head model |
| FLAME 2023 Open | CC-BY-4.0 with two extra bans: no pornographic use, no "fake, misleading or defamatory" content | Yes, with attribution; the extra clauses propagate (R6), so it is a secondary fit, never the default basis of an export |
| MHR (Meta Momentum Human Rig) | Apache-2.0 | Yes. The default body model (neck, shoulders, torso) |
| FLAME 2017 / 2019 / 2020 / 2023 (academic) | MPI non-commercial research licence | No (separate licence required) |
| Basel Face Model | Non-commercial | No |
| ICT-FaceKit (light) | MIT | Yes |
| ARKit face topology and blendshape targets | Produced at runtime by Apple's framework | Embedded in every capture that holds face-tracking data ([prsncap.md](prsncap.md) §3.2); the writer is responsible for having the right to redistribute it |
| SMPL-X (body) | Non-commercial | No (separate licence required) |

Licence constraints propagate through derivations (R6): every derived entry's
`derivation.license_constraints` is the union of its models' `use_restrictions` and its
inputs' constraints, and exporters check that union against the intended use.

## Synthetic output and acceptable use

- Every entry in `generation/` carries `"synthetic_capable": true`.
- Generated output never goes into `samples/` or `training/`. A clone's audio or a LoRA's
  image is not evidence of the person, and feeding it back would train the file on itself.
  A writer MUST refuse to write a `samples/` or `training/` entry whose origin is marked
  generated (`origin.synthetic: true`).
- Anything rendered from a generation asset MUST be marked as AI-generated with a C2PA
  content credential.
- Writers MUST honour the acceptable-use terms of the models involved (for example FLAME
  2023 Open's ban on pornographic use) and SHOULD pass them on in the file.

## Security

### Integrity and signing

Every entry is hashed in the manifest. `signatures/manifest.sig` is a detached Ed25519
(RFC 8032) signature over the [canonical JSON](#canonical-json) bytes of the whole
`manifest.json`, `signature` block included. The signature is stored **raw (64 bytes)**,
so nothing is circular. The block:

```json
"signature": {"path": "signatures/manifest.sig", "alg": "Ed25519",
              "key_id": "<first 16 hex digits of SHA-256(public key)>",
              "public_key": "<raw 32-byte public key, standard base64 with padding>"}
```

A reader:

- with no `signature` block, reads the file as unsigned;
- MUST refuse a file whose manifest names a signature file the package does not carry;
- MUST refuse a file whose `key_id` is not the first 16 hex digits of SHA-256 over the
  decoded `public_key`;
- MUST refuse a file whose Ed25519 signature does not verify over the canonical manifest
  bytes (the manifest was altered after signing);
- treats a signature with an algorithm it does not implement as present but unverified.

**Keys are per install.** Each installation of a writing application has its own Ed25519
key pair, generated locally and never synced between installs or devices. The signature
identifies the install (the key) that wrote the file, not a person. Readers keep a list of
trusted public keys (or `key_id`s); a valid signature by a key not on that list proves
integrity only, and the reader applies the tier rule in
[Provenance tiers](#provenance-tiers). Ed25519 signatures are deterministic (RFC 8032); a signer whose signatures
are randomised produces different but equally valid bytes. Vectors:
[`conformance/hash/`](../conformance/hash/).

### Confidentiality, per entry

An encrypted entry has `"enc": {"alg": "AES-256-GCM", "kid": "…", "nonce": "…"}`, and the
file stores ciphertext. The manifest's hash covers the ciphertext. `person.json` and the
manifest stay plaintext unless `"redact": true` is set on the manifest, which encrypts
`person.json` as well. A reader without the key keeps encrypted entries and copies them
through.

### Protected templates

Protected templates (ISO/IEC 24745) carry `"protected": {"scheme": "…", "kid": "…"}`. They
can only be compared within the same scheme and key, and readers MUST NOT treat them as
raw vectors.

## Expiry

An entry's `expires` follows the retention period of the data it came from. Readers drop
expired entries on load and don't write them out again.

## Conformance

[`conformance/`](../conformance/) holds one invalid file per rule, valid files a reader
must notice something about, and byte-level vectors. Rule ids used there:

| Rule | Meaning |
|---|---|
| `container` | ZIP: `mimetype` first, STORED, no extra field, a `.prsn` value; no duplicate member names |
| `version` | `format: "prsn"`, `version` an integer ≤ the reader's (1), `spec` is `<major>.<minor>` |
| `paths` | entry paths follow the path rule, including the three allowed depths; each path is listed once |
| `manifest-hash` | every listed entry is present and its size and SHA-256 match |
| `signature` | the signature file is present, `key_id` matches `public_key`, Ed25519 verifies |
| `critical` | no `critical: true` entry of a type the reader does not know |
| `person` | `person.json` is a listed entry with `id` and `display_name` (after the legacy mapping, for files before 1.1) |
| `spec-fields` | `origin` on `samples/` and `training/`; spec ≥ 1.1: `derivation`, `look`/`era`, and `frame` (spatial modalities) where required |
| `looks-eras` | every `look` is `"*"` or declared; every `era` is declared; each look is in exactly one era |
| `capture-ref` | the payload is a list (or one object) of refs with a SHA-256 `manifest_sha256` |
| `generation` | `generation/` entries carry `synthetic_capable: true`; no generated material in `samples/` or `training/` |
| `type-fields` | every entry carries the MUST fields of its record type (`source_format` on audio from a floating-point capture) |
| `entry-order` | spec ≥ 1.1: `entries` sorted by path in UTF-8 byte order |

## Appendix A: Legacy v1 namespace

Files written under the first version of this format use an older namespace. They remain
readable:

- Readers SHOULD accept both mimetypes: `application/vnd.prsn+zip` and
  `application/vnd.museli.prsn+zip`.
- Readers SHOULD treat `org.museli.<x>` and `org.prsn.<x>` as the same type for every
  `<x>` defined in both. Writers emit `org.prsn.*`.
- A reader that knows only the legacy names treats `org.prsn.*` entries as unknown and
  non-critical, so it keeps them byte for byte; nothing is lost on a round trip. A reader
  that checks the mimetype exactly may refuse current files.
- Frame name alias from the first draft of 1.1: `arkit-face-anchor` ≡ `arkit-face`.
  Readers accept it; writers emit `arkit-face`.

## Decisions (draft v1.1)

1. **Namespace:** `org.prsn`, `application/vnd.prsn+zip` and the CBEFF codes stay, marked provisional; they will be registered (IANA vendor tree) at format version 1.0.
2. **Signing keys:** one Ed25519 key per install, never synced; the signature identifies the install; readers keep a trusted-keys list.
3. **Avatar payload:** binding attributes stay trainer-defined behind a named `binding` (with `formulation` and per-basis deltas); a standard layout comes later.
4. **Remote-processing consent:** `consent.cloud_families` is per method family; `"*"` means all families.
5. **ARKit face template:** every capture with face-tracking data embeds the topology and the 52 blendshape targets, and per-frame data references them by hash; the writer is responsible for redistribution rights.
6. **`frame`:** required only for spatial modalities (face, head, body); voice entries omit it.
7. **Path depth:** depth 1 is `person.json` only, depth 2 is `<modality>/<name>.json` index records only (capture references, coverage), everything else is `<modality>/<role>/<name>` or deeper.
8. **`person.json`:** readers MUST map legacy `name`, `ids` and `links` objects to the current shape; writers always write `display_name` and arrays.
9. **Tier downgrade:** untrusted `enrolled` and `professional` both become `imported`, with `origin.was` and template `evidence` moved to `imported`.
10. **MUST vs SHOULD fields:** each record table separates the fields a reader needs (MUST, schema-enforced) from recommended ones (SHOULD).
11. **Face eviction:** the same procedure as voice, counting entries, per look, with angle-bin and expression-class floors.
12. **Entry order:** writers MUST sort entries by path; readers MUST NOT depend on order and accept unsorted legacy files.
13. **Archive size:** readers MUST accept at least 4 GiB uncompressed (ZIP64 required) and MAY refuse larger.
14. **Recipe version:** Semantic Versioning (`MAJOR.MINOR.PATCH`, pre-release allowed); a major bump means outputs are not comparable.
15. **Empty split groups:** a phase with rows but no held-out frame is listed with `"frames": []`.
16. **Float audio:** stored as 24-bit integer FLAC, with the source sample format recorded in `source_format` (for example `"f32"`).
