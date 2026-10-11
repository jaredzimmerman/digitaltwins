# digitaltwins

Open file formats for portable digital twins of people, visual styles and places. Each
format is an application-independent file that any program can read and write, and that
keeps the raw material its assets were made from, so newer methods can re-derive them later.

| Format | What it is | Spec |
|---|---|---|
| `.prsn` | A person, real or fictional: identity, face, head and body geometry, appearance (Gaussian splats, stills), voice, and the recipes that produced each asset. Its companion `.prsncap` holds the raw capture session. | [`prsn/`](prsn) |
| `.styl` | A visual style: exemplars across content, palette and rendering attributes, style embeddings, and generators (LoRAs, adapter recipes, vendor style handles) for any image model. | [`styl/`](styl) |
| `.scen` | A place and its props: photographs, geometry (splats, meshes, layout, camera rigs), lighting and dressing states, and generators; cast and style by reference. Its companion `.scencap` uses the `.prsncap` layout. | [`scen/`](scen) |

The three share one architecture (container, manifest, derivations and recipes,
provenance tiers, budgets, licences, signing), summarised in [`core/`](core), which also
defines what they share across formats: captions, reference sets for models that take
reference images, descriptors for models that take only text, held-out splits, the
`authored` tier for subjects with no physical referent, and references between files.

Each format lives in its own folder with its specification, JSON Schemas, examples,
conformance cases and tools.

## Validating

```sh
cd prsn && uv run --with jsonschema python tools/validate.py && cd ..   # .prsn
uv run --with jsonschema python core/tools/validate.py                  # .styl and .scen
```

## Status

Draft (`.prsn` 1.2, `.styl` 1.0, `.scen` 1.0, core 1.0). The specifications may still change
before a stable release; see each format's README.

## Licence

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
