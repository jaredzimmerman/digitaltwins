// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//! `action_key` (spec `derivation-recipes.md`, R1).
//!
//! `action_key` = `"sha256:" + hex(SHA-256(canonical JSON of the preimage))`,
//! where the preimage is:
//!
//! ```text
//! {"family":  derivation.family,
//!  "recipe":  {"id": derivation.recipe.id, "version": derivation.recipe.version},
//!  "models":  [derivation.models[].sha256 …]   sorted by UTF-8 bytes, duplicates kept,
//!  "params":  derivation.params                 ({} when absent or null),
//!  "inputs":  [resolved input …]                sorted by the UTF-8 bytes of each one's canonical JSON}
//! ```
//!
//! A resolved input keeps only the keys `capture`, `cache`, `sha256`, `role`
//! and `select` (whichever are present) and drops everything else (`look`,
//! `era`, an entry's `entry` path, unknown keys). `models` or `inputs` absent
//! or null mean `[]`. A derivation has no key when: an input lacks a single
//! string content hash, `family` or `recipe.version` is missing, a model lacks
//! `sha256`, or `params` is a non-object.

use crate::canon::{self, Value};
use crate::hash::sha256_hex;

/// Why a derivation has no `action_key`.
#[derive(Debug, Clone)]
pub struct ActionKeyError(pub String);

impl std::fmt::Display for ActionKeyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "no action_key: {}", self.0)
    }
}

impl std::error::Error for ActionKeyError {}

fn kept_input(input: &Value) -> Result<Vec<(String, Value)>, ActionKeyError> {
    let obj = input
        .as_object()
        .ok_or_else(|| ActionKeyError("input is not an object".to_string()))?;
    let mut hashes = 0;
    for key in ["capture", "cache", "sha256"] {
        if let Some(v) = obj.iter().find(|(k, _)| k == key).map(|(_, v)| v) {
            if v.as_str().is_none() {
                return Err(ActionKeyError(format!("input {key} is not a string")));
            }
            hashes += 1;
        }
    }
    if hashes != 1 {
        return Err(ActionKeyError(
            "an input needs exactly one string content hash".to_string(),
        ));
    }
    let mut kept = Vec::new();
    for (k, v) in obj {
        if ["capture", "cache", "sha256", "role", "select"].contains(&k.as_str()) {
            kept.push((k.clone(), v.clone()));
        }
    }
    Ok(kept)
}

/// Build the canonical JSON bytes of the R1 preimage for a `derivation` block.
pub fn preimage_bytes(derivation: &Value) -> Result<Vec<u8>, ActionKeyError> {
    let family = derivation
        .get("family")
        .and_then(|v| v.as_str())
        .ok_or_else(|| ActionKeyError("family missing".to_string()))?;
    let recipe = derivation.get("recipe");
    let (recipe_id, recipe_version) = match recipe {
        Some(r) => {
            let id = r.get("id").and_then(|v| v.as_str());
            let version = r.get("version").and_then(|v| v.as_str());
            match (id, version) {
                (Some(id), Some(version)) => (id, version),
                _ => {
                    return Err(ActionKeyError(
                        "recipe.id and recipe.version required".to_string(),
                    ))
                }
            }
        }
        None => {
            return Err(ActionKeyError(
                "recipe.id and recipe.version required".to_string(),
            ))
        }
    };

    let mut models: Vec<String> = Vec::new();
    if let Some(m) = derivation.get("models") {
        if !matches!(m, Value::Null) {
            let arr = m
                .as_array()
                .ok_or_else(|| ActionKeyError("models is not an array".to_string()))?;
            for item in arr {
                let sha = item
                    .get("sha256")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| ActionKeyError("model without sha256".to_string()))?;
                models.push(sha.to_string());
            }
        }
    }
    models.sort();

    let params = match derivation.get("params") {
        None | Some(Value::Null) => Value::Object(Vec::new()),
        Some(p) if p.is_object() => p.clone(),
        Some(_) => return Err(ActionKeyError("params must be an object".to_string())),
    };

    let mut inputs: Vec<Vec<u8>> = Vec::new();
    if let Some(ins) = derivation.get("inputs") {
        if !matches!(ins, Value::Null) {
            let arr = ins
                .as_array()
                .ok_or_else(|| ActionKeyError("inputs is not an array".to_string()))?;
            for item in arr {
                let kept = kept_input(item)?;
                let bytes = canon::to_canonical(&Value::Object(kept))
                    .map_err(|e| ActionKeyError(e.to_string()))?;
                inputs.push(bytes);
            }
        }
    }
    inputs.sort();
    let inputs: Vec<Value> = inputs
        .into_iter()
        .map(|b| canon::parse(&b).expect("re-parse of canonical bytes"))
        .collect();

    let preimage = Value::Object(vec![
        ("family".to_string(), Value::Str(family.to_string())),
        (
            "recipe".to_string(),
            Value::Object(vec![
                ("id".to_string(), Value::Str(recipe_id.to_string())),
                ("version".to_string(), Value::Str(recipe_version.to_string())),
            ]),
        ),
        (
            "models".to_string(),
            Value::Array(models.into_iter().map(Value::Str).collect()),
        ),
        ("params".to_string(), params),
        ("inputs".to_string(), Value::Array(inputs)),
    ]);
    canon::to_canonical(&preimage).map_err(|e| ActionKeyError(e.to_string()))
}

/// Compute the `action_key` (`"sha256:<hex>"`) for a `derivation` block.
pub fn action_key(derivation: &Value) -> Result<String, ActionKeyError> {
    Ok(format!("sha256:{}", sha256_hex(&preimage_bytes(derivation)?)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn minimal_preimage() {
        let d = canon::parse(
            br#"{"family":"org.prsn.method.masks","recipe":{"id":"r","version":"1.0.0"}}"#,
        )
        .unwrap();
        let pre = preimage_bytes(&d).unwrap();
        assert_eq!(
            String::from_utf8(pre).unwrap(),
            r#"{"family":"org.prsn.method.masks","inputs":[],"models":[],"params":{},"recipe":{"id":"r","version":"1.0.0"}}"#
        );
    }

    #[test]
    fn rejects() {
        // Input with two content hashes.
        let d = canon::parse(
            br#"{"family":"f","recipe":{"id":"r","version":"1"},"inputs":[{"capture":"a","sha256":"b"}]}"#,
        )
        .unwrap();
        assert!(action_key(&d).is_err());
        // Missing family.
        let d = canon::parse(br#"{"recipe":{"id":"r","version":"1"}}"#).unwrap();
        assert!(action_key(&d).is_err());
        // Non-object params.
        let d = canon::parse(
            br#"{"family":"f","recipe":{"id":"r","version":"1"},"params":[1]}"#,
        )
        .unwrap();
        assert!(action_key(&d).is_err());
    }
}
