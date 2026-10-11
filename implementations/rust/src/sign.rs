// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//! Ed25519 (RFC 8032) key generation, deterministic signing and verification.
//!
//! Each writing installation has its own key pair, generated locally and never
//! synced. The signature identifies the install that wrote the file.

use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};

/// Generate a fresh 32-byte key seed from the OS random source.
///
/// (Also available as [`generate_seed`]; both names return the same thing.)
pub fn generate_key() -> std::io::Result<[u8; 32]> {
    generate_seed()
}

/// Generate a fresh 32-byte seed from the OS random source.
pub fn generate_seed() -> std::io::Result<[u8; 32]> {
    let mut seed = [0u8; 32];
    let mut f = std::fs::File::open("/dev/urandom")?;
    use std::io::Read;
    f.read_exact(&mut seed)?;
    Ok(seed)
}

/// Derive the raw 32-byte public key from a 32-byte seed.
pub fn public_key_from_seed(seed: &[u8; 32]) -> [u8; 32] {
    SigningKey::from_bytes(seed).verifying_key().to_bytes()
}

/// Deterministic (RFC 8032) signature over `message`.
pub fn sign_detached(seed: &[u8; 32], message: &[u8]) -> [u8; 64] {
    SigningKey::from_bytes(seed).sign(message).to_bytes()
}

/// Verify a detached signature. Returns `false` (rather than an error) when
/// the signature simply does not verify; malformed keys/signatures are errors.
pub fn verify_detached(
    public_key: &[u8; 32],
    message: &[u8],
    signature: &[u8; 64],
) -> Result<bool, String> {
    let vk = VerifyingKey::from_bytes(public_key).map_err(|e| format!("bad public key: {e}"))?;
    let sig = Signature::try_from(&signature[..]).map_err(|e| format!("bad signature: {e}"))?;
    Ok(vk.verify(message, &sig).is_ok())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hash::hex_decode;

    #[test]
    fn rfc8032_test1_pubkey() {
        // Real RFC 8032 §7.1 test 1 seed; expected public key from the
        // conformance vectors (conformance/hash/ed25519.json).
        let seed: [u8; 32] = hex_decode(
            "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        )
        .and_then(|v| v.try_into().ok())
        .expect("seed");
        let pk = public_key_from_seed(&seed);
        assert_eq!(
            crate::hash::hex_encode(&pk),
            "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
        );
        let sig = sign_detached(&seed, b"");
        assert!(verify_detached(&pk, b"", &sig).unwrap());
        let mut bad = sig;
        bad[0] ^= 1;
        assert!(!verify_detached(&pk, b"", &bad).unwrap());
        assert!(!verify_detached(&pk, b"x", &sig).unwrap());
    }
}
