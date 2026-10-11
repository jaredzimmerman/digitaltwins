# styl

`.styl` is a portable, application-independent file that describes one visual style: the
exemplars that define it, its written attributes (palette, typography, rendering rules),
the embeddings used to measure it, and the generators built from it for any image model
(LoRAs, adapter recipes, vendor style handles), with the recipes that made each one.

Status: **Draft 1.0**. Files declare `"format": "styl"`, `"version": 1`, `"spec": "1.0"`.

The container, manifest, derivation, provenance, budget, licence and security rules are
shared with `.prsn`; see [digitaltwins core](../core/spec/core.md).

```
harbor-ink.styl
├── mimetype          application/vnd.styl+zip
├── manifest.json
├── style.json        name, kind, rights (no images)
├── style/
│   ├── captions-*.json  refset-*.json  descriptor.json  holdout.json
│   ├── samples/      exemplars across content classes (the definition)
│   ├── attributes/   DTCG palette and typography, rendering rules, bible
│   ├── templates/    style embeddings
│   ├── training/     curated training sets
│   └── generation/   LoRAs, embeddings, adapter refs, vendor refs, prompt fragments
└── signatures/manifest.sig
```

| Document | Covers |
|---|---|
| [spec/styl.md](spec/styl.md) | The format |
| [schemas/](schemas/) | `styl-manifest`, `styl-entry` (per-record MUST fields), `style` (the subject record) |
| [examples/harbor-ink/](examples/harbor-ink/) | An original style: two authored anchors, an imported exemplar with its rights, an approved synthetic exemplar at lineage 1, day and night palette variants, rendering rules and a bible, a CSD template with its spread, captions that exclude style, a 3-style-slot reference set, a descriptor, a held-out split, a training set, a style LoRA scored with `csd-csls`, a zero-shot adapter recipe, a vendor style handle and a prompt fragment |
| [conformance/](conformance/) | One file per rule, listed in `rules.json` |

## Validating

From the repository root:

```sh
uv run --with jsonschema python core/tools/validate.py
python3 core/tools/build_examples.py   # regenerate examples and cases
```
