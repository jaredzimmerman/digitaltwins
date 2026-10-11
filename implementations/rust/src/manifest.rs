// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//! Manifest validation rules (spec `prsn.md`, "Conformance").
//!
//! Rule ids: `container`, `version`, `paths`, `manifest-hash`, `signature`,
//! `critical`, `person`, `spec-fields`, `looks-eras`, `capture-ref`,
//! `generation`, `type-fields`, `entry-order`.
//!
//! `container`, `version` and `critical` violations refuse the file at
//! [`Package::open`]; the rest are reported by [`Package::validate`].

use std::collections::HashSet;

use crate::canon::{self, Value};
use crate::hash::sha256_hex;
use crate::package::{read_member, Error, Package};

/// A conformance rule id.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum RuleId {
    Container,
    Version,
    Paths,
    ManifestHash,
    Signature,
    Critical,
    Person,
    SpecFields,
    LooksEras,
    CaptureRef,
    Generation,
    TypeFields,
    EntryOrder,
}

impl RuleId {
    pub fn as_str(&self) -> &'static str {
        match self {
            RuleId::Container => "container",
            RuleId::Version => "version",
            RuleId::Paths => "paths",
            RuleId::ManifestHash => "manifest-hash",
            RuleId::Signature => "signature",
            RuleId::Critical => "critical",
            RuleId::Person => "person",
            RuleId::SpecFields => "spec-fields",
            RuleId::LooksEras => "looks-eras",
            RuleId::CaptureRef => "capture-ref",
            RuleId::Generation => "generation",
            RuleId::TypeFields => "type-fields",
            RuleId::EntryOrder => "entry-order",
        }
    }
}

const ROLES: [&str; 5] = ["templates", "samples", "geometry", "training", "generation"];
const SPATIAL_MODALITIES: [&str; 3] = ["face", "head", "body"];

fn valid_segment(seg: &str) -> bool {
    !seg.is_empty()
        && seg != "."
        && seg != ".."
        && seg.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'.' || b == b'_' || b == b'-')
}

fn entry_role(path: &str) -> Option<(&str, &str)> {
    let segs: Vec<&str> = path.split('/').collect();
    if segs.len() >= 3 {
        Some((segs[0], segs[1]))
    } else {
        None
    }
}

fn is_sha256_hex(s: &str) -> bool {
    let hex = s.strip_prefix("sha256:").unwrap_or(s);
    hex.len() == 64 && hex.bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
}

