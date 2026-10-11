# Split vectors

`vectors.json`: cases for the seeded-stride rule of
[spec/prsncap.md](../../spec/prsncap.md) §5. Each case gives `seed`, `stride`,
`stills_stride` and per-stream rows (`phase`, optionally `dropped: true`) in index order;
`expected` is the resulting `splits.json`.

| Case | What it shows |
|---|---|
| `contract-worked-example` | The worked example in the spec: offsets 2 and 2 |
| `dropped-frames-keep-their-index` | Dropped frames are skipped but keep their index |
| `per-phase-indices-restart` | Indices restart in each phase; a phase with no held-out frame is listed with `frames: []` |
| `other-seed-offsets` | A seed giving different offsets for frames and stills |
| `seed-multiple-of-stride` | Offset 0 |
| `empty-stream-omitted` | A stream with no rows is omitted |
