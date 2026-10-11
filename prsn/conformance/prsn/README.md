# `.prsn` package cases

Directory-form packages, each a copy of an example (`valid-v11` unless noted) with one
change.
`rules.json` lists every case with its `rule`, its `outcome` and `why`:

- `refuse`: a reader MUST refuse to load the file.
- `invalid`: a validator MUST report the `rule`; the file breaks exactly that rule (and
  every other rule passes). Unless the case is about the signature or hashes, the package
  is re-sealed, so hashes and signature still verify.
- `valid`: the file is valid, but a reader must do something specific with it.

Rule ids are defined in [spec/prsn.md, Conformance](../../spec/prsn.md#conformance).

| Case | Rule | Outcome | What changed |
|---|---|---|---|
| `version-too-new` | `version` | refuse | `version: 2`; refuse and show the version |
| `version-not-integer` | `version` | refuse | `version: "1"` (a string) |
| `critical-unknown-type` | `critical` | refuse | adds `com.vendor.face.thing` with `critical: true` |
| `spec11-missing-derivation` | `spec-fields` | invalid | spec 1.1 mesh without `derivation` |
| `sample-missing-origin` | `spec-fields` | invalid | sample without `origin` |
| `look-not-declared` | `looks-eras` | invalid | sample `look` not in `manifest.looks` |
| `generation-not-synthetic-capable` | `generation` | invalid | `generation/` entry without `synthetic_capable: true` |
| `sample-marked-synthetic` | `generation` | invalid | sample with `origin.synthetic: true` |
| `capture-ref-bad-hash` | `capture-ref` | invalid | `manifest_sha256: "not-a-hash"` |
| `spec11-geometry-missing-frame` | `spec-fields` | invalid | spec 1.1 face mesh without `frame` |
| `mesh-missing-topology` | `type-fields` | invalid | a mesh without its MUST field `topology` |
| `voice-float-without-source-format` | `type-fields` | invalid | (from `voice-v11`) a float-captured voice sample without `source_format` |
| `bad-entry-path` | `paths` | invalid | an entry at `face/samples/F-0002.heic` (upper case) |
| `path-two-segments-not-index` | `paths` | invalid | a sample at `face/f-0002.heic`: depth 2 is for `<modality>/<name>.json` index records only |
| `path-one-segment` | `paths` | invalid | a top-level entry `notes.json` other than `person.json` |
| `path-listed-twice` | `paths` | invalid | one path appears twice in `entries` |
| `entries-unsorted` | `entry-order` | invalid | spec 1.1 manifest with entries in reverse path order |
| `person-missing-display-name` | `person` | invalid | spec 1.1 `person.json` written in the legacy shape (`name`, no `display_name`) |
| `manifest-hash-mismatch` | `manifest-hash` | invalid | one byte of `head.glb` flipped after sealing |
| `entry-missing` | `manifest-hash` | invalid | `head.glb` deleted after sealing |
| `signature-manifest-altered` | `signature` | invalid | `created` changed after signing |
| `signature-key-id-mismatch` | `signature` | invalid | wrong `key_id`, re-signed so the signature itself verifies |
| `signature-file-missing` | `signature` | invalid | `signatures/manifest.sig` deleted |
| `unsigned` | | valid | no signature block: read as unsigned, top tiers not vouched for |
| `unlisted-file` | | valid | an extra file not in the manifest: ignored, never written back |
| `expired-entry` | | valid | sample `expires: 2001-01-01`: dropped on load, not written again |
| `retired-scopes-key` | | valid | top-level `scopes`: dropped on load, not written back |
| `unknown-noncritical-type` | | valid | adds `com.vendor.face.thing` (not critical): skipped, carried through |
| `legacy-entries-unsorted` | | valid | (from `valid-v10-legacy`) unsorted entries in a spec 1.0 file: accepted, order never relied on |
| `person-legacy-shape` | | valid | (from `valid-v10-legacy`) `name`, `ids` object, `links` object: mapped to the current shape on read |

The valid examples are listed in `rules.json` under `valid` (they live in `examples/prsn/`).
