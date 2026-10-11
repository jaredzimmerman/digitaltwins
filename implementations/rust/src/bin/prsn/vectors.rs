// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//! `prsn vectors <conformance-dir>`: run every v1-relevant conformance
//! vector suite and print per-suite pass/fail counts.
//!
//! Suites: `json/canonical.json`, `hash/sha256.json`,
//! `hash/action_key.json`, `hash/ed25519.json`, `hash/manifest.json`,
//! `tiers/downgrade.json`, `container/cases.json` (+ fixtures),
//! `prsn/rules.json` (+ fixtures), and `examples/prsn/valid-v11`.

use std::path::{Path, PathBuf};

use base64::{engine::general_purpose::STANDARD, Engine as _};
use sha2::{Digest, Sha256};

use prsn::{
    action_key, canon, hex_decode, hex_encode, key_id_hex, public_key_from_seed, sha256_hex,
    sign_detached, tiers, verify_detached, Package, PackageBuilder, Value,
};

struct SuiteResult {
    pass: u64,
    fail: u64,
    failures: Vec<String>,
}

impl SuiteResult {
    fn new() -> Self {
        SuiteResult {
            pass: 0,
            fail: 0,
            failures: Vec::new(),
        }
    }
    fn ok(&mut self) {
        self.pass += 1;
    }
    fn bad(&mut self, msg: String) {
        self.fail += 1;
        self.failures.push(msg);
    }
}

fn load_json(dir: &Path, rel: &str) -> Value {
    let bytes = std::fs::read(dir.join(rel))
        .unwrap_or_else(|e| panic!("read {rel}: {e}"));
    canon::parse(&bytes).unwrap_or_else(|e| panic!("parse {rel}: {e}"))
}

fn get<'a>(v: &'a Value, key: &str) -> &'a Value {
    v.get(key)
        .unwrap_or_else(|| panic!("vector missing key `{key}`"))
}

fn as_str(v: &Value) -> &str {
    v.as_str().expect("vector value is not a string")
}

// ---------------------------------------------------------------------------
// json/canonical.json
// ---------------------------------------------------------------------------

fn suite_json_canonical(dir: &Path) -> SuiteResult {
    let mut r = SuiteResult::new();
    let doc = load_json(dir, "json/canonical.json");
    for v in get(&doc, "valid").as_array().expect("valid array") {
        let name = as_str(get(v, "name")).to_string();
        let input: Vec<u8> = match v.get("input_hex") {
            Some(Value::Str(hex)) => match hex_decode(hex) {
                Some(b) => b,
                None => {
                    r.bad(format!("{name}: bad input_hex"));
                    continue;
                }
            },
            _ => as_str(get(v, "input")).as_bytes().to_vec(),
        };
        let expected = as_str(get(v, "expected")).as_bytes();
        let expected_sha = as_str(get(v, "expected_sha256"));
        match canon::parse(&input) {
            Err(e) => r.bad(format!("{name}: valid input rejected: {e}")),
            Ok(value) => match canon::to_canonical(&value) {
                Err(e) => r.bad(format!("{name}: serialize failed: {e}")),
                Ok(bytes) => {
                    if bytes != expected {
                        r.bad(format!(
                            "{name}: bytes differ:\n  got      {}\n  expected {}",
                            String::from_utf8_lossy(&bytes),
                            String::from_utf8_lossy(expected)
                        ));
                    } else if sha256_hex(&bytes) != expected_sha {
                        r.bad(format!("{name}: sha256 mismatch"));
                    } else {
                        r.ok();
                    }
                }
            },
        }
    }
    for v in get(&doc, "invalid").as_array().expect("invalid array") {
        let name = as_str(get(v, "name")).to_string();
        let input: Vec<u8> = match v.get("input_hex") {
            Some(Value::Str(hex)) => hex_decode(hex).expect("bad input_hex"),
            _ => as_str(get(v, "input")).as_bytes().to_vec(),
        };
        match canon::parse(&input) {
            Err(_) => r.ok(),
            Ok(_) => r.bad(format!("{name}: invalid input accepted")),
        }
    }
    r
}

