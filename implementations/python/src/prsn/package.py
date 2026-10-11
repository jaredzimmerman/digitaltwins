# Copyright 2026 Jared Zimmerman
# SPDX-License-Identifier: Apache-2.0
"""The ``.prsn`` container: ZIP / directory packages, manifest integrity,
Ed25519 manifest signatures, provenance tier downgrade, and the writer.

A package is opened with :func:`open_package`, which parses the container,
strict-parses ``manifest.json``, checks the header, verifies every entry's
presence/size/SHA-256, verifies the detached Ed25519 signature when one is
present, and applies the provenance tier downgrade when the signer is not
trusted. Anything that must refuse the file raises :class:`PrsnError` carrying
the spec rule id (``container``, ``version``, ``manifest-hash``, ``signature``
or ``critical``).
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from . import keys
from .canonical import JSONError, canonical, parse

MIMETYPE_CURRENT = b"application/vnd.prsn+zip"
MIMETYPE_LEGACY = b"application/vnd.museli.prsn+zip"  # Appendix A
SIGNATURE_PATH_DEFAULT = "signatures/manifest.sig"
FORMAT_VERSION_MAX = 1  # this reader's supported manifest.version
RETIRED_TOP_LEVEL_KEYS = ("scopes",)
TOP_TIERS = ("enrolled", "professional")
_TOP_TIER_SET = frozenset(TOP_TIERS)
LEGACY_TYPE_PREFIX = "org.museli."

#: Record types defined by spec/prsn.md and spec/voice.md. ``critical`` is
#: judged against this list (after the legacy ``org.museli.*`` mapping).
KNOWN_TYPES = frozenset(
    {
        "org.prsn.person",
        "org.prsn.face.capture-ref",
        "org.prsn.face.sample",
        "org.prsn.face.mesh",
        "org.prsn.face.landmarks",
        "org.prsn.face.params",
        "org.prsn.face.blendshapes",
        "org.prsn.face.expression-track",
        "org.prsn.face.expression-map",
        "org.prsn.face.splat",
        "org.prsn.face.coverage",
        "org.prsn.face.expression-clip",
        "org.prsn.face.avatar",
        "org.prsn.face.template",
        "org.prsn.image.lora",
        "org.prsn.image.embedding",
        "org.prsn.image.faceid",
        "org.prsn.avatar.vrm",
        "org.prsn.body.params",
        "org.prsn.body.mesh",
        "org.prsn.voice.template",
        "org.prsn.voice.sample",
        "org.prsn.voice.sample-index",
        "org.prsn.voice.training",
        "org.prsn.voice.training-set",
        "org.prsn.voice.seed",
        "org.prsn.voice.prompt",
        "org.prsn.voice.generation",
        "org.prsn.voice.lora",
        "org.prsn.voice.rvc",
        "org.prsn.voice.piper",
    }
)

_SPEC_RE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")


class PrsnError(Exception):
    """A refused file. ``rule`` is the spec conformance rule id."""

    def __init__(self, rule: str, message: str):
        super().__init__(f"[{rule}] {message}")
        self.rule = rule
        self.message = message


@dataclass
class Issue:
    """One finding from semantic validation: an ``error`` (rule broken) or a
    ``note`` (something the reader must notice or did on load)."""

    severity: str  # "error" | "note"
    rule: str | None
    message: str


@dataclass
class SignatureInfo:
    present: bool
    verified: bool
    path: str | None = None
    public_key: bytes | None = None
    key_id: str | None = None
    note: str | None = None


def canonical_type(t: str) -> str:
    """Map a legacy ``org.museli.*`` type name to ``org.prsn.*``."""
    if t.startswith(LEGACY_TYPE_PREFIX):
        return "org.prsn." + t[len(LEGACY_TYPE_PREFIX) :]
    return t


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# container reading
# --------------------------------------------------------------------------- #


def _local_extra_len(zip_bytes: bytes, header_offset: int) -> int:
    """Extra-field length from the ZIP *local* file header."""
    if zip_bytes[header_offset : header_offset + 4] != b"PK\x03\x04":
        raise PrsnError("container", "bad ZIP local file header")
    return int.from_bytes(zip_bytes[header_offset + 28 : header_offset + 30], "little")


def _read_zip(path: Path) -> tuple[dict[str, bytes], bool]:
    raw = path.read_bytes()
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        raise PrsnError("container", f"not a ZIP file: {e}") from None
    with zf as z:
        infos = z.infolist()
        if not infos or infos[0].filename != "mimetype":
            raise PrsnError("container", "the first ZIP member must be `mimetype`")
        first = infos[0]
        if first.compress_type != zipfile.ZIP_STORED:
            raise PrsnError("container", "`mimetype` must be STORED")
        if _local_extra_len(raw, first.header_offset) != 0:
            raise PrsnError("container", "`mimetype` must have no extra field")
        names = [i.filename for i in infos]
        if len(set(names)) != len(names):
            raise PrsnError("container", "a ZIP member name appears more than once")
        files: dict[str, bytes] = {}
        for info in infos:
            if info.filename.endswith("/"):
                continue
            files[info.filename] = z.read(info.filename)
    mt = files.get("mimetype")
    if mt not in (MIMETYPE_CURRENT, MIMETYPE_LEGACY):
        raise PrsnError("container", f"mimetype is not a .prsn media type: {mt!r}")
    return files, mt == MIMETYPE_LEGACY


def _read_dir(path: Path) -> tuple[dict[str, bytes], bool]:
    files: dict[str, bytes] = {}
    for p in sorted(path.rglob("*")):
        if p.is_file():
            files[p.relative_to(path).as_posix()] = p.read_bytes()
    mt = files.get("mimetype")
    if mt is not None and mt not in (MIMETYPE_CURRENT, MIMETYPE_LEGACY):
        raise PrsnError("container", f"mimetype is not a .prsn media type: {mt!r}")
    return files, mt == MIMETYPE_LEGACY


# --------------------------------------------------------------------------- #
# manifest loading and integrity
# --------------------------------------------------------------------------- #


def _parse_manifest(files: dict[str, bytes]) -> tuple[dict, bytes]:
    raw = files.get("manifest.json")
    if raw is None:
        raise PrsnError("version", "no manifest.json")
    try:
        m = parse(raw)
    except JSONError as e:
        raise PrsnError("version", f"manifest.json is not strict JSON: {e}") from None
    if not isinstance(m, dict):
        raise PrsnError("version", "manifest.json is not an object")
    if m.get("format") != "prsn":
        raise PrsnError("version", f"manifest.format is {m.get('format')!r}, not \"prsn\"")
    version = m.get("version")
    if type(version) is not int or version < 1:
        raise PrsnError("version", f"manifest.version must be an integer >= 1, got {version!r}")
    spec = m.get("spec")
    if spec is not None and (not isinstance(spec, str) or not _SPEC_RE.match(spec)):
        raise PrsnError("version", f"manifest.spec must be \"<major>.<minor>\", got {spec!r}")
    if version > FORMAT_VERSION_MAX:
        raise PrsnError(
            "version",
            f"manifest.version {version} is newer than this reader ({FORMAT_VERSION_MAX})",
        )
    entries = m.get("entries")
    if not isinstance(entries, list):
        raise PrsnError("version", "manifest.entries must be an array")
    return m, raw


def _check_entry_hashes(m: dict, files: dict[str, bytes]) -> None:
    for e in m.get("entries") or []:
        if not isinstance(e, dict) or not isinstance(e.get("path"), str):
            raise PrsnError("manifest-hash", f"malformed manifest entry: {e!r}")
        p = e["path"]
        data = files.get(p)
        if data is None:
            raise PrsnError("manifest-hash", f"{p} is listed but not in the package")
        if len(data) != e.get("bytes") or sha256_hex(data) != e.get("sha256"):
            raise PrsnError("manifest-hash", f"{p}: size or SHA-256 does not match the manifest")


def _check_signature(m: dict, files: dict[str, bytes]) -> SignatureInfo:
    block = m.get("signature")
    if not block:
        return SignatureInfo(present=False, verified=False)
    if not isinstance(block, dict):
        raise PrsnError("signature", "manifest.signature must be an object")
    path = block.get("path", SIGNATURE_PATH_DEFAULT)
    sig = files.get(path)
    if sig is None:
        raise PrsnError("signature", f"the manifest names {path} but the package does not carry it")
    if len(sig) != keys.SIGNATURE_BYTES:
        raise PrsnError("signature", f"{path} must hold 64 raw signature bytes")
    try:
        pub = base64.b64decode(block.get("public_key", ""), validate=True)
    except (binascii.Error, ValueError):
        raise PrsnError("signature", "signature.public_key is not valid base64")
    if len(pub) != keys.PUBLIC_KEY_BYTES:
        raise PrsnError("signature", "signature.public_key must decode to 32 bytes")
    if keys.key_id(pub) != block.get("key_id"):
        raise PrsnError(
            "signature", "signature.key_id is not the first 16 hex digits of SHA-256(public_key)"
        )
    if block.get("alg") != "Ed25519":
        return SignatureInfo(
            present=True,
            verified=False,
            path=path,
            public_key=pub,
            key_id=block.get("key_id"),
            note=f"signature algorithm {block.get('alg')!r} is present but unverified",
        )
    if not keys.verify(pub, canonical(m), sig):
        raise PrsnError("signature", "Ed25519 signature does not verify over the canonical manifest")
    return SignatureInfo(
        present=True, verified=True, path=path, public_key=pub, key_id=block.get("key_id")
    )


def _check_critical(m: dict) -> None:
    for e in m.get("entries") or []:
        if not isinstance(e, dict):
            continue
        t = canonical_type(str(e.get("type", "")))
        if t not in KNOWN_TYPES and e.get("critical") is True:
            raise PrsnError(
                "critical",
                f"{e.get('path')}: critical entry of unknown type {e.get('type')}: refusing the file",
            )


# --------------------------------------------------------------------------- #
# provenance tiers and person.json
# --------------------------------------------------------------------------- #


def apply_tier_downgrade(entries: list[dict], trusted: bool) -> list[dict]:
    """Downgrade ``enrolled``/``professional`` origins to ``imported`` (keeping
    the claimed tier as ``origin.was``) and move a template's ``evidence``
    seconds for those tiers into ``imported`` (sum rounded to 0.1), for a file
    whose signer is not trusted. Trusted files are returned unchanged.

    Returns a deep copy; the input is never mutated.
    """
    out = copy.deepcopy(entries)
    if trusted:
        return out
    for e in out:
        if not isinstance(e, dict):
            continue
        origin = e.get("origin")
        if isinstance(origin, dict) and origin.get("tier") in _TOP_TIER_SET:
            e["origin"] = {**origin, "tier": "imported", "was": origin["tier"]}
        evidence = e.get("evidence")
        if isinstance(evidence, dict) and _TOP_TIER_SET & set(evidence):
            moved = sum(evidence.pop(t) for t in sorted(_TOP_TIER_SET & set(evidence)))
            evidence["imported"] = round(evidence.get("imported", 0.0) + moved, 1)
    return out


def map_legacy_person(p: dict) -> dict:
    """Map a pre-1.1 ``person.json`` shape to the current one (spec/prsn.md)."""
    out = dict(p)
    if "display_name" not in out and isinstance(out.get("name"), str):
        out["display_name"] = out.pop("name")
    if isinstance(out.get("ids"), dict):
        out["ids"] = [{"scheme": k, "value": str(v)} for k, v in out["ids"].items()]
    if isinstance(out.get("links"), dict):
        out["links"] = [{"rel": k, "href": str(v)} for k, v in out["links"].items()]
    return out


def key_trusted(signature: SignatureInfo, trusted_keys) -> bool:
    """Whether a verified signature's key is in ``trusted_keys``.

    Each trusted entry may be a ``key_id`` (16 hex chars), a standard-base64
    32-byte public key, or a 64-char hex public key.
    """
    if not signature.verified or signature.public_key is None:
        return False
    for t in trusted_keys or []:
        t = str(t).strip()
        if t == signature.key_id:
            return True
        try:
            if base64.b64decode(t, validate=True) == signature.public_key:
                return True
        except (binascii.Error, ValueError):
            pass
        if len(t) == 64:
            try:
                if bytes.fromhex(t) == signature.public_key:
                    return True
            except ValueError:
                pass
    return False


# --------------------------------------------------------------------------- #
# the opened package
# --------------------------------------------------------------------------- #


@dataclass
class Package:
    """An opened ``.prsn`` package (ZIP or directory)."""

    source: Path
    is_zip: bool
    files: dict[str, bytes]
    manifest: dict  # post-load view: scopes dropped, expired dropped, tiers downgraded
    signature: SignatureInfo
    trusted: bool
    downgraded: list[str] = field(default_factory=list)
    legacy_mimetype: bool = False
    notes: list[Issue] = field(default_factory=list)
    _original: dict = field(default_factory=dict, repr=False)  # manifest as parsed

    def verify_integrity(self) -> SignatureInfo:
        """Re-run the integrity checks: every listed entry present with
        matching size and SHA-256, the signature block valid, no unknown
        critical entries. Raises :class:`PrsnError` on failure."""
        _check_entry_hashes(self._original, self.files)
        sig = _check_signature(self._original, self.files)
        _check_critical(self._original)
        return sig

    def validate(self) -> list[Issue]:
        """Semantic validation: the spec rule table as ``Issue``\\ s."""
        from .validate import validate_package

        return validate_package(self)

    def list_entries(self) -> list[dict]:
        """The manifest's entries (post-load view), as copies."""
        return [copy.deepcopy(e) for e in self.manifest.get("entries", [])]

    def read_entry_bytes(self, path: str) -> bytes:
        """Raw bytes of a listed entry. Unlisted members are not part of the
        file and cannot be read."""
        listed = {e.get("path") for e in self.manifest.get("entries", [])}
        if path not in listed:
            raise PrsnError("entry", f"{path!r} is not a listed entry")
        data = self.files.get(path)
        if data is None:  # cannot happen after verify_integrity
            raise PrsnError("manifest-hash", f"{path} is listed but not in the package")
        return data

    def manifest_canonical_sha256(self) -> str:
        """SHA-256 of the canonical bytes of the manifest as parsed (the
        package's identity)."""
        return sha256_hex(canonical(self._original))


