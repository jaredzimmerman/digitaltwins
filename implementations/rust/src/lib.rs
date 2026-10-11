// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//! Reader/writer library for the `.prsn` digital-twin file format (v1 scope).
//!
//! - [`canon`]: strict RFC 8259 parsing and canonical JSON serialization.
//! - [`Package`]: open a `.prsn` as a ZIP or directory package, verify
//!   integrity, verify the manifest signature, validate conformance rules.
//! - [`PackageBuilder`]: build a new package and write it as ZIP or directory.
//! - [`action_key`]: derivation `action_key` (R1).
//! - [`tiers`]: provenance tier downgrade for untrusted files.
//! - [`sign`]: Ed25519 key generation, signing and verification.
//!
//! Deferred to v2 (see README): eviction procedure, frames/transform math,
//! full `.prsncap` support, JSON-Schema validation of every record type,
//! expiry handling beyond load-time drops.

pub mod action_key;
pub mod builder;
pub mod canon;
pub mod hash;
pub mod manifest;
pub mod package;
pub mod sign;
pub mod tiers;

pub use builder::{BuilderFile, PackageBuilder, WriteReport};
pub use canon::{ParseError, SerializeError, Value};
pub use hash::{hex_decode, hex_encode, key_id_hex, sha256, sha256_hex};
pub use manifest::RuleId;
pub use package::{EntryInfo, Error, Package, MIMETYPE, MIMETYPE_LEGACY, SIGNATURE_PATH, SUPPORTED_VERSION};
pub use sign::{generate_key, generate_seed, public_key_from_seed, sign_detached, verify_detached};