// ---------------------------------------------------------------------------
// hash/sha256.json
// ---------------------------------------------------------------------------

fn suite_sha256(dir: &Path) -> SuiteResult {
    let mut r = SuiteResult::new();
    let doc = load_json(dir, "hash/sha256.json");
    for v in get(&doc, "vectors").as_array().expect("vectors array") {
        let name = as_str(get(v, "name")).to_string();
        let input: Vec<u8> = if let Some(s) = v.get("input_utf8").and_then(|x| x.as_str()) {
            s.as_bytes().to_vec()
        } else {
            let g = get(v, "generator");
            let kind = as_str(get(g, "kind"));
            let length = get(g, "length").as_i64().expect("length") as usize;
            match kind {
                "repeat" => {
                    let byte = get(g, "byte").as_i64().expect("byte") as u8;
                    vec![byte; length]
                }
                "affine" => {
                    let mul = get(g, "mul").as_i64().expect("mul") as usize;
                    let add = get(g, "add").as_i64().expect("add") as usize;
                    (0..length).map(|i| ((i * mul + add) & 0xff) as u8).collect()
                }
                _ => {
                    r.bad(format!("{name}: unknown generator {kind}"));
                    continue;
                }
            }
        };
        let expected = as_str(get(v, "sha256"));
        if sha256_hex(&input) != expected {
            r.bad(format!("{name}: one-shot sha256 mismatch"));
            continue;
        }
        // Same hash fed in uneven streaming chunks.
        let mut h = Sha256::new();
        let mut i = 0;
        let mut step = 1usize;
        while i < input.len() {
            let end = (i + step).min(input.len());
            h.update(&input[i..end]);
            i = end;
            step = (step * 3 + 1) % 65537 + 1;
        }
        if hex_encode(&h.finalize()) != expected {
            r.bad(format!("{name}: streaming sha256 mismatch"));
            continue;
        }
        r.ok();
    }
    r
}

// ---------------------------------------------------------------------------
// hash/action_key.json
// ---------------------------------------------------------------------------

fn suite_action_key(dir: &Path) -> SuiteResult {
    let mut r = SuiteResult::new();
    let doc = load_json(dir, "hash/action_key.json");
    for v in get(&doc, "valid").as_array().expect("valid array") {
        let name = as_str(get(v, "name")).to_string();
        let derivation = get(v, "derivation");
        let expected_pre = as_str(get(v, "preimage")).as_bytes();
        let expected_key = as_str(get(v, "action_key"));
        match action_key::preimage_bytes(derivation) {
            Err(e) => r.bad(format!("{name}: preimage error: {e}")),
            Ok(pre) => {
                if pre != expected_pre {
                    r.bad(format!(
                        "{name}: preimage differs:\n  got      {}\n  expected {}",
                        String::from_utf8_lossy(&pre),
                        String::from_utf8_lossy(expected_pre)
                    ));
                    continue;
                }
                match action_key::action_key(derivation) {
                    Err(e) => r.bad(format!("{name}: action_key error: {e}")),
                    Ok(key) => {
                        if key != expected_key {
                            r.bad(format!("{name}: key {key} != {expected_key}"));
                        } else {
                            r.ok();
                        }
                    }
                }
            }
        }
    }
    for v in get(&doc, "invalid").as_array().expect("invalid array") {
        let name = as_str(get(v, "name")).to_string();
        match action_key::action_key(get(v, "derivation")) {
            Err(_) => r.ok(),
            Ok(key) => r.bad(format!("{name}: invalid derivation got key {key}")),
        }
    }
    r
}

// ---------------------------------------------------------------------------
// hash/ed25519.json
// ---------------------------------------------------------------------------