impl Package {
    /// Run every validation rule that does not refuse the file at open.
    /// Returns the violated rule ids (empty means the file validates).
    pub fn validate(&mut self) -> Result<Vec<RuleId>, Error> {
        let mut violated: Vec<RuleId> = Vec::new();
        let mut flag = |r: RuleId| {
            if !violated.contains(&r) {
                violated.push(r);
            }
        };

        let spec = self.spec;
        let person_path = self.person_path.clone();
        let live_paths: Vec<String> = self.live.iter().map(|&i| self.entries[i].path.clone()).collect();
        let entry_objs: Vec<Value> = {
            let arr = self
                .manifest
                .get("entries")
                .and_then(|v| v.as_array())
                .map(|a| a.to_vec())
                .unwrap_or_default();
            self.live
                .iter()
                .map(|&i| arr[self.entries[i].index].clone())
                .collect()
        };

        // ---- paths ----
        {
            let mut seen = HashSet::new();
            for (path, obj) in live_paths.iter().zip(entry_objs.iter()) {
                let _ = obj;
                if !seen.insert(path.clone()) {
                    flag(RuleId::Paths);
                }
                let segs: Vec<&str> = path.split('/').collect();
                if segs.iter().any(|s| !valid_segment(s)) {
                    flag(RuleId::Paths);
                    continue;
                }
                match segs.len() {
                    1 => {
                        if *path != person_path {
                            flag(RuleId::Paths);
                        }
                    }
                    2 => {
                        // Depth 2 is for modality-level index records only:
                        // `<modality>/<name>.json`.
                        if !segs[1].ends_with(".json") {
                            flag(RuleId::Paths);
                        }
                    }
                    _ => {
                        if !ROLES.contains(&segs[1]) {
                            flag(RuleId::Paths);
                        }
                    }
                }
            }
        }

        // ---- entry-order (spec >= 1.1) ----
        if spec >= (1, 1) {
            for w in live_paths.windows(2) {
                if w[0].as_bytes() > w[1].as_bytes() {
                    flag(RuleId::EntryOrder);
                    break;
                }
            }
        }

        // ---- manifest-hash ----
        for path in &live_paths {
            let entry = self.entries.iter().find(|e| &e.path == path).unwrap();
            match read_member(&mut self.store, path) {
                Err(_) => flag(RuleId::ManifestHash),
                Ok(bytes) => {
                    if bytes.len() as u64 != entry.bytes || sha256_hex(&bytes) != entry.sha256 {
                        flag(RuleId::ManifestHash);
                    }
                }
            }
        }

        // ---- signature ----
        if self.verify_signature().is_err() {
            flag(RuleId::Signature);
        }

        // ---- person ----
        {
            let person_ok = self.person.is_object()
                && self.person.get("id").and_then(|v| v.as_str()).is_some()
                && self
                    .person
                    .get("display_name")
                    .and_then(|v| v.as_str())
                    .is_some()
                && live_paths.iter().any(|p| p == &person_path);
            if !person_ok {
                flag(RuleId::Person);
            }
        }

        // ---- spec-fields ----
        for (path, obj) in live_paths.iter().zip(entry_objs.iter()) {
            let role = entry_role(path).map(|(_, r)| r);
            match role {
                Some("samples") | Some("training") => {
                    if obj.get("origin").and_then(|v| v.as_object()).is_none() {
                        flag(RuleId::SpecFields);
                    }
                }
                _ => {}
            }
            if spec >= (1, 1) {
                if let Some((modality, r)) = entry_role(path) {
                    if ["geometry", "generation", "templates"].contains(&r)
                        && obj.get("derivation").and_then(|v| v.as_object()).is_none()
                    {
                        flag(RuleId::SpecFields);
                    }
                    if ["samples", "geometry", "generation"].contains(&r)
                        && (obj.get("look").and_then(|v| v.as_str()).is_none()
                            || obj.get("era").and_then(|v| v.as_str()).is_none())
                    {
                        flag(RuleId::SpecFields);
                    }
                    if ["geometry", "generation"].contains(&r)
                        && SPATIAL_MODALITIES.contains(&modality)
                        && obj.get("frame").and_then(|v| v.as_str()).is_none()
                    {
                        flag(RuleId::SpecFields);
                    }
                }
            }
        }

        // ---- looks-eras ----
        {
            let look_ids: HashSet<String> = self
                .manifest
                .get("looks")
                .and_then(|v| v.as_array())
                .map(|a| {
                    a.iter()
                        .filter_map(|l| l.get("id").and_then(|v| v.as_str()).map(|s| s.to_string()))
                        .collect()
                })
                .unwrap_or_default();
            let era_ids: HashSet<String> = self
                .manifest
                .get("eras")
                .and_then(|v| v.as_array())
                .map(|a| {
                    a.iter()
                        .filter_map(|e| e.get("id").and_then(|v| v.as_str()).map(|s| s.to_string()))
                        .collect()
                })
                .unwrap_or_default();
            for obj in &entry_objs {
                if let Some(look) = obj.get("look") {
                    match look.as_str() {
                        Some("*") => {}
                        Some(id) if look_ids.contains(id) => {}
                        _ => flag(RuleId::LooksEras),
                    }
                }
                if let Some(era) = obj.get("era") {
                    match era.as_str() {
                        Some(id) if era_ids.contains(id) => {}
                        _ => flag(RuleId::LooksEras),
                    }
                }
            }
            if let Some(looks) = self.manifest.get("looks").and_then(|v| v.as_array()) {
                for look in looks {
                    match look.get("era").and_then(|v| v.as_str()) {
                        Some(id) if era_ids.contains(id) => {}
                        _ => flag(RuleId::LooksEras),
                    }
                }
            }
        }

        // ---- generation ----
        for (path, obj) in live_paths.iter().zip(entry_objs.iter()) {
            match entry_role(path).map(|(_, r)| r) {
                Some("generation") => {
                    if obj.get("synthetic_capable").and_then(|v| v.as_bool()) != Some(true) {
                        flag(RuleId::Generation);
                    }
                }
                Some("samples") | Some("training") => {
                    if obj
                        .get("origin")
                        .and_then(|o| o.get("synthetic"))
                        .and_then(|v| v.as_bool())
                        == Some(true)
                    {
                        flag(RuleId::Generation);
                    }
                }
                _ => {}
            }
        }

        // ---- capture-ref ----
        for (path, obj) in live_paths.iter().zip(entry_objs.iter()) {
            let _ = obj;
            let type_ = self.entries.iter().find(|e| &e.path == path).map(|e| e.type_.as_str());
            if matches!(type_, Some("org.prsn.face.capture-ref") | Some("org.museli.face.capture-ref")) {
                match read_member(&mut self.store, path) {
                    Err(_) => flag(RuleId::CaptureRef),
                    Ok(bytes) => match canon::parse(&bytes) {
                        Err(_) => flag(RuleId::CaptureRef),
                        Ok(payload) => {
                            let refs: Vec<&Value> = match &payload {
                                Value::Array(a) => a.iter().collect(),
                                Value::Object(_) => vec![&payload],
                                _ => {
                                    flag(RuleId::CaptureRef);
                                    Vec::new()
                                }
                            };
                            for r in refs {
                                let h = r.get("manifest_sha256").and_then(|v| v.as_str());
                                if h.map(is_sha256_hex) != Some(true) {
                                    flag(RuleId::CaptureRef);
                                }
                            }
                        }
                    },
                }
            }
        }

        // ---- type-fields ----
        for (path, obj) in live_paths.iter().zip(entry_objs.iter()) {
            let type_ = self.entries.iter().find(|e| &e.path == path).map(|e| e.type_.as_str());
            match type_ {
                Some("org.prsn.face.mesh") | Some("org.museli.face.mesh") => {
                    if obj.get("topology").is_none() {
                        flag(RuleId::TypeFields);
                    }
                }
                Some("org.prsn.voice.sample") | Some("org.museli.voice.sample") => {
                    let float_captured = obj
                        .get("captured")
                        .and_then(|c| c.get("float"))
                        .and_then(|v| v.as_bool())
                        == Some(true);
                    if float_captured && obj.get("source_format").is_none() {
                        flag(RuleId::TypeFields);
                    }
                }
                _ => {}
            }
        }

        // Canonical rule order.
        let order = [
            RuleId::Container,
            RuleId::Version,
            RuleId::Paths,
            RuleId::ManifestHash,
            RuleId::Signature,
            RuleId::Critical,
            RuleId::Person,
            RuleId::SpecFields,
            RuleId::LooksEras,
            RuleId::CaptureRef,
            RuleId::Generation,
            RuleId::TypeFields,
            RuleId::EntryOrder,
        ];
        violated.sort_by_key(|r| order.iter().position(|o| o == r).unwrap());
        Ok(violated)
    }
}
