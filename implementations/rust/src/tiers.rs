// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//! Provenance tier downgrade (spec `prsn.md`, "Provenance tiers").
//!
//! The top tiers hold only within the signer's trust. For a file that is
//! unsigned or signed by a key the reader does not trust, the reader MUST
//! treat `enrolled` and `professional` entries as `imported`, keeping the
//! claimed tier as `origin.was`, and MUST move the seconds a template's
//! `evidence` attributes to those tiers to `imported` (sum rounded to 0.1).
//! Lower tiers are unchanged.

use crate::canon::Value;

/// Apply the tier downgrade to every entry object in `entries` (each a
/// manifest entry object). Idempotent: already-downgraded entries are left
/// alone.
pub fn downgrade_entries(entries: &mut [Value]) {
    for entry in entries.iter_mut() {
        downgrade_entry(entry);
    }
}

fn downgrade_entry(entry: &mut Value) {
    // origin.tier: enrolled/professional -> imported, claimed tier kept as was.
    if let Some(origin) = entry.get_mut("origin") {
        if let Some(obj) = origin.as_object_mut() {
            let tier = obj
                .iter()
                .find(|(k, _)| k == "tier")
                .and_then(|(_, v)| v.as_str())
                .unwrap_or("")
                .to_string();
            if tier == "enrolled" || tier == "professional" {
                set_key(obj, "tier", Value::Str("imported".to_string()));
                set_key(obj, "was", Value::Str(tier));
            }
        }
    }
    // evidence: move enrolled+professional seconds into imported (sum, 0.1).
    if let Some(evidence) = entry.get_mut("evidence") {
        if let Some(obj) = evidence.as_object_mut() {
            let mut moved = 0.0f64;
            let mut any = false;
            for key in ["enrolled", "professional"] {
                if let Some(v) = take_key(obj, key) {
                    if let Some(n) = v.as_f64() {
                        moved += n;
                        any = true;
                    } else {
                        // Non-numeric evidence value: put it back untouched.
                        set_key(obj, key, v);
                    }
                }
            }
            if any {
                let base = take_key(obj, "imported")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.0);
                let total = (base + moved) * 10.0;
                let rounded = total.round() / 10.0;
                set_key(obj, "imported", Value::Float(rounded));
            }
        }
    }
}

fn set_key(obj: &mut Vec<(String, Value)>, key: &str, value: Value) {
    if let Some(slot) = obj.iter_mut().find(|(k, _)| k == key) {
        slot.1 = value;
    } else {
        obj.push((key.to_string(), value));
    }
}

fn take_key(obj: &mut Vec<(String, Value)>, key: &str) -> Option<Value> {
    obj.iter()
        .position(|(k, _)| k == key)
        .map(|i| obj.remove(i).1)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::canon;

    fn downgrade(entry_json: &str) -> String {
        let mut v = canon::parse(entry_json.as_bytes()).unwrap();
        downgrade_entries(std::slice::from_mut(&mut v));
        String::from_utf8(canon::to_canonical(&v).unwrap()).unwrap()
    }

    #[test]
    fn enrolled_sample() {
        assert_eq!(
            downgrade(r#"{"path":"s","origin":{"tier":"enrolled","how":"x"}}"#),
            r#"{"origin":{"how":"x","tier":"imported","was":"enrolled"},"path":"s"}"#
        );
    }

    #[test]
    fn professional_sample() {
        assert_eq!(
            downgrade(r#"{"path":"s","origin":{"tier":"professional","set_by":"user"}}"#),
            r#"{"origin":{"set_by":"user","tier":"imported","was":"professional"},"path":"s"}"#
        );
    }

    #[test]
    fn lower_tiers_unchanged() {
        assert_eq!(
            downgrade(r#"{"path":"s","origin":{"tier":"observed"}}"#),
            r#"{"origin":{"tier":"observed"},"path":"s"}"#
        );
        assert_eq!(
            downgrade(r#"{"path":"s","origin":{"tier":"imported"}}"#),
            r#"{"origin":{"tier":"imported"},"path":"s"}"#
        );
    }

    #[test]
    fn evidence_moved() {
        // Note: input `5.0` parses to the double 5.0, which canonically
        // serializes as `5` — same value, canonical form.
        assert_eq!(
            downgrade(
                r#"{"path":"t","evidence":{"enrolled":30.0,"professional":12.2,"imported":2.0,"observed":5.0}}"#
            ),
            r#"{"evidence":{"imported":44.2,"observed":5},"path":"t"}"#
        );
    }

    #[test]
    fn idempotent() {
        let once = downgrade(r#"{"path":"s","origin":{"tier":"enrolled"}}"#);
        let twice = downgrade(&once);
        assert_eq!(once, twice);
    }
}