fn suite_ed25519(dir: &Path) -> SuiteResult {
    let mut r = SuiteResult::new();
    let doc = load_json(dir, "hash/ed25519.json");
    for v in get(&doc, "vectors").as_array().expect("vectors array") {
        let name = as_str(get(v, "name")).to_string();
        let seed: [u8; 32] = hex_decode(as_str(get(v, "seed")))
            .expect("seed hex")
            .try_into()
            .expect("seed len");
        let pk = public_key_from_seed(&seed);
        let mut bad = false;
        if hex_encode(&pk) != as_str(get(v, "public_key")) {
            r.bad(format!("{name}: public_key mismatch"));
            bad = true;
        }
        if STANDARD.encode(pk) != as_str(get(v, "public_key_b64")) {
            r.bad(format!("{name}: public_key_b64 mismatch"));
            bad = true;
        }
        if key_id_hex(&pk) != as_str(get(v, "key_id")) {
            r.bad(format!("{name}: key_id mismatch"));
            bad = true;
        }
        let msg = hex_decode(as_str(get(v, "message"))).expect("message hex");
        let sig: [u8; 64] = hex_decode(as_str(get(v, "signature")))
            .expect("sig hex")
            .try_into()
            .expect("sig len");
        match verify_detached(&pk, &msg, &sig) {
            Ok(true) => {}
            _ => {
                r.bad(format!("{name}: signature did not verify"));
                bad = true;
            }
        }
        // A bit-flipped signature must not verify.
        let mut flipped = sig;
        flipped[0] ^= 0x01;
        if verify_detached(&pk, &msg, &flipped) != Ok(false) {
            r.bad(format!("{name}: bit-flipped signature verified"));
            bad = true;
        }
        // A modified message must not verify.
        let mut bad_msg = msg.clone();
        if bad_msg.is_empty() {
            bad_msg.push(0x00);
        } else {
            bad_msg[0] ^= 0x01;
        }
        if verify_detached(&pk, &bad_msg, &sig) != Ok(false) {
            r.bad(format!("{name}: signature over modified message verified"));
            bad = true;
        }
        if !bad {
            r.ok();
        }
    }
    r
}

// ---------------------------------------------------------------------------
// hash/manifest.json
// ---------------------------------------------------------------------------

fn suite_manifest(dir: &Path) -> SuiteResult {
    let mut r = SuiteResult::new();
    let doc = load_json(dir, "hash/manifest.json");
    let seed: [u8; 32] = hex_decode(as_str(get(&doc, "seed")))
        .expect("seed hex")
        .try_into()
        .expect("seed len");

    let top = get(&doc, "top_level");
    let person_path = as_str(get(top, "person")).to_string();
    let mut builder = PackageBuilder::new(&person_path);
    for (k, v) in top.as_object().expect("top_level object") {
        builder.set_top(k, v.clone());
    }
    for f in get(&doc, "files").as_array().expect("files array") {
        let path = as_str(get(f, "path"));
        let content = as_str(get(f, "content")).as_bytes().to_vec();
        let type_ = as_str(get(f, "type"));
        let media = as_str(get(f, "media"));
        let extra: Vec<(String, Value)> = f
            .get("extra")
            .and_then(|e| e.as_object())
            .map(|o| o.to_vec())
            .unwrap_or_default();
        if let Err(e) = builder.add_file(path, type_, media, content, extra) {
            r.bad(format!("manifest vector: add_file: {e}"));
            return r;
        }
    }
    let manifest_bytes = builder.manifest_bytes(Some(&seed)).expect("manifest bytes");
    let expected = as_str(get(&doc, "canonical_manifest")).as_bytes();
    if manifest_bytes != expected {
        r.bad(format!(
            "canonical manifest differs:\n  got      {}\n  expected {}",
            String::from_utf8_lossy(&manifest_bytes),
            String::from_utf8_lossy(expected)
        ));
        return r;
    }
    if sha256_hex(&manifest_bytes) != as_str(get(&doc, "manifest_sha256")) {
        r.bad("manifest_sha256 mismatch".to_string());
        return r;
    }
    let sig = sign_detached(&seed, &manifest_bytes);
    if hex_encode(&sig) != as_str(get(&doc, "signature")) {
        r.bad("signature bytes differ".to_string());
        return r;
    }
    let pk = public_key_from_seed(&seed);
    if verify_detached(&pk, &manifest_bytes, &sig) != Ok(true) {
        r.bad("signature does not verify".to_string());
        return r;
    }
    r.ok();
    r
}

