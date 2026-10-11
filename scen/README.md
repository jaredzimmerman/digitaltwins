# scen

`.scen` is a portable, application-independent file that describes one place (a room, a
street, a set, real or fictional) and its props: the photographs and captures it was
recorded from, the geometry rebuilt from them, the lighting and dressing states it appears
in, and the generators built from it for any image model. Cast and style are referenced
(`.prsn`, `.styl`), never copied in.

Status: **Draft 1.0**. Files declare `"format": "scen"`, `"version": 1`, `"spec": "1.0"`.

The container, manifest, derivation, provenance, budget, licence and security rules are
shared with `.prsn`; see [digitaltwins core](../core/spec/core.md). Raw capture sessions go
in a `.scencap`, which uses the `.prsncap` layout.

```
north-pier-kitchen.scen
├── mimetype          application/vnd.scen+zip
├── manifest.json     states, props, refs (cast, style), entries
├── scene.json        name, kind, coarse location, rights (no images)
├── place/
│   ├── capture-refs.json  coverage-*.json  captions-*.json  refset-*.json  descriptor.json  holdout.json
│   ├── samples/      photographs, people masked
│   ├── geometry/     splat (glTF KHR_gaussian_splatting), mesh, layout, camera rigs
│   ├── attributes/   lighting per state, palette, bible
│   ├── templates/    place embeddings
│   ├── training/     curated sets, renders of captured geometry
│   └── generation/   location LoRAs, adapter refs, vendor world ids
├── prop/             samples/ geometry/ attributes/ generation/, each entry naming its prop
└── signatures/manifest.sig
```

| Document | Covers |
|---|---|
| [spec/scen.md](spec/scen.md) | The format |
| [schemas/](schemas/) | `scen-manifest`, `scen-entry` (per-record MUST fields), `scene` (the subject record) |
| [examples/north-pier-kitchen/](examples/north-pier-kitchen/) | A real place: enrolled photographs (one with people masked), a prop sample, a splat, layout and camera rigs in `scene-canonical`, lighting per state, a DINOv2 template, a render in `training/`, captions that exclude the place, a reference set that includes a render, a confirmed descriptor, a held-out split, a location LoRA scored with `dino-cos`, a vendor world id, and refs to a style and a cast member |
| [examples/fictional-harbor-set/](examples/fictional-harbor-set/) | A fictional place: authored concept art as the anchor, an approved generated view at lineage 1, and an authored (modelled) set mesh |
| [conformance/](conformance/) | One file per rule, listed in `rules.json` |

## Validating

From the repository root:

```sh
uv run --with jsonschema python core/tools/validate.py
python3 core/tools/build_examples.py   # regenerate examples and cases
```
