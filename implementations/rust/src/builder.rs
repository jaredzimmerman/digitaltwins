// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//! Building `.prsn` packages: new package -> add entries -> write ZIP (or
//! directory) with a canonical `manifest.json` and optional signing.
//!
//! Writers list entries sorted by path in UTF-8 byte order. The ZIP member
//! order is: `mimetype`, `manifest.json`, the `person.json` entry, the other
//! entries in manifest order, then `signatures/manifest.sig`.

use std::io::Write;
use std::path::Path;

use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipWriter};

use crate::canon::{self, Value};
use crate::hash::{key_id_hex, sha256_hex};
use crate::package::{Error, MIMETYPE, SIGNATURE_PATH};
use crate::sign::{public_key_from_seed, sign_detached};

/// One file to be added to a package.
#[derive(Debug, Clone)]
pub struct BuilderFile {
    pub path: String,
    pub type_: String,
    pub media: String,
    pub bytes: Vec<u8>,
    /// Record fields beyond path/type/media/sha256/bytes (e.g. `origin`).
    pub extra: Vec<(String, Value)>,
}

/// What writing a package produced.
#[derive(Debug)]
pub struct WriteReport {
    pub manifest_bytes: Vec<u8>,
    pub manifest_sha256: String,
    pub signature: Option<[u8; 64]>,
    pub public_key: Option<[u8; 32]>,
    pub key_id: Option<String>,
}

#[derive(Debug, Default)]
pub struct PackageBuilder {
    person_path: String,
    spec: String,
    top: Vec<(String, Value)>,
    files: Vec<BuilderFile>,
}

impl PackageBuilder {
    /// Start a new package whose person record lives at `person_path`
    /// (usually `"person.json"`).
    pub fn new(person_path: &str) -> Self {
        PackageBuilder {
            person_path: person_path.to_string(),
            spec: "1.1".to_string(),
            top: Vec::new(),
            files: Vec::new(),
        }
    }

    /// Override the manifest `spec` revision (default `"1.1"`).
    pub fn set_spec(&mut self, spec: &str) {
        self.spec = spec.to_string();
    }

    /// Set a top-level manifest field (`created`, `generator`, `looks`,
    /// `eras`, `budgets`, ...).
    pub fn set_top(&mut self, key: &str, value: Value) {
        if let Some(slot) = self.top.iter_mut().find(|(k, _)| k == key) {
            slot.1 = value;
        } else {
            self.top.push((key.to_string(), value));
        }
    }

    /// Add a file. `extra` holds the entry's record fields. Duplicate paths
    /// are refused.
    pub fn add_file(
        &mut self,
        path: &str,
        type_: &str,
        media: &str,
        bytes: Vec<u8>,
        extra: Vec<(String, Value)>,
    ) -> Result<(), String> {
        if self.files.iter().any(|f| f.path == path) {
            return Err(format!("duplicate entry path: {path}"));
        }
        self.files.push(BuilderFile {
            path: path.to_string(),
            type_: type_.to_string(),
            media: media.to_string(),
            bytes,
            extra,
        });
        Ok(())
    }

    fn sorted_files(&self) -> Result<Vec<&BuilderFile>, String> {
        let mut files: Vec<&BuilderFile> = self.files.iter().collect();
        files.sort_by(|a, b| a.path.as_bytes().cmp(b.path.as_bytes()));
        Ok(files)
    }

    fn signature_block(seed: &[u8; 32]) -> Value {
        use base64::{engine::general_purpose::STANDARD, Engine as _};
        let pk = public_key_from_seed(seed);
        Value::Object(vec![
            ("path".to_string(), Value::Str(SIGNATURE_PATH.to_string())),
            ("alg".to_string(), Value::Str("Ed25519".to_string())),
            ("key_id".to_string(), Value::Str(key_id_hex(&pk))),
            (
                "public_key".to_string(),
                Value::Str(STANDARD.encode(pk)),
            ),
        ])
    }