// ---------------------------------------------------------------------------
// tiers/downgrade.json
// ---------------------------------------------------------------------------

fn suite_tiers(dir: &Path) -> SuiteResult {
    let mut r = SuiteResult::new();
    let doc = load_json(dir, "tiers/downgrade.json");
    for case in get(&doc, "cases").as_array().expect("cases array") {
        let name = as_str(get(case, "name")).to_string();
        let trusted = get(case, "trusted").as_bool().expect("trusted");
        let mut entries: Vec<Value> = get(case, "entries")
            .as_array()
            .expect("entries")
            .to_vec();
        if !trusted {
            tiers::downgrade_entries(&mut entries);
        }
        let expected = get(case, "expected").as_array().expect("expected");
        if entries.len() != expected.len() {
            r.bad(format!("{name}: entry count changed"));
            continue;
        }
        let mut ok = true;
        for (got, want) in entries.iter().zip(expected.iter()) {
            let got_b = canon::to_canonical(got).expect("canon");
            let want_b = canon::to_canonical(want).expect("canon");
            if got_b != want_b {
                r.bad(format!(
                    "{name}: entry differs:\n  got      {}\n  expected {}",
                    String::from_utf8_lossy(&got_b),
                    String::from_utf8_lossy(&want_b)
                ));
                ok = false;
            }
        }
        if ok {
            r.ok();
        }
    }
    r
}

// ---------------------------------------------------------------------------
// container/cases.json + fixtures
// ---------------------------------------------------------------------------

fn suite_container(dir: &Path) -> SuiteResult {
    let mut r = SuiteResult::new();
    let doc = load_json(dir, "container/cases.json");
    for case in get(&doc, "cases").as_array().expect("cases array") {
        let file: PathBuf = dir.join("container").join(as_str(get(case, "file")));
        let outcome = as_str(get(case, "outcome"));
        let label = file.file_name().unwrap().to_string_lossy().to_string();
        match outcome {
            "valid" => match Package::open(&file) {
                Err(e) => r.bad(format!("{label}: valid container refused: {e}")),
                Ok(mut pkg) => {
                    if let Err(problems) = pkg.verify_integrity() {
                        r.bad(format!("{label}: integrity failed: {problems:?}"));
                    } else if pkg.verify_signature().is_err() {
                        r.bad(format!("{label}: signature failed"));
                    } else {
                        match pkg.validate() {
                            Err(e) => r.bad(format!("{label}: validate errored: {e}")),
                            Ok(rule_list) if !rule_list.is_empty() => r.bad(format!(
                                "{label}: unexpected rule violations: {:?}",
                                rule_list.iter().map(|x| x.as_str()).collect::<Vec<_>>()
                            )),
                            Ok(_) => r.ok(),
                        }
                    }
                }
            },
            "refuse" => match Package::open(&file) {
                Err(_) => r.ok(),
                Ok(_) => r.bad(format!("{label}: refused container was opened")),
            },
            other => r.bad(format!("{label}: unknown outcome {other}")),
        }
    }
    r
}

// ---------------------------------------------------------------------------
// prsn/rules.json + fixtures, examples/prsn/valid-v11
// ---------------------------------------------------------------------------

