# prsn

`.prsn` is a portable, application-independent file that describes one person's face,
head and voice assets, together with references to the raw capture they were derived
from, so the assets can be re-derived with better methods later without rescanning the
person. `.prsncap` is its companion file: the raw capture session itself (video, depth,
stills, calibration, tracking, IMU, audio), written once and never changed.

This repository holds the format specification, JSON Schemas for every JSON record the
format defines, example files, conformance test cases, and a small validator. It contains
no application code.

Status: **Draft v1.1**. Files declare `"version": 1` and `"spec": "1.1"`.

## What is in a `.prsn`

A ZIP container (EPUB-style: a `mimetype` member first, then everything else) or the same
tree as a directory:

```
alex-chen.prsn
├── mimetype          application/vnd.prsn+zip
├── manifest.json     every entry with its SHA-256, size, media type and record type
├── person.json       who the file is about (no biometrics)
├── face/  voice/  body/
│   ├── samples/      raw material any future model can re-derive from
│   ├── templates/    model-specific recognition data
│   ├── geometry/     meshes, landmarks, model coefficients, splats
│   ├── training/     material that trains a generator
│   └── generation/   generative assets (avatars, LoRAs, voice seeds)
└── signatures/
    └── manifest.sig  Ed25519 over the canonical manifest
```

Key properties:

- **One index.** The manifest lists and hashes every entry; nothing else counts.
- **Extensible without version bumps.** Record types are reverse-DNS strings; readers
  skip and preserve types they don't know, and refuse only unknown `critical` entries.
- **Provenance first.** Every sample records how it was captured (`professional`,
  `enrolled`, `imported`, `observed`), and the tier outranks the quality score.
- **Re-derivable.** Derived entries carry a `derivation` block: the recipe, models and
  input content hashes, and an `action_key` that identifies the computation.
- **Bounded.** Budgets and an eviction order keep the best material as a file is enriched
  over time.
- **Licence-aware.** Model-bound entries name their model and licence, and licence
  restrictions propagate to everything derived from them.

## Specification

| Document | Covers |
|---|---|
| [spec/prsn.md](spec/prsn.md) | The `.prsn` container, manifest, record types, tiers, budgets, security |
| [spec/prsncap.md](spec/prsncap.md) | The `.prsncap` capture file: layout, `session.json`, `splits.json`, IMU records |
| [spec/voice.md](spec/voice.md) | The voice modality: sample bank, templates, seeds, eviction procedure |
| [spec/frames-and-units.md](spec/frames-and-units.md) | Coordinate frames, transforms, units, clocks |
| [spec/derivation-recipes.md](spec/derivation-recipes.md) | The `derivation` block, `action_key`, recipe descriptors |
| [spec/enrichment-model.md](spec/enrichment-model.md) | Sessions, looks, eras, coverage, per-look budgets |

The decisions taken for this draft are listed at the end of [spec/prsn.md](spec/prsn.md#decisions-draft-v11).

## Schemas

[`schemas/`](schemas/) holds JSON Schema (draft 2020-12) files for the manifest, entries,
`person.json`, capture references, the derivation block, looks, eras, budgets, coverage
records, recipe descriptors, and the `.prsncap` manifest, `session.json`, `splits.json`,
capture script and `imu.json`. See [schemas/README.md](schemas/README.md).

## Examples and conformance

- [`examples/`](examples/): valid `.prsn` packages (spec 1.1 face and voice files, a 1.0
  legacy file), a minimal `.prsncap`, and a toy recipe registry.
- [`conformance/`](conformance/): one invalid file per rule, ZIP container cases, and
  capture cases, and vectors for canonical JSON, SHA-256, `action_key`, Ed25519,
  manifests, splits, IMU records, coordinate frames, tier downgrade and eviction.

The example signing key is a published test key; never add it to a trusted-keys list.

## Validating

```
uv run --with jsonschema python tools/validate.py
```

Requires Python 3.11 or later and `jsonschema`. It validates every example against the
schemas, checks hashes and signatures, checks that every conformance case fails for its
stated rule (or passes, for the valid ones), and runs the byte-level vectors.
`tools/build_vectors.py` regenerates the examples and every derived value (hashes,
signatures, preimages) deterministically, using only the Python standard library.

## Licence

Apache License 2.0. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
