// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//! `.prsn` container: opening ZIP and directory packages, container rules,
//! integrity (size + SHA-256) checks and manifest signature verification.
//!
//! ZIP rules (spec `prsn.md`, "Container"): the first member is `mimetype`,
//! STORED, with no extra field, holding exactly `application/vnd.prsn+zip`
//! (the legacy `application/vnd.museli.prsn+zip` is accepted on read); member
//! names are unique; members the manifest does not list are ignored; every
//! listed entry must be present with matching size and SHA-256.

use std::collections::HashSet;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

use zip::ZipArchive;

use crate::canon::{self, Value};
use crate::hash::{key_id_hex, sha256_hex};
use crate::sign::verify_detached;

/// Exact bytes of the `mimetype` member for current files.
pub const MIMETYPE: &[u8] = b"application/vnd.prsn+zip";
/// Legacy mimetype (spec Appendix A); accepted on read, never written.
pub const MIMETYPE_LEGACY: &[u8] = b"application/vnd.museli.prsn+zip";
/// Highest manifest `version` this reader supports.
pub const SUPPORTED_VERSION: i64 = 1;
/// Path of the detached manifest signature.
pub const SIGNATURE_PATH: &str = "signatures/manifest.sig";

#[derive(Debug)]
pub enum Error {
    Io(String),
    Zip(String),
    Json(canon::ParseError),
    Container(String),
    Version(String),
    Critical(String),
    Manifest(String),
    Signature(String),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::Io(e) => write!(f, "I/O error: {e}"),
            Error::Zip(e) => write!(f, "ZIP error: {e}"),
            Error::Json(e) => write!(f, "{e}"),
            Error::Container(e) => write!(f, "container: {e}"),
            Error::Version(e) => write!(f, "version: {e}"),
            Error::Critical(e) => write!(f, "critical: {e}"),
            Error::Manifest(e) => write!(f, "manifest: {e}"),
            Error::Signature(e) => write!(f, "signature: {e}"),
        }
    }
}

impl std::error::Error for Error {}

impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::Io(e.to_string())
    }
}

impl From<zip::result::ZipError> for Error {
    fn from(e: zip::result::ZipError) -> Self {
        Error::Zip(e.to_string())
    }
}

impl From<canon::ParseError> for Error {
    fn from(e: canon::ParseError) -> Self {
        Error::Json(e)
    }
}

pub(crate) enum Store {
    Zip { archive: ZipArchive<File> },
    Dir(PathBuf),
}

/// One row of `manifest.json` `entries`.
#[derive(Debug, Clone)]
pub(crate) struct ManifestEntry {
    pub index: usize,
    pub path: String,
    pub type_: String,
    pub media: String,
    pub sha256: String,
    pub bytes: u64,
}

/// A read view of an entry (a live, i.e. non-expired, manifest entry).
#[derive(Debug, Clone)]
pub struct EntryInfo {
    pub path: String,
    pub type_: String,
    pub media: String,
    pub sha256: String,
    pub bytes: u64,
}

/// An opened `.prsn` package (ZIP or directory).
pub struct Package {
    pub(crate) store: Store,
    pub(crate) manifest: Value,
    /// Manifest exactly as parsed, before the retired `scopes` key is
    /// dropped: the signature is verified over this form.
    pub(crate) manifest_signed: Value,
    pub(crate) entries: Vec<ManifestEntry>,
    /// Indices into `entries` that are not expired.
    pub(crate) live: Vec<usize>,
    pub(crate) person: Value,
    pub(crate) spec: (u64, u64),
    pub(crate) person_path: String,
}

/// A record type this reader understands. Unknown non-critical types are
/// skipped and copied through; an unknown *critical* type refuses the file.
fn is_known_type(t: &str) -> bool {
    t.starts_with("org.prsn.") || t.starts_with("org.museli.")
}

