# Copyright 2026 Jared Zimmerman
# SPDX-License-Identifier: Apache-2.0
"""Semantic validation of an opened ``.prsn`` package: the spec's conformance
rule table (spec/prsn.md, "Conformance") as :class:`Issue` lists.

Refuse-level problems (container, version, manifest-hash, signature, critical)
are raised as :class:`PrsnError` during :func:`open_package`; everything here
reports per-rule errors or notes without raising.
"""

from __future__ import annotations

import re

from .canonical import JSONError, parse
from .package import (
    KNOWN_TYPES,
    Issue,
    canonical_type,
    map_legacy_person,
)

_ENTRY_PATH_RE = re.compile(r"^(?!.*(^|/)\.\.?(/|$))[a-z0-9._-]+(/[a-z0-9._-]+)*$")
_DEPTH1_TYPE_RE = re.compile(r"^(org\.prsn|org\.museli)\.person$")
_DEPTH2_PATH_RE = re.compile(r"\.json$")
_DEPTH2_TYPE_RE = re.compile(r"^(org\.prsn|org\.museli)\.[a-z0-9-]+\.(capture-ref|coverage)$")
_SAMPLES_TRAINING_RE = re.compile(r"^[a-z0-9._-]+/(samples|training)/")
_GEOMETRY_GEN_TPL_RE = re.compile(r"^[a-z0-9._-]+/(geometry|generation|templates)/")
_SAMPLES_GEOMETRY_GEN_RE = re.compile(r"^[a-z0-9._-]+/(samples|geometry|generation)/")
_SPATIAL_GEOMETRY_GEN_RE = re.compile(r"^(face|head|body)/(geometry|generation)/")
_GENERATION_RE = re.compile(r"^[a-z0-9._-]+/generation/")
_SHA256_OR_CONTENT_ID_RE = re.compile(r"^(sha256:)?[0-9a-f]{64}$")

# (types, required fields, sub-field rules). A sub-rule is False (must not be
# true), a tuple (enum membership), or a list (required keys of a dict field).
_TYPE_MUST = [
    (("org.prsn.face.mesh", "org.prsn.body.mesh"), ["topology", "coverage", "model"], {"model": ["license"]}),
    (("org.prsn.face.landmarks",), ["topology"], {}),
    (("org.prsn.face.params",), ["model", "kind"], {"model": ["license"], "kind": ("identity", "track")}),
    (("org.prsn.body.params",), ["model", "coverage"], {"model": ["license"]}),
    (("org.prsn.face.expression-track",), ["basis"], {}),
    (
        ("org.prsn.face.expression-map",),
        ["from", "to", "kind"],
        {"kind": ("generic-linear", "per-user-linear", "per-user-mlp")},
    ),
    (
        ("org.prsn.face.splat",),
        ["sh_degree", "kernel", "color_space", "coverage"],
        {"critical": False},
    ),
    (("org.prsn.face.coverage",), ["look", "derivation"], {"critical": False}),
    (
        ("org.prsn.face.avatar",),
        ["topology", "driver", "binding", "formulation", "coverage"],
        {"formulation": ("lbs-bound", "gaussian-blendshapes")},
    ),
    (("org.prsn.image.lora",), ["base_model", "trigger"], {"base_model": ["key", "sha256"]}),
    (("org.prsn.image.embedding",), ["base_model", "token"], {"base_model": ["key", "sha256"]}),
    (("org.prsn.image.faceid",), ["template"], {}),
    (("org.prsn.avatar.vrm",), ["coverage"], {}),
    (("org.prsn.face.template", "org.prsn.voice.template"), ["model"], {}),
    (("org.prsn.voice.sample",), ["seconds", "sample_rate", "bits"], {}),
    (("org.prsn.voice.seed",), ["text", "sample_rate", "bits"], {}),
    (("org.prsn.voice.prompt",), ["engine"], {"engine": ["name", "version"]}),
    (("org.prsn.voice.lora", "org.prsn.voice.rvc"), ["base_model"], {"base_model": ["key", "sha256"]}),
]


def _spec_ge_11(m: dict) -> bool:
    spec = m.get("spec")
    if not isinstance(spec, str) or "." not in spec:
        return False
    try:
        major, minor = (int(x) for x in spec.split(".", 1))
    except ValueError:
        return False
    return (major, minor) >= (1, 1)


