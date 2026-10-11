# prsn-py — reader/writer for the `.prsn` digital-twin file format (v1)

Python implementation of the [`.prsn` file format](https://github.com/jaredzimmerman/digitaltwins)
(spec draft v1.1, `format` version 1). One of three parallel implementations
(Python/Rust/TypeScript) built against the same contract so a coordinator can
cross-verify byte-exact agreement.

Copyright 2026 Jared Zimmerman · Apache-2.0 (`SPDX-License-Identifier: Apache-2.0`;
see `LICENSE`). Every source file carries the license header.

## Layout

```
src/prsn/
  canonical.py   strict RFC 8259 parser + canonical JSON serializer (no stdlib json)
  keys.py        Ed25519 (RFC 8032) via PyNaCl: keygen, key_id, sign, verify
  actionkey.py   derivation R1 action_key preimage + key
  package.py     container open (ZIP/dir), integrity, signatures, tier downgrade,
                 person.json legacy mapping, Builder (writer)
  validate.py    semantic rule-table validation (spec "Conformance" table)
  vectors.py     conformance vector runner (v1 suites)
  cli.py         canon / build / verify / vectors
tests/           pytest suite (vectors + interop + API + CLI)
```

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -e .        # installs pynacl and the `prsn` console script
.venv/bin/pip install pytest      # for the test suite
```

Requires Python 3.11+. The only runtime dependency is `pynacl` (deterministic
RFC 8032 Ed25519). Everything else is stdlib (`zipfile`, `hashlib`, `base64`,
`secrets`).

## CLI

```
prsn canon <input.json>       strict-parse, canonical-serialise, print lowercase
                              hex SHA-256 of the canonical bytes; exit != 0 on invalid input
prsn build <out.prsn>         write the fixed interop test package, signed with a
                              fresh key; prints: public_key=<b64> key_id=<hex16>
prsn verify <file.prsn|dir>   integrity verification (container rules, every entry's
                              size + SHA-256, signature via the embedded key, tier
                              downgrade applied); prints VERIFY OK plus
                              signed key_id=… or unsigned; errors to stderr; exit 0/1
prsn vectors <conformance-dir> run all v1-relevant conformance suites; prints per-suite
                              pass/fail counts; exit != 0 if any fail
```

`verify` is integrity verification (container + hashes + signature). The full
semantic rule table (spec-fields, paths, looks/eras, …) is `Package.validate()`
and is exercised by `vectors` against the repo's `prsn/` fixtures — see
"Contract decisions" below for why the two are separate.

## Public API

```python
from prsn import open_package, Builder, generate_key, action_key, parse, canonical

pkg = open_package("alex.prsn", trusted_keys=[])   # ZIP or directory; raises PrsnError on refusal
pkg.verify_integrity()       # container rules + entry hashes/sizes + signature (idempotent)
pkg.validate()               # [Issue] semantic checks: errors and notes
pkg.list_entries()           # manifest entries (post-load view)
pkg.read_entry_bytes("face/samples/f-0001.heic")

kp = generate_key()          # fresh Ed25519 KeyPair(seed, public_key); kp.key_id, kp.public_key_b64

b = Builder(generator="my-app 1.0")
b.set_person({"id": "urn:uuid:…", "display_name": "…", "aliases": [], "ids": [], "links": []})
b.add_entry("face/samples/f-0001.heic", "org.prsn.face.sample", "image/heic",
            data, origin={"tier": "enrolled", "how": "…", "at": "…"})
b.write_zip("out.prsn", seed=kp.seed)   # signed; returns the KeyPair

action_key(derivation_dict)  # "sha256:…" or raises ActionKeyError (no key)
```

`PrsnError` carries `.rule` — the spec conformance rule id (`container`,
`version`, `manifest-hash`, `signature`, `critical`).

`trusted_keys` (default `[]`) lists trusted signer keys; each entry may be a
`key_id` (16 hex chars), a base64 32-byte public key, or a hex public key. A
file that is unsigned, or signed by a key not in the set, gets the provenance
tier downgrade: `enrolled`/`professional` origins become `imported` (claimed
tier kept as `origin.was`); template `evidence` seconds for those tiers move to
`imported` (sum rounded to 0.1).

## Canonical JSON

`prsn.canonical` implements the spec's byte form without the stdlib `json`
module: strict RFC 8259 parsing (rejects bad UTF-8 incl. overlong forms and
encoded surrogates, BOM, raw control chars in strings, unknown escapes,
lone/mis-paired surrogates, duplicate keys at any depth, comments,
NaN/Infinity, `+1`, leading zeros, `.5`, `1.`, `1e`, trailing commas/content,
empty input, and number tokens overflowing a double), integer tokens fitting
int64 as exact ints, everything else as correctly-rounded doubles
(`float(token)`; underflow reads as zero). Serialisation: no whitespace, keys
sorted by Unicode code point (= UTF-8 byte order, *not* UTF-16 order), minimal
escapes (`\" \\ \b \t \n \f \r`, other C0 as `\u00xx` lowercase; `/`, U+007F,
U+2028/2029 and all non-ASCII literal), shortest round-trip double digits laid
out exactly like ECMAScript `Number.prototype.toString` (shortest digits taken
from `repr`, then re-laid-out per the spec's n/k rules; `-0.0` → `0`).

## ZIP conventions (writer)

- `mimetype` first, STORED, no extra field, exact bytes `application/vnd.prsn+zip`
  (readers also accept the legacy `application/vnd.museli.prsn+zip`).
- Member order default: `mimetype`, `manifest.json`, entries in manifest order,
  `signatures/manifest.sig`. The fixed interop package uses the exact order
  `mimetype, manifest.json, person.json, face/samples/f-0001.bin,
  voice/samples/s-0001.bin, signatures/manifest.sig`.
- Compression by media type (same rule as the spec repo's own builder):
  `audio/*`, `image/*`, `video/*`, `application/zip`,
  `application/vnd.cbeff.bir` → STORED; everything else (JSON, `.bin`
  octet-stream as "binary arrays", …) → DEFLATE; the detached signature →
  STORED. Hashes cover content bytes, so this never affects verification.
- Duplicate member names are refused on read; unlisted members are ignored
  (never part of the file); `signatures/*` is never a manifest entry.

## Contract decisions (spec ambiguities found)

1. **`verify` is integrity-only.** The task's `verify` contract lists container
   rules, entry hashes/sizes, signature, and tier downgrade — while the fixed
   interop test package (spec `"1.1"`) omits `look`/`era`/`derivation` on its
   samples, which a strict spec-1.1 validator flags under `spec-fields`. Since
   the mandated fixed package must self-verify, `verify`/`verify_integrity()`
   checks integrity only; the semantic rule table is `Package.validate()`,
   exercised by `vectors` against the repo's `prsn/` fixtures.
2. **Evidence rounding**: "sum rounded to 0.1" uses `round(x, 1)`, matching the
   spec repo's own reference implementation; vectors avoid half-way values.
3. **Unknown signature `alg`**: treated as present but unverified (a note, not
   an error); the file counts as untrusted for tier purposes.
4. **Directory-form `mimetype`**: checked when present, not required — same as
   the repo's reference reader.
5. **Non-object manifest entries**: refused (`manifest-hash`); the reference
   silently filters them. No vector covers this.

## Deferred to v2

Eviction procedure, frames/transform math, full `.prsncap` support,
JSON-Schema validation of every record type, expiry handling beyond
drop-on-load, `redact` decryption, licence-constraint propagation (R6),
staleness/upgrade (R3/R4).

## Tests

```sh
.venv/bin/python -m pytest tests/ -q
# vectors against the spec repo (default /tmp/digitaltwins/prsn/conformance):
PRSN_CONFORMANCE_DIR=/path/to/prsn/conformance .venv/bin/python -m pytest tests/ -q
.venv/bin/prsn vectors /tmp/digitaltwins/prsn/conformance
```

`tests/test_vectors.py` asserts all 173 v1 vector checks pass
(json 94 · sha256 10 · action_key 17 · ed25519 4 · manifest 1 · tiers 5 ·
container 8 · prsn 33 · examples 1). `tests/test_interop.py` byte-inspects the
written ZIP (mimetype first local header, method 0, extra length 0, exact
content bytes) and round-trips entry bytes.