fn check_valid_package(r: &mut SuiteResult, label: &str, path: &Path) {
    let mut pkg = match Package::open(path) {
        Err(e) => {
            r.bad(format!("{label}: open failed: {e}"));
            return;
        }
        Ok(p) => p,
    };
    if let Err(problems) = pkg.verify_integrity() {
        r.bad(format!("{label}: integrity failed: {problems:?}"));
        return;
    }
    match pkg.validate() {
        Err(e) => r.bad(format!("{label}: validate errored: {e}")),
        Ok(rules) if !rules.is_empty() => r.bad(format!(
            "{label}: unexpected rule violations: {:?}",
            rules.iter().map(|x| x.as_str()).collect::<Vec<_>>()
        )),
        Ok(_) => r.ok(),
    }
}

fn suite_prsn(dir: &Path) -> SuiteResult {
    let mut r = SuiteResult::new();
    let doc = load_json(dir, "prsn/rules.json");
    // `valid[].path` is relative to the `prsn/` tree (conformance/../).
    let prsn_base = dir.join("..");
    for v in get(&doc, "valid").as_array().expect("valid array") {
        let id = as_str(get(v, "id")).to_string();
        let path: PathBuf = prsn_base.join(as_str(get(v, "path")));
        check_valid_package(&mut r, &format!("valid example {id}"), &path);
    }
    for case in get(&doc, "cases").as_array().expect("cases array") {
        let id = as_str(get(case, "id")).to_string();
        let path: PathBuf = dir.join("prsn").join(&id);
        match as_str(get(case, "outcome")) {
            "refuse" => match Package::open(&path) {
                Err(_) => r.ok(),
                Ok(_) => r.bad(format!("{id}: must be refused, but opened")),
            },
            "invalid" => {
                let expected = as_str(get(case, "rule")).to_string();
                match Package::open(&path) {
                    Err(e) => r.bad(format!("{id}: open refused an `invalid` case: {e}")),
                    Ok(mut pkg) => match pkg.validate() {
                        Err(e) => r.bad(format!("{id}: validate errored: {e}")),
                        Ok(rules) => {
                            let got: Vec<&str> =
                                rules.iter().map(|x| x.as_str()).collect();
                            if got == [expected.as_str()] {
                                r.ok();
                            } else {
                                r.bad(format!(
                                    "{id}: expected rule [{expected}], got [{:?}]",
                                    got.join(", ")
                                ));
                            }
                        }
                    },
                }
            }
            "valid" => {
                let mut pkg = match Package::open(&path) {
                    Err(e) => {
                        r.bad(format!("{id}: open failed: {e}"));
                        continue;
                    }
                    Ok(p) => p,
                };
                let rules = match pkg.validate() {
                    Err(e) => {
                        r.bad(format!("{id}: validate errored: {e}"));
                        continue;
                    }
                    Ok(rules) => rules,
                };
                if !rules.is_empty() {
                    r.bad(format!(
                        "{id}: unexpected rule violations: {:?}",
                        rules.iter().map(|x| x.as_str()).collect::<Vec<_>>()
                    ));
                    continue;
                }
                let behavior_ok = match id.as_str() {
                    "expired-entry" => {
                        // The expired entry is dropped on load.
                        pkg.entries().iter().all(|e| {
                            pkg.entry_object(&e.path)
                                .and_then(|o| o.get("expires"))
                                .is_none()
                        })
                    }
                    "retired-scopes-key" => pkg.manifest().get("scopes").is_none(),
                    "person-legacy-shape" => {
                        let p = pkg.person();
                        p.get("display_name").and_then(|v| v.as_str()).is_some()
                            && p.get("ids").and_then(|v| v.as_array()).is_some()
                            && p.get("links").and_then(|v| v.as_array()).is_some()
                    }
                    "unlisted-file" => {
                        !pkg.entries().iter().any(|e| e.path == "face/samples/stray.heic")
                    }
                    "unsigned" => matches!(pkg.verify_signature(), Ok(None)),
                    "unknown-noncritical-type" => pkg
                        .entries()
                        .iter()
                        .any(|e| e.path == "face/geometry/vendor.bin"),
                    "legacy-entries-unsorted" => true,
                    _ => true,
                };
                if behavior_ok {
                    r.ok();
                } else {
                    r.bad(format!("{id}: expected reader behavior not observed"));
                }
            }
            other => r.bad(format!("{id}: unknown outcome {other}")),
        }
    }
    r
}