def _check_entry_paths(entries: list[dict], issues: list[Issue]) -> None:
    seen: set = set()
    for e in entries:
        p = e.get("path")
        if not isinstance(p, str) or not _ENTRY_PATH_RE.match(p):
            issues.append(Issue("error", "paths", f"{p!r}: bad entry path"))
            continue
        t = str(e.get("type", ""))
        depth = p.count("/") + 1
        if depth == 1:
            if not _DEPTH1_TYPE_RE.match(t):
                issues.append(Issue("error", "paths", f"{p!r}: depth 1 holds person.json only"))
        elif depth == 2:
            if not (_DEPTH2_PATH_RE.search(p) and _DEPTH2_TYPE_RE.match(t)):
                issues.append(
                    Issue(
                        "error",
                        "paths",
                        f"{p!r}: depth 2 is for <modality>/<name>.json index records only",
                    )
                )
        if p in seen:
            issues.append(Issue("error", "paths", f"{p!r} is listed twice"))
        seen.add(p)


def _check_entry_order(m: dict, entries: list[dict], spec11: bool, issues: list[Issue]) -> None:
    paths = [e.get("path") for e in entries]
    if paths != sorted(paths, key=lambda s: s.encode("utf-8")):
        if spec11:
            issues.append(
                Issue("error", "entry-order", "manifest entries are not sorted by path in UTF-8 byte order")
            )
        else:
            issues.append(
                Issue(
                    "note",
                    None,
                    "entries not sorted by path (accepted in a pre-1.1 file; order is never relied on)",
                )
            )


def _check_type_fields(e: dict, issues: list[Issue]) -> None:
    t = canonical_type(str(e.get("type", "")))
    p = e.get("path", "?")
    for types, required, sub in _TYPE_MUST:
        if t not in types:
            continue
        for f in required:
            if f not in e:
                issues.append(Issue("error", "type-fields", f"{p}: {t} needs `{f}`"))
        for f, rule in sub.items():
            if rule is False:
                if f in e and e[f] is not False:
                    issues.append(Issue("error", "type-fields", f"{p}: `{f}` must be false or absent"))
            elif isinstance(rule, tuple):
                if f in e and e[f] not in rule:
                    issues.append(Issue("error", "type-fields", f"{p}: `{f}` must be one of {list(rule)}"))
            else:
                v = e.get(f)
                if f in e and (not isinstance(v, dict) or any(k not in v for k in rule)):
                    issues.append(Issue("error", "type-fields", f"{p}: `{f}` needs {rule}"))
    captured = e.get("captured")
    if isinstance(captured, dict) and captured.get("float") is True and "source_format" not in e:
        issues.append(Issue("error", "type-fields", f"{p}: audio from a float capture needs `source_format`"))


def _check_entry_rules(entries: list[dict], spec11: bool, issues: list[Issue]) -> None:
    for e in entries:
        p = e.get("path", "?")
        if _SAMPLES_TRAINING_RE.search(p) and "origin" not in e:
            issues.append(Issue("error", "spec-fields", f"{p}: `origin` required on samples/ and training/"))
        if spec11:
            if _GEOMETRY_GEN_TPL_RE.search(p) and "derivation" not in e:
                issues.append(Issue("error", "spec-fields", f"{p}: `derivation` required (spec 1.1)"))
            if _SAMPLES_GEOMETRY_GEN_RE.search(p) and ("look" not in e or "era" not in e):
                issues.append(Issue("error", "spec-fields", f"{p}: `look` and `era` required (spec 1.1)"))
            if _SPATIAL_GEOMETRY_GEN_RE.search(p) and "frame" not in e:
                issues.append(Issue("error", "spec-fields", f"{p}: `frame` required (spec 1.1, spatial modality)"))
        if _GENERATION_RE.search(p) and e.get("synthetic_capable") is not True:
            issues.append(Issue("error", "generation", f"{p}: generation/ entries carry `synthetic_capable: true`"))
        if _SAMPLES_TRAINING_RE.search(p):
            origin = e.get("origin")
            if isinstance(origin, dict) and origin.get("synthetic") is True:
                issues.append(Issue("error", "generation", f"{p}: generated material in samples/ or training/"))
        _check_type_fields(e, issues)


