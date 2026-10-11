# Derivations and recipe descriptors

Status: **Draft v1.1**. Part of the [`.prsn` specification](prsn.md).

This is the mechanism behind "never rescan": every derived asset says exactly how it was
made, so it can be remade, by any implementation, with a better recipe from the same raw
captures.

## 1. The `derivation` block

Required (`spec` ≥ 1.1) on every `.prsn` entry under `geometry/`, `generation/` and
`templates/`, and on every cache item. Optional on `samples/` (a still cut from a capture
is derived too). Schema: [`derivation.schema.json`](../schemas/derivation.schema.json).

```json
"derivation": {
  "family": "org.prsn.method.static-splat",
  "recipe": {"id": "org.example.recipe.splat.mcmc", "version": "1.2.0", "rank": 40},
  "tool":   {"name": "example-writer", "version": "1.0.0", "build": "git:3f9c2e1",
             "platform": "macOS 27.0 / Apple M3"},
  "models": [
    {"role": "segmenter", "key": "sam2.1-hiera-large", "sha256": "…", "license": "Apache-2.0"},
    {"role": "head-model", "key": "gnm-head-v3", "sha256": "…", "license": "Apache-2.0", "use_restrictions": []}
  ],
  "inputs": [
    {"capture": "sha256:<manifest hash>", "look": "look-2026-10", "era": "era-1",
     "select": {"streams": ["d0/rgb.front", "d0/depth.front"], "phases": ["orbit", "face"], "exclude_split": "holdout"}},
    {"cache": "sha256:<action_key of the mask job>", "role": "masks"},
    {"entry": "face/geometry/gnm-head.fit.npz", "sha256": "…", "role": "init-mesh"}
  ],
  "params": {"iterations": 30000, "sh_degree": 3, "densify": "mcmc", "cap": 600000, "seed": 1234},
  "action_key": "sha256:…",
  "determinism": "bitwise" | "seeded-nonbitwise" | "none",
  "eval": {"split": "holdout", "metric": "psnr", "value": 31.8, "extra": {"lpips": 0.071},
           "per_capture": [{"capture": "sha256:…", "value": 31.8}]},
  "supersedes": "sha256:<previous entry sha256>" | null,
  "created": "2026-11-14T03:12:09Z", "duration_s": 1840,
  "license_constraints": ["no-pornographic-use"]
}
```