fn suite_example_valid_v11(dir: &Path) -> SuiteResult {
    let mut r = SuiteResult::new();
    let label = "examples/prsn/valid-v11";
    let path = dir.join("..").join(label);
    let mut pkg = match Package::open(&path) {
        Err(e) => {
            r.bad(format!("{label}: open failed: {e}"));
            return r;
        }
        Ok(p) => p,
    };
    if let Err(problems) = pkg.verify_integrity() {
        r.bad(format!("{label}: integrity failed: {problems:?}"));
        return r;
    }
    match pkg.validate() {
        Err(e) => {
            r.bad(format!("{label}: validate errored: {e}"));
            return r;
        }
        Ok(rules) if !rules.is_empty() => {
            r.bad(format!(
                "{label}: unexpected rule violations: {:?}",
                rules.iter().map(|x| x.as_str()).collect::<Vec<_>>()
            ));
            return r;
        }
        Ok(_) => {}
    }
    let key_id = match pkg.verify_signature() {
        Err(e) => {
            r.bad(format!("{label}: signature failed: {e}"));
            return r;
        }
        Ok(None) => {
            r.bad(format!("{label}: expected a signature"));
            return r;
        }
        Ok(Some(k)) => k,
    };
    if key_id != "7b403348c09944ad" {
        r.bad(format!("{label}: unexpected key_id {key_id}"));
        return r;
    }
    // The published test key is NOT trusted: the tier downgrade must apply.
    pkg.apply_tier_downgrade(&[]);
    let sample = pkg
        .entry_object("face/samples/f-0001.heic")
        .expect("sample entry");
    let origin = sample.get("origin").expect("origin");
    let tier = origin.get("tier").and_then(|v| v.as_str());
    let was = origin.get("was").and_then(|v| v.as_str());
    if tier == Some("imported") && was == Some("enrolled") {
        r.ok();
    } else {
        r.bad(format!(
            "{label}: downgrade not applied (tier={tier:?}, was={was:?})"
        ));
    }
    r
}

pub fn run(args: &[String]) {
    let dir = args.get(2).unwrap_or_else(|| {
        eprintln!("usage: prsn vectors <conformance-dir>");
        std::process::exit(2);
    });
    let dir = Path::new(dir);
    let suites: Vec<(&str, SuiteResult)> = vec![
        ("json/canonical", suite_json_canonical(dir)),
        ("hash/sha256", suite_sha256(dir)),
        ("hash/action_key", suite_action_key(dir)),
        ("hash/ed25519", suite_ed25519(dir)),
        ("hash/manifest", suite_manifest(dir)),
        ("tiers/downgrade", suite_tiers(dir)),
        ("container", suite_container(dir)),
        ("prsn/rules", suite_prsn(dir)),
        ("examples/valid-v11", suite_example_valid_v11(dir)),
    ];
    let mut total_pass = 0u64;
    let mut total_fail = 0u64;
    for (name, s) in &suites {
        println!("{name}: {} passed, {} failed", s.pass, s.fail);
        total_pass += s.pass;
        total_fail += s.fail;
    }
    for (name, s) in &suites {
        for f in &s.failures {
            println!("FAIL [{name}] {f}");
        }
    }
    println!("total: {total_pass} passed, {total_fail} failed");
    if total_fail > 0 {
        std::process::exit(1);
    }
}
