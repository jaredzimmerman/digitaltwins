// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//! `prsn` command-line interface.
//!
//! - `prsn canon <input.json>`: strict-parse, canonical-serialize, print the
//!   lowercase hex SHA-256 of the canonical bytes.
//! - `prsn build <out.prsn>`: write the fixed interop test package, signed
//!   with a fresh key; prints `public_key=<b64> key_id=<hex16>`.
//! - `prsn verify <file.prsn|dir>`: container rules, entry hashes/sizes,
//!   signature via the embedded key, tier downgrade applied.
//! - `prsn vectors <conformance-dir>`: run all v1-relevant conformance
//!   vectors, printing per-suite pass/fail counts.

mod vectors;

use std::path::Path;

use prsn::{canon, sha256_hex, Package, PackageBuilder, Value};

fn die(msg: &str) -> ! {
    eprintln!("prsn: {msg}");
    std::process::exit(1);
}

fn usage() -> ! {
    eprintln!("usage: prsn <canon <input.json> | build <out.prsn> | verify <file.prsn|dir> | vectors <conformance-dir>>");
    std::process::exit(2);
}

/// The fixed interop test package all three language implementations write.
fn fixed_package_builder() -> PackageBuilder {
    let mut b = PackageBuilder::new("person.json");
    b.set_top("created", Value::Str("2026-10-10T00:00:00Z".to_string()));
    b.set_top("generator", Value::Str("prsn-rs 0.1.0".to_string()));

    let person = canon::parse(
        br#"{"id":"urn:uuid:3b1f2a4c-9d5e-4f6a-8b7c-1d2e3f4a5b6c","display_name":"Interop Test","aliases":[],"ids":[],"links":[]}"#,
    )
    .expect("fixed person.json parses");
    let person_bytes = canon::to_canonical(&person).expect("fixed person.json serializes");
    b.add_file(
        "person.json",
        "org.prsn.person",
        "application/json",
        person_bytes,
        Vec::new(),
    )
    .expect("add person.json");

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
    .expect("add face sample");
    b.add_file(
        "voice/samples/s-0001.bin",
        "org.prsn.voice.sample",
        "application/octet-stream",
        b"voice sample".to_vec(),
        vec![("origin".to_string(), origin())],
    )
    .expect("add voice sample");
    b
}

fn cmd_canon(args: &[String]) {
    let path = args.get(2).unwrap_or_else(|| usage());
    let bytes = std::fs::read(path).unwrap_or_else(|e| die(&format!("read {path}: {e}")));
    let value = canon::parse(&bytes).unwrap_or_else(|e| die(&format!("{e}")));
    let canonical = canon::to_canonical(&value).unwrap_or_else(|e| die(&format!("{e}")));
    println!("{}", sha256_hex(&canonical));
}

fn cmd_build(args: &[String]) {
    let out = args.get(2).unwrap_or_else(|| usage());
    let seed = prsn::generate_seed().unwrap_or_else(|e| die(&format!("keygen: {e}")));
    let builder = fixed_package_builder();
    let report = builder
        .write_zip(Path::new(out), Some(&seed))
        .unwrap_or_else(|e| die(&format!("write: {e}")));
    use base64::{engine::general_purpose::STANDARD, Engine as _};
    let public_key_b64 = STANDARD.encode(report.public_key.expect("signed"));
    let key_id = report.key_id.expect("signed");
    println!("public_key={public_key_b64} key_id={key_id}");
}

fn cmd_verify(args: &[String]) {
    let path = args.get(2).unwrap_or_else(|| usage());
    let mut pkg = Package::open(Path::new(path)).unwrap_or_else(|e| die(&format!("{e}")));
    if let Err(problems) = pkg.verify_integrity() {
        for p in problems {
            eprintln!("integrity: {p}");
        }
        std::process::exit(1);
    }
    match pkg.verify_signature() {
        Err(e) => {
            eprintln!("signature: {e}");
            std::process::exit(1);
        }
        Ok(status) => {
            // No trusted keys by default: the downgrade applies unless the
            // caller trusts the signing key.
            pkg.apply_tier_downgrade(&[]);
            println!("VERIFY OK");
            match status {
                Some(key_id) => println!("signed key_id={key_id}"),
                None => println!("unsigned"),
            }
        }
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(|s| s.as_str()) {
        Some("canon") => cmd_canon(&args),
        Some("build") => cmd_build(&args),
        Some("verify") => cmd_verify(&args),
        Some("vectors") => vectors::run(&args),
        _ => usage(),
    }
}