`family`, `recipe` (`id`, `version`), `action_key` and `determinism` are required. Each
input carries **exactly one** content hash: `capture` (a capture's manifest content id),
`cache` (a cache item's `action_key`) or `sha256` (a `.prsn` entry's hash, with its `entry`
path for readability).

### Rules

- **R1 `action_key`** = `"sha256:" + hex(SHA-256(canonical JSON of the preimage))`, where
  canonical JSON is the rule in [prsn.md](prsn.md#canonical-json) and the preimage is:

  ```
  {"family":  derivation.family,
   "recipe":  {"id": derivation.recipe.id, "version": derivation.recipe.version},
   "models":  [derivation.models[].sha256 …]   sorted by UTF-8 bytes, duplicates kept,
   "params":  derivation.params                 ({} when absent or null),
   "inputs":  [resolved input …]                sorted by the UTF-8 bytes of each one's canonical JSON}
  ```

  A resolved input keeps only the keys `capture`, `cache`, `sha256`, `role` and `select`
  (whichever are present) and drops everything else (`look`, `era`, an entry's `entry`
  path, unknown keys). `models` or `inputs` absent or null mean `[]`. Not in the key:
  `recipe.rank`, `tool` (including `tool.build`), `determinism`, `eval`, `supersedes`,
  `created`, `duration_s`, `license_constraints`, and `action_key` itself. A derivation
  whose input lacks a single string content hash, or that lacks `family` or
  `recipe.version`, has a model without `sha256`, or has non-object `params`, has no key.

  Two derivations with the same key are interchangeable; an implementation looks the key
  up before recomputing anything. `tool.build` is recorded but is not part of the key, so
  that a tool update does not invalidate every cached result: a recipe whose output
  changes with the tool must bump `recipe.version`, and R5's `eval` verifies any
  non-bitwise re-derivation. When a recipe wraps an external tool pinned to a commit, the
  pin is part of `recipe.version` by convention (bump the recipe when the pin moves).

  Vectors: [`conformance/hash/action_key.json`](../conformance/hash/action_key.json).
- **R2 Inputs are content hashes, never paths.** A capture is its manifest hash. A
  `select` is part of the input. A cache item is its `action_key`. A `.prsn` entry is its
  `sha256`.
- **R3 Staleness.** An entry is stale when an input hash cannot be resolved (capture
  demoted or deleted, cache purged and not re-creatable) or when an input cache item was
  recomputed with a different output hash. Staleness propagates down the input graph.
  Stale entries stay usable but are flagged and cannot be the `supersedes` target of an
  automatic upgrade.
- **R4 Upgrade.** See §3.
- **R5 Determinism is declared.** `bitwise` (fixed seeds, verified by re-running),
  `seeded-nonbitwise` (typically GPU), `none`. Re-derivation is verified by `eval`, not by
  hash, unless `bitwise`.
- **R6 Licences propagate.** `license_constraints` = the union of the models' and inputs'
  constraints. Exporters refuse an export whose intended use is in the union.
- **R7 Live-session outputs** (on-device coverage, proxies) are derived too;
  `tool.platform` names the device. They are not archived.
- **R8 Generated media** rendered from a `generation/` asset carry a C2PA manifest whose
  ingredients include the asset's `action_key` and the source capture hashes.

## 2. Recipe descriptors

A recipe registry is a directory of JSON files, one per recipe, at
`<family-short>/<id>@<version>.json`, where `<family-short>` is the last label of the
family (`static-splat` for `org.prsn.method.static-splat`). Schema:
[`recipe.schema.json`](../schemas/recipe.schema.json). Example:

```json
{
  "id": "org.example.recipe.splat.mcmc", "version": "1.2.0",
  "family": "org.prsn.method.static-splat", "rank": 40,
  "produces": {"type": "org.prsn.face.splat", "path_template": "face/geometry/splat-{look}.glb"},
  "requires": {"all": ["rgb.*", "depth.truedepth"], "any": ["tracking.arkit-face", "landmarks.any"], "min_captures": 1},
  "needs": {"compute": "metal", "ram_gb": 12, "disk_gb": 20, "est_minutes": 40},
  "models": [{"role": "segmenter", "key": "sam2.1-hiera-large", "sha256": "…", "license": "Apache-2.0", "source": "https://…"}],
  "deps": [{"family": "org.prsn.method.masks", "role": "masks", "min_rank": 10},
           {"family": "org.prsn.method.poses", "role": "poses", "min_rank": 10}],
  "params_schema": {"$ref": "schemas/splat-params.json"},
  "params_default": {"iterations": 30000, "sh_degree": 3, "densify": "mcmc", "seed": 1234},
  "determinism": "seeded-nonbitwise",
  "eval": {"metric": "psnr", "higher_is_better": true, "min_improvement": 0.3, "no_regression_per_capture": 0.5},
  "license_constraints": []
}
```

Other fields (for example how an application runs the recipe) are allowed.

- `id` is reverse-DNS; `family` is reverse-DNS.
- `version` (here and in `derivation.recipe.version`) follows Semantic Versioning 2.0.0:
  `MAJOR.MINOR.PATCH`, optionally with a pre-release suffix (`1.3.0-rc.1`) or build metadata.
  A **major** bump means the recipe's outputs are not comparable with earlier majors (for
  example a different metric scale or output type); minor and patch bumps produce
  comparable outputs. Any change to the output bumps at least the patch (R1).
- `rank` (an integer ≥ 0) orders recipes within a family; higher is preferred. Two recipes
  MUST NOT share a rank within a family.
- `requires` matches capability tags ([prsncap.md](prsncap.md) §4.1): `all` tags must all
  be present, at least one of `any`; `*` is a wildcard; a `?` suffix marks a tag optional
  (it only affects `params`). `min_captures` is the fewest captures the recipe needs. For
  multi-capture assets every referenced capture must meet `requires`, unless
  `requires.mode` is `"any-capture"`.
- `needs.compute` ∈ `cpu`, `metal`, `mlx`, `mps`, `cuda`. A `cuda` recipe MUST also carry
  a non-empty `local_infeasible_reason` (why it can't run locally today) and a non-empty
  `return_local_trigger` (what change would move it back). A job is sent off the local
  machine only when the person's `consent.cloud_families` lists the family (or holds `"*"`,
  meaning every family) and the person approved that job.
- `models` pin every model by `sha256`, with its `license`.
- `deps` name other families whose current best entry is an input (resolved by hash when
  the job is planned). A family MUST NOT depend on itself, and family dependencies MUST
  NOT form a cycle.
- `determinism`: as R5. `eval.metric` is one of the fixed names: `psnr`, `lpips`, `ssim`
  (image synthesis families); `p2p-mm` (point-to-plane distance against held-out depth;
  geometry families); `landmark-px` (fits, landmarks on held-out frames);
  `coverage-fraction`; `auraface-sim` (stills-bank consistency); `none` (export families,
  which are adopted when their inputs are).

Method families defined so far (short names, under `org.prsn.method.`): `masks`,
`keyframes`, `calib-fit`, `poses`, `depth-fuse`, `head-fit` (sub-key per model:
`gnm-head`, `flame-2023-open`, `ict-facekit`), `expression-map`, `expression-track`,
`static-splat`, `splat-display`, `stills-bank`, `lora-export`, `probe-hdr`, `colour-ccm`,
`coverage`, `admit`, `tier-demote`, `multiview-calibration`, `body-fit`, `avatar`,
`avatar-distill`.

## 3. Upgrades and adoption (R4)

For each person, each look/era and each family:

1. **Resolve** the current best entry (highest rank, not stale) and its inputs.
2. **Candidates** are recipes in the family with a higher rank whose `requires` are met by
   the referenced captures' `capabilities` and whose `deps` resolve.
3. **Reuse** a result with the same `action_key` when one exists; otherwise run the recipe.
4. **Score** on the union of the input captures' `splits.json` held-out sets with the
   family's metric; record `eval.per_capture`.
5. **Adopt** only if `value` improves on the current entry by at least `min_improvement`
   **and** no `per_capture` value gets worse by more than `no_regression_per_capture`. On
   adoption set `supersedes` and keep the previous entry (flagged `superseded`) until the
   user confirms. Families with metric `none` adopt when their inputs changed.

Staleness (R3) is recomputed before candidates are chosen.

## 4. Conformance

- [`conformance/hash/action_key.json`](../conformance/hash/action_key.json): preimage and
  key vectors, and derivations that must be rejected.
- [`examples/recipes/`](../examples/recipes/): a valid toy registry (two families, ranks
  10/20/30, one `cuda` recipe).
- [`conformance/recipes/`](../conformance/recipes/): descriptors and registries that must
  be rejected, one rule each.
