# Voice in `.prsn`

Status: **Draft v1.1**. Part of the [`.prsn` specification](prsn.md); the container,
manifest, tier, budget and security rules there apply here.

The voice modality lives under `voice/` with the usual roles: `templates/`, `samples/`,
`training/` and `generation/`. Voice is non-spatial: its entries carry no `frame`. Voice is
identity-level, so its `samples/` and `generation/` entries carry `look: "*"` in spec 1.1
files. The MUST/SHOULD field split for each type is in [prsn.md, Voice](prsn.md#voice). Its central idea is a **clean sample bank**: keeping a
person's best raw clips, losslessly, is what makes moving to a new recognition or
generation model possible without asking the person to record again.

## Templates (`voice/templates/`)

`org.prsn.voice.template`: a CBEFF BIR (ISO/IEC 19785) holding one speaker vector. One
template per embedding model; several are allowed (typically the current model and the
previous one, kept for readers that still use it).

Entry fields:

| Field | Meaning |
|---|---|
| `model` | `{"key", "sha256", "dim"}` of the embedding model, plus `license` |
| `evidence_seconds` | Total seconds of audio behind the vector |
| `evidence` | The same, split by provenance tier, e.g. `{"enrolled": 44.8, "observed": 15.2}` |
| `n_samples` | Number of clips behind the vector |
| `samples` | SHA-256s of the sample entries it was derived from (when derived from the bank) |
| `derived_from` | Where the vector came from, e.g. `voice/samples` |
| `updated` | When the template was last written |
| `protected` | Present when the vector is protected (ISO/IEC 24745); see [prsn.md, Security](prsn.md#protected-templates) |

A template derived from the bank is recomputed from the whole bank whenever the bank
changes, never kept as a running average. A writer SHOULD NOT replace a template that was
not derived from the bank with a bank-derived one until the bank holds enough audio to be
at least as good (about 30 s; recognition gains level off between 30 and 45 s).

The `voice.templates` budget (`{"models": N}`, default 3) keeps one template per model for
the newest N models, by `updated`.

## Samples: the clean bank (`voice/samples/`)

`org.prsn.voice.sample`: one clip per entry.

- **Content.** One speaker (overlap fraction 0), mono, 3 to 15 s, level above a floor,
  unclipped and **not denoised** (denoising removes cues that recognition uses).
- **Encoding.** FLAC, **at the sample rate and bit depth it was captured at**: nothing is
  resampled or lossy-encoded on the way in, so a future model trained at a higher rate, or
  on features a codec would strip, can still use every clip. Integer captures keep their
  depth (16-bit stays 16-bit). A floating-point capture is stored as 24-bit integer FLAC
  (lossless for any real microphone signal, though not bit-exact for arbitrary float data),
  and the entry MUST record the source sample format in `source_format`. A model that wants a lower rate (for
  example 16 kHz) derives it when reading and never writes it back.
- **Size.** The bank holds about 60 s, spread across conditions: recognition gains level
  off around 30 to 45 s, and the rest buys condition coverage. About 45 s at 48 kHz/24-bit
  mono is roughly 3 to 4 MB after FLAC.

Entry fields:

| Field | Meaning |
|---|---|
| `seconds` | Clip length |
| `sample_rate`, `bits`, `channels` | As stored (`channels` is 1) |
| `source_format` | The capture's sample format: `s16`, `s24`, `s32` (signed integer), `f32`, `f64` (float). MUST when the capture was floating point; SHOULD otherwise |
| `captured` | The capture format: `{"device", "rate", "bits", "float"}` |
| `condition` | `quiet` / `noisy` / `headset` / `far-field` |
| `overlap` | Fraction of the clip with more than one speaker (0 for a bank clip) |
| `source` | Where the clip was cut from (an opaque, writer-defined reference) |
| `text` | Transcript, when known (needed for a clip to become a seed) |
| `origin` | Provenance tier ([prsn.md, Provenance tiers](prsn.md#provenance-tiers)) |
| `quality` | `{"score", "snr_db", "speech", "length", "agree", "standard", "by", "at"}` (below) |
| `expires` | Retention limit, when one applies |

**Quality.** Voice has no ISO/IEC 29794 part, so the score is the writer's own and its
`standard` names that score, never a standard. Components: `snr_db`, `speech` (the
fraction of frames with speech), `length` (saturating at about 10 s), `agree` (cosine
agreement with the person's template); `by` names the scorer and the hash of the model
that scored it. Scores from different scorers are not comparable: when the scorer changes,
every sample is re-scored before the next eviction.

**Sample index.** `voice/samples/samples.bir`, type `org.prsn.voice.sample-index`: a CBEFF
BIR with one ISO/IEC 19794-13-aligned data block per clip, carrying the clip's metadata and
its SHA-256 (never the audio a second time). It is rebuilt from the sample entries on every
write.

## Training (`voice/training/`)

`org.prsn.voice.training`: clone-training material, one clip per entry with the words it
carries. Same rules as samples: lossless, never resampled on the way in, `origin`
required. `org.prsn.voice.training-set` (`voice/training/training.json`) records the
training set itself: why it was staged, its sources, and the clip order it was used in.

## Generation (`voice/generation/`)

- `org.prsn.voice.seed` (`voice/generation/seed.flac`): the reference line a cloner
  conditions on, lossless at native rate, with `text` (its transcript), `source`, and
  `source_sample` (the SHA-256 of the bank clip it was cut from; that clip is pinned and
  never evicted).
- `org.prsn.voice.generation` (`voice/generation/generation.json`): which seed, which
  engine and version verified it, and the verification scores (clone-versus-real
  similarity, naming rate, word error rate), plus a `history` of earlier seeds and of
  rejected attempts, as scores only (no audio). An earlier seed that is still among the
  best clips is already in `samples/`.
- `org.prsn.voice.prompt`: an engine-specific cached speaker prompt (safetensors) with
  engine and version. Disposable: a reader without that engine regenerates from the seed.
- `org.prsn.voice.lora`, `org.prsn.voice.rvc`, `org.prsn.voice.piper`: trained
  generators ([prsn.md, Voice](prsn.md#voice)).

All carry `"synthetic_capable": true`.

**Choosing a seed.** Candidates are bank clips with a transcript, 4 to 15 s long, not
already tried. Top-tier (`professional`, `enrolled`) clips are preferred. A new seed is
adopted only if its clone round trip scores higher than the current one; a lower-tier clip
replaces a top-tier seed only if it wins by more than a minimum gain (0.02 on the
similarity scale is the reference value). A rejected attempt is recorded in the history so
the same clip isn't retried.

## Admission

A candidate clip is admitted only if all hold:

- it is not generated material (`origin.synthetic`, or any sign that it came out of a
  generator); generated audio is never evidence of the person;
- mono, 3 to 15 s, level above a floor, not clipped;
- a single speaker (overlap 0);
- it matches the person's template at the recognition threshold plus a margin. A file with
  no template yet can only be started by deliberate capture (`enrolled` or
  `professional`).

A writer SHOULD admit at most a few candidates (3 is the reference value) per person per
encounter, so one long encounter can't take over the bank, and SHOULD skip a candidate
whose `source` is already in the bank.

## Budgets and the protected reserve

Defaults, used for any key a file does not give:

```json
"budgets": {
  "voice.samples":    {"seconds": 60, "bytes": 8000000, "per_condition_min_seconds": 8, "reserve_seconds": 45},
  "voice.generation": {"candidates": 0},
  "voice.templates":  {"models": 3}
}
```

- `voice.samples` is over budget when the bank's total `seconds` exceeds `seconds` or its
  total entry size exceeds `bytes`.
- `per_condition_min_seconds` is the coverage floor: each condition's best material is
  protected up to this many seconds (and its single best clip always), even when it scores
  lower than other conditions' clips. One clean far-field clip matters more than a fifth
  clean headset clip.
- `reserve_seconds` is the **protected reserve**: the top tiers (`professional`,
  `enrolled`) hold this share of the bank, and lower-tier clips only use the rest plus
  whatever the top tiers leave unused. Absent, it equals `seconds`.
- `voice.generation.candidates` is how many alternative seeds are kept beside the current
  one (0: only the current seed and its history as scores).

## Eviction

The voice sample bank uses the generic [eviction procedure](prsn.md#eviction-procedure)
with these parameters: the measure is each entry's `seconds`; the cap is `seconds` and
`bytes`; entries are grouped by `condition` with floor `per_condition_min_seconds`; the
reserve is `reserve_seconds`; pinned entries are the current seed's `source_sample` and
anything about to become a seed. Vectors with `role: "voice.samples"`:
[`conformance/eviction/vectors.json`](../conformance/eviction/vectors.json).
