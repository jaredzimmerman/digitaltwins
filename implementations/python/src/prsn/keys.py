# Copyright 2026 Jared Zimmerman
# SPDX-License-Identifier: Apache-2.0
"""Ed25519 (RFC 8032) keys and manifest signatures.

PyNaCl wraps libsodium, whose Ed25519 is the deterministic RFC 8032 scheme
the format requires: signing the same message with the same key always yields
the same 64 bytes.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

SEED_BYTES = 32
PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64


@dataclass(frozen=True)
class KeyPair:
    """An Ed25519 key pair. ``seed`` is the 32-byte private seed."""

    seed: bytes
    public_key: bytes

    @property
    def key_id(self) -> str:
        """First 16 hex digits of SHA-256 over the raw public key."""
        return key_id(self.public_key)

    @property
    def public_key_b64(self) -> str:
        """Raw 32-byte public key, standard base64 with padding."""
        return base64.b64encode(self.public_key).decode("ascii")


def generate_key() -> KeyPair:
    """Generate a fresh key pair from 32 random bytes (the seed)."""
    seed = secrets.token_bytes(SEED_BYTES)
    return keypair_from_seed(seed)


def keypair_from_seed(seed: bytes) -> KeyPair:
    """Derive the key pair for a 32-byte seed."""
    if len(seed) != SEED_BYTES:
        raise ValueError(f"seed must be {SEED_BYTES} bytes, got {len(seed)}")
    return KeyPair(seed=bytes(seed), public_key=public_key_from_seed(seed))


def public_key_from_seed(seed: bytes) -> bytes:
    """Derive the raw 32-byte Ed25519 public key from a 32-byte seed."""
    if len(seed) != SEED_BYTES:
        raise ValueError(f"seed must be {SEED_BYTES} bytes, got {len(seed)}")
    return bytes(SigningKey(seed).verify_key)


def key_id(public_key: bytes) -> str:
    """First 16 hex digits of SHA-256 over the raw 32-byte public key."""
    return hashlib.sha256(public_key).hexdigest()[:16]


def sign(seed: bytes, message: bytes) -> bytes:
    """Deterministic RFC 8032 signature: raw 64 bytes."""
    sig = SigningKey(seed).sign(message).signature
    assert len(sig) == SIGNATURE_BYTES
    return sig


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """True when ``signature`` is a valid Ed25519 signature over ``message``."""
    if len(public_key) != PUBLIC_KEY_BYTES or len(signature) != SIGNATURE_BYTES:
        return False
    try:
        VerifyKey(public_key).verify(signature + message)
    except BadSignatureError:
        return False
    return True
