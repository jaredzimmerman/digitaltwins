#!/usr/bin/env python3
"""Validates the `.styl` and `.scen` examples and checks their conformance cases.

    uv run --with jsonschema python core/tools/validate.py

Python 3.11+, one dependency (`jsonschema`). Canonical JSON, SHA-256 and Ed25519 come from
`prsn/tools/prsnfmt.py` (standard library only). `.prsn` has its own validator,
`prsn/tools/validate.py`, which applies the same core rules to `.prsn` files.

Exit status 0 when every example is valid and every case fails for exactly its stated rule.
"""

from __future__ import annotations

import base64
import binascii
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "prsn" / "tools"))
import prsnfmt as P  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dtwin_checks as X  # noqa: E402

GH = "https://github.com/jaredzimmerman/digitaltwins/"
TODAY = "2026-10-10"
INDEX_KINDS = {"captions": "captions.schema.json", "refset": "refset.schema.json",
               "descriptor": "descriptor.schema.json", "holdout": "holdout.schema.json"}

FORMATS = {
    "styl": {
        "mimetype": "application/vnd.styl+zip", "subject_key": "style", "subject_type": "org.styl.style",
        "subject_schema": "styl/schemas/style.schema.json", "state_index": "variants", "state_field": "variant",
        "authored_allowed": lambda subj: True,
        "known": {"org.styl.style", "org.styl.style.exemplar", "org.styl.style.palette",
                  "org.styl.style.typography", "org.styl.style.rendering", "org.styl.style.bible",
                  "org.styl.style.template", "org.styl.style.training-set", "org.styl.style.coverage",
                  "org.styl.image.lora", "org.styl.image.embedding", "org.styl.image.adapter-ref",
                  "org.styl.image.vendor-ref", "org.styl.image.prompt",
                  *(f"org.styl.style.{k}" for k in INDEX_KINDS)},
    },
    "scen": {
        "mimetype": "application/vnd.scen+zip", "subject_key": "scene", "subject_type": "org.scen.scene",
        "subject_schema": "scen/schemas/scene.schema.json", "state_index": "states", "state_field": "state",
        "authored_allowed": lambda subj: subj.get("kind") == "fictional-place",
        "known": {"org.scen.scene", "org.scen.place.capture-ref", "org.scen.place.coverage",
                  "org.scen.place.sample", "org.scen.prop.sample", "org.scen.place.splat", "org.scen.place.mesh",
                  "org.scen.place.layout", "org.scen.place.cameras", "org.scen.prop.mesh", "org.scen.prop.splat",
                  "org.scen.place.lighting", "org.scen.place.palette", "org.scen.place.bible",
                  "org.scen.place.template", "org.scen.place.render", "org.scen.place.training-set",
                  "org.scen.image.lora", "org.scen.image.adapter-ref", "org.scen.image.vendor-ref",
                  *(f"org.scen.{m}.{k}" for m in ("place", "prop") for k in INDEX_KINDS)},
    },
}

# --------------------------------------------------------------------------- #
# schemas: prsn (shared defs), core, styl, scen in one registry
# --------------------------------------------------------------------------- #

_resources = []
for folder in ("prsn/schemas", "core/schemas", "styl/schemas", "scen/schemas"):
    for f in sorted((REPO / folder).glob("*.schema.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        want = GH + folder + "/" + f.name
        if doc.get("$id") != want:
            raise SystemExit(f"{folder}/{f.name}: $id must be {want}")
        Draft202012Validator.check_schema(doc)
        _resources.append((doc["$id"], Resource.from_contents(doc)))
REGISTRY = Registry().with_resources(_resources)


def schema_errors(ref: str, instance) -> list[str]:
    v = Draft202012Validator({"$ref": ref if ref.startswith("https://") else GH + ref}, registry=REGISTRY)
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:160]}"
            for e in sorted(v.iter_errors(instance), key=lambda e: list(e.absolute_path))]


class Report:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []
        self.notes: list[str] = []

    def err(self, rule: str, msg: str) -> None:
        self.errors.append((rule, msg))

    @property
    def rules(self) -> set[str]:
        return {a for a, _ in self.errors}