/// Names of all central-directory entries, in order, parsed directly from
/// the raw ZIP bytes.
///
/// This is done by hand rather than through the `zip` crate because the
/// crate's central-directory view can silently drop a duplicated entry, and
/// the container rule ("no duplicate member names") needs the exact record.
fn read_central_names(file: &mut File) -> Result<Vec<String>, Error> {
    let len = file.metadata()?.len();
    // The end-of-central-directory record is the last occurrence of its
    // signature in the tail of the file (the comment may contain it).
    let tail_len = len.min(65536 + 22);
    file.seek(SeekFrom::End(-(tail_len as i64)))?;
    let mut tail = vec![0u8; tail_len as usize];
    file.read_exact(&mut tail)?;
    let sig: [u8; 4] = [0x50, 0x4b, 0x05, 0x06];
    let eocd_rel = tail
        .windows(4)
        .rposition(|w| w == sig)
        .ok_or_else(|| Error::Container("ZIP end-of-central-directory not found".to_string()))?;
    let eocd = &tail[eocd_rel..];
    if eocd.len() < 22 {
        return Err(Error::Container("truncated end-of-central-directory".to_string()));
    }
    let count16 = u16::from_le_bytes(eocd[10..12].try_into().unwrap());
    // ZIP64 uses a separate end-of-central-directory record; follow it.
    let cd_offset = if count16 == 0xffff {
        let loc_sig: [u8; 4] = [0x50, 0x4b, 0x06, 0x07];
        let loc_rel = tail[..eocd_rel]
            .windows(4)
            .rposition(|w| w == loc_sig)
            .ok_or_else(|| Error::Container("ZIP64 end-of-central-directory locator not found".to_string()))?;
        let loc = &tail[loc_rel..];
        if loc.len() < 20 {
            return Err(Error::Container("truncated ZIP64 locator".to_string()));
        }
        let zip64_eocd_off = u64::from_le_bytes(loc[8..16].try_into().unwrap());
        file.seek(SeekFrom::Start(zip64_eocd_off))?;
        let mut rec = [0u8; 56];
        file.read_exact(&mut rec)
            .map_err(|_| Error::Container("truncated ZIP64 end-of-central-directory".to_string()))?;
        if u32::from_le_bytes(rec[0..4].try_into().unwrap()) != 0x0606_4b50 {
            return Err(Error::Container("bad ZIP64 end-of-central-directory".to_string()));
        }
        let off = u64::from_le_bytes(rec[48..56].try_into().unwrap());
        off
    } else {
        u32::from_le_bytes(eocd[16..20].try_into().unwrap()) as u64
    };
    let eocd_abs = len - tail_len + eocd_rel as u64;
    if cd_offset > eocd_abs {
        return Err(Error::Container("bad central directory offset".to_string()));
    }
    let cd_len = eocd_abs - cd_offset;
    file.seek(SeekFrom::Start(cd_offset))?;
    let mut cd = vec![0u8; cd_len as usize];
    file.read_exact(&mut cd)?;

    let mut names = Vec::new();
    let mut pos = 0usize;
    // Walk every entry record; `count` is not trusted as a bound (a lying
    // count must not hide a duplicated name).
    while pos + 46 <= cd.len() && names.len() < 10_000_000 {
        if u32::from_le_bytes(cd[pos..pos + 4].try_into().unwrap()) != 0x0201_4b50 {
            break;
        }
        let nlen = u16::from_le_bytes(cd[pos + 28..pos + 30].try_into().unwrap()) as usize;
        let elen = u16::from_le_bytes(cd[pos + 30..pos + 32].try_into().unwrap()) as usize;
        let clen = u16::from_le_bytes(cd[pos + 32..pos + 34].try_into().unwrap()) as usize;
        let name_start = pos + 46;
        let name_end = name_start + nlen;
        if name_end > cd.len() {
            return Err(Error::Container("truncated central directory entry".to_string()));
        }
        let name = std::str::from_utf8(&cd[name_start..name_end])
            .map_err(|_| Error::Container("non-UTF-8 member name".to_string()))?
            .to_string();
        names.push(name);
        pos = name_end + elen + clen;
    }
    Ok(names)
}