def _check_person(pkg, m: dict, files: dict[str, bytes], listed: set, spec11: bool, issues: list[Issue]) -> None:
    person_path = m.get("person", "person.json")
    if person_path not in listed or person_path not in files:
        issues.append(Issue("error", "person", f"{person_path} is not a listed entry"))
        return
    if m.get("redact"):
        issues.append(Issue("note", None, "redact: person.json is encrypted"))
        return
    try:
        person = parse(files[person_path])
    except JSONError as ex:
        issues.append(Issue("error", "person", f"person.json is not strict JSON: {ex}"))
        return
    if not isinstance(person, dict):
        issues.append(Issue("error", "person", "person.json is not an object"))
        return
    if not spec11:
        mapped = map_legacy_person(person)
        if mapped != person:
            issues.append(
                Issue("note", None, "legacy person.json shape mapped (name -> display_name, ids/links objects -> arrays)")
            )
        person = mapped
    if not isinstance(person.get("id"), str) or not isinstance(person.get("display_name"), str):
        issues.append(Issue("error", "person", "person.json needs string `id` and `display_name`"))


def _check_capture_refs(entries: list[dict], files: dict[str, bytes], issues: list[Issue]) -> list[dict]:
    refs: list[dict] = []
    for e in entries:
        if canonical_type(str(e.get("type", ""))) != "org.prsn.face.capture-ref":
            continue
        p = e.get("path")
        if p not in files:
            continue  # a missing listed entry already refused the file
        try:
            payload = parse(files[p])
        except JSONError as ex:
            issues.append(Issue("error", "capture-ref", f"{p}: not strict JSON: {ex}"))
            continue
        if isinstance(payload, dict):
            issues.append(Issue("note", None, f"{p}: single-object capture-ref read as a one-item list"))
            payload = [payload]
        if not isinstance(payload, list):
            issues.append(Issue("error", "capture-ref", f"{p}: capture-ref payload must be a list"))
            continue
        for ref in payload:
            if not isinstance(ref, dict):
                issues.append(Issue("error", "capture-ref", f"{p}: capture-ref item must be an object"))
                continue
            h = ref.get("manifest_sha256")
            if not isinstance(h, str) or not _SHA256_OR_CONTENT_ID_RE.match(h):
                issues.append(Issue("error", "capture-ref", f"{p}: manifest_sha256 is not a SHA-256"))
            else:
                refs.append(ref)
    return refs


def _check_looks_eras(m: dict, entries: list[dict], refs: list[dict], issues: list[Issue]) -> None:
    looks = {lk.get("id"): lk for lk in m.get("looks") or [] if isinstance(lk, dict)}
    eras = {er.get("id"): er for er in m.get("eras") or [] if isinstance(er, dict)}
    for lid, lk in looks.items():
        owners = [eid for eid, er in eras.items() if lid in (er.get("looks") or [])]
        if lk.get("era") not in eras or owners != [lk.get("era")]:
            issues.append(Issue("error", "looks-eras", f"look {lid} must belong to exactly one declared era"))
    for what, items in (("entry", entries), ("capture-ref", refs)):
        for x in items:
            name = x.get("path") or x.get("file")
            if "look" in x and x["look"] != "*" and x["look"] not in looks:
                issues.append(Issue("error", "looks-eras", f"{what} {name}: look {x['look']!r} is not in manifest.looks"))
            if "era" in x and x["era"] not in eras:
                issues.append(Issue("error", "looks-eras", f"{what} {name}: era {x['era']!r} is not in manifest.eras"))


def validate_package(pkg) -> list[Issue]:
    """Run the semantic rule table over an opened package."""
    issues: list[Issue] = list(pkg.notes)
    m = pkg.manifest
    files = pkg.files
    spec11 = _spec_ge_11(m)
    entries = [e for e in m.get("entries", []) if isinstance(e, dict)]

    _check_entry_paths(entries, issues)
    _check_entry_order(m, entries, spec11, issues)
    _check_entry_rules(entries, spec11, issues)

    for e in entries:
        t = canonical_type(str(e.get("type", "")))
        if t != str(e.get("type", "")):
            issues.append(Issue("note", None, f"{e.get('path')}: legacy type name read as {t}"))
        if t not in KNOWN_TYPES and e.get("critical") is not True:
            issues.append(Issue("note", None, f"{e.get('path')}: unknown type {e.get('type')}, carried through unread"))

    listed = {e.get("path") for e in entries}
    for p in sorted(files):
        if p not in listed and p not in ("mimetype", "manifest.json") and not p.startswith("signatures/"):
            issues.append(Issue("note", None, f"{p}: not listed in the manifest; ignored, never written back"))

    _check_person(pkg, m, files, listed, spec11, issues)
    refs = _check_capture_refs(entries, files, issues)
    _check_looks_eras(m, entries, refs, issues)
    return issues
