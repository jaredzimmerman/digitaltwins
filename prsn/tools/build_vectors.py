#!/usr/bin/env python3
"""Regenerates every example package and every derived value in the conformance vectors.

    python3 tools/build_vectors.py

Standard library only (plus tools/prsnfmt.py). Output is deterministic: fixed key, fixed
timestamps, canonical JSON, deterministic Ed25519, fixed ZIP timestamps. Re-running leaves
the tree byte-identical.

What it writes:

- examples/prsn/{valid-v11, valid-v10-legacy, voice-v11}/   directory-form `.prsn` packages
- conformance/prsn/<case>/ + rules.json                     one directory package per rule
- conformance/container/*.prsn + cases.json                 ZIP-form container cases
- examples/prsncap/minimal-depth.prsncap/                   tracking data + embedded template, re-sealed
- conformance/prsncap/                                       capture cases + cases.json
- conformance/hash/{sha256,action_key,ed25519,manifest}.json  derived fields recomputed
- conformance/json/canonical.json                           expected_sha256 recomputed

The descriptive fields of the hash and JSON vectors (inputs, derivations, seeds, messages,
files) are the source of truth; this script only recomputes what follows from them.

The signing key is a published test key (seed = SHA-256 of "prsn-example-signing-key").
Never trust it for anything.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import shutil
import sys
import warnings
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prsnfmt as P  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SEED = hashlib.sha256(b"prsn-example-signing-key").digest()
MIMETYPE = "application/vnd.prsn+zip"
LEGACY_MIMETYPE = "application/vnd.museli.prsn+zip"
CREATED = "2026-10-02T18:30:00Z"
GENERATOR = "example-writer 1.0.0"
CAP = hashlib.sha256(b"synthetic capture manifest").hexdigest()
PERSON = {"id": "urn:uuid:5a1e0000-0000-4000-8000-000000000001", "display_name": "Example Person",
          "aliases": [], "links": []}
DERIV = {"family": "org.prsn.method.head-fit",
         "recipe": {"id": "org.example.recipe.headfit.gnm", "version": "1.0.0", "rank": 10},
         "tool": {"name": "example-writer", "version": "1.0.0"},
         "models": [{"role": "head-model", "key": "gnm-head-v3", "sha256": "c" * 64, "license": "Apache-2.0",
                     "use_restrictions": []}],
         "inputs": [{"capture": "sha256:" + CAP, "look": "look-a", "era": "era-1",
                     "select": {"streams": ["d0/rgb.front"], "phases": ["orbit"], "exclude_split": "holdout"}}],
         "params": {"seed": 1}, "determinism": "seeded-nonbitwise", "supersedes": None,
         "license_constraints": []}
DERIV["action_key"] = P.action_key(DERIV)
LOOKS = [{"id": "look-a", "label": "Oct 2026", "era": "era-1", "default": True, "sessions": ["sha256:" + CAP],
          "state": {"hair_length": "short", "facial_hair": "none", "glasses": False}, "created": CREATED}]
ERAS = [{"id": "era-1", "label": "2026", "looks": ["look-a"], "identity_ref": None, "started": "2026-10-02",
         "ended": None, "linked_from": None}]
ORIGIN = {"tier": "enrolled", "how": "example-guided-v1", "at": CREATED}
REF = {"file": "example-20261002T1804Z.prsncap", "manifest_sha256": CAP, "tier": "minimal",
       "capabilities": ["depth.truedepth.30", "tracking.arkit-face"], "look": "look-a", "era": "era-1",
       "captured_at": "2026-10-02T18:04:11Z", "script": {"id": "example-guided", "version": "1.0.0", "kind": "full"}}
FACE_BUDGET = {"face.samples": {"per_look": {"count": 48, "bytes": 160000000},
                                "floors": {"per_angle_bin_min": 2, "per_expression_class_min": 3},
                                "angle_bins": "yaw15",
                                "expression_classes": ["neutral", "smile-closed", "smile-open", "laugh", "speaking",
                                                       "serious", "surprised"]}}
LEGACY_FACE_BUDGET = {"face.samples": {"count": 48, "bytes": 120000000, "per_condition_min_count": 3}}
SAMPLE_BYTES = b"\x00\x00\x00\x18ftypheic" + bytes(20)
MESH_BYTES = b"glTF\x02\x00\x00\x00" + bytes(56)


def clean(d: Path) -> None:
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)


# --------------------------------------------------------------------------- #
# .prsn packages
# --------------------------------------------------------------------------- #

class Pkg:
    """A directory package being assembled: files on disk plus per-path entry fields."""

    def __init__(self, root: Path, spec: str | None = "1.1", legacy: bool = False):
        self.root = root
        self.meta: dict[str, dict] = {}
        self.top = {"format": "prsn", "version": 1, "created": CREATED, "generator": GENERATOR,
                    "person": "person.json",
                    "budgets": copy.deepcopy(LEGACY_FACE_BUDGET if legacy else FACE_BUDGET)}
        if spec:
            self.top["spec"] = spec
        if not legacy:
            self.top["looks"] = copy.deepcopy(LOOKS)
            self.top["eras"] = copy.deepcopy(ERAS)
        self.mimetype = MIMETYPE

    def put(self, path: str, data: bytes, type_: str, media: str, **fields) -> None:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self.meta[path] = {"type": type_, "media": media, **fields}

    def put_json(self, path: str, obj, type_: str, **fields) -> None:
        self.put(path, P.canonical(obj), type_, "application/json", **fields)

    def seal(self, signed: bool = True) -> None:
        P.seal_package(self.root, self.top, self.meta, SEED if signed else None, mimetype=self.mimetype)


def face_package(root: Path, spec: str | None = "1.1", legacy: bool = False) -> Pkg:
    clean(root)
    k = Pkg(root, spec, legacy)
    k.put_json("person.json", PERSON, "org.prsn.person")
    s = {"pose": {"yaw": -32.5, "pitch": 4.1, "roll": 1.0}, "condition": "profile", "expression": "neutral",
         "origin": dict(ORIGIN)}
    if not legacy:
        s.update(look="look-a", era="era-1")
    k.put("face/samples/f-0001.heic", SAMPLE_BYTES, "org.prsn.face.sample", "image/heic", **s)
    mesh = {"topology": "gnm-head-v3", "coverage": ["face", "scalp", "ears", "neck"],
            "model": {"key": "gnm-head-v3", "sha256": "c" * 64, "license": "Apache-2.0"}}
    if not legacy:
        mesh.update(frame="head-canonical", look="*", era="era-1", derivation=copy.deepcopy(DERIV))
    k.put("face/geometry/head.glb", MESH_BYTES, "org.prsn.face.mesh", "model/gltf-binary", **mesh)
    if legacy:
        k.put_json("face/capture-refs.json", {a: b for a, b in REF.items() if a not in ("look", "era")},
                   "org.museli.face.capture-ref")
    else:
        k.put_json("face/capture-refs.json", [REF], "org.prsn.face.capture-ref")
    return k


def voice_derivation(family: str, recipe: str, inputs: list[dict]) -> dict:
    d = {"family": family, "recipe": {"id": recipe, "version": "1.0.0", "rank": 10},
         "tool": {"name": "example-writer", "version": "1.0.0"},
         "models": [{"role": "embedder", "key": "example-embedder", "sha256": "e" * 64, "license": "Apache-2.0"}],
         "inputs": inputs, "params": {}, "determinism": "bitwise", "supersedes": None, "license_constraints": []}
    d["action_key"] = P.action_key(d)
    return d


def voice_package(root: Path) -> Pkg:
    """A spec 1.1 voice file: template, sample bank, seed and generation record. Voice is
    identity-level (`look: "*"`) and non-spatial (no `frame`)."""
    clean(root)
    k = Pkg(root, spec="1.1")
    k.top["budgets"] = {"voice.samples": {"seconds": 60, "bytes": 8000000, "per_condition_min_seconds": 8,
                                          "reserve_seconds": 45},
                        "voice.generation": {"candidates": 0}, "voice.templates": {"models": 3}}
    k.put_json("person.json", PERSON, "org.prsn.person")
    flac = b"fLaC" + bytes(60)
    sample_sha = P.sha256_hex(flac)
    k.put("voice/samples/s-0001.flac", flac, "org.prsn.voice.sample", "audio/flac",
          seconds=6.0, sample_rate=48000, bits=24, channels=1, source_format="f32",
          captured={"device": "example microphone", "rate": 48000, "bits": 32, "float": True},
          condition="quiet", overlap=0.0, source="example:session-1@12.0", text="the quick brown fox",
          origin={"tier": "enrolled", "how": "example-guided-v1", "at": CREATED, "set_by": "example-writer"},
          quality={"score": 0.82, "snr_db": 31.0, "speech": 0.94, "length": 0.6, "agree": 0.71,
                   "standard": "example-voice-quality-1", "by": "example-embedder@0123abcd", "at": CREATED},
          look="*", era="era-1")
    bank = [{"sha256": sample_sha, "role": "samples"}]
    k.put("voice/templates/example-embedder-192.bir", b"PK\x03\x04" + bytes(60), "org.prsn.voice.template",
          "application/vnd.cbeff.bir",
          model={"key": "example-embedder", "sha256": "e" * 64, "dim": 192, "license": "Apache-2.0"},
          evidence_seconds=6.0, evidence={"enrolled": 6.0}, n_samples=1, samples=[sample_sha],
          derived_from="voice/samples", updated=CREATED,
          derivation=voice_derivation("org.example.method.voice-embed", "org.example.recipe.voice.embed", bank))
    seed = b"fLaC" + bytes(40)
    seed_deriv = voice_derivation("org.example.method.voice-seed", "org.example.recipe.voice.seed", bank)
    k.put("voice/generation/seed.flac", seed, "org.prsn.voice.seed", "audio/flac",
          seconds=5.0, sample_rate=48000, bits=24, source_format="f32", text="the quick brown fox",
          source="example:session-1@12.0", source_sample=sample_sha, synthetic_capable=True,
          look="*", era="era-1", derivation=seed_deriv)
    k.put_json("voice/generation/generation.json",
               {"seed": {"path": "voice/generation/seed.flac", "source": "example:session-1@12.0",
                         "text": "the quick brown fox", "seconds": 5.0},
                "verified_by": {"engine": "example-tts", "version": "1.0.0"},
                "scores": {"similarity": 0.81, "naming_rate": 1.0, "wer": 0.04},
                "history": [], "synthetic_capable": True},
               "org.prsn.voice.generation", synthetic_capable=True, look="*", era="era-1",
               derivation=seed_deriv)
    return k


def _manifest(root: Path) -> dict:
    return P.parse((root / "manifest.json").read_bytes())


def build_prsn() -> None:
    ex = ROOT / "examples" / "prsn"
    face_package(ex / "valid-v11").seal()
    face_package(ex / "valid-v10-legacy", spec=None, legacy=True).seal()
    voice_package(ex / "voice-v11").seal()

    out = ROOT / "conformance" / "prsn"
    for d in out.iterdir() if out.exists() else []:
        if d.is_dir():
            shutil.rmtree(d)
    out.mkdir(parents=True, exist_ok=True)
    cases = []

    def case(cid, rule, outcome, why, pre=None, post=None, signed=True, build=face_package):
        k = build(out / cid)
        if pre:
            pre(k)
        k.seal(signed=signed)
        if post:
            post(k.root)
        cases.append({"id": cid, "rule": rule, "outcome": outcome, "why": why})

    def e(k, path):
        return k.meta[path]

    # -- refused outright
    case("version-too-new", "version", "refuse", "manifest.version is 2; a version-1 reader refuses it and shows the version",
         pre=lambda k: k.top.update(version=2))
    case("version-not-integer", "version", "refuse", "manifest.version is the string \"1\", not an integer",
         pre=lambda k: k.top.update(version="1"))

    def critical_unknown(k):
        k.put("face/geometry/vendor.bin", b"vendor", "com.vendor.face.thing", "application/octet-stream",
              critical=True, derivation=copy.deepcopy(DERIV), look="*", era="era-1", frame="head-canonical")
    case("critical-unknown-type", "critical", "refuse", "a critical entry of a type the reader does not know",
         pre=critical_unknown)

    # -- invalid (a strict validator rejects; a lenient reader may open with errors)
    case("spec11-missing-derivation", "spec-fields", "invalid", "spec 1.1 geometry entry without `derivation`",
         pre=lambda k: e(k, "face/geometry/head.glb").pop("derivation"))
    case("sample-missing-origin", "spec-fields", "invalid", "samples/ entry without `origin`",
         pre=lambda k: e(k, "face/samples/f-0001.heic").pop("origin"))
    case("look-not-declared", "looks-eras", "invalid", "entry `look` is not in manifest.looks",
         pre=lambda k: e(k, "face/samples/f-0001.heic").update(look="look-missing"))

    def generation_no_flag(k):
        k.put("face/generation/lora.safetensors", b"safetensors-stub", "org.prsn.image.lora",
              "application/octet-stream", derivation=copy.deepcopy(DERIV), look="look-a", era="era-1",
              frame="head-canonical", base_model={"key": "example-base", "sha256": "b" * 64}, trigger="exampleperson")
    case("generation-not-synthetic-capable", "generation", "invalid",
         "generation/ entry without `synthetic_capable: true`", pre=generation_no_flag)
    case("sample-marked-synthetic", "generation", "invalid",
         "samples/ entry whose origin says it was generated; generated output never enters samples/ or training/",
         pre=lambda k: e(k, "face/samples/f-0001.heic")["origin"].update(synthetic=True))

    def bad_ref(k):
        k.put_json("face/capture-refs.json", [{**REF, "manifest_sha256": "not-a-hash"}], "org.prsn.face.capture-ref")
    case("capture-ref-bad-hash", "capture-ref", "invalid", "capture-ref manifest_sha256 is not a SHA-256", pre=bad_ref)

    def bad_path(k):
        k.put("face/samples/F-0002.heic", SAMPLE_BYTES, "org.prsn.face.sample", "image/heic",
              **{a: b for a, b in e(k, "face/samples/f-0001.heic").items() if a not in ("type", "media")})
    case("bad-entry-path", "paths", "invalid", "entry path has an upper-case segment", pre=bad_path)

    def listed_twice(root):
        m = _manifest(root)
        i = next(n for n, x in enumerate(m["entries"]) if x["path"] == "face/samples/f-0001.heic")
        m["entries"].insert(i + 1, copy.deepcopy(m["entries"][i]))
        P.write_manifest_signed(root, m, SEED)
    case("path-listed-twice", "paths", "invalid", "the same path appears twice in manifest.entries", post=listed_twice)

    def two_segments(k):
        k.put("face/f-0002.heic", SAMPLE_BYTES, "org.prsn.face.sample", "image/heic",
              **{a: b for a, b in e(k, "face/samples/f-0001.heic").items() if a not in ("type", "media")})
    case("path-two-segments-not-index", "paths", "invalid",
         "a sample at `face/f-0002.heic`: only modality-level index records (`<modality>/<name>.json`) may sit at depth 2",
         pre=two_segments)

    def one_segment(k):
        k.put_json("notes.json", {"note": "x"}, "org.example.person.note")
    case("path-one-segment", "paths", "invalid", "a top-level entry other than person.json", pre=one_segment)

    def reverse_entries(root):
        m = _manifest(root)
        m["entries"].reverse()
        P.write_manifest_signed(root, m, SEED)
    case("entries-unsorted", "entry-order", "invalid", "spec 1.1 manifest whose entries are not sorted by path",
         post=reverse_entries)
    case("legacy-entries-unsorted", None, "valid",
         "spec 1.0 manifest with unsorted entries: readers accept it and never depend on order",
         post=reverse_entries, build=lambda root: face_package(root, spec=None, legacy=True))

    def legacy_person(k):
        k.put_json("person.json", {"id": PERSON["id"], "name": "Example Person", "aliases": [],
                                   "ids": {"example": "abc123"}, "links": {"homepage": "https://example.org/"}},
                   "org.prsn.person")
    case("person-legacy-shape", None, "valid",
         "spec 1.0 person.json with `name`, an `ids` object and a `links` object: readers map it to the current shape",
         pre=legacy_person, build=lambda root: face_package(root, spec=None, legacy=True))

    case("spec11-geometry-missing-frame", "spec-fields", "invalid", "spec 1.1 face geometry entry without `frame`",
         pre=lambda k: e(k, "face/geometry/head.glb").pop("frame"))
    case("mesh-missing-topology", "type-fields", "invalid", "a mesh without its MUST field `topology`",
         pre=lambda k: e(k, "face/geometry/head.glb").pop("topology"))
    case("voice-float-without-source-format", "type-fields", "invalid",
         "a voice sample captured as float without `source_format`",
         pre=lambda k: e(k, "voice/samples/s-0001.flac").pop("source_format"), build=voice_package)

    def no_display_name(k):
        k.put_json("person.json", {"id": PERSON["id"], "name": "Example Person"}, "org.prsn.person")
    case("person-missing-display-name", "person", "invalid", "spec 1.1 person.json written in the legacy shape (`name`, no `display_name`)", pre=no_display_name)

    def tamper(root):
        p = root / "face/geometry/head.glb"
        b = bytearray(p.read_bytes())
        b[-1] ^= 1
        p.write_bytes(bytes(b))
    case("manifest-hash-mismatch", "manifest-hash", "invalid", "an entry's bytes no longer match its sha256", post=tamper)
    case("entry-missing", "manifest-hash", "invalid", "a listed entry is not in the package",
         post=lambda root: (root / "face/geometry/head.glb").unlink())

    def alter_after_signing(root):
        m = _manifest(root)
        m["created"] = "1999-01-01T00:00:00Z"
        (root / "manifest.json").write_bytes(P.canonical(m))
    case("signature-manifest-altered", "signature", "invalid", "manifest changed after it was signed",
         post=alter_after_signing)

    def wrong_key_id(root):
        m = _manifest(root)
        m["signature"]["key_id"] = "0000000000000000"
        P.write_manifest_signed(root, m, SEED)
    case("signature-key-id-mismatch", "signature", "invalid",
         "signature verifies, but key_id is not the first 16 hex digits of SHA-256(public_key)", post=wrong_key_id)
    case("signature-file-missing", "signature", "invalid",
         "the manifest names signatures/manifest.sig but the package does not carry it",
         post=lambda root: (root / "signatures/manifest.sig").unlink())

    # -- valid, with something a reader must notice
    case("unsigned", None, "valid", "no signature block: valid, but integrity is unproven and tiers are not vouched for",
         signed=False)
    case("unlisted-file", None, "valid", "a file the manifest does not list is ignored and never written back",
         post=lambda root: (root / "face/samples/stray.heic").write_bytes(b"not listed"))
    case("expired-entry", None, "valid", "an entry past `expires` is dropped on load and not written again",
         pre=lambda k: e(k, "face/samples/f-0001.heic").update(expires="2001-01-01"))
    case("retired-scopes-key", None, "valid", "top-level `scopes` from an early draft is dropped on load, not carried",
         pre=lambda k: k.top.update(scopes={"voice.recognise": True}))

    def unknown_noncritical(k):
        k.put("face/geometry/vendor.bin", b"vendor", "com.vendor.face.thing", "application/octet-stream",
              derivation=copy.deepcopy(DERIV), look="*", era="era-1", frame="head-canonical")
    case("unknown-noncritical-type", None, "valid",
         "an unknown non-critical type is skipped on read and copied through byte for byte on rewrite",
         pre=unknown_noncritical)

    doc = {"version": 1, "spec": "spec/prsn.md (draft v1.1)",
           "outcomes": {"refuse": "a reader MUST refuse to load the file",
                        "invalid": "a validator MUST report `rule`; the file breaks exactly that rule",
                        "valid": "the file is valid; `why` says what a reader must do with it"},
           "valid": [{"id": "valid-v11", "path": "examples/prsn/valid-v11", "spec": "1.1"},
                     {"id": "valid-v10-legacy", "path": "examples/prsn/valid-v10-legacy", "spec": None},
                     {"id": "voice-v11", "path": "examples/prsn/voice-v11", "spec": "1.1"}],
           "cases": cases}
    (out / "rules.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# ZIP container cases
# --------------------------------------------------------------------------- #

def _stored(media: str) -> bool:
    return media.startswith(("audio/", "image/", "video/")) or media in ("application/zip", "application/vnd.cbeff.bir")


def _zi(name: str, stored: bool, extra: bytes = b"") -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    zi.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    zi.create_system = 3
    if extra:
        zi.extra = extra
    return zi


def zip_package(src: Path, dest: Path, *, mimetype=MIMETYPE, mimetype_first=True, mimetype_stored=True,
                mimetype_extra=b"", extra_members=()) -> None:
    m = _manifest(src)
    members = [(_zi("manifest.json", False), (src / "manifest.json").read_bytes())]
    for x in m["entries"]:
        members.append((_zi(x["path"], _stored(x["media"])), (src / x["path"]).read_bytes()))
    sig = src / "signatures/manifest.sig"
    if sig.exists():
        members.append((_zi("signatures/manifest.sig", True), sig.read_bytes()))
    for name, data in extra_members:
        members.append((_zi(name, False), data))
    mt = (_zi("mimetype", mimetype_stored, mimetype_extra), mimetype.encode("ascii"))
    members = [mt] + members if mimetype_first else members[:1] + [mt] + members[1:]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate names are deliberate in one case
        with zipfile.ZipFile(dest, "w") as z:
            for zi, data in members:
                z.writestr(zi, data)


def build_container() -> None:
    out = ROOT / "conformance" / "container"
    out.mkdir(parents=True, exist_ok=True)
    for f in list(out.glob("*.prsn")) + [out / "cases.json"]:
        if f.exists():
            f.unlink()
    src = ROOT / "examples" / "prsn" / "valid-v11"
    cases = []

    def case(name, rule, outcome, why, **kw):
        zip_package(src, out / f"{name}.prsn", **kw)
        cases.append({"file": f"{name}.prsn", "rule": rule, "outcome": outcome, "why": why})

    case("valid", None, "valid", "examples/prsn/valid-v11 in ZIP form")
    case("legacy-mimetype", None, "valid", "the legacy v1 mimetype; readers SHOULD accept it", mimetype=LEGACY_MIMETYPE)
    case("unlisted-member", None, "valid", "a member the manifest does not list is ignored and never written back",
         extra_members=[("face/samples/smuggled.heic", b"not listed")])
    case("mimetype-not-first", "container", "refuse", "`mimetype` is not the first member", mimetype_first=False)
    case("mimetype-compressed", "container", "refuse", "`mimetype` is DEFLATE-compressed", mimetype_stored=False)
    case("mimetype-extra-field", "container", "refuse", "`mimetype` has a local extra field",
         mimetype_extra=b"\xfe\xca\x00\x00")
    case("mimetype-wrong", "container", "refuse", "`mimetype` is not a .prsn media type", mimetype="application/zip")
    case("duplicate-member", "container", "refuse", "two members share a name (readers could see different bytes)",
         extra_members=[("person.json", b"{}")])
    doc = {"version": 1, "spec": "spec/prsn.md, Container", "cases": cases}
    (out / "cases.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# .prsncap example
# --------------------------------------------------------------------------- #

ARKIT_VERTS = 1220
ARKIT_BLENDSHAPES = 52


def add_tracking(root: Path, meta: dict, embed_template: bool = True) -> None:
    """Face-tracking data for the `expr` phase: frames.jsonl, face-verts.f16, and the embedded
    ARKit face template (topology.json + blendshape-targets.f32) that both reference by hash.
    Payloads are zero-filled stand-ins with the right sizes."""
    t = root / "devices/d0/tracking.arkit"
    depth_rows = [json.loads(x) for x in (t / "depth/frames.jsonl").read_text().splitlines() if x.strip()]
    eye = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
    rows = []
    for r in depth_rows:
        rows.append({"pts_ns": r["pts_ns"], "phase": r["phase"], "tracking_state": "normal",
                     "T_cvcam_from_face": eye[:3] + [0.0] + [0, -1.0, 0, 0, 0, 0, -1.0, 0.35] + eye[12:],
                     "T_arkitcam_from_face": eye[:11] + [-0.35] + eye[12:],
                     "T_arkitworld_from_arkitcam": eye, "K": [1400.0, 0, 960.5, 0, 1400.0, 720.25, 0, 0, 1.0],
                     "blendshapes": [0.0] * ARKIT_BLENDSHAPES, "T_face_from_eyeL": eye, "T_face_from_eyeR": eye,
                     "look_at": [0.0, 0.0, 1.0], "light": {"ambient": 1000.0, "temp": 6500.0, "sh": [0.0] * 27}})
    (t / "frames.jsonl").write_bytes(b"".join(P.canonical(r) + b"\n" for r in rows))
    (t / "face-verts.f16").write_bytes(bytes(2 * 3 * ARKIT_VERTS * len(rows)))
    base = {"device": "d0", "stream": "d0/tracking.arkit"}
    refs = {}
    for f in ("topology.json", "blendshape-targets.f32"):
        if (t / f).exists():
            (t / f).unlink()
    if embed_template:
        topo = {"topology": "arkit-1220", "vertex_count": ARKIT_VERTS, "triangles": [[0, 1, 2]], "uvs": [],
                "note": "stand-in: a real template holds every triangle and UV of the 1220-vertex topology"}
        (t / "topology.json").write_bytes(P.canonical(topo))
        (t / "blendshape-targets.f32").write_bytes(bytes(4 * 3 * ARKIT_VERTS * ARKIT_BLENDSHAPES))
        refs = {"topology_sha256": P.sha256_hex((t / "topology.json").read_bytes()),
                "targets_sha256": P.sha256_hex((t / "blendshape-targets.f32").read_bytes())}
        meta["devices/d0/tracking.arkit/topology.json"] = {
            "type": "org.prsn.capture.tracking-topology", "media": "application/json", **base}
        meta["devices/d0/tracking.arkit/blendshape-targets.f32"] = {
            "type": "org.prsn.capture.tracking-targets", "media": "application/octet-stream", **base,
            "count": ARKIT_BLENDSHAPES, "vertex_count": ARKIT_VERTS}
    else:
        refs = {"topology_sha256": "0" * 64, "targets_sha256": "0" * 64}
    meta["devices/d0/tracking.arkit/frames.jsonl"] = {
        "type": "org.prsn.capture.tracking", "media": "application/jsonl", **base, **refs}
    meta["devices/d0/tracking.arkit/face-verts.f16"] = {
        "type": "org.prsn.capture.tracking-mesh", "media": "application/octet-stream", **base, **refs}
    # splits: the tracking stream now has rows (two `expr` frames, none held out at offset 2)
    splits = P.parse((root / "splits.json").read_bytes())
    splits["holdout"] = [h for h in splits["holdout"] if h["stream"] != "d0/tracking.arkit"]
    splits["holdout"].append({"stream": "d0/tracking.arkit", "phase": "expr", "frames": []})
    (root / "splits.json").write_bytes(P.canonical(splits))


def build_prsncap() -> None:
    root = ROOT / "examples" / "prsncap" / "minimal-depth.prsncap"
    m = _manifest(root)
    meta = {x["path"]: {a: b for a, b in x.items() if a not in ("path", "sha256", "bytes")} for x in m["entries"]}
    top = {a: b for a, b in m.items() if a not in ("entries", "signature")}
    top["generator"] = "ExampleCapture 1.0"
    add_tracking(root, meta)
    P.seal_package(root, top, meta, SEED, mimetype="application/vnd.prsn.capture+zip")

    out = ROOT / "conformance" / "prsncap"
    out.mkdir(parents=True, exist_ok=True)
    for d in out.glob("*.prsncap"):
        shutil.rmtree(d)
    bad = out / "tracking-template-missing.prsncap"
    shutil.copytree(root, bad)
    meta2 = {k: dict(v) for k, v in meta.items()}
    for k in [k for k in meta2 if k.endswith(("topology.json", "blendshape-targets.f32"))]:
        del meta2[k]
    add_tracking(bad, meta2, embed_template=False)
    P.seal_package(bad, top, meta2, SEED, mimetype="application/vnd.prsn.capture+zip")
    doc = {"version": 1, "spec": "spec/prsncap.md",
           "cases": [{"id": "tracking-template-missing", "rule": "tracking-template", "outcome": "invalid",
                      "why": "face-tracking data without the embedded ARKit face template it references"}]}
    (out / "cases.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# hash and JSON vectors
# --------------------------------------------------------------------------- #

def _dump(path: Path, doc) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=True, indent=1) + "\n", encoding="utf-8")


def _gen(spec):
    if spec["kind"] == "repeat":
        return bytes([spec["byte"]]) * spec["length"]
    m, a = spec["mul"], spec["add"]
    return bytes(((i * m + a) & 0xFF) for i in range(spec["length"]))


def build_hash() -> None:
    h = ROOT / "conformance" / "hash"
    d = json.loads((h / "sha256.json").read_text())
    for v in d["vectors"]:
        data = v["input_utf8"].encode("utf-8") if "input_utf8" in v else _gen(v["generator"])
        v["sha256"] = P.sha256_hex(data)
    _dump(h / "sha256.json", d)

    d = json.loads((h / "action_key.json").read_text())
    for v in d["valid"]:
        v["preimage"] = P.action_key_preimage(v["derivation"]).decode("utf-8")
        v["action_key"] = P.action_key(v["derivation"])
    for v in d["invalid"]:
        try:
            P.action_key(v["derivation"])
        except P.ActionKeyError:
            continue
        raise SystemExit(f"invalid action_key vector {v['name']} is accepted")
    _dump(h / "action_key.json", d)

    d = json.loads((h / "ed25519.json").read_text())
    for v in d["vectors"]:
        seed = bytes.fromhex(v["seed"])
        pub = P.ed25519_public_key(seed)
        v.update(public_key=pub.hex(), public_key_b64=base64.b64encode(pub).decode(), key_id=P.key_id(pub),
                 signature=P.ed25519_sign(seed, bytes.fromhex(v["message"])).hex())
    _dump(h / "ed25519.json", d)

    d = json.loads((h / "manifest.json").read_text())
    seed = bytes.fromhex(d["seed"])
    entries = []
    for f in sorted(d["files"], key=lambda f: f["path"].encode("utf-8")):
        b = f["content"].encode("utf-8")
        x = dict(f["extra"])
        x.update(path=f["path"], type=f["type"], media=f["media"], sha256=P.sha256_hex(b), bytes=len(b))
        entries.append(x)
    m = dict(d["top_level"], entries=entries, signature=P.signature_block(seed))
    body = P.canonical(m)
    d.update(canonical_manifest=body.decode("utf-8"), manifest_sha256=P.sha256_hex(body),
             signature=P.ed25519_sign(seed, body).hex())
    _dump(h / "manifest.json", d)


def build_json() -> None:
    p = ROOT / "conformance" / "json" / "canonical.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    for v in d["valid"]:
        got = P.dumps(P.parse(v["input"].encode("utf-8", "surrogatepass")))
        if got != v["expected"]:
            raise SystemExit(f"canonical vector {v['name']}: expected disagrees with the reference serialiser")
        v["expected_sha256"] = P.sha256_hex(v["expected"].encode("utf-8"))
    _dump(p, d)


def main() -> None:
    build_prsn()
    build_container()
    build_prsncap()
    build_hash()
    build_json()
    print("ok")


if __name__ == "__main__":
    main()