fn check_zip_mimetype(file: &mut File) -> Result<(), Error> {
    file.seek(SeekFrom::Start(0))?;
    let mut hdr = [0u8; 30];
    file.read_exact(&mut hdr).map_err(|_| {
        Error::Container("not a ZIP file (short read on first local header)".to_string())
    })?;
    if u32::from_le_bytes(hdr[0..4].try_into().unwrap()) != 0x0403_4b50 {
        return Err(Error::Container(
            "not a ZIP file (bad first local header signature)".to_string(),
        ));
    }
    let method = u16::from_le_bytes(hdr[8..10].try_into().unwrap());
    let name_len = u16::from_le_bytes(hdr[26..28].try_into().unwrap()) as usize;
    let extra_len = u16::from_le_bytes(hdr[28..30].try_into().unwrap()) as usize;
    let csize = u32::from_le_bytes(hdr[18..22].try_into().unwrap()) as usize;
    if name_len > 256 || csize > 4096 {
        return Err(Error::Container("implausible mimetype local header".to_string()));
    }
    let mut name = vec![0u8; name_len];
    file.read_exact(&mut name)?;
    if name != b"mimetype" {
        return Err(Error::Container(format!(
            "first member is not `mimetype` (is {:?})",
            String::from_utf8_lossy(&name)
        )));
    }
    if method != 0 {
        return Err(Error::Container(
            "`mimetype` must be STORED (method 0)".to_string(),
        ));
    }
    if extra_len != 0 {
        return Err(Error::Container(
            "`mimetype` must have no extra field".to_string(),
        ));
    }
    let mut content = vec![0u8; csize];
    file.read_exact(&mut content)?;
    if content != MIMETYPE && content != MIMETYPE_LEGACY {
        return Err(Error::Container(format!(
            "`mimetype` holds {:?}, not a .prsn media type",
            String::from_utf8_lossy(&content)
        )));
    }
    Ok(())
}

impl Package {
    /// Open a `.prsn` package: a directory package, or a ZIP file.
    pub fn open(path: &Path) -> Result<Package, Error> {
        if path.is_dir() {
            Package::open_dir(path)
        } else {
            Package::open_zip(path)
        }
    }

    /// Open the ZIP interchange form.
    pub fn open_zip(path: &Path) -> Result<Package, Error> {
        let mut file = File::open(path)?;
        check_zip_mimetype(&mut file)?;
        // Central-directory order, parsed from the raw bytes (the `zip`
        // crate's view can silently drop a duplicated entry).
        let central_names = read_central_names(&mut file)?;
        if central_names.is_empty() {
            return Err(Error::Container("empty ZIP".to_string()));
        }
        if central_names[0] != "mimetype" {
            return Err(Error::Container(
                "first member is not `mimetype`".to_string(),
            ));
        }
        let mut seen = HashSet::new();
        for name in &central_names {
            if !seen.insert(name.clone()) {
                return Err(Error::Container(format!("duplicate member name: {name}")));
            }
        }
        let archive = ZipArchive::new(file)?;
        let mut store = Store::Zip { archive };
        let manifest_raw = read_member(&mut store, "manifest.json").map_err(|_| {
            Error::Manifest("manifest.json is missing from the package".to_string())
        })?;
        assemble(store, manifest_raw)
    }

    /// Open the directory working form (same tree, same `manifest.json`).
    pub fn open_dir(path: &Path) -> Result<Package, Error> {
        let mime_path = path.join("mimetype");
        let content = std::fs::read(&mime_path).map_err(|_| {
            Error::Container("directory package has no `mimetype` file".to_string())
        })?;
        if content != MIMETYPE && content != MIMETYPE_LEGACY {
            return Err(Error::Container(
                "`mimetype` is not a .prsn media type".to_string(),
            ));
        }
        let manifest_path = path.join("manifest.json");
        let manifest_raw = std::fs::read(&manifest_path)
            .map_err(|_| Error::Manifest("manifest.json is missing from the package".to_string()))?;
        assemble(Store::Dir(path.to_path_buf()), manifest_raw)
    }

    /// The working manifest (retired `scopes` dropped, tiers possibly
    /// downgraded by [`Package::apply_tier_downgrade`]).
    pub fn manifest(&self) -> &Value {
        &self.manifest
    }

    /// The person record (`person.json`), legacy shape mapped when the file
    /// predates spec 1.1.
    pub fn person(&self) -> &Value {
        &self.person
    }

    /// The manifest `spec` revision as `(major, minor)`; absent means `(1, 0)`.
    pub fn spec(&self) -> (u64, u64) {
        self.spec
    }

    /// Live (non-expired) manifest entries, in manifest order.
    pub fn list_entries(&self) -> Vec<EntryInfo> {
        self.live
            .iter()
            .map(|&i| {
                let e = &self.entries[i];
                EntryInfo {
                    path: e.path.clone(),
                    type_: e.type_.clone(),
                    media: e.media.clone(),
                    sha256: e.sha256.clone(),
                    bytes: e.bytes,
                }
            })
            .collect()
    }

    /// Alias for [`Package::list_entries`].
    pub fn entries(&self) -> Vec<EntryInfo> {
        self.list_entries()
    }

