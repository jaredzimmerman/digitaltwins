# `.prsncap` cases

Directory-form captures, each a copy of `examples/prsncap/minimal-depth.prsncap` with one
change. `cases.json` lists each case with its `rule` and `outcome`.

| Case | Rule | Outcome | What changed |
|---|---|---|---|
| `tracking-template-missing.prsncap` | `tracking-template` | invalid | face-tracking frames and vertices whose `topology_sha256` / `targets_sha256` name an ARKit face template the capture does not embed ([prsncap.md](../../spec/prsncap.md) §3.2) |
