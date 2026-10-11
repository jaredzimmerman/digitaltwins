# Copyright 2026 Jared Zimmerman
# SPDX-License-Identifier: Apache-2.0
"""prsn: reader/writer for the ``.prsn`` digital-twin file format (v1).

Public API:

- :func:`open_package` — open a ``.prsn`` ZIP or directory package
- :meth:`Package.verify_integrity` — container rules, entry hashes, signature
- :meth:`Package.validate` — semantic rule-table validation
- :meth:`Package.list_entries`, :meth:`Package.read_entry_bytes`
- :class:`Builder` — assemble a package and write a signed ZIP
- :func:`generate_key` — fresh Ed25519 key pair
- :func:`action_key` — derivation R1 action key
- :func:`parse`, :func:`dumps`, :func:`canonical` — canonical JSON
"""

from .actionkey import ActionKeyError, action_key, preimage
from .canonical import JSONError, canonical, dumps, parse
from .keys import (
    KeyPair,
    generate_key,
    key_id,
    keypair_from_seed,
    public_key_from_seed,
    sign,
    verify,
)
from .package import (
    Builder,
    Issue,
    Package,
    PrsnError,
    SignatureInfo,
    apply_tier_downgrade,
    canonical_type,
    key_trusted,
    map_legacy_person,
    open_package,
    sha256_hex,
)
from .validate import validate_package

__all__ = [
    "ActionKeyError",
    "Builder",
    "Issue",
    "JSONError",
    "KeyPair",
    "Package",
    "PrsnError",
    "SignatureInfo",
    "action_key",
    "apply_tier_downgrade",
    "canonical",
    "canonical_type",
    "dumps",
    "generate_key",
    "key_id",
    "key_trusted",
    "keypair_from_seed",
    "map_legacy_person",
    "open_package",
    "parse",
    "preimage",
    "public_key_from_seed",
    "sha256_hex",
    "sign",
    "validate_package",
    "verify",
]

__version__ = "0.1.0"