    /// Read the bytes of a live manifest entry. Members the manifest does
    /// not list are not part of the file and cannot be read this way.
    pub fn read_entry_bytes(&mut self, path: &str) -> Result<Vec<u8>, Error> {
        let known = self.live.iter().any(|&i| self.entries[i].path == path);
        if !known {
            return Err(Error::Manifest(format!("no such entry: {path}")));
        }
        read_member(&mut self.store, path)
    }

    /// Verify every live entry is present with matching size and SHA-256.
    /// Returns the list of problems (empty means OK).
    pub fn verify_integrity(&mut self) -> Result<(), Vec<String>> {
        let mut problems = Vec::new();
        for &i in &self.live.clone() {
            let e = &self.entries[i];
            match read_member(&mut self.store, &e.path) {
                Err(err) => problems.push(format!("{}: missing ({err})", e.path)),
                Ok(bytes) => {
                    if bytes.len() as u64 != e.bytes {
                        problems.push(format!(
                            "{}: size {} != manifest {}",
                            e.path,
                            bytes.len(),
                            e.bytes
                        ));
                    }
                    let hex = sha256_hex(&bytes);
                    if hex != e.sha256 {
                        problems.push(format!("{}: SHA-256 mismatch", e.path));
                    }
                }
            }
        }
        if problems.is_empty() {
            Ok(())
        } else {
            Err(problems)
        }
    }

    /// Verify the manifest signature.
    ///
    /// Returns `Ok(None)` when the manifest has no `signature` block
    /// (unsigned), `Ok(Some(key_id))` when the Ed25519 signature verifies,
    /// and `Err` when the block is present but broken: signature file
    /// missing, `key_id` not matching the public key, or a bad signature.
    pub fn verify_signature(&mut self) -> Result<Option<String>, Error> {
        let block = match self.manifest_signed.get("signature") {
            None | Some(Value::Null) => return Ok(None),
            Some(b) => b,
        };
        let obj = block
            .as_object()
            .ok_or_else(|| Error::Signature("signature block is not an object".to_string()))?;
        let get_str = |key: &str| {
            obj.iter()
                .find(|(k, _)| k == key)
                .and_then(|(_, v)| v.as_str())
                .ok_or_else(|| Error::Signature(format!("signature block missing `{key}`")))
        };
        let alg = get_str("alg")?;
        if alg != "Ed25519" {
            return Err(Error::Signature(format!("unsupported signature alg: {alg}")));
        }
        let key_id = get_str("key_id")?.to_string();
        let public_key_b64 = get_str("public_key")?;
        let sig_path = obj
            .iter()
            .find(|(k, _)| k == "path")
            .and_then(|(_, v)| v.as_str())
            .unwrap_or(SIGNATURE_PATH);
        let public_key: [u8; 32] = {
            use base64::{engine::general_purpose::STANDARD, Engine as _};
            let raw = STANDARD
                .decode(public_key_b64)
                .map_err(|e| Error::Signature(format!("public_key is not base64: {e}")))?;
            raw.try_into()
                .map_err(|_| Error::Signature("public_key is not 32 bytes".to_string()))?
        };
        if key_id_hex(&public_key) != key_id {
            return Err(Error::Signature(
                "key_id is not the first 16 hex digits of SHA-256(public_key)".to_string(),
            ));
        }
        let sig_bytes = read_member(&mut self.store, sig_path)
            .map_err(|_| Error::Signature(format!("signature file missing: {sig_path}")))?;
        let sig_arr: [u8; 64] = sig_bytes
            .as_slice()
            .try_into()
            .map_err(|_| Error::Signature("signature is not 64 bytes".to_string()))?;
        // The signature covers the canonical JSON of the whole manifest.json,
        // signature block included (and before the retired `scopes` key is
        // dropped from the working copy).
        let canonical = canon::to_canonical(&self.manifest_signed)
            .map_err(|e| Error::Signature(format!("cannot canonicalise manifest: {e}")))?;
        let ok = verify_detached(&public_key, &canonical, &sig_arr)
            .map_err(Error::Signature)?;
        if !ok {
            return Err(Error::Signature(
                "Ed25519 signature does not verify (manifest altered after signing)".to_string(),
            ));
        }
        Ok(Some(key_id))
    }

