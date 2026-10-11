# Copyright 2026 Jared Zimmerman
# SPDX-License-Identifier: Apache-2.0
"""Conformance vector runner: the v1-relevant suites under
``prsn/conformance/`` plus the valid examples.

Each suite function returns ``(passed, failed, failures)`` where ``failures``
is a list of labels for the vectors/cases that did not behave as specified.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from . import keys
from .actionkey import ActionKeyError, action_key, preimage
from .canonical import JSONError, canonical, dumps, parse
from .package import PrsnError, apply_tier_downgrade, open_package, sha256_hex

SuiteResult = tuple[int, int, list[str]]  # (passed, failed, failure labels)


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# json/canonical.json
# --------------------------------------------------------------------------- #


def run_json_vectors(path: Path) -> SuiteResult:
    doc = _load_json(path)
    passed, failed, bad = 0, 0, []
    for v in doc["valid"]:
        try:
            out = dumps(parse(v["input"].encode("utf-8", "surrogatepass")))
        except JSONError:
            out = None
        if out != v["expected"] or (
            out is not None and sha256_hex(out.encode("utf-8")) != v["expected_sha256"]
        ):
            failed += 1
            bad.append(v["name"])
        else:
            passed += 1
    for v in doc["invalid"]:
        if "input_hex" in v:
            data = bytes.fromhex(v["input_hex"])
        else:
            data = v["input"].encode("utf-8", "surrogatepass")
        try:
            parse(data)
            failed += 1
            bad.append(v["name"] + " (accepted, must reject)")
        except JSONError:
            passed += 1
    return passed, failed, bad


# --------------------------------------------------------------------------- #
# hash/sha256.json
# --------------------------------------------------------------------------- #


def _uneven_chunks(data: bytes):
    sizes = [1, 65537, 3, 1048576, 99991]
    i, k = 0, 0
    while i < len(data):
        n = sizes[k % len(sizes)]
        k += 1
        yield data[i : i + n]
        i += n


def _vector_bytes(v: dict) -> bytes:
    if "input_utf8" in v:
        return v["input_utf8"].encode("utf-8")
    g = v["generator"]
    if g["kind"] == "repeat":
        return bytes([g["byte"]]) * g["length"]
    return bytes(((i * g["mul"] + g["add"]) & 0xFF) for i in range(g["length"]))


def run_sha256_vectors(path: Path) -> SuiteResult:
    doc = _load_json(path)
    passed, failed, bad = 0, 0, []
    for v in doc["vectors"]:
        data = _vector_bytes(v)
        one_shot = sha256_hex(data)
        h = hashlib.sha256()
        for chunk in _uneven_chunks(data):
            h.update(chunk)
        if one_shot == v["sha256"] and h.hexdigest() == v["sha256"]:
            passed += 1
        else:
            failed += 1
            bad.append(v["name"])
    return passed, failed, bad


# --------------------------------------------------------------------------- #
# hash/action_key.json
# --------------------------------------------------------------------------- #


def run_action_key_vectors(path: Path) -> SuiteResult:
    doc = _load_json(path)
    passed, failed, bad = 0, 0, []
    for v in doc["valid"]:
        try:
            pre = preimage(v["derivation"])
            ok = pre.decode("utf-8") == v["preimage"] and action_key(v["derivation"]) == v["action_key"]
        except (ActionKeyError, UnicodeDecodeError):
            ok = False
        if ok:
            passed += 1
        else:
            failed += 1
            bad.append(v["name"])
    for v in doc["invalid"]:
        try:
            action_key(v["derivation"])
            failed += 1
            bad.append(v["name"] + " (has a key, must not)")
        except ActionKeyError:
            passed += 1
    return passed, failed, bad


# --------------------------------------------------------------------------- #
# hash/ed25519.json
# --------------------------------------------------------------------------- #


def run_ed25519_vectors(path: Path) -> SuiteResult:
    doc = _load_json(path)
    passed, failed, bad = 0, 0, []
    for v in doc["vectors"]:
        seed = bytes.fromhex(v["seed"])
        pub = bytes.fromhex(v["public_key"])
        msg = bytes.fromhex(v["message"])
        sig = bytes.fromhex(v["signature"])
        flipped = bytes([sig[0] ^ 1]) + sig[1:]
        ok = (
            keys.public_key_from_seed(seed) == pub
            and keys.key_id(pub) == v["key_id"]
            and base64.b64encode(pub).decode("ascii") == v["public_key_b64"]
            and keys.verify(pub, msg, sig)
            and not keys.verify(pub, msg, flipped)
            and not keys.verify(pub, msg + b"x", sig)
        )
        if ok:
            passed += 1
        else:
            failed += 1
            bad.append(v["name"])
    return passed, failed, bad


# --------------------------------------------------------------------------- #
# hash/manifest.json — build the manifest, canonicalise, sign
# --------------------------------------------------------------------------- #


def run_manifest_vector(path: Path) -> SuiteResult:
    mv = _load_json(path)
    entries = []
    for f in mv["files"]:
        content = f["content"].encode("utf-8")
        entry = {
            "path": f["path"],
            "type": f["type"],
            "media": f["media"],
            "sha256": sha256_hex(content),
            "bytes": len(content),
        }
        entry.update(f.get("extra", {}))
        entries.append(entry)
    entries.sort(key=lambda e: e["path"].encode("utf-8"))
    m = dict(mv["top_level"])
    m["entries"] = entries
    pub = keys.public_key_from_seed(bytes.fromhex(mv["seed"]))
    m["signature"] = {
        "path": "signatures/manifest.sig",
        "alg": "Ed25519",
        "key_id": keys.key_id(pub),
        "public_key": base64.b64encode(pub).decode("ascii"),
    }
    body = canonical(m)
    files_ok = all(
        any(
            e["path"] == f["path"] and e["sha256"] == sha256_hex(f["content"].encode("utf-8"))
            for e in m["entries"]
        )
        for f in mv["files"]
    )
    ok = (
        body == mv["canonical_manifest"].encode("utf-8")
        and sha256_hex(body) == mv["manifest_sha256"]
        and files_ok
        and keys.verify(pub, body, bytes.fromhex(mv["signature"]))
    )
    return (1, 0, []) if ok else (0, 1, ["manifest build/hash/signature"])


# --------------------------------------------------------------------------- #
# tiers/downgrade.json
# --------------------------------------------------------------------------- #


def run_tier_vectors(path: Path) -> SuiteResult:
    doc = _load_json(path)
    passed, failed, bad = 0, 0, []
    for c in doc["cases"]:
        got = apply_tier_downgrade(c["entries"], c["trusted"])
        if got == c["expected"]:
            passed += 1
        else:
            failed += 1
            bad.append(c["name"])
    return passed, failed, bad


# --------------------------------------------------------------------------- #
# container/*.prsn
# --------------------------------------------------------------------------- #


def _open_case(path: Path):
    """Open a package case: returns ("ok", pkg) or ("refused", rule)."""
    try:
        return "ok", open_package(path, trusted_keys=[])
    except PrsnError as e:
        return "refused", e.rule


def run_container_cases(conformance_dir: Path) -> SuiteResult:
    d = conformance_dir / "container"
    cases = _load_json(d / "cases.json")["cases"]
    passed, failed, bad = 0, 0, []
    for c in cases:
        status, result = _open_case(d / c["file"])
        if c["outcome"] == "valid":
            if status == "ok":
                errors = [i for i in result.validate() if i.severity == "error"]
                ok = not errors
            else:
                ok = False
        else:  # refuse
            ok = status == "refused" and result == c["rule"]
        if ok:
            passed += 1
        else:
            failed += 1
            bad.append(f"{c['file']} (expected {c['outcome']})")
    return passed, failed, bad


# --------------------------------------------------------------------------- #
# prsn/ directory cases + valid examples
# --------------------------------------------------------------------------- #


def run_prsn_cases(conformance_dir: Path) -> SuiteResult:
    d = conformance_dir / "prsn"
    repo = conformance_dir.parent
    rules = _load_json(d / "rules.json")
    passed, failed, bad = 0, 0, []

    for v in rules["valid"]:
        status, result = _open_case(repo / v["path"])
        if status == "ok":
            errors = [i for i in result.validate() if i.severity == "error"]
            ok = not errors
        else:
            ok = False
        if ok:
            passed += 1
        else:
            failed += 1
            bad.append(f"valid/{v['id']}")

    for c in rules["cases"]:
        status, result = _open_case(d / c["id"])
        if c["outcome"] == "refuse":
            ok = status == "refused" and result == c["rule"]
        elif status == "refused":
            # integrity-level refusal (manifest-hash, signature)
            ok = c["outcome"] == "invalid" and result == c["rule"]
        elif c["outcome"] == "valid":
            issues = result.validate()
            errors = [i for i in issues if i.severity == "error"]
            notes = [i for i in issues if i.severity == "note"]
            ok = not errors and bool(notes)
        else:  # invalid: validator must report exactly the stated rule
            errors = [i for i in result.validate() if i.severity == "error"]
            ok = {i.rule for i in errors} == {c["rule"]}
        if ok:
            passed += 1
        else:
            failed += 1
            bad.append(f"{c['id']} (expected {c['outcome']}:{c['rule']})")
    return passed, failed, bad


# --------------------------------------------------------------------------- #
# examples/prsn/valid-v11: read, hash-verify, signature-verify, untrusted key
# --------------------------------------------------------------------------- #


def run_example_valid_v11(conformance_dir: Path) -> SuiteResult:
    p = conformance_dir.parent / "examples" / "prsn" / "valid-v11"
    status, result = _open_case(p)
    if status != "ok":
        return 0, 1, [f"valid-v11 refused: {result}"]
    sample = next(
        (e for e in result.list_entries() if e["path"] == "face/samples/f-0001.heic"), None
    )
    ok = (
        result.signature.present
        and result.signature.verified
        and result.signature.key_id == "7b403348c09944ad"
        and not result.trusted  # the published test key is never trusted
        and sample is not None
        and sample["origin"]["tier"] == "imported"
        and sample["origin"]["was"] == "enrolled"
    )
    return (1, 0, []) if ok else (0, 1, ["valid-v11 read/hash/signature/downgrade"])


# --------------------------------------------------------------------------- #
# all suites
# --------------------------------------------------------------------------- #


def run_suites(conformance_dir: Path) -> list[tuple[str, SuiteResult]]:
    """Run every v1-relevant conformance suite. Returns [(name, result)]."""
    conformance_dir = Path(conformance_dir)
    return [
        ("json", run_json_vectors(conformance_dir / "json" / "canonical.json")),
        ("sha256", run_sha256_vectors(conformance_dir / "hash" / "sha256.json")),
        ("action_key", run_action_key_vectors(conformance_dir / "hash" / "action_key.json")),
        ("ed25519", run_ed25519_vectors(conformance_dir / "hash" / "ed25519.json")),
        ("manifest", run_manifest_vector(conformance_dir / "hash" / "manifest.json")),
        ("tiers", run_tier_vectors(conformance_dir / "tiers" / "downgrade.json")),
        ("container", run_container_cases(conformance_dir)),
        ("prsn", run_prsn_cases(conformance_dir)),
        ("examples", run_example_valid_v11(conformance_dir)),
    ]