    /// Build the manifest value (entries sorted by path in UTF-8 byte
    /// order), including the signature block when `seed` is given.
    pub fn manifest_value(&self, seed: Option<&[u8; 32]>) -> Result<Value, String> {
        let files = self.sorted_files()?;
        let mut entries = Vec::with_capacity(files.len());
        for f in files {
            let mut obj = vec![
                ("path".to_string(), Value::Str(f.path.clone())),
                ("type".to_string(), Value::Str(f.type_.clone())),
                ("media".to_string(), Value::Str(f.media.clone())),
                ("sha256".to_string(), Value::Str(sha256_hex(&f.bytes))),
                ("bytes".to_string(), Value::Int(f.bytes.len() as i64)),
            ];
            obj.extend(f.extra.clone());
            entries.push(Value::Object(obj));
        }
        let mut top = vec![
            ("format".to_string(), Value::Str("prsn".to_string())),
            ("version".to_string(), Value::Int(1)),
            ("spec".to_string(), Value::Str(self.spec.clone())),
        ];
        top.extend(self.top.clone());
        top.push(("person".to_string(), Value::Str(self.person_path.clone())));
        top.push(("entries".to_string(), Value::Array(entries)));
        if let Some(seed) = seed {
            top.push(("signature".to_string(), Self::signature_block(seed)));
        }
        // Later fields win on reserved keys, so set_top("spec", …) etc.
        // override the structural defaults instead of duplicating them.
        let mut seen = std::collections::HashSet::new();
        let mut deduped = Vec::new();
        for (k, v) in top.into_iter().rev() {
            if seen.insert(k.clone()) {
                deduped.push((k, v));
            }
        }
        deduped.reverse();
        Ok(Value::Object(deduped))
    }

    /// Canonical JSON bytes of the manifest (what is hashed and signed).
    pub fn manifest_bytes(&self, seed: Option<&[u8; 32]>) -> Result<Vec<u8>, String> {
        let v = self.manifest_value(seed)?;
        canon::to_canonical(&v).map_err(|e| e.to_string())
    }

    fn compression_for(media: &str) -> CompressionMethod {
        // Spec: JSON is DEFLATE; audio/images/video/CBEFF/nested ZIPs are
        // STORED (already compressed). Raw byte payloads go STORED.
        if media == "application/json" {
            CompressionMethod::Deflated
        } else {
            CompressionMethod::Stored
        }
    }

    /// Write the ZIP interchange form.
    pub fn write_zip(&self, out: &Path, seed: Option<&[u8; 32]>) -> Result<WriteReport, Error> {
        let manifest_bytes = self
            .manifest_bytes(seed)
            .map_err(Error::Manifest)?;
        let signature: Option<[u8; 64]> =
            seed.map(|s| sign_detached(s, &manifest_bytes));

        let file = std::fs::File::create(out)?;
        let mut zip = ZipWriter::new(file);
        let stored = SimpleFileOptions::default().compression_method(CompressionMethod::Stored);
        let deflated = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);

        // `mimetype` first, STORED, no extra field.
        zip.start_file("mimetype", stored)?;
        zip.write_all(MIMETYPE)?;

        zip.start_file("manifest.json", deflated)?;
        zip.write_all(&manifest_bytes)?;

        // The person entry right after the manifest, then the rest in
        // manifest (sorted) order.
        let files = self.sorted_files().map_err(Error::Manifest)?;
        let (person_first, rest): (Vec<&&BuilderFile>, Vec<&&BuilderFile>) =
            files.iter().partition(|f| f.path == self.person_path);
        for f in person_first.into_iter().chain(rest.into_iter()) {
            let opts = SimpleFileOptions::default()
                .compression_method(Self::compression_for(&f.media));
            zip.start_file(&f.path, opts)?;
            zip.write_all(&f.bytes)?;
        }

        if let Some(sig) = &signature {
            zip.start_file(SIGNATURE_PATH, stored)?;
            zip.write_all(sig)?;
        }
        zip.finish().map_err(Error::from)?;

        let public_key = seed.map(public_key_from_seed);
        let key_id = public_key.as_ref().map(|pk| key_id_hex(pk));
        Ok(WriteReport {
            manifest_sha256: sha256_hex(&manifest_bytes),
            manifest_bytes,
            signature,
            public_key,
            key_id,
        })
    }

    /// Write the directory working form (same tree, same `manifest.json`).
    pub fn write_dir(&self, dir: &Path, seed: Option<&[u8; 32]>) -> Result<WriteReport, Error> {
        let manifest_bytes = self.manifest_bytes(seed).map_err(Error::Manifest)?;
        let signature: Option<[u8; 64]> = seed.map(|s| sign_detached(s, &manifest_bytes));

        std::fs::create_dir_all(dir)?;
        std::fs::write(dir.join("mimetype"), MIMETYPE)?;
        std::fs::write(dir.join("manifest.json"), &manifest_bytes)?;
        for f in &self.files {
            let p = dir.join(&f.path);
            if let Some(parent) = p.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(&p, &f.bytes)?;
        }
        if let Some(sig) = &signature {
            let p = dir.join(SIGNATURE_PATH);
            if let Some(parent) = p.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(&p, sig)?;
        }

        let public_key = seed.map(public_key_from_seed);
        let key_id = public_key.as_ref().map(|pk| key_id_hex(pk));
        Ok(WriteReport {
            manifest_sha256: sha256_hex(&manifest_bytes),
            manifest_bytes,
            signature,
            public_key,
            key_id,
        })
    }
}
