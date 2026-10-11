# Canonical JSON vectors

`canonical.json` pins the one byte form in which manifests and `action_key` preimages are
hashed and signed ([spec/prsn.md, Canonical JSON](../../spec/prsn.md#canonical-json)).

- `valid[]`: `{name, input, expected, expected_sha256}`. Parse `input` (UTF-8 text) and
  serialise canonically; the result must equal `expected` byte for byte, and its SHA-256
  must equal `expected_sha256`.
- `invalid[]`: `{name, input}` or `{name, input_hex}` (raw bytes). The parser must reject
  each one.

The cases cover key order by code point (not UTF-16, see `key_sort_codepoint_not_utf16`),
string escaping, number layout (shortest round-trip digits in ECMAScript layout), integers
beyond 2^53, and every parsing refusal listed in the spec.

Implementation notes: check booleans before integers in languages where `bool` is an
integer type; a typical permissive JSON library accepts lone surrogates, duplicate keys,
`NaN` and big integers, so strict parsing needs its own checks; never use a library's
default float formatting (`1e-07` and `2.0` differ from the canonical `1e-7` and `2`).
