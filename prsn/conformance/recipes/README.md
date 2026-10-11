# Recipe descriptor cases

For [spec/derivation-recipes.md](../../spec/derivation-recipes.md) §2. The valid toy
registry is in `examples/recipes/`.

## `invalid.json`

Descriptors that must be rejected, one rule broken each, each a variant of the toy rank-10
splat recipe. `expect_code` names the broken rule:

| Variant | Code | Broken rule |
|---|---|---|
| `cuda_without_reason` | `cuda-without-reason` | `cuda` recipe without `local_infeasible_reason` |
| `cuda_without_trigger` | `cuda-without-trigger` | `cuda` recipe without `return_local_trigger` |
| `cuda_empty_reason` | `cuda-without-reason` | `local_infeasible_reason` is empty |
| `unknown_compute` | `bad-compute` | `needs.compute` not in the fixed set |
| `unpinned_model` | `unpinned-model` | a model whose `sha256` is not a hash |
| `unknown_metric` | `bad-metric` | `eval.metric` not a fixed name |
| `bad_version` | `bad-version` | `version` not `MAJOR.MINOR.PATCH` |
| `negative_rank` | `bad-rank` | `rank` below 0 |
| `family_without_prefix` | `bad-family` | `family` not reverse-DNS |
| `missing_eval` | `bad-eval` | `eval` missing |
| `bad_determinism` | `bad-determinism` | `determinism` not in the fixed set |
| `dep_on_own_family` | `dep-cycle` | a recipe depends on its own family |
| `requires_not_list` | `bad-requires` | `requires.all` is not a list |

## `registries/`

Registry folders that must fail as a whole:

| Folder | Code | Problem |
|---|---|---|
| `duplicate-rank/` | `duplicate-rank` | two `static-splat` recipes share rank 10 |
| `misplaced-file/` | `bad-file-name` | a `static-splat` recipe stored under `masks/` |
| `family-cycle/` | `dep-cycle` | `masks` depends on `static-splat`, which depends on `masks` |
