# digitaltwins

Open file formats for portable digital twins of people. Each format is an
application-independent file that any program can read and write, and that keeps the raw
material its assets were made from, so newer methods can re-derive them later.

| Format | What it is | Spec |
|---|---|---|
| `.prsn` | A person: identity, face and head geometry, appearance (Gaussian splats, stills), voice, and the recipes that produced each asset. Its companion `.prsncap` holds the raw capture session. | [`prsn/`](prsn) |
| `.styl` | Planned. | — |
| `.scen` | Planned. | — |

Each format lives in its own folder with its specification, JSON Schemas, examples,
conformance cases and tools.

## Validating

```sh
cd prsn
uv run --with jsonschema python tools/validate.py
```

## Status

Draft. The specifications may still change before a 1.x release; see each format's README.

## Licence

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
