# Schemas

JSON Schema, draft 2020-12. Each file's `$id` is
`https://github.com/jaredzimmerman/digitaltwins/prsn/schemas/<name>.schema.json`, and cross-references
are relative, so load them all into one registry (as `tools/validate.py` does).

Schemas are strict where the specification says MUST and open (`additionalProperties`
allowed) where it lets records carry extra fields, because readers keep fields they do not
understand.

| Schema | Validates | Spec |
|---|---|---|
| `defs.schema.json` | Shared definitions: hashes, content ids, paths, record types, dates, `origin`, `quality`, `pose`, `model`, `signature`, `enc`, `protected` | [prsn.md](../spec/prsn.md) |
| `prsn-manifest.schema.json` | `.prsn` `manifest.json`, including the spec ≥ 1.1 field requirements | [prsn.md](../spec/prsn.md#manifestjson) |
| `prsn-entry.schema.json` | One `manifest.entries[]` row; its `$defs` hold the per-rule checks (`depthRule`, `originRule`, `notGeneratedRule`, `generationRule`, `typeRules` for MUST fields, `v11Fields`) | [prsn.md](../spec/prsn.md#fields-common-to-all-entries) |
| `person.schema.json` | `person.json` | [prsn.md](../spec/prsn.md#personjson) |
| `capture-refs.schema.json` | The `org.prsn.face.capture-ref` payload (a list, or one object) | [prsn.md](../spec/prsn.md#companion-capture-file-prsncap) |
| `derivation.schema.json` | The `derivation` block | [derivation-recipes.md](../spec/derivation-recipes.md) |
| `look.schema.json`, `era.schema.json` | `manifest.looks[]`, `manifest.eras[]` | [enrichment-model.md](../spec/enrichment-model.md) |
| `budgets.schema.json` | `manifest.budgets` | [prsn.md](../spec/prsn.md#budgets), [voice.md](../spec/voice.md) |
| `coverage.schema.json` | The `org.prsn.face.coverage` payload | [enrichment-model.md](../spec/enrichment-model.md) §6 |
| `recipe.schema.json` | A recipe descriptor | [derivation-recipes.md](../spec/derivation-recipes.md) §2 |
| `prsncap-manifest.schema.json` | `.prsncap` `manifest.json` | [prsncap.md](../spec/prsncap.md) §3 |
| `session.schema.json` | `.prsncap` `session.json` (`consent.cloud_families` accepts `"*"`) | [prsncap.md](../spec/prsncap.md) §4 |
| `splits.schema.json` | `.prsncap` `splits.json` | [prsncap.md](../spec/prsncap.md) §5 |
| `script.schema.json` | `.prsncap` `script/script.json` | [prsncap.md](../spec/prsncap.md) §7 |
| `imu.schema.json` | `.prsncap` `motion/imu.json` | [prsncap.md](../spec/prsncap.md) §3.1 |

Some rules are not expressible in a schema and are checked by `tools/validate.py` instead:
entry hashes and sizes, signatures and `key_id`, duplicate paths, look/era references,
unknown `critical` types, `version` newer than the reader, entry order, the legacy `person.json` mapping, embedded ARKit template references, ZIP member order and
compression, recipe file placement, rank uniqueness and dependency cycles.
