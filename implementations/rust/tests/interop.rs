// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//! Interop tests: build the fixed test package, byte-inspect the ZIP,
//! round-trip through open/verify/extract, and exercise the directory form.

use std::io::{Read, Seek, SeekFrom};
use std::path::PathBuf;

use prsn::{canon, key_id_hex, Package, PackageBuilder, Value};

const PERSON_CANONICAL: &str = r#"{"aliases":[],"display_name":"Interop Test","id":"urn:uuid:3b1f2a4c-9d5e-4f6a-8b7c-1d2e3f4a5b6c","ids":[],"links":[]}"#;

fn fixed_builder() -> PackageBuilder {
    let mut b = PackageBuilder::new("person.json");
    b.set_top("created", Value::Str("2026-10-10T00:00:00Z".to_string()));
    b.set_top("generator", Value::Str("prsn-rs 0.1.0".to_string()));
    let person = canon::parse(
        br#"{"id":"urn:uuid:3b1f2a4c-9d5e-4f6a-8b7c-1d2e3f4a5b6c","display_name":"Interop Test","aliases":[],"ids":[],"links":[]}"#,
    )
    .unwrap();
    b.add_file(
        "person.json",
        "org.prsn.person",
        "application/json",
        canon::to_canonical(&person).unwrap(),
        Vec::new(),
    )
    .unwrap();
    let origin = || {
        Value::Object(vec![
            ("tier".to_string(), Value::Str("imported".to_string())),
            ("how".to_string(), Value::Str("interop-fixture".to_string())),
            ("at".to_string(), Value::Str("2026-10-10T00:00:00Z".to_string())),
        ])
    };
    b.add_file(
        "face/samples/f-0001.bin",
        "org.prsn.face.sample",
        "application/octet-stream",
        b"hello prsn".to_vec(),
        vec![("origin".to_string(), origin())],
    )
    .unwrap();
    b.add_file(
        "voice/samples/s-0001.bin",
        "org.prsn.voice.sample",
        "application/octet-stream",
        b"voice sample".to_vec(),
        vec![("origin".to_string(), origin())],
    )
    .unwrap();
    b
}

fn tmp_path(name: &str) -> PathBuf {
    let mut p = std::env::temp_dir();
    p.push(format!("prsn-rust-test-{}-{}", std::process::id(), name));
    p
}

/// Byte-inspect the first local file header: it must be `mimetype`, STORED,
/// with no extra field and the exact content bytes.
fn assert_mimetype_first(path: &PathBuf) {
    let mut f = std::fs::File::open(path).unwrap();
    let mut hdr = [0u8; 30];
    f.read_exact(&mut hdr).unwrap();
    assert_eq!(u32::from_le_bytes(hdr[0..4].try_into().unwrap()), 0x0403_4b50);
    assert_eq!(u16::from_le_bytes(hdr[8..10].try_into().unwrap()), 0, "method");
    let nlen = u16::from_le_bytes(hdr[26..28].try_into().unwrap()) as usize;
    let elen = u16::from_le_bytes(hdr[28..30].try_into().unwrap()) as usize;
    assert_eq!(elen, 0, "extra field length");
    let csize = u32::from_le_bytes(hdr[18..22].try_into().unwrap()) as usize;
    f.seek(SeekFrom::Start(30)).unwrap();
    let mut name = vec![0u8; nlen];
    f.read_exact(&mut name).unwrap();
    assert_eq!(name, b"mimetype");
    let mut content = vec![0u8; csize];
    f.read_exact(&mut content).unwrap();
    assert_eq!(content, b"application/vnd.prsn+zip");
}

/// Central-directory member names in order, via the `zip` crate (no
/// duplicates here, so its view is complete).
fn central_names(path: &PathBuf) -> Vec<String> {
    let file = std::fs::File::open(path).unwrap();
    let mut archive = zip::ZipArchive::new(file).unwrap();
    (0..archive.len())
        .map(|i| archive.by_index(i).unwrap().name().to_string())
        .collect()
}

