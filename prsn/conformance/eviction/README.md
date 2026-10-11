# Eviction vectors

`vectors.json`: the [eviction procedure](../../spec/prsn.md#eviction-procedure) for both
budgeted roles. `role: "voice.samples"` cases measure seconds, group by `condition`, and
exercise the protected reserve, floors, pinned entries, redundancy and the top-tier
newcomer rule. `role: "face.samples"` cases count entries, run per `look`, and group by
`angle_bin` and `expression_class` with their own floors.

Each case gives a `bank` (entries with `name`, `tier`, `score`, `bytes`, `at`, optionally
`expires`, and either `seconds` + `condition` or `look` + `angle_bin` +
`expression_class`), a `budget`, optional `pinned` names, `redundancy` (name → value in
[0, 1]) and `newcomer`. Running the procedure with the file's `today` must remove exactly
the entries in `evicted`, in that order.

| Case | Rule it pins |
|---|---|
| `tier-outranks-score` | Lower tiers go first, however well they score |
| `lowest-tier-first-then-lowest-quality` | Within the lowest tier, lowest effective quality |
| `ties-go-to-the-older-entry` | Equal quality: older goes |
| `condition-floor-protects-its-best` | A condition's best material is protected up to the floor |
| `material-above-a-floor-is-not-protected` | Only up to the floor; then the next tier gives |
| `seed-source-is-pinned` | Pinned entries are never removed |
| `last-of-a-condition-survives` | The last entry of a condition is never removed |
| `last-of-a-condition-survives-floors-yielding` | Not even when floors yield |
| `lower-tiers-yield-floors-before-the-reserve` | Lower-tier floors give before the reserve does |
| `reserve-gives-only-over-its-share` | The reserve gives only when the top tiers exceed it |
| `top-tier-newcomer-worse-goes-itself` | A top-tier newcomer only displaces a worse clip in its condition |
| `top-tier-newcomer-better-displaces` | A better newcomer displaces the worst in its condition |
| `pinned-newcomer-stays` | A pinned newcomer never goes |
| `near-duplicate-goes-first` | Redundancy lowers effective quality |
| `without-redundancy` | The same bank, scored on score alone |
| `expired-first` | Expired entries go first, even within budget |
| `budget-by-bytes` | The byte cap counts as well as the seconds cap |
| `face-lowest-tier-first` | Counts instead of seconds; lowest tier gives first |
| `face-angle-bin-floor` | An angle bin's best stills are protected up to its floor |
| `face-expression-class-floor` | An expression class's best stills are protected up to its floor |
| `face-last-of-a-bin-survives` | The only still of an angle bin is never removed |
| `face-tier-outranks-score` | Tier before score, with counts |
| `face-budget-is-per-look` | Each look has its own budget |

`tools/validate.py` contains a reference implementation of the procedure and checks every
case.
