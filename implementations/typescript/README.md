# prsn-ts

A TypeScript (Node.js) reader/writer library for the `.prsn` digital-twin file
format, v1 scope. One of three parallel implementations (Python / Rust /
TypeScript) of the same contract; byte-exact agreement on the shared contract
matters more than idiomatic style.

Spec source: `prsn/spec/prsn.md` and `prsn/spec/derivation-recipes.md`
(draft v1.1). This README summarises; it does not reproduce the spec.

## Layout

```
src/
  json.ts       strict RFC 8259 parser + canonical JSON serializer (own code;
                JSON.parse/JSON.stringify are NOT used on the canonical path)
  bytes.ts      SHA-256 (one-shot + streaming)
  zip.ts        minimal ZIP reader/writer (STORED/DEFLATE, ZIP64 read support)
  ed.ts         Ed25519 (RFC 8032) via @noble/curves; keygen, key_id
  manifest.ts   manifest.json parsing + full rule validation (rule ids match
                the spec's conformance table)
  actionkey.ts  R1 action_key preimage + key
  tiers.ts      provenance tier downgrade
  package.ts    PrsnPackage (open/verify/list/read), PrsnBuilder, interop package
  vectors.ts    conformance vector runner (v1 suites)
  cli.ts        CLI (canon/build/verify/vectors)
  index.ts      public API surface
test/
  package.test.ts  unit tests (node:test): ZIP byte layout, JSON strictness,
                   round-trips, legacy mimetype, trust/tamper behaviour
```

Every source file carries `Copyright 2026 Jared Zimmerman` +
`SPDX-License-Identifier: Apache-2.0`; see `LICENSE`.

## Setup

Node v24. Dependencies: `@noble/curves` (Ed25519), `typescript` and
`@types/node` (dev). No ZIP dependency — the container reader/writer is
hand-written (see "Design notes") so the `mimetype` local header is
byte-exact.

```sh
npm install
npm run build        # tsc -> dist/   (CLI at dist/cli.js)
npm test             # build tests -> dist-test/, run with node:test
npm run vectors      # build, then run all v1 conformance vectors
```

## CLI

```
node dist/cli.js canon <input.json>
    Strict-parse, canonical-serialize, print lowercase hex SHA-256 of the
    canonical bytes. Exit non-zero on invalid input.

node dist/cli.js build <out.prsn>
    Write the fixed interop test package (spec below), signed with a fresh
    key. Prints: public_key=<base64> key_id=<16 hex>

node dist/cli.js verify <file.prsn|dir>
    Full verification: container rules, every listed entry present with
    matching size + SHA-256, signature via the embedded key, tier downgrade
    applied. Prints VERIFY OK plus `signed key_id=…` or `unsigned`
    (and a note when the tier downgrade changed anything). Errors go to
    stderr; exit 0/1.

node dist/cli.js vectors <conformance-dir>
    Run all v1-relevant conformance suites; print per-suite pass/fail
    counts; exit non-zero if any fail.
```

`verify` checks exactly: container rules + manifest parses with
`format=="prsn"` and integer `version` 1..1 + all entry hashes/sizes +
signature. It deliberately does **not** enforce the deeper package rules
(`spec-fields`, `type-fields`, `entry-order`, …) — those live in
`pkg.validate()` and are exercised by the `vectors` command's `prsn` suite.

## Public API

```ts
import {
  PrsnPackage, PrsnBuilder, generateKey,           // packages
  parseJson, canonicalBytes,                       // canonical JSON
  actionKey,                                       // R1 action_key
  applyTierDowngrade,                              // provenance tiers
  runVectors,                                      // conformance
} from "prsn-ts"; // or ./dist/index.js

const pkg = await PrsnPackage.open("file.prsn");   // ZIP or directory
const pkg2 = await PrsnPackage.open("dir/");

pkg.verifyIntegrity()   // { ok, issues, notes, signed, keyId, trusted,
                        //   downgradedOrigins, downgradedEvidence }
pkg.validate()          // full rule validation: { issues: [{rule, message}], notes }
pkg.listEntries()       // EntryView[] (expired entries dropped)
pkg.readEntryBytes("face/samples/f-0001.bin")
pkg.downgradedEntries() // entries with the tier downgrade applied
pkg.isTrustedSigner()   // signature verifies && key in trustedKeys

const b = new PrsnBuilder({ generator: "my-writer 1.0", created: "2026-10-10T00:00:00Z" });
b.setPerson(personJson);
b.addEntry("voice/samples/s-0001.bin", bytes, { type, media, fields: { origin } });
const zip: Uint8Array = b.buildZip(seed /* optional: signs */);
await b.writeDir("out/", seed);

const kp = generateKey(); // { seed, publicKey, publicKeyB64, keyId }
```

Trusted keys are a parameter: `PrsnPackage.open(path, { trustedKeys })`
accepts `key_id`s (16 lowercase hex) or base64 public keys; default empty,
so the tier downgrade applies unless a key is explicitly trusted.

## Design notes

- **JSON AST.** Parsed values are an AST (`JsonInt` backed by `bigint`,
  `JsonFloat` for doubles, `JsonObject` as an ordered entry list), so
  int64 integers never lose precision and int/double stay distinct.
