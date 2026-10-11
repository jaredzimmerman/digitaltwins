// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//! SHA-256 helpers and key identifiers.

use sha2::{Digest, Sha256};

/// SHA-256 of `data` as raw bytes.
pub fn sha256(data: &[u8]) -> [u8; 32] {
    let digest = Sha256::digest(data);
    let mut out = [0u8; 32];
    out.copy_from_slice(&digest);
    out
}

/// SHA-256 of `data` as 64 lowercase hex digits (the form `manifest.json`
/// `sha256` fields use).
pub fn sha256_hex(data: &[u8]) -> String {
    hex_encode(&sha256(data))
}

/// First 16 hex digits of SHA-256 over the raw 32-byte public key: the
/// `manifest.signature.key_id` value.
pub fn key_id_hex(public_key: &[u8]) -> String {
    hex_encode(&sha256(public_key))[..16].to_string()
}

pub fn hex_encode(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push(char::from_digit((b >> 4) as u32, 16).unwrap());
        s.push(char::from_digit((b & 0xf) as u32, 16).unwrap());
    }
    s
}

pub fn hex_decode(s: &str) -> Option<Vec<u8>> {
    if s.len() % 2 != 0 {
        return None;
    }
    let mut out = Vec::with_capacity(s.len() / 2);
    let bytes = s.as_bytes();
    for i in (0..bytes.len()).step_by(2) {
        let hi = (bytes[i] as char).to_digit(16)?;
        let lo = (bytes[i + 1] as char).to_digit(16)?;
        out.push((hi * 16 + lo) as u8);
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_sha256() {
        assert_eq!(
            sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(sha256_hex(b""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    }
}
