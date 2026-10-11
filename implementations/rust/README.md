# prsn-rs

A reader/writer library for the [`.prsn` digital-twin file format](https://github.com/jaredzimmerman/digitaltwins) (v1 scope), in Rust. One of three parallel implementations (Python / Rust / TypeScript) built against the same contract so the coordinator can cross-verify byte-exact agreement.

License: Apache-2.0. Every source file carries `Copyright 2026 Jared Zimmerman` + `SPDX-License-Identifier: Apache-2.0`.

## Layout

```
src/
  lib.rs        public API re-exports
  canon.rs      strict RFC 8259 JSON parsing + canonical serialization
                (hand-written; serde_json is NOT used on the canonical path)
  hash.rs       SHA-256, key_id helpers
  sign.rs       Ed25519 (RFC 8032) keygen / deterministic sign / verify
  action_key.rs derivation action_key (R1 preimage + key)
  tiers.rs      provenance tier downgrade for untrusted files
  package.rs    container open (ZIP + directory), integrity, signature
  manifest.rs   conformance rule validation (RuleId)
  builder.rs    PackageBuilder: new package -> add entries -> write ZIP/dir
  bin/prsn/
    main.rs     CLI: canon | build | verify | vectors
    vectors.rs  conformance-vector runner
tests/
  interop.rs    fixed-package build, ZIP byte inspection, round-trips
```

## Public API

```rust
use prsn::{Package, PackageBuilder, Value};

// Open (auto-detects ZIP vs directory package)
let mut pkg = Package::open("alex-chen.prsn".as_ref())?;

// Container rules are enforced at open (mimetype first/STORED/no-extra,
// no duplicate member names); version and critical-unknown-type refuse.

// Integrity: every listed entry present with matching size + SHA-256
pkg.verify_integrity().map_err(|problems| ...)?;

// Signature: Ok(None) = unsigned, Ok(Some(key_id)) = verifies, Err = broken
let status = pkg.verify_signature()?;

// Tier downgrade (untrusted unless a key_id is explicitly trusted)
pkg.apply_tier_downgrade(&[]);

// Entries and bytes (unlisted members are not part of the file)
for e in pkg.list_entries() { println!("{} {}", e.path, e.sha256); }
let bytes: Vec<u8> = pkg.read_entry_bytes("person.json")?;

// Full rule validation (rule ids from spec prsn.md, Conformance)
let rules: Vec<prsn::RuleId> = pkg.validate()?;
assert!(rules.is_empty());

// Canonical JSON
let v: Value = prsn::canon::parse(br#"{"b":1,"a":2}"#)?;
let bytes: Vec<u8> = prsn::canon::to_canonical(&v)?; // {"a":2,"b":1}

// action_key (derivation-recipes.md R1)
let key: String = prsn::action_key::action_key(&derivation)?; // "sha256:<hex>"

// Keys
let seed: [u8; 32] = prsn::generate_key()?;           // 32 random bytes
let pk: [u8; 32] = prsn::public_key_from_seed(&seed);
let key_id: String = prsn::key_id_hex(&pk);            // first 16 hex of SHA-256(pk)

// Build
let mut b = PackageBuilder::new("person.json");
b.set_top("created", Value::Str("2026-10-10T00:00:00Z".into()));
b.set_top("generator", Value::Str("prsn-rs 0.1.0".into()));
b.add_file("person.json", "org.prsn.person", "application/json", person_bytes, vec![])?;
b.add_file("face/samples/f-0001.bin", "org.prsn.face.sample",
           "application/octet-stream", bytes,
           vec![("origin".into(), origin_value)])?;
let report = b.write_zip("out.prsn".as_ref(), Some(&seed))?; // or write_dir
```

Full verification (what `prsn verify` does) = `Package::open` (container
rules) + `verify_integrity` (sizes + hashes) + `verify_signature` (Ed25519
over the canonical manifest bytes, signature block included) +
`apply_tier_downgrade`.

## CLI

```
prsn canon <input.json>        strict-parse, canonical-serialize, print
                               lowercase hex SHA-256 of the canonical bytes
                               (exit non-zero on invalid input)
prsn build <out.prsn>          write the fixed interop test package, signed
                               with a fresh key; prints
                               public_key=<b64> key_id=<hex16>
prsn verify <file.prsn|dir>    container rules, entry hashes/sizes,
                               signature via embedded key, tier downgrade
                               applied; prints VERIFY OK plus
                               signed key_id=… or unsigned (exit 0/1)
prsn vectors <conformance-dir>  run all v1-relevant conformance vectors;
                               prints per-suite pass/fail counts
```

## Conformance

```
prsn vectors /path/to/digitaltwins/prsn/conformance
```

Current results (2026-10-10): **173 passed, 0 failed** —

| suite | checks |
|---|---|
| json/canonical | 94 (57 valid byte-exact + sha256, 37 invalid rejected) |
| hash/sha256 | 10 (one-shot + uneven streaming chunks) |
| hash/action_key | 17 (10 preimage+key, 7 invalid) |
| hash/ed25519 | 4 (pubkey/key_id/verify + bit-flip + modified-message rejects) |
| hash/manifest | 1 (manifest build, canonical bytes, sha256, signature) |
| tiers/downgrade | 5 |
| container | 8 fixtures |
| prsn/rules | 33 (30 cases + 3 valid examples) |
| examples/valid-v11 | 1 (read + hash + signature verify, untrusted downgrade) |

Plus a 400-document differential fuzz against the repo's Python reference
(`tools/prsnfmt.py`): 400/400 byte-exact agreement (compared via SHA-256),
covering key sorting (code-point, not UTF-16), escapes, and number layouts.

`cargo test` runs unit tests (parser/serializer edge cases, tiers, ed25519)
and `tests/interop.rs` (fixed-package build, mimetype local-header byte
inspection, ZIP member order, hash/signature verification, entry byte
round-trip, directory form, unsigned form).

The fixed interop package is written to
`../interop/rust.prsn` (`prsn build ../interop/rust.prsn`) and self-verifies
with `prsn verify`.

## Notes on the contract

- Canonical JSON uses a hand-written strict parser/serializer, not
  serde_json (which accepts duplicate keys and formats numbers differently).
  Object keys sort by Unicode code point — Rust `str` ordering is UTF-8
  byte order, which equals code point order. Doubles use shortest
  round-trip digits (via `ryu`) re-laid-out per the spec's ECMAScript
  n/k rules (`format!("{}")` of `f64` is shortest but not ECMAScript layout).
- The signature is verified over the canonical JSON of the whole
  `manifest.json`, signature block included, before the retired `scopes`
  key is dropped from the working copy (the `retired-scopes-key` vector's
  signature covers the manifest *with* `scopes`).
- `mimetype` handling: on read both `application/vnd.prsn+zip` and the
  legacy `application/vnd.museli.prsn+zip` are accepted; writers emit the
  new one. The first-member / STORED / no-extra-field checks are done by
  parsing the first local file header from the raw bytes, and the
  central directory is walked manually for first-member and duplicate-name
  checks — the `zip` crate's central-directory view silently drops a
  duplicated entry (seen on `duplicate-member.prsn`: 8 records, crate
  reports 7), so it cannot be trusted for that rule. ZIP64 end-of-central-
  directory records are followed.
- ZIP member order on write: `mimetype`, `manifest.json`, the person
  entry, remaining entries in manifest (sorted) order,
  `signatures/manifest.sig`. JSON payloads are DEFLATE, raw byte payloads
  STORED; `mimetype` is STORED with no extra field (byte-inspected in tests).
- Legacy `person.json` shape mapping (`name`→`display_name`, `ids`/`links`
  objects→arrays) applies to pre-1.1 files only: a spec-1.1 file using the
  legacy shape fails the `person` rule (per `person-missing-display-name`).
- The `entry-order` rule uses strict `>` so adjacent duplicate paths (the
  `path-listed-twice` case) report only `paths`.
- Expired entries (`expires` before today, UTC) are dropped on load;
  unlisted members are ignored and never readable via `read_entry_bytes`.
- Tier downgrade: unsigned, or signed-by-untrusted-key, files get
  `enrolled`/`professional` → `imported` with `origin.was` kept, and
  `evidence` seconds for those tiers summed into `imported` (rounded to
  0.1). Trusted keys are an explicit parameter, default empty.

## Deferred to v2

Per the task scope, not implemented: eviction procedure, frames/transform
math, full `.prsncap` support, JSON-Schema validation of every record type,
expiry handling beyond load-time drops.
