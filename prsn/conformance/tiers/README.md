# Tier downgrade vectors

`downgrade.json`: what a reader does with entries of a file that is unsigned or signed by a
key it does not trust ([spec/prsn.md, Provenance tiers](../../spec/prsn.md#provenance-tiers)).
`enrolled` and `professional` origins become `imported`, with the claimed tier kept as
`origin.was`; a template's `evidence` seconds for those tiers move to `imported` (sum
rounded to 0.1; the vectors avoid half-way values). `imported` and `observed` are
unchanged, and a trusted file is unchanged.

Each case gives `trusted`, input `entries` (only the fields that matter) and the `expected`
entries.

| Case | What it shows |
|---|---|
| `untrusted-enrolled-sample` | `enrolled` → `imported`, `was: "enrolled"` |
| `untrusted-professional-sample` | `professional` → `imported`, `was: "professional"` |
| `untrusted-lower-tiers-unchanged` | `observed` and `imported` stay |
| `untrusted-template-evidence` | evidence seconds from both top tiers move to `imported` |
| `trusted-file-unchanged` | nothing changes for a trusted signer |
