#!/usr/bin/env python3
"""Regenerates the `.styl` and `.scen` examples and conformance cases.

    python3 core/tools/build_examples.py

Standard library only (plus prsn/tools/prsnfmt.py). Deterministic: fixed key, fixed
timestamps, canonical JSON, deterministic Ed25519. Re-running leaves the tree byte-identical.

Writes:
- styl/examples/harbor-ink/                       an original style, directory form
- scen/examples/north-pier-kitchen/               a real place
- scen/examples/fictional-harbor-set/             a fictional place with authored anchors
- <fmt>/conformance/<case>/ and <fmt>/conformance/rules.json

Media payloads are stubs with the right magic bytes. The signing key is the published
`.prsn` test key (seed = SHA-256 of "prsn-example-signing-key"); never trust it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "prsn" / "tools"))
import prsnfmt as P  # noqa: E402

SEED = hashlib.sha256(b"prsn-example-signing-key").digest()
CREATED = "2026-10-10T18:00:00Z"
GENERATOR = "example-writer 1.0.0"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(24)
HEIC = b"\x00\x00\x00\x18ftypheic" + bytes(20)
GLB = b"glTF\x02\x00\x00\x00" + bytes(56)
APPROVED = {"by": "user", "at": CREATED}


def clean(d: Path) -> None:
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)


def deriv(family: str, recipe: str, inputs: list[dict], models: list[dict] | None = None,
          params: dict | None = None, **extra) -> dict:
    d = {"family": family, "recipe": {"id": recipe, "version": "1.0.0", "rank": 10},
         "tool": {"name": "example-writer", "version": "1.0.0"}, "models": models or [], "inputs": inputs,
         "params": params or {}, "determinism": "seeded-nonbitwise", "supersedes": None,
         "license_constraints": [], **extra}
    d["action_key"] = P.action_key(d)
    return d


def model(key: str, ch: str, role: str, license_: str = "Apache-2.0", dim: int | None = None) -> dict:
    m = {"role": role, "key": key, "sha256": ch * 64, "license": license_}
    if dim:
        m["dim"] = dim
    return m


class Pkg:
    def __init__(self, root: Path, fmt: str, subject_key: str, mimetype: str):
        clean(root)
        self.root, self.meta, self.mimetype = root, {}, mimetype
        self.top = {"format": fmt, "version": 1, "spec": "1.0", "created": CREATED, "generator": GENERATOR,
                    subject_key: f"{'style' if fmt == 'styl' else 'scene'}.json"}

    def put(self, path: str, data: bytes, type_: str, media: str, **fields) -> str:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self.meta[path] = {"type": type_, "media": media, **fields}
        return P.sha256_hex(data)

    def put_json(self, path: str, obj, type_: str, **fields) -> str:
        return self.put(path, P.canonical(obj), type_, "application/json", **fields)

    def seal(self, signed: bool = True) -> None:
        P.seal_package(self.root, self.top, self.meta, SEED if signed else None, mimetype=self.mimetype)


# --------------------------------------------------------------------------- #
# .styl
# --------------------------------------------------------------------------- #

STYLE = {"id": "urn:uuid:5a1e0000-0000-4000-8000-0000000000a1", "display_name": "Harbor Ink", "kind": "original",
         "description": "Loose ink line with flat watercolour washes and a muted harbour palette.",
         "rights": {"holder": "Example Studio", "license": "LicenseRef-example-style"},
         "authors": ["Example Studio"], "influences": [], "consent": {"vendors": ["example-vendor"]},
         "aliases": [], "links": []}
OWN = {"holder": "Example Studio", "license": "LicenseRef-example-style"}


def styl_package(root: Path) -> Pkg:
    k = Pkg(root, "styl", "style", "application/vnd.styl+zip")
    k.top["variants"] = [{"id": "var-day", "label": "Daylight palette", "default": True, "state": {"palette": "day"}},
                         {"id": "var-night", "label": "Night palette", "state": {"palette": "night"}}]
    k.top["budgets"] = {"style.samples": {"count": 64, "bytes": 200000000, "floors": {"per_content_class_min": 3}}}
    k.put_json("style.json", STYLE, "org.styl.style")
    anchor = {"tier": "authored", "how": "example-author-upload", "at": CREATED, "set_by": "user",
              "anchor": True, "lineage": 0}
    ex = {}
    for name, cls, subj in (("e-0001", "person", "a fisherman mending a net"),
                            ("e-0002", "landscape", "the harbour at low tide")):
        ex[name] = k.put(f"style/samples/{name}.png", PNG + name.encode(), "org.styl.style.exemplar", "image/png",
                         origin=dict(anchor), content_class=cls, subject=subj, medium="ink and watercolour",
                         color_space="srgb", rights=OWN, variant="*")
    ex["e-0003"] = k.put("style/samples/e-0003.png", PNG + b"e-0003", "org.styl.style.exemplar", "image/png",
                         origin={"tier": "imported", "how": "example-import", "at": CREATED,
                                 "set_by": "example-writer"},
                         content_class="architecture", subject="a warehouse with a crane", medium="ink",
                         color_space="srgb", rights={"holder": "Example Archive", "license": "CC-BY-4.0"},
                         variant="*")
    gen = model("example-image-editor", "d", "generator")
    ex["e-0004"] = k.put("style/samples/e-0004.png", PNG + b"e-0004", "org.styl.style.exemplar", "image/png",
                         origin={"tier": "authored", "how": "example-guided-generation", "at": CREATED,
                                 "set_by": "user", "synthetic": True, "approved": APPROVED, "lineage": 1,
                                 "admit": {"metric": "csd-csls", "value": 0.64, "threshold": 0.55}},
                         content_class="animal", subject="a gull on a bollard", medium="ink and watercolour",
                         color_space="srgb", rights=OWN, variant="*",
                         derivation=deriv("org.example.method.style-generation", "org.example.recipe.style-gen",
                                          [{"sha256": ex["e-0001"], "role": "anchor"},
                                           {"sha256": ex["e-0002"], "role": "anchor"}], [gen], {"seed": 4}))
    bank = [{"sha256": h, "role": "samples"} for h in ex.values()]
    k.put_json("style/attributes/palette.json",
               {"ink": {"$type": "color", "$value": "#1b2a41"}, "paper": {"$type": "color", "$value": "#f2ead8"},
                "accent": {"$type": "color", "$value": "#c9a227"}, "shadow": {"$type": "color", "$value": "#5c6b73"}},
               "org.styl.style.palette", origin={"tier": "authored", "at": CREATED, "set_by": "user"},
               color_space="srgb", weights={"ink": 0.12, "paper": 0.61, "accent": 0.05, "shadow": 0.22},
               variant="var-day")
    k.put_json("style/attributes/palette-night.json",
               {"ink": {"$type": "color", "$value": "#0d1321"}, "paper": {"$type": "color", "$value": "#3e4a61"},
                "accent": {"$type": "color", "$value": "#f0c75e"}},
               "org.styl.style.palette", origin={"tier": "authored", "at": CREATED, "set_by": "user"},
               color_space="srgb", variant="var-night")
    k.put_json("style/attributes/rendering.json",
               {"medium": "ink and watercolour", "line": {"weight": "medium", "variation": "high", "closure": "open"},
                "shading": "flat washes", "texture": "cold-press paper grain", "lighting": "soft overcast",
                "lens": {"focal_mm": 35, "depth_of_field": "deep"},
                "composition": ["horizon in the upper third", "generous negative space"]},
               "org.styl.style.rendering", origin={"tier": "authored", "at": CREATED, "set_by": "user"}, variant="*")
    k.put("style/attributes/bible.md", b"# Harbor Ink\n\nOpen ink lines; washes never fully fill the line.\n",
          "org.styl.style.bible", "text/markdown", origin={"tier": "authored", "at": CREATED, "set_by": "user"},
          variant="*")
    csd = model("csd-vit-l", "a", "style-embedder", "LicenseRef-see-model-card")
    k.put("style/templates/csd-vit-l.npz", b"PK\x03\x04" + bytes(40), "org.styl.style.template",
          "application/octet-stream", model={"key": "csd-vit-l", "sha256": "a" * 64, "dim": 768,
                                             "license": "LicenseRef-see-model-card"},
          readout="csls", spread={"mean": 0.71, "sd": 0.05, "min": 0.63}, variant="*",
          derivation=deriv("org.example.method.style-embed", "org.example.recipe.style-embed", bank, [csd]))
    k.put_json("style/holdout.json", {"seed": 11, "items": [ex["e-0003"]], "method": "stratified",
                                      "strata": "content_class"},
               "org.styl.style.holdout",
               derivation=deriv("org.dtwin.method.holdout", "org.example.recipe.holdout", bank, params={"seed": 11}))
    vlm = model("example-vlm", "f", "captioner")
    caps = {"convention": "natural", "excludes": ["style"],
            "items": [{"sha256": ex["e-0001"], "text": "a fisherman mending a net on a dock"},
                      {"sha256": ex["e-0002"], "text": "a harbour at low tide with moored boats"},
                      {"sha256": ex["e-0004"], "text": "a gull standing on a bollard"}]}
    caps_sha = k.put_json("style/captions-natural.json", caps, "org.styl.style.captions",
                          derivation=deriv("org.dtwin.method.captions", "org.example.recipe.captions", bank, [vlm],
                                           {"convention": "natural"}))
    refset = {"target": {"key": "gemini-3-pro-image", "slots": {"style": 3}},
              "items": [{"sha256": ex["e-0002"], "slot": "style", "rank": 1},
                        {"sha256": ex["e-0001"], "slot": "style", "rank": 2},
                        {"sha256": ex["e-0004"], "slot": "style", "rank": 3}]}
    refset_sha = k.put_json("style/refset-gemini-3-pro-image.json", refset, "org.styl.style.refset",
                            derivation=deriv("org.dtwin.method.refset", "org.example.recipe.refset", bank,
                                             params={"target": "gemini-3-pro-image"}))
    k.put_json("style/descriptor.json",
               {"state": "*", "text": "Loose ink line drawing with flat watercolour washes on cream paper.",
                "invariants": ["loose open ink line", "flat watercolour washes", "cream paper grain"],
                "avoid": ["gradients", "photorealism", "saturated neon colour"],
                "palette": ["#1b2a41", "#f2ead8", "#c9a227", "#5c6b73"]},
               "org.styl.style.descriptor", origin={"tier": "authored", "at": CREATED, "set_by": "user"})
    train = [ex["e-0001"], ex["e-0002"], ex["e-0004"]]
    k.put_json("style/training/set-lora-v1.json",
               {"samples": train, "captions": caps_sha, "variant": "*",
                "why": "all non-held-out exemplars; one per content class present"},
               "org.styl.style.training-set", origin={"tier": "authored", "at": CREATED, "set_by": "user"},
               variant="*")
    base = model("example-base", "b", "base")
    k.put("style/generation/lora-example-base.safetensors", b"safetensors-stub", "org.styl.image.lora",
          "application/octet-stream", base_model={"key": "example-base", "sha256": "b" * 64}, rank=16,
          strength=0.8, training_samples=train, training_captions=caps_sha, synthetic_capable=True, variant="*",
          derivation=deriv("org.example.method.lora-train", "org.example.recipe.style-lora",
                           [{"sha256": h, "role": "samples"} for h in train] + [{"sha256": caps_sha, "role": "captions"}],
                           [base], {"steps": 1500, "seed": 1},
                           eval={"split": "holdout", "metric": "csd-csls", "value": 0.68}))
    k.put_json("style/generation/adapter-uso.json", {"adapter": {"key": "uso-flux1-dev", "license": "Apache-2.0"},
                                                     "refset": refset_sha, "weights": {"style": 0.8}},
               "org.styl.image.adapter-ref", adapter={"key": "uso-flux1-dev", "license": "Apache-2.0"},
               refset=refset_sha, weights={"style": 0.8}, synthetic_capable=True, variant="*",
               derivation=deriv("org.example.method.adapter-config", "org.example.recipe.adapter",
                                [{"sha256": refset_sha, "role": "refset"}]))
    k.put_json("style/generation/vendor-recraft.json", {"note": "identifier only"}, "org.styl.image.vendor-ref",
               vendor="example-vendor", kind="style_id", value="sty_0001", vendor_model="example-model-4",
               portable=False, created_from=[ex["e-0001"], ex["e-0002"]], synthetic_capable=True, variant="*",
               derivation=deriv("org.example.method.vendor-upload", "org.example.recipe.vendor",
                                [{"sha256": ex["e-0001"], "role": "samples"},
                                 {"sha256": ex["e-0002"], "role": "samples"}]))
    k.put_json("style/generation/prompt-example-engine.json",
               {"engine": {"name": "example-engine", "version": "2"},
                "positive": "loose open ink line, flat watercolour washes, cream paper grain",
                "negative": "gradients, photorealism"},
               "org.styl.image.prompt", engine={"name": "example-engine", "version": "2"}, synthetic_capable=True,
               variant="*", derivation=deriv("org.example.method.prompt", "org.example.recipe.prompt",
                                             [{"sha256": refset_sha, "role": "refset"}]))
    return k


# --------------------------------------------------------------------------- #
# .scen
# --------------------------------------------------------------------------- #

SCENE = {"id": "urn:uuid:5a1e0000-0000-4000-8000-0000000000b1", "display_name": "North Pier kitchen",
         "kind": "real-place", "description": "A narrow galley kitchen with a window over the sink.",
         "location": {"precision": "city", "label": "San Francisco"},
         "rights": {"holder": "Example Owner", "license": "LicenseRef-example-location"},
         "consent": {"vendors": ["example-vendor"], "exact_location": False}, "aliases": [], "links": []}
FICT_SCENE = {"id": "urn:uuid:5a1e0000-0000-4000-8000-0000000000b2", "display_name": "Harbor set, stage 2",
              "kind": "fictional-place", "description": "A stylised harbour quay for an animated series.",
              "location": {"precision": "none"}, "rights": {"holder": "Example Studio",
                                                             "license": "LicenseRef-example-set"},
              "aliases": [], "links": []}


def cam(x: float, yaw: float) -> dict:
    return {"T_scene_from_camera": [[1, 0, 0, x], [0, 1, 0, 1.6], [0, 0, 1, 2.5], [0, 0, 0, 1]],
            "fov_deg": 70, "yaw_deg": yaw, "device": "example-phone"}


def scen_package(root: Path) -> Pkg:
    k = Pkg(root, "scen", "scene", "application/vnd.scen+zip")
    k.top["states"] = [{"id": "st-morning", "label": "Morning, clear", "default": True,
                        "state": {"time_of_day": "morning", "weather": "clear", "dressing": "breakfast"}},
                       {"id": "st-night", "label": "Night, rain", "state": {"time_of_day": "night", "weather": "rain"}}]
    k.top["props"] = [{"id": "kettle", "label": "Copper kettle", "fixed": False}]
    k.top["refs"] = [{"format": "styl", "id": STYLE["id"], "role": "style", "label": "Harbor Ink"},
                     {"format": "prsn", "id": "urn:uuid:5a1e0000-0000-4000-8000-000000000012", "role": "cast",
                      "label": "Mira Example"}]
    k.top["budgets"] = {"place.samples": {"per_state": {"count": 80, "bytes": 400000000},
                                          "floors": {"per_zone_min": 2, "per_viewpoint_bin_min": 1}}}
    k.put_json("scene.json", SCENE, "org.scen.scene")
    enrolled = {"tier": "enrolled", "how": "example-scene-guided-v1", "at": CREATED, "set_by": "example-writer"}
    s = {}
    for name, zone, people, x, yaw, st in (("p-0001", "galley", "none", 0.0, 0.0, "st-morning"),
                                           ("p-0002", "window", "masked", 1.2, 45.0, "st-morning"),
                                           ("p-0003", "galley", "none", -0.8, 180.0, "st-night")):
        extra = {}
        if people == "masked":
            extra["derivation"] = deriv("org.example.method.people-mask", "org.example.recipe.mask",
                                        [{"capture": "sha256:" + "9" * 64, "role": "source"}],
                                        [model("example-segmenter", "5", "segmenter")])
        s[name] = k.put(f"place/samples/{name}.heic", HEIC + name.encode(), "org.scen.place.sample", "image/heic",
                        origin=dict(enrolled), people=people, zone=zone, camera=cam(x, yaw),
                        viewpoint="cam-wide" if name == "p-0001" else None, state=st, **extra)
        if k.meta[f"place/samples/{name}.heic"]["viewpoint"] is None:
            k.meta[f"place/samples/{name}.heic"].pop("viewpoint")
    kettle = k.put("prop/samples/kettle-0001.heic", HEIC + b"kettle", "org.scen.prop.sample", "image/heic",
                   origin=dict(enrolled), prop="kettle", state="*")
    bank = [{"sha256": h, "role": "samples"} for h in s.values()]
    seg = model("example-segmenter", "5", "segmenter")
    fit = [{"sha256": s[n], "role": "samples"} for n in ("p-0001", "p-0002")]   # p-0003 is held out
    splat = k.put("place/geometry/place.glb", GLB + b"splat", "org.scen.place.splat", "model/gltf-binary",
                  sh_degree=3, kernel="ellipse", color_space="srgb-linear", zones=["galley", "window"],
                  frame="scene-canonical", state="*",
                  derivation=deriv("org.example.method.scene-splat", "org.example.recipe.scene-splat", fit, [seg],
                                   {"iterations": 30000, "seed": 3},
                                   eval={"split": "holdout", "metric": "psnr", "value": 29.4}))
    k.put_json("place/geometry/layout.json",
               {"units": "m", "anchor": {"id": "floor-corner-ne", "position": [0, 0, 0]},
                "zones": [{"id": "galley", "polygon": [[0, 0], [3.2, 0], [3.2, 1.4], [0, 1.4]]},
                          {"id": "window", "polygon": [[3.2, 0], [4.0, 0], [4.0, 1.4], [3.2, 1.4]]}],
                "fixtures": [{"id": "sink", "T_scene_from_prop": [[1, 0, 0, 3.5], [0, 1, 0, 0.9], [0, 0, 1, 0.3],
                                                                  [0, 0, 0, 1]]}],
                "signage": [{"id": "calendar", "text": "OCTOBER"}]},
               "org.scen.place.layout", frame="scene-canonical", state="*",
               derivation=deriv("org.example.method.layout", "org.example.recipe.layout",
                                [{"sha256": splat, "role": "geometry"}]))
    k.put_json("place/geometry/cameras.json",
               {"rigs": [{"id": "cam-wide", "label": "Establishing, from the door", **cam(0.0, 0.0)},
                         {"id": "cam-window", "label": "Over the sink", **cam(1.2, 45.0)}]},
               "org.scen.place.cameras", frame="scene-canonical", state="*",
               derivation=deriv("org.example.method.camera-rigs", "org.example.recipe.rigs", bank))
    for st, temp in (("st-morning", 5600), ("st-night", 3000)):
        k.put_json(f"place/attributes/lighting-{st}.json",
                   {"key": {"direction": [0.4, -0.6, -0.7], "kelvin": temp, "source": "window" if temp > 4000
                            else "pendant"}, "fill_ratio": 0.35},
                   "org.scen.place.lighting", origin={"tier": "enrolled", "how": "example-probe", "at": CREATED,
                                                      "set_by": "example-writer"}, state=st)
    k.put("place/attributes/bible.md", b"# North Pier kitchen\n\nThe calendar always reads OCTOBER.\n",
          "org.scen.place.bible", "text/markdown", origin={"tier": "imported", "at": CREATED, "set_by": "user"},
          state="*")
    k.put("place/templates/dinov2-l.npz", b"PK\x03\x04" + bytes(40), "org.scen.place.template",
          "application/octet-stream", model={"key": "dinov2-large", "sha256": "7" * 64, "dim": 1024,
                                             "license": "Apache-2.0"}, state="*",
          derivation=deriv("org.example.method.place-embed", "org.example.recipe.place-embed", bank,
                           [model("dinov2-large", "7", "embedder")]))
    render = k.put("place/training/r-0001.png", PNG + b"render", "org.scen.place.render", "image/png",
                   origin={"tier": "imported", "render": True, "at": CREATED, "set_by": "example-writer"},
                   camera=cam(2.0, 270.0), state="st-morning",
                   derivation=deriv("org.example.method.render", "org.example.recipe.render",
                                    [{"sha256": splat, "role": "geometry"}], params={"yaw": 270}))
    k.put_json("place/holdout.json", {"seed": 5, "items": [s["p-0003"]], "method": "stratified", "strata": "zone"},
               "org.scen.place.holdout",
               derivation=deriv("org.dtwin.method.holdout", "org.example.recipe.holdout", bank, params={"seed": 5}))
    caps = {"convention": "natural", "excludes": ["place"], "trigger": "npk_kitchen",
            "items": [{"sha256": s["p-0001"], "text": "npk_kitchen, wide shot from the doorway, morning light"},
                      {"sha256": s["p-0002"], "text": "npk_kitchen, medium shot toward the window, morning"},
                      {"sha256": render, "text": "npk_kitchen, reverse angle from the window, morning"}]}
    caps_sha = k.put_json("place/captions-natural.json", caps, "org.scen.place.captions",
                          derivation=deriv("org.dtwin.method.captions", "org.example.recipe.captions",
                                           bank + [{"sha256": render, "role": "renders"}],
                                           [model("example-vlm", "f", "captioner")]))
    k.put_json("place/refset-example-editor.json",
               {"target": {"key": "example-image-editor", "slots": {"image": 3}},
                "items": [{"sha256": s["p-0001"], "slot": "image", "rank": 1},
                          {"sha256": s["p-0002"], "slot": "image", "rank": 2},
                          {"sha256": render, "slot": "image", "rank": 3, "render": True}]},
               "org.scen.place.refset",
               derivation=deriv("org.dtwin.method.refset", "org.example.recipe.refset", bank,
                                params={"target": "example-image-editor"}))
    k.put_json("place/descriptor.json",
               {"state": "*", "text": "A narrow galley kitchen, white tile, a window over a steel sink.",
                "invariants": ["white subway tile", "steel sink under the window", "calendar reading OCTOBER"],
                "avoid": ["island counter", "open-plan living room"]},
               "org.scen.place.descriptor",
               origin={"tier": "imported", "confirmed_by": "user", "at": CREATED, "set_by": "example-writer"},
               derivation=deriv("org.dtwin.method.descriptor", "org.example.recipe.descriptor", bank,
                                [model("example-vlm", "f", "describer")]))
    train = [s["p-0001"], s["p-0002"], render]
    k.put("place/generation/lora-example-base.safetensors", b"safetensors-stub", "org.scen.image.lora",
          "application/octet-stream", base_model={"key": "example-base", "sha256": "b" * 64},
          trigger="npk_kitchen", rank=16, training_samples=train, training_captions=caps_sha,
          synthetic_capable=True, frame="scene-canonical", state="*",
          derivation=deriv("org.example.method.lora-train", "org.example.recipe.place-lora",
                           [{"sha256": h, "role": "samples"} for h in train] + [{"sha256": caps_sha, "role": "captions"}],
                           [model("example-base", "b", "base")], {"steps": 2000, "seed": 1},
                           eval={"split": "holdout", "metric": "dino-cos", "value": 0.81}))
    k.put_json("place/generation/vendor-world.json", {"note": "identifier only"}, "org.scen.image.vendor-ref",
               vendor="example-vendor", kind="world_id", value="wld_0001", portable=False,
               created_from=[s["p-0001"], s["p-0002"]], synthetic_capable=True, frame="scene-canonical", state="*",
               derivation=deriv("org.example.method.vendor-upload", "org.example.recipe.vendor",
                                [{"sha256": s["p-0001"], "role": "samples"},
                                 {"sha256": s["p-0002"], "role": "samples"}]))
    _ = kettle
    return k


def fictional_scen_package(root: Path) -> Pkg:
    k = Pkg(root, "scen", "scene", "application/vnd.scen+zip")
    k.top["states"] = [{"id": "st-dusk", "label": "Dusk", "default": True, "state": {"time_of_day": "dusk"}}]
    k.put_json("scene.json", FICT_SCENE, "org.scen.scene")
    concept = k.put("place/samples/c-0001.png", PNG + b"concept", "org.scen.place.sample", "image/png",
                    origin={"tier": "authored", "how": "example-concept-art", "at": CREATED, "set_by": "user",
                            "anchor": True, "lineage": 0}, people="none", zone="quay", state="st-dusk")
    k.put("place/samples/c-0002.png", PNG + b"view", "org.scen.place.sample", "image/png",
          origin={"tier": "authored", "how": "example-guided-generation", "at": CREATED, "set_by": "user",
                  "synthetic": True, "approved": APPROVED, "lineage": 1,
                  "admit": {"metric": "dino-cos", "value": 0.77, "threshold": 0.7}},
          people="none", zone="quay", state="st-dusk",
          derivation=deriv("org.example.method.view-generation", "org.example.recipe.view-gen",
                           [{"sha256": concept, "role": "anchor"}], [model("example-image-editor", "d", "generator")]))
    k.put("place/geometry/set.glb", GLB + b"set", "org.scen.place.mesh", "model/gltf-binary", zones=["quay"],
          frame="scene-canonical", state="*",
          origin={"tier": "authored", "how": "example-modelled-set", "at": CREATED, "set_by": "user"})
    return k


# --------------------------------------------------------------------------- #
# conformance
# --------------------------------------------------------------------------- #

def cases_for(fmt: str, valid: list[tuple[str, str, callable]], cases: list[tuple]) -> None:
    for vid, path, build in valid:
        build(REPO / fmt / path).seal()
    out = REPO / fmt / "conformance"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    rows = []
    for cid, rule, outcome, why, build, pre, signed in cases:
        k = build(out / cid)
        if pre:
            pre(k)
        k.seal(signed=signed)
        rows.append({"id": cid, "rule": rule, "outcome": outcome, "why": why})
    doc = {"version": 1, "spec": f"spec/{fmt}.md (draft 1.0)",
           "outcomes": {"refuse": "a reader MUST refuse to load the file",
                        "invalid": "a validator MUST report `rule`; the file breaks exactly that rule",
                        "valid": "the file is valid; `why` says what a reader must do with it"},
           "valid": [{"id": vid, "path": path, "spec": "1.0"} for vid, path, _ in valid], "cases": rows}
    (out / "rules.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def m(k: Pkg, path: str) -> dict:
    return k.meta[path]


def edit_json(k: Pkg, path: str, fn) -> None:
    p = k.root / path
    doc = P.parse(p.read_bytes())
    fn(doc)
    p.write_bytes(P.canonical(doc))


def dangling_caption(k: Pkg) -> None:
    edit_json(k, "style/captions-natural.json", lambda d: d["items"][0].update(sha256="0" * 64))
    new = P.sha256_hex((k.root / "style/captions-natural.json").read_bytes())
    m(k, "style/generation/lora-example-base.safetensors")["training_captions"] = new


def main() -> None:
    S = styl_package
    cases_for("styl", [("harbor-ink", "examples/harbor-ink", S)], [
        ("version-too-new", "version", "refuse", "manifest.version is 2", S, lambda k: k.top.update(version=2), True),
        ("critical-unknown-type", "critical", "refuse", "a critical entry of an unknown type", S,
         lambda k: k.put("style/generation/vendor.bin", b"x", "com.vendor.style.thing", "application/octet-stream",
                         critical=True, synthetic_capable=True, variant="*",
                         derivation=deriv("org.example.method.x", "org.example.recipe.x", [])), True),
        ("exemplar-missing-content-class", "type-fields", "invalid", "an exemplar without `content_class`", S,
         lambda k: m(k, "style/samples/e-0003.png").pop("content_class"), True),
        ("exemplar-missing-rights", "type-fields", "invalid", "an exemplar without `rights`", S,
         lambda k: m(k, "style/samples/e-0003.png").pop("rights"), True),
        ("variant-not-declared", "states", "invalid", "an entry whose `variant` is not in manifest.variants", S,
         lambda k: m(k, "style/attributes/palette.json").update(variant="var-dawn"), True),
        ("frame-on-style-entry", "spec-fields", "invalid", "a `.styl` entry with a `frame` (no spatial modality)", S,
         lambda k: m(k, "style/templates/csd-vit-l.npz").update(frame="head-canonical"), True),
        ("template-without-derivation", "spec-fields", "invalid", "a template without `derivation`", S,
         lambda k: m(k, "style/templates/csd-vit-l.npz").pop("derivation"), True),
        ("synthetic-imported-exemplar", "generation", "invalid",
         "a generated exemplar whose tier is `imported`, not `authored`", S,
         lambda k: m(k, "style/samples/e-0003.png")["origin"].update(synthetic=True), True),
        ("captions-describe-unknown-sample", "index", "invalid", "a caption naming a hash the file does not hold", S,
         dangling_caption, True),
        ("vendor-ref-without-samples", "type-fields", "invalid",
         "a vendor reference whose `created_from` names no sample of the file", S,
         lambda k: m(k, "style/generation/vendor-recraft.json").update(created_from=["0" * 64]), True),
        ("lineage-mismatch", "authored", "invalid",
         "an exemplar generated from lineage-0 anchors that claims lineage 2", S,
         lambda k: m(k, "style/samples/e-0004.png")["origin"].update(lineage=2), True),
        ("render-outside-scen", "authored", "invalid", "`origin.render` in a .styl (renders are .scen only)", S,
         lambda k: m(k, "style/training/set-lora-v1.json")["origin"].update(render=True), True),
        ("unsigned", None, "valid", "no signature block: valid, top tiers including `authored` are not vouched for",
         S, None, False),
    ])
    R, Fp = scen_package, fictional_scen_package
    cases_for("scen", [("north-pier-kitchen", "examples/north-pier-kitchen", R),
                       ("fictional-harbor-set", "examples/fictional-harbor-set", Fp)], [
        ("people-present", "people", "invalid", "a place sample with identifiable people left in (`people: present`)",
         R, lambda k: m(k, "place/samples/p-0001.heic").update(people="present"), True),
        ("prop-not-declared", "props", "invalid", "a prop entry naming a prop not in manifest.props", R,
         lambda k: m(k, "prop/samples/kettle-0001.heic").update(prop="teapot"), True),
        ("exact-location-without-consent", "location", "invalid",
         "coordinates in scene.json without `precision: exact` and consent", R,
         lambda k: k.put_json("scene.json", {**SCENE, "location": {"precision": "city", "lat": 37.8, "lon": -122.4}},
                              "org.scen.scene"), True),
        ("authored-on-real-place", "authored", "invalid", "authored material in a real place's file", R,
         lambda k: m(k, "place/samples/p-0001.heic").update(origin={"tier": "authored", "at": CREATED,
                                                                     "set_by": "user"}), True),
        ("render-in-samples", "authored", "invalid", "a render of geometry placed in samples/", R,
         lambda k: m(k, "place/samples/p-0003.heic")["origin"].update(render=True), True),
        ("lighting-for-every-state", "type-fields", "invalid", "a lighting record with `state: \"*\"`", R,
         lambda k: m(k, "place/attributes/lighting-st-night.json").update(state="*"), True),
        ("geometry-missing-frame", "spec-fields", "invalid", "place geometry without `frame`", R,
         lambda k: m(k, "place/geometry/place.glb").pop("frame"), True),
        ("state-not-declared", "states", "invalid", "a sample whose `state` is not in manifest.states", R,
         lambda k: m(k, "place/samples/p-0001.heic").update(state="st-noon"), True),
        ("exact-precision-without-consent", "location", "invalid",
         "`precision: exact` in scene.json without consent.exact_location", R,
         lambda k: k.put_json("scene.json", {**SCENE, "location": {"precision": "exact", "label": "x"}},
                              "org.scen.scene"), True),
        ("zone-not-in-layout", "type-fields", "invalid", "a sample naming a zone the layout does not define", R,
         lambda k: m(k, "place/samples/p-0001.heic").update(zone="pantry"), True),
        ("masked-without-derivation", "people", "invalid", "`people: masked` with no derivation naming the method", R,
         lambda k: m(k, "place/samples/p-0002.heic").pop("derivation"), True),
        ("fictional-without-anchor", "authored", "invalid",
         "a fictional place with an authored synthetic view and no anchor", Fp,
         lambda k: m(k, "place/samples/c-0001.png")["origin"].pop("anchor"), True),
    ])
    print("ok")


if __name__ == "__main__":
    main()