- **Key sort is by Unicode code point**, not UTF-16 code units:
  `compareCodePoints` iterates code points (`for..of`) and compares
  `codePointAt(0)`. `Array.prototype.sort()` without a comparator would
  misorder non-BMP keys (e.g. U+1F600 vs U+E000).
- **Doubles** serialize with ECMAScript `Number.prototype.toString`
  (`String(n)`), which is exactly the layout the spec requires; `-0`
  renders as `0`; NaN/±Infinity throw.
- **ZIP.** The reader parses the central directory order-preservingly
  (duplicate names are visible) plus each local header; the writer emits
  deterministic headers (no extra fields, fixed DOS timestamp
  2026-10-10). Member order on write: `mimetype`, `manifest.json`,
  entries sorted by path in UTF-8 byte order, `signatures/manifest.sig`.
  Compression: audio/image/video (and nested ZIPs) STORED, everything else
  DEFLATE. Readers support ZIP64; writers emit it only when needed.
- **Ed25519** via `@noble/curves` (deterministic RFC 8032). `key_id` is the
  first 16 hex chars of SHA-256 over the raw 32-byte public key; the
  manifest `public_key` is standard base64 with padding.
- **Tier downgrade** mirrors the reference: `origin.tier` in
  {enrolled, professional} → `imported` with `origin.was` keeping the claim;
  template `evidence` seconds for those tiers move to `imported`, summed and
  rounded to 0.1 (half-to-even, like the reference).
- **Legacy (Appendix A).** Readers accept
  `application/vnd.museli.prsn+zip` and treat `org.museli.*` types as
  `org.prsn.*`; writers emit the new namespace. The legacy `person.json`
  shape (`name`, `ids`/`links` objects) is mapped for pre-1.1 files only.
- **Type-field checks** (`type-fields` rule) implement the MUST-field table
  from the schemas directly (no JSON-Schema engine in v1); full
  JSON-Schema validation is deferred to v2.

## The fixed interop package

`buildInteropPackage()` (also `build` CLI) writes, to
`~/workspace/digitaltwins-impl/interop/typescript.prsn`:

- `person.json` = canonical JSON of
  `{"id":"urn:uuid:3b1f2a4c-9d5e-4f6a-8b7c-1d2e3f4a5b6c","display_name":"Interop Test","aliases":[],"ids":[],"links":[]}`
- `face/samples/f-0001.bin` (`org.prsn.face.sample`, `application/octet-stream`,
  10 bytes `hello prsn`, origin `{"tier":"imported","how":"interop-fixture","at":"2026-10-10T00:00:00Z"}`)
- `voice/samples/s-0001.bin` (`org.prsn.voice.sample`, `application/octet-stream`,
  12 bytes `voice sample`, same origin shape)
- manifest `{"format":"prsn","version":1,"spec":"1.1","created":"2026-10-10T00:00:00Z",
  "generator":"prsn-ts 0.1.0","person":"person.json","entries":[…],"signature":{…}}`,
  entries sorted by path in UTF-8 byte order
- ZIP order: `mimetype`, `manifest.json`, `person.json`,
  `face/samples/f-0001.bin`, `voice/samples/s-0001.bin`,
  `signatures/manifest.sig`; signed with a fresh key.

## Deferred to v2

- eviction procedure, frames/transform math, full `.prsncap` support,
  JSON-Schema validation of every record type, expiry handling
  (expiry is *noticed* — expired entries are dropped on load — but no
  retention engine), encryption (`enc`/`redact`), protected templates.

## Spec ambiguities found

1. **Key order for code points vs UTF-8 bytes.** The spec says keys sort by
   Unicode code point, "which equals UTF-8 byte order". For well-formed
   strings these coincide, so one comparator serves both the manifest
   key sort and the action_key model/input sorts. (Resolved: single
   code-point comparator everywhere.)
2. **Legacy `org.museli.*` types vs `type-fields`.** The spec says readers
   treat the namespaces as the same type, but the schema enums list only
   `org.prsn.*`. (Resolved: canonicalize legacy → current before the
   MUST-field checks; the reference validator does not, but no vector
   covers it.)
3. **`verify` scope.** The CLI contract defines verification as
   "(container rules, all entry hashes/sizes, signature via embedded key,
   tier downgrade applied)". (Resolved: `verify`/`verifyIntegrity` check
   exactly that plus manifest parseability and the version refusal; the
   deeper rules — spec-fields, type-fields, entry-order, … — are in
   `validate()` and covered by the `vectors` prsn suite. Note the fixed
   interop package itself omits spec-1.1 `look`/`era` and voice MUST
   fields, so enforcing them in `verify` would contradict the contract.)
4. **Evidence rounding ties.** "Rounded to 0.1" with no tie-break stated.
   (Resolved: half-to-even, matching the reference implementation; the
   vectors avoid halfway values.)
5. **`mimetype` extra-field check.** The reference validator reads the
   central-directory extra field; the fixture description says "local
   extra field". (Resolved: refuse when *either* header carries an extra
   field; the fixture has it in both.)

## License

Apache License 2.0 — see `LICENSE`.
