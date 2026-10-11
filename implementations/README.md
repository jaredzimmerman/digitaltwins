# Implementations

Reader/writer libraries for the `.prsn` format, in three languages, built against the same
contract so their output can be cross-checked byte for byte.

| Folder | Language | Package |
|---|---|---|
| [`python/`](python) | Python | `prsn` |
| [`rust/`](rust) | Rust | `prsn` crate |
| [`typescript/`](typescript) | TypeScript (Node.js) | `prsn-ts` |
| [`interop/`](interop) | — | The same signed test package written by each implementation |

Scope: `.prsn` draft v1.1 (`format` version 1). The 1.2 additions (fictional people and
the `authored` tier, index records, vendor and adapter references) are not implemented
yet, so the 1.2 conformance cases in `../prsn/conformance/prsn/` fail for now.

Each library runs the conformance vectors from [`../prsn/conformance`](../prsn/conformance);
see its README for build and test commands. Apache License 2.0, see [`../LICENSE`](../LICENSE).