def open_package(path: str | Path, trusted_keys=None) -> Package:
    """Open a ``.prsn`` package: a ``.prsn`` ZIP file or a directory package.

    Parses the container, strict-parses ``manifest.json``, checks the header,
    verifies every entry's presence/size/SHA-256 and the manifest signature,
    then applies the load-time transforms (retired keys dropped, expired
    entries dropped, provenance tier downgrade for untrusted signers).

    Raises :class:`PrsnError` (with a spec ``rule``) on anything the format
    says a reader must refuse.
    """
    src = Path(path)
    if src.is_dir():
        files, legacy = _read_dir(src)
        is_zip = False
    else:
        files, legacy = _read_zip(src)
        is_zip = True

    m, raw = _parse_manifest(files)

    # Integrity, in order: hashes, signature, critical. The signature is over
    # the canonical bytes of the manifest as parsed, before load transforms.
    _check_entry_hashes(m, files)
    signature = _check_signature(m, files)
    _check_critical(m)
    trusted = key_trusted(signature, trusted_keys)

    notes: list[Issue] = []
    if legacy:
        notes.append(Issue("note", None, "legacy v1 mimetype (accepted)"))
    if raw != canonical(m):
        notes.append(
            Issue(
                "note",
                None,
                "manifest.json is not stored in canonical form "
                "(identity is still its canonical hash)",
            )
        )
    if not signature.present:
        notes.append(Issue("note", None, "unsigned: integrity unproven; top tiers are not vouched for"))
    elif signature.note:
        notes.append(Issue("note", None, signature.note))

    view = copy.deepcopy(m)
    for k in RETIRED_TOP_LEVEL_KEYS:
        if k in view:
            del view[k]
            notes.append(Issue("note", None, f"top-level `{k}` is retired: dropped on load"))
    today = date.today().isoformat()
    kept = []
    for e in view.get("entries", []):
        exp = e.get("expires") if isinstance(e, dict) else None
        if exp and str(exp) < today:
            notes.append(
                Issue("note", None, f"{e.get('path')}: expired {exp}; dropped on load, not written again")
            )
        else:
            kept.append(e)
    view["entries"] = kept

    before = {(e.get("path"), str(e.get("origin", {}).get("tier"))) for e in kept if isinstance(e, dict)}
    view["entries"] = apply_tier_downgrade(kept, trusted)
    downgraded = sorted(
        {
            e.get("path")
            for e in view["entries"]
            if isinstance(e, dict)
            and (e.get("path"), str(e.get("origin", {}).get("tier"))) not in before
            and isinstance(e.get("origin"), dict)
            and e["origin"].get("was") in _TOP_TIER_SET
        }
    )
    if downgraded:
        notes.append(
            Issue(
                "note",
                None,
                f"tier downgrade applied to {len(downgraded)} "
                f"{'entry' if len(downgraded) == 1 else 'entries'} "
                f"({', '.join(downgraded)}): signer not trusted",
            )
        )

    return Package(
        source=src,
        is_zip=is_zip,
        files=files,
        manifest=view,
        signature=signature,
        trusted=trusted,
        downgraded=downgraded,
        legacy_mimetype=legacy,
        notes=notes,
        _original=m,
    )