def read_dir(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def check_signature(m: dict, files: dict[str, bytes], r: Report) -> None:
    block = m.get("signature")
    if not block:
        r.notes.append("unsigned: integrity unproven; top tiers (including authored) are not vouched for")
        return
    path = block.get("path", "signatures/manifest.sig")
    if path not in files:
        r.err("signature", f"the manifest names {path} but the package does not carry it")
        return
    try:
        pub = base64.b64decode(block.get("public_key", ""), validate=True)
    except (binascii.Error, ValueError):
        r.err("signature", "public_key is not base64")
        return
    if P.key_id(pub) != block.get("key_id"):
        r.err("signature", "key_id does not match public_key")
    if not P.ed25519_verify(pub, P.canonical(m), files[path]):
        r.err("signature", "Ed25519 signature does not verify over the canonical manifest")


ENTRY_RULES = {   # core / format $defs -> rule id
    "core/schemas/entry.schema.json#/$defs/container": "paths",
    "core/schemas/entry.schema.json#/$defs/depthRule": "paths",
    "core/schemas/entry.schema.json#/$defs/originRule": "spec-fields",
    "core/schemas/entry.schema.json#/$defs/derivationRule": "spec-fields",
    "core/schemas/entry.schema.json#/$defs/generationRule": "generation",
    "core/schemas/entry.schema.json#/$defs/notGeneratedRule": "generation",
    "core/schemas/rules.schema.json#/$defs/authoredSynthetic": "authored",
    "core/schemas/rules.schema.json#/$defs/anchorRule": "authored",
    "core/schemas/rules.schema.json#/$defs/renderRule": "authored",
    "core/schemas/rules.schema.json#/$defs/indexRecord": "index",
    "core/schemas/rules.schema.json#/$defs/attributesRule": "type-fields",
    "core/schemas/rules.schema.json#/$defs/vendorRef": "type-fields",
    "core/schemas/rules.schema.json#/$defs/adapterRef": "type-fields",
    "core/schemas/rules.schema.json#/$defs/imageAdapter": "type-fields",
}
FORMAT_RULES = {
    "styl": {"subjectRule": "paths", "variantRule": "spec-fields", "noFrame": "spec-fields", "typeRules": "type-fields"},
    "scen": {"subjectRule": "paths", "stateRule": "spec-fields", "propRule": "props", "frameRule": "spec-fields",
             "typeRules": "type-fields"},
}


def check_package(files: dict[str, bytes], fmt: str) -> Report:
    F = FORMATS[fmt]
    r = Report()
    mt = files.get("mimetype")
    if mt is not None and mt.decode("ascii", "replace") != F["mimetype"]:
        r.err("container", f"mimetype {mt!r} is not {F['mimetype']}")
    raw = files.get("manifest.json")
    if raw is None:
        r.err("version", "no manifest.json")
        return r
    try:
        m = P.parse(raw)
    except P.JSONError as e:
        r.err("version", f"manifest.json is not strict JSON: {e}")
        return r
    if m.get("format") != fmt or not isinstance(m.get("version"), int) or isinstance(m.get("version"), bool):
        r.err("version", f"format must be {fmt!r} and version an integer")
        return r
    if m["version"] > 1:
        r.err("version", f"version {m['version']} is newer than this reader (1)")
        return r
    entries = [e for e in m.get("entries") or [] if isinstance(e, dict)]

    seen = set()
    for e in entries:
        if e.get("path") in seen:
            r.err("paths", f"{e.get('path')} is listed twice")
        seen.add(e.get("path"))
    keys = [str(e.get("path", "")).encode() for e in entries]
    if keys != sorted(keys):
        r.err("entry-order", "entries are not sorted by path")

    for e in entries:
        p = e.get("path")
        for ref, rule in ENTRY_RULES.items():
            for x in schema_errors(ref, e):
                r.err(rule, f"{p}: {ref.rsplit('/', 1)[-1]} ({x})")
        for d, rule in FORMAT_RULES[fmt].items():
            for x in schema_errors(f"{fmt}/schemas/{fmt}-entry.schema.json#/$defs/{d}", e):
                r.err(rule, f"{p}: {d} ({x})")
        t = str(e.get("type", ""))
        if t not in F["known"]:
            if e.get("critical") is True:
                r.err("critical", f"{p}: critical entry of unknown type {t}")
            else:
                r.notes.append(f"{p}: unknown type {t}, carried through unread")

    for e in entries:
        p = e.get("path")
        if p not in files:
            r.err("manifest-hash", f"{p} is listed but not in the package")
        elif len(files[p]) != e.get("bytes") or P.sha256_hex(files[p]) != e.get("sha256"):
            r.err("manifest-hash", f"{p}: size or sha256 does not match")
    listed = {e.get("path") for e in entries}
    for p in files:
        if p not in listed and p not in ("mimetype", "manifest.json") and not p.startswith("signatures/"):
            r.notes.append(f"{p}: not listed in the manifest; ignored")
    check_signature(m, files, r)

    # subject record
    subj = {}
    sp = m.get(F["subject_key"])
    if sp not in listed or sp not in files:
        r.err("subject", f"{F['subject_key']}: {sp!r} is not a listed entry")
    else:
        try:
            subj = P.parse(files[sp])
        except P.JSONError as ex:
            r.err("subject", f"{sp} is not JSON: {ex}")
        for x in schema_errors(F["subject_schema"], subj):
            r.err("subject", x)
    subj = subj if isinstance(subj, dict) else {}

    # states / variants and props
    states = {s.get("id") for s in m.get(F["state_index"]) or [] if isinstance(s, dict)}
    for e in entries:
        v = e.get(F["state_field"])
        if v is not None and v != "*" and v not in states:
            r.err("states", f"{e.get('path')}: {F['state_field']} {v!r} is not declared")
    if fmt == "scen":
        props = {x.get("id") for x in m.get("props") or [] if isinstance(x, dict)}
        for e in entries:
            if "prop" in e and e["prop"] not in props:
                r.err("props", f"{e.get('path')}: prop {e['prop']!r} is not in manifest.props")
        fictional = subj.get("kind") == "fictional-place"
        allowed = ("none", "masked", "removed") + (("fictional",) if fictional else ())
        for e in entries:
            if e.get("type") != "org.scen.place.sample":
                continue
            if e.get("people") not in allowed:
                r.err("people", f"{e.get('path')}: people must be one of {allowed} (got {e.get('people')!r})")
            elif e.get("people") in ("masked", "removed") and not e.get("derivation"):
                r.err("people", f"{e.get('path')}: people {e['people']} but no derivation naming the masking method")
        loc = subj.get("location") or {}
        exact_ok = (subj.get("consent") or {}).get("exact_location") is True
        if loc.get("precision") == "exact" and not exact_ok:
            r.err("location", "precision `exact` needs consent.exact_location: true")
        elif ("lat" in loc or "lon" in loc) and loc.get("precision") != "exact":
            r.err("location", "coordinates need precision `exact`")
        # frames, zones and viewpoints
        for e in entries:
            want = {"place": "scene-canonical", "prop": "prop-canonical"}.get(str(e.get("path", "")).split("/")[0])
            if "frame" in e and want and e["frame"] != want:
                r.err("spec-fields", f"{e.get('path')}: frame must be {want}")
        def payload(t):
            e = next((x for x in entries if x.get("type") == t and x.get("path") in files), None)
            try:
                return P.parse(files[e["path"]]) if e else None
            except P.JSONError:
                return None
        layout, cams = payload("org.scen.place.layout"), payload("org.scen.place.cameras")
        zones = {z.get("id") for z in (layout or {}).get("zones") or []} if layout else None
        rigs = {c.get("id") for c in (cams or {}).get("rigs") or []} if cams else None
        for e in entries:
            if zones is not None:
                for z in ([e["zone"]] if "zone" in e else []) + list(e.get("zones") or []):
                    if z not in zones:
                        r.err("type-fields", f"{e.get('path')}: zone {z!r} is not in the layout")
            if rigs is not None and "viewpoint" in e and e["viewpoint"] not in rigs:
                r.err("type-fields", f"{e.get('path')}: viewpoint {e['viewpoint']!r} is not a camera rig")

    # cross-entry rules (core §4 to §6)
    X.check_authored(entries, F["authored_allowed"](subj), fmt == "scen", r.err)
    X.check_index(entries, files, P.parse, schema_errors, GH + "core/schemas/", fmt == "scen", r.err)
    X.check_references(entries, subj, r.err)

    if not r.errors:
        for x in schema_errors(f"{fmt}/schemas/{fmt}-manifest.schema.json", m):
            r.err("schema", x)
    return r


def main() -> int:
    passed = failed = 0

    def ok(cond: bool, label: str, detail: str = "") -> None:
        nonlocal passed, failed
        passed += cond
        failed += not cond
        print(f"  {'ok  ' if cond else 'FAIL'}  {label}" + ("" if cond or not detail else f"\n        {detail}"))

    print(f"schemas\n  ok    {len(_resources)} schemas (prsn defs, core, styl, scen) load with matching $id")
    for fmt in FORMATS:
        rules = json.loads((REPO / fmt / "conformance" / "rules.json").read_text())
        print(f"\n{fmt}/examples (must be valid)")
        for v in rules["valid"]:
            r = check_package(read_dir(REPO / fmt / v["path"]), fmt)
            ok(not r.errors, v["id"], "; ".join(f"[{a}] {b}" for a, b in r.errors[:6]))
            for n in r.notes:
                print(f"          note: {n}")
        print(f"\n{fmt}/conformance")
        for c in rules["cases"]:
            r = check_package(read_dir(REPO / fmt / "conformance" / c["id"]), fmt)
            if c["outcome"] == "valid":
                ok(not r.errors, f"{c['id']}: valid", "; ".join(f"[{a}] {b}" for a, b in r.errors[:6]))
            else:
                ok(r.rules == {c["rule"]}, f"{c['id']}: {c['outcome']} by rule `{c['rule']}`",
                   f"got {sorted(r.rules)}: " + "; ".join(f"[{a}] {b}" for a, b in r.errors[:6]))
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
