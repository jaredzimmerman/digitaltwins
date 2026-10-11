"""Cross-entry checks shared by every digitaltwins validator (core.md §4 to §6).

Schema rules are per entry; these need the whole manifest. Each function reports through
`err(rule, message)`. Used by `prsn/tools/validate.py` and `core/tools/validate.py`.
"""

from __future__ import annotations

INDEX_KINDS = {"captions": "captions.schema.json", "refset": "refset.schema.json",
               "descriptor": "descriptor.schema.json", "holdout": "holdout.schema.json"}


def _origin(e: dict) -> dict:
    o = e.get("origin")
    return o if isinstance(o, dict) else {}


def _role(e: dict) -> str:
    parts = str(e.get("path", "")).split("/")
    return parts[1] if len(parts) > 2 else ""


def _kind(e: dict) -> str:
    return str(e.get("type", "")).rsplit(".", 1)[-1]


def check_authored(entries: list[dict], allowed: bool, render_allowed: bool, err) -> None:
    """§4.1 authored only where allowed; §4.3 a file with authored material keeps an anchor, and
    lineage is 1 + the highest lineage among the authored samples a derivation used; §4.4
    renders only in .scen."""
    tier = lambda e: _origin(e).get("was") or _origin(e).get("tier")  # noqa: E731
    authored = [e for e in entries if tier(e) == "authored"]
    if authored and not allowed:
        for e in authored:
            err("authored", f"{e.get('path')}: tier `authored` is not valid for this subject")
        return
    if authored and not any(_origin(e).get("anchor") is True for e in authored):
        err("authored", "the file holds authored material but no anchor (origin.anchor: true)")
    by_sha = {e.get("sha256"): e for e in entries}
    for e in authored:
        lin = _origin(e).get("lineage")
        if not isinstance(lin, int) or lin == 0:
            continue
        ins = [by_sha.get(i.get("sha256")) for i in (e.get("derivation") or {}).get("inputs") or []
               if isinstance(i, dict)]
        parents = [_origin(x).get("lineage") for x in ins if x and isinstance(_origin(x).get("lineage"), int)]
        if not parents:
            err("authored", f"{e.get('path')}: lineage {lin} but its derivation names no authored sample of this file")
        elif lin != 1 + max(parents):
            err("authored", f"{e.get('path')}: lineage {lin}, expected {1 + max(parents)} from its inputs")
    if not render_allowed:
        for e in entries:
            if _origin(e).get("render") is True:
                err("authored", f"{e.get('path')}: `origin.render` is only valid in a .scen")


def check_index(entries: list[dict], files: dict[str, bytes], parse, schema_errors, core_base: str,
                render_refset: bool, err) -> None:
    """§5: index payloads match their schemas; every hash resolves; refset slots exist;
    anchors are never held out; held-out samples feed no caption, reference set, training
    set or generator."""
    by_sha = {e.get("sha256"): e for e in entries}
    payloads: dict[str, dict] = {}
    for e in entries:
        kind = _kind(e)
        if kind not in INDEX_KINDS or e.get("path") not in files:
            continue
        try:
            payload = parse(files[e["path"]])
        except Exception as ex:  # strict parser error
            err("index", f"{e['path']}: not JSON: {ex}")
            continue
        for x in schema_errors(core_base + INDEX_KINDS[kind], payload):
            err("index", f"{e['path']}: {x}")
        if not isinstance(payload, dict):
            continue
        payloads[e["path"]] = payload
        roles = ("samples",) if kind in ("refset", "holdout") else ("samples", "training")
        slots = set(((payload.get("target") or {}).get("slots") or {}))
        for it in payload.get("items") or []:
            h = it if isinstance(it, str) else (it or {}).get("sha256")
            tgt = by_sha.get(h)
            render = kind == "refset" and render_refset and isinstance(it, dict) and it.get("render") is True
            ok_roles = roles + (("training",) if render else ())
            if tgt is None:
                err("index", f"{e['path']}: item {str(h)[:12]}… does not resolve to an entry of this file")
            elif _role(tgt) not in ok_roles:
                err("index", f"{e['path']}: item {tgt['path']} is not under {'/'.join(ok_roles)}")
            elif kind == "holdout" and _origin(tgt).get("anchor") is True:
                err("index", f"{e['path']}: anchor {tgt['path']} is held out; anchors never are")
            if kind == "refset" and isinstance(it, dict) and it.get("slot") not in slots:
                err("index", f"{e['path']}: slot {it.get('slot')!r} is not one of target.slots")

    held = set()
    for e in entries:
        if _kind(e) == "holdout":
            held |= set((payloads.get(e.get("path")) or {}).get("items") or [])
    if not held:
        return
    for e in entries:
        p = e.get("path")
        pay = payloads.get(p) or {}
        if _kind(e) in ("captions", "refset"):
            for it in pay.get("items") or []:
                if isinstance(it, dict) and it.get("sha256") in held:
                    err("index", f"{p}: names held-out sample {it['sha256'][:12]}…")
        used = set(e.get("training_samples") or [])
        if _role(e) == "generation":
            used |= {i.get("sha256") for i in (e.get("derivation") or {}).get("inputs") or [] if isinstance(i, dict)}
        if used & held:
            err("index", f"{p}: trains on or generates from held-out sample(s)")


def check_references(entries: list[dict], subject: dict, err) -> None:
    """§6: vendor references name samples of this file and a consented vendor; adapter
    references name a reference set; adapters name their captions and training samples."""
    by_sha = {e.get("sha256"): e for e in entries}
    vendors = set(((subject or {}).get("consent") or {}).get("vendors") or [])
    for e in entries:
        p, t = e.get("path"), str(e.get("type", ""))
        if t.endswith(".image.vendor-ref"):
            for h in e.get("created_from") or []:
                if _role(by_sha.get(h) or {}) != "samples":
                    err("type-fields", f"{p}: created_from {str(h)[:12]}… is not a sample of this file")
            if e.get("vendor") not in vendors:
                err("consent", f"{p}: vendor {e.get('vendor')!r} is not in the subject record's consent.vendors")
        if t.endswith(".image.adapter-ref") and _kind(by_sha.get(e.get("refset")) or {}) != "refset":
            err("type-fields", f"{p}: refset does not name a reference-set record of this file")
        if "training_captions" in e and _kind(by_sha.get(e["training_captions"]) or {}) != "captions":
            err("type-fields", f"{p}: training_captions does not name a captions record of this file")
        for h in e.get("training_samples") or []:
            if _role(by_sha.get(h) or {}) not in ("samples", "training"):
                err("type-fields", f"{p}: training sample {str(h)[:12]}… is not a sample or training entry")