# --------------------------------------------------------------------------- #
# writer
# --------------------------------------------------------------------------- #


def _stored_media(media: str) -> bool:
    """Already-compressed payloads are STORED; JSON/PLY/binary arrays DEFLATE."""
    return media.startswith(("audio/", "image/", "video/")) or media in (
        "application/zip",
        "application/vnd.cbeff.bir",
    )


def _zip_info(name: str, stored: bool) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    zi.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    zi.create_system = 3
    zi.extra = b""
    return zi


class Builder:
    """Assemble a new ``.prsn`` package: add entries, then write a ZIP with a
    canonical ``manifest.json`` and an optional Ed25519 signature."""

    def __init__(
        self,
        *,
        generator: str = "prsn-py 0.1.0",
        created: str | None = None,
        spec: str = "1.1",
        person_path: str = "person.json",
    ):
        self.generator = generator
        self.created = created or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.spec = spec
        self.person_path = person_path
        self._person: dict | None = None
        self._entries: dict[str, tuple[bytes, str, str, dict]] = {}
        self._top_extra: dict = {}

    def set_person(self, person: dict) -> None:
        """Set the ``person.json`` payload (written in canonical form)."""
        if not isinstance(person, dict):
            raise PrsnError("person", "person.json payload must be an object")
        self._person = person

    def set_top_field(self, name: str, value) -> None:
        """Set an extra top-level manifest field (kept as given)."""
        self._top_extra[name] = value

    def add_entry(self, path: str, type: str, media: str, data: bytes, **fields) -> None:
        """Add one entry. ``fields`` are the entry's extra manifest fields
        (``origin``, ``derivation``, ``look``, ...)."""
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("entry data must be bytes")
        self._entries[path] = (bytes(data), type, media, dict(fields))

    def manifest_dict(self, signature_block: dict | None = None) -> dict:
        """The manifest as a dict (entries sorted by path in UTF-8 byte order)."""
        entries = []
        for path in sorted(self._entries, key=lambda p: p.encode("utf-8")):
            data, type, media, fields = self._entries[path]
            entry = {
                "path": path,
                "type": type,
                "media": media,
                "sha256": sha256_hex(data),
                "bytes": len(data),
            }
            entry.update(fields)
            entries.append(entry)
        m = {
            "format": "prsn",
            "version": 1,
            "spec": self.spec,
            "created": self.created,
            "generator": self.generator,
            "person": self.person_path,
            "entries": entries,
        }
        m.update(self._top_extra)
        if signature_block is not None:
            m["signature"] = signature_block
        return m

    def write_zip(
        self,
        dest: str | Path,
        *,
        seed: bytes | None = None,
        member_order: list[str] | None = None,
    ) -> keys.KeyPair | None:
        """Write the package as a ``.prsn`` ZIP.

        With ``seed`` (32 bytes), the manifest is signed with the derived
        Ed25519 key and ``signatures/manifest.sig`` is included; the key pair
        is returned. ``member_order`` fixes the ZIP member order exactly.
        """
        if self._person is not None and self.person_path not in self._entries:
            self.add_entry(
                self.person_path, "org.prsn.person", "application/json", canonical(self._person)
            )

        keypair = None
        if seed is not None:
            keypair = keys.keypair_from_seed(seed)
            block = {
                "path": SIGNATURE_PATH_DEFAULT,
                "alg": "Ed25519",
                "key_id": keypair.key_id,
                "public_key": keypair.public_key_b64,
            }
            manifest = self.manifest_dict(block)
            signature_bytes = keys.sign(seed, canonical(manifest))
        else:
            manifest = self.manifest_dict(None)
            signature_bytes = None
        manifest_bytes = canonical(manifest)

        members: list[tuple[str, bytes, bool]] = [("mimetype", MIMETYPE_CURRENT, True)]
        members.append(("manifest.json", manifest_bytes, False))
        for path in sorted(self._entries, key=lambda p: p.encode("utf-8")):
            data, _type, media, _fields = self._entries[path]
            members.append((path, data, _stored_media(media)))
        if signature_bytes is not None:
            members.append((SIGNATURE_PATH_DEFAULT, signature_bytes, True))

        if member_order is not None:
            rank = {name: i for i, name in enumerate(member_order)}
            members.sort(key=lambda m: (rank.get(m[0], len(rank)), m[0]))

        dest = Path(dest)
        with zipfile.ZipFile(dest, "w") as z:
            for name, data, stored in members:
                z.writestr(_zip_info(name, stored), data)
        return keypair
