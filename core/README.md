# core

Rules shared by `.prsn`, `.styl` and `.scen`, and the pieces that let the three work
together.

| Document | Covers |
|---|---|
| [spec/core.md](spec/core.md) | Which `.prsn` rules are shared and how each format parameterises them; the `attributes/` role; the `authored` tier, anchors and lineage; index records (captions, reference sets, descriptors, held-out splits); image adapter, adapter and vendor references; references between files; consistency metrics |

## Schemas

[`schemas/`](schemas/) (JSON Schema draft 2020-12, `$id` under
`https://github.com/jaredzimmerman/digitaltwins/core/schemas/`). They reference the shared
definitions in [`../prsn/schemas/defs.schema.json`](../prsn/schemas/defs.schema.json) by
absolute `$id`, so load the `prsn`, `core` and format schema folders into one registry.

| Schema | Validates |
|---|---|
| `entry.schema.json` | Container fields and role rules for `.styl` and `.scen` entries |
| `rules.schema.json` | One `$def` per shared rule: `authoredSynthetic`, `anchorRule`, `renderRule`, `attributesRule`, `indexRecord`, `vendorRef`, `adapterRef`, `imageAdapter` (also applied to `.prsn` from spec 1.2) |
| `captions.schema.json`, `refset.schema.json`, `descriptor.schema.json`, `holdout.schema.json` | Index record payloads (core §5) |
| `refs.schema.json` | `manifest.refs` (core §7) |
| `state.schema.json` | `manifest.variants[]` (`.styl`) and `manifest.states[]` (`.scen`) |

## Tools

- `tools/validate.py`: validates the `.styl` and `.scen` examples and checks every
  conformance case (`uv run --with jsonschema python core/tools/validate.py`, from the
  repository root).
- `tools/build_examples.py`: regenerates them deterministically (standard library only).

`.prsn` keeps its own validator and builder in [`../prsn/tools/`](../prsn/tools/); they load
the core schemas too.
