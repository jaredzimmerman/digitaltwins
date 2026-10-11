# ZIP container cases

ZIP-form `.prsn` files built from `examples/prsn/valid-v11`. `cases.json` gives each
file's expected outcome. A reader opens the ZIP, checks the container rules, then applies
every package rule to the members.

| File | Outcome | What it tests |
|---|---|---|
| `valid.prsn` | valid | The interchange form of `valid-v11`: `mimetype` first and STORED, media STORED, JSON and binary DEFLATE |
| `legacy-mimetype.prsn` | valid | The legacy mimetype `application/vnd.museli.prsn+zip`, which readers SHOULD accept |
| `unlisted-member.prsn` | valid | A member the manifest does not list: ignored, never written back |
| `mimetype-not-first.prsn` | refuse (`container`) | `mimetype` is the second member |
| `mimetype-compressed.prsn` | refuse (`container`) | `mimetype` is DEFLATE-compressed |
| `mimetype-extra-field.prsn` | refuse (`container`) | `mimetype` has an extra field |
| `mimetype-wrong.prsn` | refuse (`container`) | `mimetype` holds `application/zip` |
| `duplicate-member.prsn` | refuse (`container`) | `person.json` appears twice |

Readers MUST support ZIP64 and accept archives up to at least 4 GiB uncompressed; these
small cases do not exercise that limit.