    /// Apply the provenance tier downgrade: if the file is unsigned, or
    /// signed by a key not in `trusted_key_ids`, every entry with
    /// `origin.tier` in {enrolled, professional} becomes `imported` (claimed
    /// tier kept as `origin.was`) and template `evidence` seconds move to
    /// `imported`.
    pub fn apply_tier_downgrade(&mut self, trusted_key_ids: &[String]) {
        let trusted = match self.verify_signature() {
            Ok(Some(key_id)) => trusted_key_ids.iter().any(|k| k == &key_id),
            _ => false,
        };
        if trusted {
            return;
        }
        if let Some(entries) = self.manifest.get_mut("entries").and_then(|v| v.as_array_mut()) {
            crate::tiers::downgrade_entries(entries);
        }
    }

    /// Full entry object for a live entry path (all record fields).
    pub fn entry_object(&self, path: &str) -> Option<&Value> {
        let e = self.entries.iter().find(|e| e.path == path)?;
        if !self.live.iter().any(|&i| self.entries[i].index == e.index) {
            return None;
        }
        self.manifest.get("entries")?.as_array()?.get(e.index)
    }
}

pub(crate) fn read_member(store: &mut Store, name: &str) -> Result<Vec<u8>, Error> {
    match store {
        Store::Zip { archive } => {
            let mut f = archive
                .by_name(name)
                .map_err(|_| Error::Manifest(format!("member missing: {name}")))?;
            let mut buf = Vec::new();
            f.read_to_end(&mut buf)?;
            Ok(buf)
        }
        Store::Dir(dir) => {
            // Keep reads inside the package directory.
            let mut rel = PathBuf::new();
            for comp in Path::new(name).components() {
                match comp {
                    std::path::Component::Normal(c) => rel.push(c),
                    _ => {
                        return Err(Error::Manifest(format!("bad member path: {name}")));
                    }
                }
            }
            std::fs::read(dir.join(rel))
                .map_err(|_| Error::Manifest(format!("member missing: {name}")))
        }
    }
}

fn assemble(mut store: Store, manifest_raw: Vec<u8>) -> Result<Package, Error> {
    let manifest_signed: Value = canon::parse(&manifest_raw)?;
    let obj = manifest_signed
        .as_object()
        .ok_or_else(|| Error::Manifest("manifest.json must be an object".to_string()))?;

    let get = |key: &str| obj.iter().find(|(k, _)| k == key).map(|(_, v)| v);

    if get("format").and_then(|v| v.as_str()) != Some("prsn") {
        return Err(Error::Version("manifest.format must be \"prsn\"".to_string()));
    }
    let version = get("version").and_then(|v| v.as_i64());
    match version {
        Some(n) if (1..=SUPPORTED_VERSION).contains(&n) => {}
        Some(n) => {
            return Err(Error::Version(format!(
                "unsupported manifest version {n} (reader supports {SUPPORTED_VERSION})"
            )))
        }
        None => {
            return Err(Error::Version(
                "manifest.version must be an integer".to_string(),
            ))
        }
    }
    let spec: (u64, u64) = match get("spec") {
        None | Some(Value::Null) => (1, 0),
        Some(Value::Str(s)) => parse_spec(s)?,
        Some(_) => {
            return Err(Error::Version(
                "manifest.spec must be \"<major>.<minor>\"".to_string(),
            ))
        }
    };

    let entries_raw = get("entries")
        .and_then(|v| v.as_array())
        .ok_or_else(|| Error::Manifest("manifest.entries must be an array".to_string()))?;
    let mut entries = Vec::with_capacity(entries_raw.len());
    for (index, item) in entries_raw.iter().enumerate() {
        let e = item
            .as_object()
            .ok_or_else(|| Error::Manifest(format!("entry {index} is not an object")))?;
        let str_field = |key: &str| {
            e.iter()
                .find(|(k, _)| k == key)
                .and_then(|(_, v)| v.as_str())
                .ok_or_else(|| Error::Manifest(format!("entry {index} missing string `{key}`")))
                .map(|s| s.to_string())
        };
        let bytes = e
            .iter()
            .find(|(k, _)| k == "bytes")
            .and_then(|(_, v)| v.as_i64())
            .filter(|n| *n >= 0)
            .ok_or_else(|| Error::Manifest(format!("entry {index} missing integer `bytes`")))?
            as u64;
        let type_ = str_field("type")?;
        if item.get("critical").and_then(|v| v.as_bool()) == Some(true) && !is_known_type(&type_) {
            return Err(Error::Critical(format!(
                "critical entry of unknown type: {type_}"
            )));
        }
        entries.push(ManifestEntry {
            index,
            path: str_field("path")?,
            type_,
            media: str_field("media")?,
            sha256: str_field("sha256")?,
            bytes,
        });
    }

    // The retired `scopes` key (an early draft's consent object) is dropped on
    // load and never written back. The signature is verified over the
    // as-parsed form (kept in `manifest_signed`), so drop it only afterwards.
    let mut manifest = manifest_signed.clone();
    manifest.remove("scopes");

    let person_path = get("person")
        .and_then(|v| v.as_str())
        .ok_or_else(|| Error::Manifest("manifest.person is missing".to_string()))?
        .to_string();
    let person_bytes = read_member(&mut store, &person_path)
        .map_err(|_| Error::Manifest(format!("person file missing: {person_path}")))?;
    let mut person: Value = canon::parse(&person_bytes)
        .map_err(|_| Error::Manifest(format!("person file is not strict JSON: {person_path}")))?;
    if spec < (1, 1) {
        map_legacy_person(&mut person);
    }

    // Expired entries are dropped on load.
    let today = today_ymd();
    let live: Vec<usize> = entries_raw
        .iter()
        .enumerate()
        .filter(|(_, item)| !is_expired(item, &today))
        .map(|(i, _)| i)
        .collect();

    Ok(Package {
        store,
        manifest,
        manifest_signed,
        entries,
        live,
        person,
        spec,
        person_path,
    })
}

