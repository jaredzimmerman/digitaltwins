# Examples

Valid files. Every one passes `tools/validate.py`. They are tiny: media payloads are
stubs with the right magic bytes, not real images or audio. All are signed with the
published test key (seed = SHA-256 of `prsn-example-signing-key`); regenerate them with
`python3 tools/build_vectors.py`.

## `prsn/` (directory form)

| Package | What it shows |
|---|---|
| `valid-v11/` | A spec 1.1 file: one face sample, one GNM head mesh with a `derivation`, one look and one era, a capture-ref **list**. Valid with no notes. |
| `valid-v10-legacy/` | A spec 1.0 file: no `spec`, no looks/eras/frames/derivations, and a capture-ref written as a single object under the legacy type name `org.museli.face.capture-ref`. Valid; a 1.1 reader fills `look: "*"`, `era: "era-0"`, `frame` from `topology` (`gnm-head-v3` → `head-canonical`) and flags the entries legacy. |
| `voice-v11/` | A spec 1.1 voice file: a template with its evidence mix, one bank sample (float capture, so `source_format: "f32"`) with quality components, a seed pinned to its source sample, a generation record, and voice budgets. Voice entries are identity-level (`look: "*"`), carry derivations, and have no `frame` (voice is non-spatial). |
| `fictional-v12/` | A spec 1.2 fictional character (`person.json` `kind: "fictional"`): an authored model-sheet anchor and a full-body anchor, two approved synthetic views at lineage 1 with admit scores, a held-out split, natural-language captions that exclude identity, a reference set for a 4-character-slot model, an authored descriptor, a LoRA trained on the non-held-out samples with `training_captions` and an `arcface-cos` eval, and a non-portable vendor reference. Looks have no sessions. |

A ZIP-form copy of `valid-v11` is `conformance/container/valid.prsn`.

## `prsncap/minimal-depth.prsncap/`

A minimal synthetic capture: one device, a depth stream with two phases (one dropped
frame), a face-tracking phase with tracking frames, per-frame face vertices and depth, the
embedded ARKit face template (topology and 52 blendshape targets, zero-filled stand-ins of
the real sizes) referenced by hash, calibration with distortion LUTs, the capture script,
`session.json`, `splits.json` and a signed manifest. The validator checks the manifest,
hashes, signature, every JSON record against its schema, the template references, and that
`splits.json` matches the seeded-stride rule for the depth and tracking streams.

## `recipes/`

A toy recipe registry laid out as `<family-short>/<id>@<version>.json`: family `masks`
(one recipe, rank 10, `cpu`) and family `static-splat` (ranks 10 and 20 on `metal`, rank
30 on `cuda` with the required `local_infeasible_reason` and `return_local_trigger`). Each
splat recipe depends on `masks`; rank 20 pins one model and uses optional `?` tags.
