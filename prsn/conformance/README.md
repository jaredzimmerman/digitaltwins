# Conformance

Test material for implementations of the `.prsn` and `.prsncap` formats. `tools/validate.py`
runs all of it. Each folder has its own README.

| Folder | Contents | Spec |
|---|---|---|
| [`prsn/`](prsn/) | One directory-form `.prsn` per rule, plus valid files a reader must notice something about; `rules.json` lists the expected outcome of each | [prsn.md](../spec/prsn.md) |
| [`prsncap/`](prsncap/) | `.prsncap` packages that break one capture rule; `cases.json` | [prsncap.md](../spec/prsncap.md) |
| [`tiers/`](tiers/) | Tier downgrade for untrusted files | [prsn.md, Provenance tiers](../spec/prsn.md#provenance-tiers) |
| [`container/`](container/) | ZIP-form `.prsn` files exercising the container rules; `cases.json` | [prsn.md, Container](../spec/prsn.md#container) |
| [`json/`](json/) | Canonical JSON parse and serialise vectors | [prsn.md, Canonical JSON](../spec/prsn.md#canonical-json) |
| [`hash/`](hash/) | SHA-256, `action_key`, Ed25519 and manifest build/sign vectors | [prsn.md, Security](../spec/prsn.md#security), [derivation-recipes.md](../spec/derivation-recipes.md) |
| [`splits/`](splits/) | Seeded-stride held-out frame selection | [prsncap.md](../spec/prsncap.md) §5 |
| [`imu/`](imu/) | `imu.bin` record decoding and encoding | [prsncap.md](../spec/prsncap.md) §3.1 |
| [`frames/`](frames/) | Coordinate-frame, Euler-angle, bin and back-projection vectors | [frames-and-units.md](../spec/frames-and-units.md) |
| [`eviction/`](eviction/) | The eviction procedure, voice (seconds) and face (counts per look) | [prsn.md, Eviction procedure](../spec/prsn.md#eviction-procedure) |
| [`recipes/`](recipes/) | Recipe descriptors and registries that must be rejected | [derivation-recipes.md](../spec/derivation-recipes.md) §2 |

Everything here is deterministic. `tools/build_vectors.py` regenerates the packages and
every derived value (hashes, signatures, preimages, keys); `tools/gen_frames_vectors.py`
regenerates the frames vectors.