fn parse_spec(s: &str) -> Result<(u64, u64), Error> {
    let mut parts = s.split('.');
    let bad = || Error::Version("manifest.spec must be \"<major>.<minor>\"".to_string());
    let major: u64 = parts.next().ok_or_else(bad)?.parse().map_err(|_| bad())?;
    let minor: u64 = parts.next().ok_or_else(bad)?.parse().map_err(|_| bad())?;
    if parts.next().is_some() {
        return Err(bad());
    }
    Ok((major, minor))
}

/// Map the pre-1.1 `person.json` shape: `name` -> `display_name`, an `ids`
/// object -> `[{scheme, value}]`, a `links` object -> `[{rel, href}]`.
fn map_legacy_person(person: &mut Value) {
    if person.get("display_name").is_none() {
        if let Some(name) = person.remove("name") {
            person.set("display_name", name);
        }
    }
    for (obj_key, item_a, item_b) in [("ids", "scheme", "value"), ("links", "rel", "href")] {
        let mapped = person.get(obj_key).and_then(|v| v.as_object()).map(|pairs| {
            pairs
                .iter()
                .map(|(k, v)| {
                    Value::Object(vec![
                        (item_a.to_string(), Value::Str(k.clone())),
                        (item_b.to_string(), v.clone()),
                    ])
                })
                .collect::<Vec<Value>>()
        });
        if let Some(arr) = mapped {
            person.set(obj_key, Value::Array(arr));
        }
    }
}

fn is_expired(entry: &Value, today: &str) -> bool {
    let s = match entry.get("expires").and_then(|v| v.as_str()) {
        Some(s) if s.len() >= 10 => &s[..10],
        _ => return false,
    };
    let b = s.as_bytes();
    let looks_like_date = b.len() == 10
        && b[4] == b'-'
        && b[7] == b'-'
        && b[..4].iter().all(|c| c.is_ascii_digit())
        && b[5..7].iter().all(|c| c.is_ascii_digit())
        && b[8..10].iter().all(|c| c.is_ascii_digit());
    looks_like_date && s < today
}

/// Today's UTC date as `YYYY-MM-DD`.
fn today_ymd() -> String {
    let days = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| (d.as_secs() / 86400) as i64)
        .unwrap_or(0);
    let (y, m, d) = civil_from_days(days);
    format!("{y:04}-{m:02}-{d:02}")
}

/// Howard Hinnant's `civil_from_days`: days since 1970-01-01 -> (y, m, d).
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = (if mp < 10 { mp + 3 } else { mp - 9 }) as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn civil_date_known() {
        assert_eq!(civil_from_days(20736), (2026, 10, 10));
        assert_eq!(civil_from_days(0), (1970, 1, 1));
        // today_ymd is a well-formed date string
        let t = today_ymd();
        assert_eq!(t.len(), 10);
        assert!(t.as_bytes()[4] == b'-' && t.as_bytes()[7] == b'-');
    }
}