#[test]
fn build_verify_roundtrip_zip() {
    let out = tmp_path("fixed.prsn");
    let seed = [0x42u8; 32];
    let builder = fixed_builder();
    let report = builder.write_zip(&out, Some(&seed)).unwrap();

    // Byte-level container checks.
    assert_mimetype_first(&out);
    assert_eq!(
        central_names(&out),
        vec![
            "mimetype",
            "manifest.json",
            "person.json",
            "face/samples/f-0001.bin",
            "voice/samples/s-0001.bin",
            "signatures/manifest.sig",
        ]
    );

    // Manifest entries are sorted by path in UTF-8 byte order.
    let manifest: Value = canon::parse(&report.manifest_bytes).unwrap();
    let paths: Vec<String> = manifest
        .get("entries")
        .unwrap()
        .as_array()
        .unwrap()
        .iter()
        .map(|e| e.get("path").unwrap().as_str().unwrap().to_string())
        .collect();
    assert_eq!(paths, vec!["face/samples/f-0001.bin", "person.json", "voice/samples/s-0001.bin"]);
    let mut sorted = paths.clone();
    sorted.sort();
    assert_eq!(paths, sorted);

    // The signature block is well-formed.
    let sig_block = manifest.get("signature").unwrap();
    assert_eq!(sig_block.get("alg").unwrap().as_str().unwrap(), "Ed25519");
    let key_id = sig_block.get("key_id").unwrap().as_str().unwrap();
    assert_eq!(key_id, key_id_hex(&report.public_key.unwrap()));
    assert_eq!(report.signature.unwrap().len(), 64);

    // Open, verify integrity, verify signature, round-trip entry bytes.
    let mut pkg = Package::open(&out).unwrap();
    pkg.verify_integrity().expect("integrity");
    // The fixed package is intentionally minimal: its spec-1.1 sample
    // entries carry no look/era/derivation, so the spec-fields rule fires.
    // (The `verify` CLI contract covers container+hashes+signature only.)
    let rules = pkg.validate().expect("validate");
    assert_eq!(
        rules.iter().map(|r| r.as_str()).collect::<Vec<_>>(),
        vec!["spec-fields"]
    );
    match pkg.verify_signature().expect("signature") {
        Some(k) => assert_eq!(k, key_id),
        None => panic!("expected a signature"),
    }
    assert_eq!(pkg.read_entry_bytes("person.json").unwrap(), PERSON_CANONICAL.as_bytes());
    assert_eq!(pkg.read_entry_bytes("face/samples/f-0001.bin").unwrap(), b"hello prsn");
    assert_eq!(pkg.read_entry_bytes("voice/samples/s-0001.bin").unwrap(), b"voice sample");

    // person.json parses with the expected shape.
    let person = pkg.person();
    assert_eq!(person.get("display_name").unwrap().as_str().unwrap(), "Interop Test");

    std::fs::remove_file(&out).ok();
}

#[test]
fn directory_roundtrip() {
    let dir = tmp_path("fixed-dir");
    let seed = [0x07u8; 32];
    fixed_builder().write_dir(&dir, Some(&seed)).unwrap();

    let mut pkg = Package::open(&dir).unwrap();
    pkg.verify_integrity().expect("integrity");
    assert!(pkg.verify_signature().expect("signature").is_some());
    assert_eq!(pkg.read_entry_bytes("face/samples/f-0001.bin").unwrap(), b"hello prsn");

    // Unlisted members are not part of the file.
    std::fs::write(dir.join("stray.txt"), b"stray").unwrap();
    let mut pkg2 = Package::open(&dir).unwrap();
    assert!(pkg2.read_entry_bytes("stray.txt").is_err());
    assert!(!pkg2.entries().iter().any(|e| e.path == "stray.txt"));

    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn unsigned_package_verifies() {
    let out = tmp_path("unsigned.prsn");
    fixed_builder().write_zip(&out, None).unwrap();
    let mut pkg = Package::open(&out).unwrap();
    pkg.verify_integrity().expect("integrity");
    assert_eq!(pkg.verify_signature().expect("signature"), None);
    std::fs::remove_file(&out).ok();
}
