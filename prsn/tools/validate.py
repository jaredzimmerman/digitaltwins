#!/usr/bin/env python3
"""Validates the examples against the schemas and checks every conformance case.

    uv run --with jsonschema python tools/validate.py

Python 3.11+, one dependency (`jsonschema`, draft 2020-12). `prsnfmt.py` beside this file
supplies canonical JSON, SHA-256 and Ed25519 verification (standard library only).

Exit status 0 when every example is valid and every conformance case behaves as stated.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import math
import struct
import sys
import zipfile
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prsnfmt as P  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://github.com/jaredzimmerman/digitaltwins/prsn/schemas/"
MIMETYPES = {"application/vnd.prsn+zip": "current", "application/vnd.museli.prsn+zip": "legacy"}
CAPTURE_MIMETYPE = "application/vnd.prsn.capture+zip"
LEGACY_PREFIX, PREFIX = "org.museli.", "org.prsn."
RETIRED_KEYS = ("scopes",)
TODAY = date(2026, 10, 10).isoformat()   # fixed so the vectors give the same answer on any day

# Record types defined by spec/prsn.md and spec/voice.md. A reader that implements the whole
# spec knows these; `critical` is judged against this list.
KNOWN_TYPES = {
    "org.prsn.person",
    "org.prsn.face.capture-ref", "org.prsn.face.sample", "org.prsn.face.mesh", "org.prsn.face.landmarks",
    "org.prsn.face.params", "org.prsn.face.blendshapes", "org.prsn.face.expression-track",
    "org.prsn.face.expression-map", "org.prsn.face.splat", "org.prsn.face.coverage",
    "org.prsn.face.expression-clip", "org.prsn.face.avatar", "org.prsn.face.template",
    "org.prsn.image.lora", "org.prsn.image.embedding", "org.prsn.image.faceid", "org.prsn.avatar.vrm",
    "org.prsn.body.params", "org.prsn.body.mesh",
    "org.prsn.voice.template", "org.prsn.voice.sample", "org.prsn.voice.sample-index",
    "org.prsn.voice.training", "org.prsn.voice.training-set", "org.prsn.voice.seed",
    "org.prsn.voice.prompt", "org.prsn.voice.generation", "org.prsn.voice.lora", "org.prsn.voice.rvc",
    "org.prsn.voice.piper",
}

# --------------------------------------------------------------------------- #
# schemas
# --------------------------------------------------------------------------- #

_resources = []
for f in sorted((ROOT / "schemas").glob("*.schema.json")):
    doc = json.loads(f.read_text(encoding="utf-8"))
    if doc.get("$id") != BASE + f.name:
        raise SystemExit(f"{f.name}: $id must be {BASE + f.name}")
    Draft202012Validator.check_schema(doc)
    _resources.append((doc["$id"], Resource.from_contents(doc)))
REGISTRY = Registry().with_resources(_resources)


def schema_errors(ref: str, instance) -> list[str]:
    """Errors of `instance` against `ref` (`name.schema.json` or `name.schema.json#/$defs/x`)."""
    v = Draft202012Validator({"$ref": BASE + ref}, registry=REGISTRY)
    out = []
    for e in sorted(v.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        out.append(f"{where}: {e.message[:160]}")
    return out


# --------------------------------------------------------------------------- #
# .prsn packages
# --------------------------------------------------------------------------- #

class Report:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []
        self.notes: list[str] = []

    def err(self, rule: str, msg: str) -> None:
        self.errors.append((rule, msg))

    @property
    def rules(self) -> set[str]:
        return {r for r, _ in self.errors}


def _spec_ge_11(spec) -> bool:
    if not isinstance(spec, str) or "." not in spec:
        return False
    try:
        major, minor = (int(x) for x in spec.split(".", 1))
    except ValueError:
        return False
    return (major, minor) >= (1, 1)


def canonical_type(t: str) -> str:
    return PREFIX + t[len(LEGACY_PREFIX):] if t.startswith(LEGACY_PREFIX) else t


def check_signature(m: dict, files: dict[str, bytes], r: Report) -> None:
    block = m.get("signature")
    if not block:
        r.notes.append("unsigned: integrity unproven; top tiers are not vouched for")
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
        r.err("signature", "key_id is not the first 16 hex digits of SHA-256(public_key)")
    if block.get("alg") != "Ed25519":
        r.notes.append(f"signature algorithm {block.get('alg')!r} not checkable here")
        return
    if not P.ed25519_verify(pub, P.canonical(m), files[path]):
        r.err("signature", "Ed25519 signature does not verify over the canonical manifest")


def map_legacy_person(p: dict) -> dict:
    """spec/prsn.md, person.json: the mapping readers apply to the legacy shape."""
    out = dict(p)
    if "display_name" not in out and isinstance(out.get("name"), str):
        out["display_name"] = out.pop("name")
    if isinstance(out.get("ids"), dict):
        out["ids"] = [{"scheme": k, "value": str(v)} for k, v in out["ids"].items()]
    if isinstance(out.get("links"), dict):
        out["links"] = [{"rel": k, "href": str(v)} for k, v in out["links"].items()]
    return out


def check_prsn(files: dict[str, bytes]) -> Report:
    """Check a .prsn given as {path: bytes} (directory or ZIP form)."""
    r = Report()
    mt = files.get("mimetype")
    if mt is not None:
        kind = MIMETYPES.get(mt.decode("ascii", "replace"))
        if kind is None:
            r.err("container", f"mimetype {mt!r} is not a .prsn media type")
        elif kind == "legacy":
            r.notes.append("legacy v1 mimetype (accepted)")
    raw = files.get("manifest.json")
    if raw is None:
        r.err("version", "no manifest.json")
        return r
    try:
        m = P.parse(raw)
    except P.JSONError as e:
        r.err("version", f"manifest.json is not strict JSON: {e}")
        return r
    if not isinstance(m, dict):
        r.err("version", "manifest.json is not an object")
        return r
    if raw != P.canonical(m):
        r.notes.append("manifest.json is not stored in canonical form (identity is still its canonical hash)")

    # version / format
    for e in schema_errors("prsn-manifest.schema.json#/$defs/header", m):
        r.err("version", e)
    if isinstance(m.get("version"), int) and m["version"] > 1:
        r.err("version", f"version {m['version']} is newer than this reader (1): refuse and show it")
    if "version" in r.rules:
        return r
    spec11 = _spec_ge_11(m.get("spec"))
    entries = [e for e in m.get("entries") or [] if isinstance(e, dict)]

    # paths
    seen = set()
    for e in entries:
        p = e.get("path")
        for x in schema_errors("defs.schema.json#/$defs/entryPath", p):
            r.err("paths", f"{p!r}: {x}")
        for x in schema_errors("prsn-entry.schema.json#/$defs/depthRule", e):
            r.err("paths", f"{p!r}: depth rule ({x})")
        if p in seen:
            r.err("paths", f"{p} is listed twice")
        seen.add(p)

    # entry order: writers sort by path (UTF-8 bytes); readers never depend on it
    keys = [str(e.get("path", "")).encode("utf-8") for e in entries]
    if keys != sorted(keys):
        if spec11:
            r.err("entry-order", "manifest entries are not sorted by path")
        else:
            r.notes.append("entries not sorted by path (accepted in a pre-1.1 file; order is never relied on)")

    # per-entry rules
    for e in entries:
        p = e.get("path")
        for x in schema_errors("prsn-entry.schema.json#/$defs/originRule", e):
            r.err("spec-fields", f"{p}: origin required on samples/ and training/ ({x})")
        if spec11:
            for x in schema_errors("prsn-entry.schema.json#/$defs/v11Fields", e):
                r.err("spec-fields", f"{p}: {x}")
        for x in schema_errors("prsn-entry.schema.json#/$defs/generationRule", e):
            r.err("generation", f"{p}: generation/ entries carry synthetic_capable: true ({x})")
        for x in schema_errors("prsn-entry.schema.json#/$defs/notGeneratedRule", e):
            r.err("generation", f"{p}: generated material in samples/ or training/ ({x})")
        for x in schema_errors("prsn-entry.schema.json#/$defs/typeRules", e):
            r.err("type-fields", f"{p}: MUST field missing or wrong ({x})")

    # critical / unknown types
    for e in entries:
        t = str(e.get("type", ""))
        ct = canonical_type(t)
        if ct != t:
            r.notes.append(f"{e.get('path')}: legacy type name {t} read as {ct}")
        if ct not in KNOWN_TYPES:
            if e.get("critical") is True:
                r.err("critical", f"{e.get('path')}: critical entry of unknown type {t}: refuse the file")
            else:
                r.notes.append(f"{e.get('path')}: unknown type {t}, carried through unread")
        if e.get("expires") and str(e["expires"]) < TODAY:
            r.notes.append(f"{e.get('path')}: expired {e['expires']}; dropped on load, not written again")

    # hashes
    for e in entries:
        p = e.get("path")
        if p not in files:
            r.err("manifest-hash", f"{p} is listed but not in the package")
            continue
        b = files[p]
        if len(b) != e.get("bytes") or P.sha256_hex(b) != e.get("sha256"):
            r.err("manifest-hash", f"{p}: size or sha256 does not match the manifest")
    listed = {e.get("path") for e in entries}
    for p in sorted(files):
        if p not in listed and p not in ("mimetype", "manifest.json") and not p.startswith("signatures/"):
            r.notes.append(f"{p}: not listed in the manifest; ignored, never written back")
    for k in RETIRED_KEYS:
        if k in m:
            r.notes.append(f"top-level `{k}` is retired: dropped on load")

    check_signature(m, files, r)

    # person.json
    person_path = m.get("person", "person.json")
    if person_path not in listed or person_path not in files:
        r.err("person", f"{person_path} is not a listed entry")
    elif m.get("redact"):
        r.notes.append("redact: person.json is encrypted")
    else:
        try:
            person = P.parse(files[person_path])
        except P.JSONError as ex:
            r.err("person", f"person.json is not JSON: {ex}")
            person = None
        if isinstance(person, dict):
            if not spec11:
                mapped = map_legacy_person(person)
                if mapped != person:
                    r.notes.append("legacy person.json shape mapped (name -> display_name, ids/links objects -> arrays)")
                person = mapped
            for x in schema_errors("person.schema.json", person):
                r.err("person", x)

    # capture refs
    refs = []
    for e in entries:
        if canonical_type(str(e.get("type", ""))) == "org.prsn.face.capture-ref" and e.get("path") in files:
            try:
                payload = P.parse(files[e["path"]])
            except P.JSONError as ex:
                r.err("capture-ref", f"{e['path']}: not JSON: {ex}")
                continue
            for x in schema_errors("capture-refs.schema.json", payload):
                r.err("capture-ref", f"{e['path']}: {x}")
            if isinstance(payload, dict):
                r.notes.append(f"{e['path']}: single-object capture-ref read as a one-item list")
                payload = [payload]
            refs += [x for x in payload if isinstance(x, dict)]

    # looks and eras
    looks = {lk.get("id"): lk for lk in m.get("looks") or [] if isinstance(lk, dict)}
    eras = {er.get("id"): er for er in m.get("eras") or [] if isinstance(er, dict)}
    for lid, lk in looks.items():
        owners = [eid for eid, er in eras.items() if lid in (er.get("looks") or [])]
        if lk.get("era") not in eras or owners != [lk.get("era")]:
            r.err("looks-eras", f"look {lid} must belong to exactly one declared era ({owners})")
    for what, items in (("entry", entries), ("capture-ref", refs)):
        for x in items:
            name = x.get("path") or x.get("file")
            if "look" in x and x["look"] != "*" and x["look"] not in looks:
                r.err("looks-eras", f"{what} {name}: look {x['look']!r} is not in manifest.looks")
            if "era" in x and x["era"] not in eras:
                r.err("looks-eras", f"{what} {name}: era {x['era']!r} is not in manifest.eras")

    # everything else the schema says
    if not r.errors:
        for x in schema_errors("prsn-manifest.schema.json", m):
            r.err("schema", x)
    return r


def read_dir(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def read_zip(path: Path) -> tuple[dict[str, bytes], Report]:
    r = Report()
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if not infos or infos[0].filename != "mimetype":
            r.err("container", "the first member must be `mimetype`")
        elif infos[0].compress_type != zipfile.ZIP_STORED:
            r.err("container", "`mimetype` must be STORED")
        elif infos[0].extra:
            r.err("container", "`mimetype` must have no extra field")
        if len(set(names)) != len(names):
            r.err("container", "a member name appears more than once")
        files = {i.filename: z.read(i) for i in infos if not i.filename.endswith("/")}
    return files, r


# --------------------------------------------------------------------------- #
# .prsncap
# --------------------------------------------------------------------------- #

def holdout(seed: int, stride: int, stills_stride: int, streams: list[tuple[str, list[dict]]]) -> list[dict]:
    """spec/prsncap.md section 5."""
    out = []
    for stream, rows in streams:
        if not rows:
            continue
        stills = stream.endswith("/stills")
        s = stills_stride if stills else stride
        o = seed % s
        groups: dict = {}
        for row in rows:
            groups.setdefault(None if stills else row["phase"], []).append(row)
        for phase, grp in groups.items():
            h = {"stream": stream, "frames": [i for i, row in enumerate(grp) if i % s == o and not row.get("dropped")]}
            if phase is not None:
                h["phase"] = phase
            out.append(h)
    return out


def check_prsncap(root: Path) -> Report:
    r = Report()
    files = read_dir(root)
    mt = files.get("mimetype", b"").decode("ascii", "replace")
    if mt != CAPTURE_MIMETYPE:
        r.err("container", f"mimetype {mt!r} is not {CAPTURE_MIMETYPE}")
    m = P.parse(files["manifest.json"])
    for x in schema_errors("prsncap-manifest.schema.json", m):
        r.err("schema", x)
    for e in m.get("entries", []):
        b = files.get(e["path"])
        if b is None or len(b) != e["bytes"] or P.sha256_hex(b) != e["sha256"]:
            r.err("manifest-hash", f"{e['path']}: missing, or size/sha256 mismatch")
    check_signature(m, files, r)
    session = P.parse(files["session.json"])
    splits = P.parse(files["splits.json"])
    script = P.parse(files["script/script.json"])
    for name, doc in (("session.schema.json", session), ("splits.schema.json", splits), ("script.schema.json", script)):
        for x in schema_errors(name, doc):
            r.err("schema", f"{name}: {x}")
    if session["script"]["id"] != script["id"]:
        r.err("session", "session.script.id differs from script/script.json")
    phase_ids = {p["id"] for p in script["phases"]}
    for p in session["phases"]:
        if p["id"] not in phase_ids:
            r.err("session", f"phase {p['id']} is not in the script")
    # splits: recompute for every stream that has its own frames.jsonl
    streams = []
    for s in session["streams"]:
        dev, name = s["id"].split("/", 1)
        idx = files.get(f"devices/{dev}/{name}/frames.jsonl")
        if idx is not None:
            streams.append((s["id"], [json.loads(line) for line in idx.decode().splitlines() if line.strip()]))
    # the ARKit face template is embedded, and per-frame tracking data references it by hash
    by_type: dict = {}
    for e in m.get("entries", []):
        by_type.setdefault((e.get("device"), e.get("type")), []).append(e)
    for e in m.get("entries", []):
        if e.get("type") in ("org.prsn.capture.tracking", "org.prsn.capture.tracking-mesh"):
            for kind, field in (("tracking-topology", "topology_sha256"), ("tracking-targets", "targets_sha256")):
                held = [x["sha256"] for x in by_type.get((e.get("device"), "org.prsn.capture." + kind), [])]
                if e.get(field) not in held:
                    r.err("tracking-template", f"{e['path']}: {field} does not name an embedded {kind} entry")
    want = holdout(splits["seed"], splits["stride"], splits["stills_stride"], streams)
    have = [h for h in splits["holdout"] if any(h["stream"] == s for s, _ in streams)]
    if want != have:
        r.err("splits", f"splits.json holdout {have} != seeded-stride rule {want}")
    return r


# --------------------------------------------------------------------------- #
# eviction reference (spec/voice.md, Eviction)
# --------------------------------------------------------------------------- #

RANK = {"professional": 4, "enrolled": 3, "imported": 2, "observed": 1}
TOP = {"professional", "enrolled"}


def evict(bank: list[dict], budget: dict, pinned=(), redundancy=None, newcomer=None, today=TODAY,
          measure: str = "seconds", groupings=None) -> list[str]:
    """spec/prsn.md, Eviction procedure. `measure` is `seconds` (voice) or `count` (face, one
    per entry). `groupings` is a list of (field, floor): an entry is floor-protected if it is
    protected within any of its groups, and is never removed while it is the last entry of any
    of its groups. Voice: [("condition", per_condition_min_seconds)]. Face (run per look):
    [("angle_bin", per_angle_bin_min), ("expression_class", per_expression_class_min)]."""
    red = redundancy or {}
    if groupings is None:
        groupings = [("condition", budget.get("per_condition_min_seconds", 0))]

    def size(e):
        return e["seconds"] if measure == "seconds" else 1

    cap = budget.get(measure if measure == "seconds" else "count", math.inf)
    reserve = budget.get("reserve_" + measure, cap)
    keep = list(bank)
    gone = [e for e in keep if e.get("expires") and e["expires"] < today]
    keep = [e for e in keep if e not in gone]

    def eq(e):
        return e["score"] * (1 - max(0.0, min(1.0, red.get(e["name"], 0.0))))

    def worst(c):
        return min(c, key=lambda e: (eq(e), e["at"]))

    def over():
        return (sum(size(e) for e in keep) > cap + 1e-6
                or sum(e["bytes"] for e in keep) > budget.get("bytes", math.inf))

    def floors():
        out = set()
        for field, floor in groupings:
            for g in {e[field] for e in keep}:
                ranked = sorted((e for e in keep if e[field] == g),
                                key=lambda e: (RANK[e["tier"]], eq(e), e["at"]), reverse=True)
                held = 0.0
                for i, e in enumerate(ranked):
                    if held >= floor and i > 0:
                        break
                    out.add(e["name"])
                    held += size(e)
        return out

    def last_of_a_group(e):
        return any(sum(x[f] == e[f] for x in keep) <= 1 for f, _ in groupings)

    def same_group(a, b):
        return all(a[f] == b[f] for f, _ in groupings)

    while over():
        removable = [e for e in keep if e["name"] not in pinned and not last_of_a_group(e)]
        if not removable:
            break
        prot = floors()
        victim = None
        lower = [e for e in removable if e["tier"] not in TOP]
        for rank in sorted({RANK[e["tier"]] for e in lower}):
            pool = [e for e in lower if RANK[e["tier"]] == rank and e["name"] not in prot]
            if pool:
                victim = worst(pool)
                break
        top_size = sum(size(e) for e in keep if e["tier"] in TOP)
        if victim is None and top_size > reserve + 1e-6:
            top = [e for e in removable if e["tier"] in TOP]
            n = next((e for e in keep if e["name"] == newcomer), None)
            if n is not None and n["tier"] in TOP and n["name"] not in pinned:
                rivals = [e for e in top if e is not n and same_group(e, n)
                          and RANK[e["tier"]] <= RANK[n["tier"]] and eq(e) < eq(n)]
                victim = worst(rivals) if rivals else n
            else:
                for rank in sorted({RANK[e["tier"]] for e in top}):
                    pool = ([e for e in top if RANK[e["tier"]] == rank and e["name"] not in prot]
                            or [e for e in top if RANK[e["tier"]] == rank])
                    if pool:
                        victim = worst(pool)
                        break
        if victim is None and lower:
            low = min(RANK[e["tier"]] for e in lower)
            victim = worst([e for e in lower if RANK[e["tier"]] == low])
        if victim is None:
            break
        keep.remove(victim)
        gone.append(victim)
    return [e["name"] for e in gone]


def evict_face(bank: list[dict], budget: dict, **kw) -> list[str]:
    """Face stills bank: the procedure runs per look, counting entries."""
    per_look = dict(budget.get("per_look", {}))
    floors = budget.get("floors", {})
    groupings = [("angle_bin", floors.get("per_angle_bin_min", 0)),
                 ("expression_class", floors.get("per_expression_class_min", 0))]
    gone = []
    for look in sorted({e["look"] for e in bank}):
        gone += evict([e for e in bank if e["look"] == look], per_look, measure="count", groupings=groupings, **kw)
    return gone


def downgrade(entries: list[dict], trusted: bool) -> list[dict]:
    """spec/prsn.md, Provenance tiers: entries of a file whose signer is not trusted."""
    if trusted:
        return entries
    out = []
    for e in json.loads(json.dumps(entries)):
        o = e.get("origin")
        if isinstance(o, dict) and o.get("tier") in TOP:
            e["origin"] = {**o, "tier": "imported", "was": o["tier"]}
        ev = e.get("evidence")
        if isinstance(ev, dict) and TOP & set(ev):
            moved = sum(ev.pop(t) for t in sorted(TOP & set(ev)))
            ev["imported"] = round(ev.get("imported", 0.0) + moved, 1)
        out.append(e)
    return out


# --------------------------------------------------------------------------- #
# recipe registries
# --------------------------------------------------------------------------- #

def registry_errors(root: Path) -> list[tuple[str, str]]:
    errs = []
    recipes = []
    for f in sorted(root.rglob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for x in schema_errors("recipe.schema.json", d):
            errs.append(("schema", f"{f.name}: {x}"))
        short = str(d.get("family", "")).rsplit(".", 1)[-1]
        want = f"{short}/{d.get('id')}@{d.get('version')}.json"
        if f.relative_to(root).as_posix() != want:
            errs.append(("bad-file-name", f"{f.relative_to(root)} should be {want}"))
        recipes.append(d)
    ranks: dict = {}
    for d in recipes:
        key = (d.get("family"), d.get("rank"))
        if key in ranks:
            errs.append(("duplicate-rank", f"{d.get('id')} and {ranks[key]} share rank {d.get('rank')}"))
        ranks[key] = d.get("id")
    graph: dict = {}
    for d in recipes:
        graph.setdefault(d.get("family"), set()).update(x.get("family") for x in d.get("deps") or [])
    state: dict = {}

    def visit(n):
        if state.get(n) == 1:
            return True
        if state.get(n) == 2:
            return False
        state[n] = 1
        cyc = any(visit(m) for m in graph.get(n, ()))
        state[n] = 2
        return cyc
    if any(visit(n) for n in list(graph)):
        errs.append(("dep-cycle", "family dependencies form a cycle"))
    return errs


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #

class Run:
    def __init__(self) -> None:
        self.failures = 0
        self.passed = 0

    def ok(self, cond: bool, label: str, detail: str = "") -> None:
        if cond:
            self.passed += 1
            print(f"  ok    {label}")
        else:
            self.failures += 1
            print(f"  FAIL  {label}" + (f"\n        {detail}" if detail else ""))

    def section(self, title: str) -> None:
        print(f"\n{title}")


def describe(r: Report) -> str:
    return "; ".join(f"[{a}] {b}" for a, b in r.errors[:6])


def main() -> int:
    run = Run()

    run.section("schemas")
    run.ok(True, f"{len(_resources)} schemas are valid draft 2020-12 with matching $id")

    run.section("examples/prsn (must be valid)")
    rules = json.loads((ROOT / "conformance/prsn/rules.json").read_text())
    for v in rules["valid"]:
        r = check_prsn(read_dir(ROOT / v["path"]))
        notes = f" ({len(r.notes)} notes)" if r.notes else ""
        run.ok(not r.errors, f"{v['id']}{notes}", describe(r))
        for n in r.notes:
            print(f"          note: {n}")

    run.section("conformance/prsn")
    for c in rules["cases"]:
        r = check_prsn(read_dir(ROOT / "conformance/prsn" / c["id"]))
        if c["outcome"] == "valid":
            run.ok(not r.errors and bool(r.notes), f"{c['id']}: valid; {r.notes[:1]}", describe(r))
        else:
            run.ok(r.rules == {c["rule"]}, f"{c['id']}: {c['outcome']} by rule `{c['rule']}`",
                   f"got {sorted(r.rules)}: {describe(r)}")

    run.section("conformance/container (ZIP form)")
    cases = json.loads((ROOT / "conformance/container/cases.json").read_text())
    for c in cases["cases"]:
        files, r = read_zip(ROOT / "conformance/container" / c["file"])
        if not r.errors:
            inner = check_prsn(files)
            r.errors += inner.errors
            r.notes += inner.notes
        if c["outcome"] == "valid":
            run.ok(not r.errors, f"{c['file']}: valid", describe(r))
        else:
            run.ok(r.rules == {c["rule"]}, f"{c['file']}: {c['outcome']} by rule `{c['rule']}`",
                   f"got {sorted(r.rules)}: {describe(r)}")

    run.section("examples/prsncap")
    for d in sorted((ROOT / "examples/prsncap").iterdir()):
        if d.is_dir():
            r = check_prsncap(d)
            run.ok(not r.errors, d.name, describe(r))

    run.section("conformance/prsncap")
    pc = json.loads((ROOT / "conformance/prsncap/cases.json").read_text())
    for c in pc["cases"]:
        r = check_prsncap(ROOT / "conformance/prsncap" / f"{c['id']}.prsncap")
        run.ok(r.rules == {c["rule"]}, f"{c['id']}: {c['outcome']} by rule `{c['rule']}`",
               f"got {sorted(r.rules)}: {describe(r)}")

    run.section("examples/recipes and conformance/recipes")
    errs = registry_errors(ROOT / "examples/recipes")
    run.ok(not errs, "examples/recipes is a valid registry", str(errs))
    for d in sorted((ROOT / "conformance/recipes/registries").iterdir()):
        codes = {c for c, _ in registry_errors(d)}
        want = {"duplicate-rank": "duplicate-rank", "misplaced-file": "bad-file-name", "family-cycle": "dep-cycle"}[d.name]
        run.ok(codes == {want}, f"registries/{d.name}: rejected with `{want}`", str(codes))
    inv = json.loads((ROOT / "conformance/recipes/invalid.json").read_text())
    for v in inv["variants"]:
        rec = v["recipe"]
        errs = schema_errors("recipe.schema.json", rec)
        if v["expect_code"] == "dep-cycle":
            errs += [f"depends on its own family {rec['family']}"
                     for d in rec.get("deps") or [] if d.get("family") == rec.get("family")]
        run.ok(bool(errs), f"{v['name']}: rejected ({v['expect_code']})", "accepted")

    run.section("conformance/json (canonical JSON)")
    cj = json.loads((ROOT / "conformance/json/canonical.json").read_text(encoding="utf-8"))
    bad = []
    for v in cj["valid"]:
        try:
            out = P.dumps(P.parse(v["input"].encode("utf-8", "surrogatepass")))
        except P.JSONError as e:
            out = f"<rejected: {e}>"
        if out != v["expected"] or P.sha256_hex(out.encode("utf-8")) != v["expected_sha256"]:
            bad.append(v["name"])
    for v in cj["invalid"]:
        data = bytes.fromhex(v["input_hex"]) if "input_hex" in v else v["input"].encode("utf-8", "surrogatepass")
        try:
            P.parse(data)
            bad.append(v["name"])
        except P.JSONError:
            pass
    run.ok(not bad, f"{len(cj['valid'])} valid and {len(cj['invalid'])} invalid vectors", str(bad))

    run.section("conformance/hash")
    sv = json.loads((ROOT / "conformance/hash/sha256.json").read_text())
    bad = []
    for v in sv["vectors"]:
        if "input_utf8" in v:
            data = v["input_utf8"].encode("utf-8")
        else:
            g = v["generator"]
            data = (bytes([g["byte"]]) * g["length"] if g["kind"] == "repeat"
                    else bytes(((i * g["mul"] + g["add"]) & 0xFF) for i in range(g["length"])))
        if P.sha256_hex(data) != v["sha256"]:
            bad.append(v["name"])
    run.ok(not bad, f"sha256: {len(sv['vectors'])} vectors", str(bad))
    ak = json.loads((ROOT / "conformance/hash/action_key.json").read_text())
    bad = [v["name"] for v in ak["valid"]
           if P.action_key_preimage(v["derivation"]).decode() != v["preimage"] or P.action_key(v["derivation"]) != v["action_key"]]
    for v in ak["invalid"]:
        try:
            P.action_key(v["derivation"])
            bad.append(v["name"])
        except P.ActionKeyError:
            pass
    run.ok(not bad, f"action_key: {len(ak['valid'])} valid, {len(ak['invalid'])} invalid", str(bad))
    ed = json.loads((ROOT / "conformance/hash/ed25519.json").read_text())
    bad = []
    for v in ed["vectors"]:
        pub, msg, sig = bytes.fromhex(v["public_key"]), bytes.fromhex(v["message"]), bytes.fromhex(v["signature"])
        flipped = bytes([sig[0] ^ 1]) + sig[1:]
        if (P.ed25519_public_key(bytes.fromhex(v["seed"])) != pub or P.key_id(pub) != v["key_id"]
                or base64.b64encode(pub).decode() != v["public_key_b64"] or not P.ed25519_verify(pub, msg, sig)
                or P.ed25519_verify(pub, msg, flipped) or P.ed25519_verify(pub, msg + b"x", sig)):
            bad.append(v["name"])
    run.ok(not bad, f"ed25519: {len(ed['vectors'])} vectors", str(bad))
    mv = json.loads((ROOT / "conformance/hash/manifest.json").read_text())
    body = mv["canonical_manifest"].encode("utf-8")
    m = P.parse(body)
    pub = base64.b64decode(m["signature"]["public_key"])
    files_ok = all(any(e["path"] == f["path"] and e["sha256"] == P.sha256_hex(f["content"].encode()) for e in m["entries"])
                   for f in mv["files"])
    run.ok(P.canonical(m) == body and P.sha256_hex(body) == mv["manifest_sha256"] and files_ok
           and P.ed25519_verify(pub, body, bytes.fromhex(mv["signature"]))
           and not schema_errors("prsn-manifest.schema.json#/$defs/header", m), "manifest: build, hash, signature")

    run.section("conformance/splits")
    sp = json.loads((ROOT / "conformance/splits/vectors.json").read_text())
    for c in sp["cases"]:
        got = holdout(c["seed"], c["stride"], c["stills_stride"], [(s["stream"], s["rows"]) for s in c["streams"]])
        exp = c["expected"]
        run.ok(got == exp["holdout"] and not schema_errors("splits.schema.json", exp), c["name"],
               f"got {got}")

    run.section("conformance/imu")
    iv = json.loads((ROOT / "conformance/imu/imu-10.json").read_text())
    blob = (ROOT / "conformance/imu" / iv["bin"]).read_bytes()
    bad = []
    for rec in iv["records"]:
        chunk = blob[80 * rec["index"]: 80 * rec["index"] + 80]
        pts, kind, flags, reserved, seq, *v = struct.unpack("<qBBHI16f", chunk)
        if ((pts, kind, flags, reserved, seq) != (rec["pts_ns"], rec["kind_code"], rec["flags"], rec["reserved"], rec["seq"])
                or v != rec["v"] or chunk.hex() != rec["hex"]):
            bad.append(rec["index"])
    run.ok(not bad and len(blob) == iv["bin_bytes"] and P.sha256_hex(blob) == iv["bin_sha256"],
           f"imu-10.bin decodes to imu-10.json ({len(iv['records'])} records)", str(bad))

    run.section("conformance/frames")
    fr = sorted((ROOT / "conformance/frames").glob("*.json"))
    run.ok(all(isinstance(json.loads(f.read_text()), dict) for f in fr), f"{len(fr)} vector files parse")
    bins = json.loads((ROOT / "conformance/frames/bins.json").read_text())
    bad = [b for b in bins["yaw_bins"] if min(max(math.floor((b["yaw"] + 180) / 15), 0), 23) != b["bin"]]
    bad += [b for b in bins["pitch_bins"] if min(max(math.floor((b["pitch"] + 90) / 15), 0), 11) != b["bin"]]
    run.ok(not bad, "bins.json: yaw and pitch bin ids", str(bad))

    run.section("conformance/eviction")
    ev = json.loads((ROOT / "conformance/eviction/vectors.json").read_text())
    for c in ev["cases"]:
        kw = dict(pinned=set(c.get("pinned", [])), redundancy=c.get("redundancy"), newcomer=c.get("newcomer"),
                  today=ev["today"])
        if c.get("role", "voice.samples") == "face.samples":
            got = evict_face(c["bank"], c["budget"], **kw)
        else:
            got = evict(c["bank"], c["budget"], **kw)
        budget_ok = not schema_errors("budgets.schema.json", {c.get("role", "voice.samples"): c["budget"]})
        run.ok(got == c["evicted"] and budget_ok, f"{c['name']}: evicts {c['evicted']}", f"got {got}")

    run.section("conformance/tiers")
    tv = json.loads((ROOT / "conformance/tiers/downgrade.json").read_text())
    for c in tv["cases"]:
        got = downgrade(c["entries"], c["trusted"])
        run.ok(got == c["expected"], c["name"], f"got {got}")

    print(f"\n{run.passed} passed, {run.failures} failed")
    return 1 if run.failures else 0


if __name__ == "__main__":
    sys.exit(main())
