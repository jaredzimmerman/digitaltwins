"""Small, dependency-free helpers for the `.prsn` / `.prsncap` file formats.

Used by `validate.py` and `build_vectors.py`. Standard library only:

- `parse` / `dumps`: the strict JSON parser and the canonical serialiser
  (spec/prsn.md, "Canonical JSON").
- `ed25519_public_key`, `ed25519_sign`, `ed25519_verify`: RFC 8032 Ed25519, a direct
  transcription of the RFC's reference algorithm. Slow but adequate for a few
  signatures; not constant time, so use it for test vectors only, never for real keys.
- `key_id`, `sha256_hex`, `seal_package`: manifest helpers.
"""

from __future__ import annotations

import base64
import hashlib
import math
import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# canonical JSON
# --------------------------------------------------------------------------- #


class JSONError(ValueError):
    pass


_WS = " \t\n\r"
_ESC = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
_INT64 = (-(2 ** 63), 2 ** 63 - 1)


def parse(data: bytes | str):
    """Strict RFC 8259 parse with the extra refusals of spec/prsn.md (duplicate keys,
    lone surrogates, BOM, NaN/Infinity, overflow)."""
    if isinstance(data, bytes):
        if data.startswith(b"\xef\xbb\xbf"):
            raise JSONError("byte-order mark")
        try:
            text = data.decode("utf-8", "strict")
        except UnicodeDecodeError as e:
            raise JSONError(f"invalid UTF-8: {e}") from None
    else:
        text = data
        if text.startswith("﻿"):
            raise JSONError("byte-order mark")
    for ch in text:
        if 0xD800 <= ord(ch) <= 0xDFFF:
            raise JSONError("lone surrogate in input")
    p = _Parser(text)
    p.ws()
    if p.i >= len(text):
        raise JSONError("empty input")
    v = p.value()
    p.ws()
    if p.i != len(text):
        raise JSONError(f"trailing content at {p.i}")
    return v


class _Parser:
    def __init__(self, s: str):
        self.s, self.i = s, 0

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in _WS:
            self.i += 1

    def err(self, msg):
        raise JSONError(f"{msg} at offset {self.i}")

    def value(self):
        if self.i >= len(self.s):
            self.err("unexpected end")
        c = self.s[self.i]
        if c == "{":
            return self.obj()
        if c == "[":
            return self.arr()
        if c == '"':
            return self.string()
        for lit, val in (("true", True), ("false", False), ("null", None)):
            if self.s.startswith(lit, self.i):
                self.i += len(lit)
                return val
        if c == "-" or c.isdigit():
            return self.number()
        self.err(f"unexpected {c!r}")

    def obj(self):
        self.i += 1
        out: dict = {}
        self.ws()
        if self.i < len(self.s) and self.s[self.i] == "}":
            self.i += 1
            return out
        while True:
            self.ws()
            if self.i >= len(self.s) or self.s[self.i] != '"':
                self.err("expected key")
            k = self.string()
            if k in out:
                self.err(f"duplicate key {k!r}")
            self.ws()
            if self.i >= len(self.s) or self.s[self.i] != ":":
                self.err("expected ':'")
            self.i += 1
            self.ws()
            out[k] = self.value()
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
                continue
            if self.i < len(self.s) and self.s[self.i] == "}":
                self.i += 1
                return out
            self.err("expected ',' or '}'")

    def arr(self):
        self.i += 1
        out = []
        self.ws()
        if self.i < len(self.s) and self.s[self.i] == "]":
            self.i += 1
            return out
        while True:
            self.ws()
            out.append(self.value())
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
                continue
            if self.i < len(self.s) and self.s[self.i] == "]":
                self.i += 1
                return out
            self.err("expected ',' or ']'")

    def _hex4(self):
        h = self.s[self.i:self.i + 4]
        if len(h) != 4 or any(c not in "0123456789abcdefABCDEF" for c in h):
            self.err("bad \\u escape")
        self.i += 4
        return int(h, 16)

    def string(self):
        self.i += 1
        buf = []
        while True:
            if self.i >= len(self.s):
                self.err("unterminated string")
            c = self.s[self.i]
            if c == '"':
                self.i += 1
                return "".join(buf)
            if ord(c) < 0x20:
                self.err("raw control character in string")
            if c != "\\":
                buf.append(c)
                self.i += 1
                continue
            self.i += 1
            if self.i >= len(self.s):
                self.err("unterminated escape")
            e = self.s[self.i]
            self.i += 1
            if e in _ESC:
                buf.append(_ESC[e])
            elif e == "u":
                cp = self._hex4()
                if 0xD800 <= cp <= 0xDBFF:
                    if not self.s.startswith("\\u", self.i):
                        self.err("lone high surrogate")
                    self.i += 2
                    lo = self._hex4()
                    if not 0xDC00 <= lo <= 0xDFFF:
                        self.err("mis-paired surrogate")
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                elif 0xDC00 <= cp <= 0xDFFF:
                    self.err("lone low surrogate")
                buf.append(chr(cp))
            else:
                self.err(f"unknown escape \\{e}")

    def number(self):
        s, j = self.s, self.i
        if s[j] == "-":
            j += 1
        if j >= len(s) or not s[j].isdigit():
            self.err("bad number")
        if s[j] == "0":
            j += 1
            if j < len(s) and s[j].isdigit():
                self.err("leading zero")
        else:
            while j < len(s) and s[j].isdigit():
                j += 1
        is_int = True
        if j < len(s) and s[j] == ".":
            is_int = False
            j += 1
            if j >= len(s) or not s[j].isdigit():
                self.err("bad fraction")
            while j < len(s) and s[j].isdigit():
                j += 1
        if j < len(s) and s[j] in "eE":
            is_int = False
            j += 1
            if j < len(s) and s[j] in "+-":
                j += 1
            if j >= len(s) or not s[j].isdigit():
                self.err("bad exponent")
            while j < len(s) and s[j].isdigit():
                j += 1
        tok = s[self.i:j]
        self.i = j
        if is_int:
            n = int(tok)
            if _INT64[0] <= n <= _INT64[1]:
                return n
        f = float(tok)
        if math.isinf(f):
            raise JSONError(f"number {tok} overflows a double")
        return f


def _num(x: float) -> str:
    if math.isnan(x) or math.isinf(x):
        raise JSONError("NaN and Infinity cannot be serialised")
    if x == 0:
        return "0"
    s = repr(abs(x))
    mant, exp = (s.split("e") + ["0"])[:2]
    ip, fp = (mant.split(".") + [""])[:2]
    digits = ip + fp
    n = len(ip) + int(exp)
    while len(digits) > 1 and digits[0] == "0":
        digits, n = digits[1:], n - 1
    digits = digits.rstrip("0") or "0"
    k = len(digits)
    if k <= n <= 21:
        out = digits + "0" * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        out = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return ("-" if x < 0 else "") + out


def _str(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif o < 0x20:
            out.append({8: "\\b", 9: "\\t", 10: "\\n", 12: "\\f", 13: "\\r"}.get(o, f"\\u{o:04x}"))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def dumps(v) -> str:
    """Canonical JSON text: sorted keys (code point order), no whitespace, minimal escapes,
    ECMAScript-style shortest numbers."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _num(v)
    if isinstance(v, str):
        return _str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(dumps(x) for x in v) + "]"
    if isinstance(v, dict):
        for k in v:
            if not isinstance(k, str):
                raise JSONError("object keys must be strings")
        return "{" + ",".join(_str(k) + ":" + dumps(v[k]) for k in sorted(v)) + "}"
    raise JSONError(f"cannot serialise {type(v).__name__}")


def canonical(v) -> bytes:
    return dumps(v).encode("utf-8")


# --------------------------------------------------------------------------- #
# hashes, key ids, action_key
# --------------------------------------------------------------------------- #

def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def key_id(public_key: bytes) -> str:
    return sha256_hex(public_key)[:16]


class ActionKeyError(ValueError):
    pass


def action_key_preimage(d: dict) -> bytes:
    """spec/derivation-recipes.md R1."""
    if not isinstance(d.get("family"), str):
        raise ActionKeyError("family missing")
    r = d.get("recipe")
    if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not isinstance(r.get("version"), str):
        raise ActionKeyError("recipe.id and recipe.version required")
    models = []
    for m in d.get("models") or []:
        if not isinstance(m, dict) or not isinstance(m.get("sha256"), str):
            raise ActionKeyError("model without sha256")
        models.append(m["sha256"])
    params = d.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ActionKeyError("params must be an object")
    ins = []
    for i in d.get("inputs") or []:
        hashes = [k for k in ("capture", "cache", "sha256") if k in i]
        if len(hashes) != 1 or not isinstance(i[hashes[0]], str):
            raise ActionKeyError("an input needs exactly one string content hash")
        ins.append({k: v for k, v in i.items() if k in ("capture", "cache", "sha256", "role", "select")})
    ins.sort(key=canonical)
    pre = {"family": d["family"], "recipe": {"id": r["id"], "version": r["version"]},
           "models": sorted(models, key=lambda s: s.encode("utf-8")), "params": params, "inputs": ins}
    return canonical(pre)


def action_key(d: dict) -> str:
    return "sha256:" + sha256_hex(action_key_preimage(d))


# --------------------------------------------------------------------------- #
# Ed25519 (RFC 8032 section 5.1, reference transcription)
# --------------------------------------------------------------------------- #

_p = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_d = -121665 * pow(121666, _p - 2, _p) % _p
_I = pow(2, (_p - 1) // 4, _p)


def _xrecover(y, sign):
    x2 = (y * y - 1) * pow(_d * y * y + 1, _p - 2, _p) % _p
    if x2 == 0:
        if sign:
            return None
        return 0
    x = pow(x2, (_p + 3) // 8, _p)
    if (x * x - x2) % _p != 0:
        x = x * _I % _p
    if (x * x - x2) % _p != 0:
        return None
    if (x & 1) != sign:
        x = _p - x
    return x


_By = 4 * pow(5, _p - 2, _p) % _p
_B = (_xrecover(_By, 0), _By, 1, _xrecover(_By, 0) * _By % _p)


def _add(P, Q):
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % _p
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % _p
    C = 2 * P[3] * Q[3] * _d % _p
    D = 2 * P[2] * Q[2] % _p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _p, G * H % _p, F * G % _p, E * H % _p)


def _mul(s, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _eq(P, Q):
    return (P[0] * Q[2] - Q[0] * P[2]) % _p == 0 and (P[1] * Q[2] - Q[1] * P[2]) % _p == 0


def _enc(P):
    zi = pow(P[2], _p - 2, _p)
    x, y = P[0] * zi % _p, P[1] * zi % _p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _dec(b):
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _p:
        return None
    x = _xrecover(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _p)


def _h(m):
    return hashlib.sha512(m).digest()


def _expand(seed):
    if len(seed) != 32:
        raise ValueError("Ed25519 seed must be 32 bytes")
    h = _h(seed)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def ed25519_public_key(seed: bytes) -> bytes:
    a, _ = _expand(seed)
    return _enc(_mul(a, _B))


def ed25519_sign(seed: bytes, msg: bytes) -> bytes:
    a, prefix = _expand(seed)
    A = _enc(_mul(a, _B))
    r = int.from_bytes(_h(prefix + msg), "little") % _L
    R = _enc(_mul(r, _B))
    k = int.from_bytes(_h(R + A + msg), "little") % _L
    return R + int.to_bytes((r + k * a) % _L, 32, "little")


def ed25519_verify(public: bytes, msg: bytes, sig: bytes) -> bool:
    if len(public) != 32 or len(sig) != 64:
        return False
    A = _dec(public)
    R = _dec(sig[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _L:
        return False
    k = int.from_bytes(_h(sig[:32] + public + msg), "little") % _L
    return _eq(_mul(s, _B), _add(R, _mul(k, A)))


# --------------------------------------------------------------------------- #
# packages
# --------------------------------------------------------------------------- #

NOT_ENTRIES_TOP = {"manifest.json", "mimetype"}


def package_files(root: Path) -> list[str]:
    """Files of a directory package that are manifest entries: not `manifest.json`,
    `mimetype`, anything under top-level `signatures/`, or any dot-segment path."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in filenames:
            if f.startswith("."):
                continue
            rel = Path(dirpath, f).relative_to(root).as_posix()
            if rel in NOT_ENTRIES_TOP or rel.startswith("signatures/"):
                continue
            out.append(rel)
    return sorted(out, key=lambda s: s.encode("utf-8"))


def signature_block(seed: bytes) -> dict:
    pub = ed25519_public_key(seed)
    return {"path": "signatures/manifest.sig", "alg": "Ed25519", "key_id": key_id(pub),
            "public_key": base64.b64encode(pub).decode("ascii")}


def seal_package(root: Path, top: dict, meta: dict[str, dict], seed: bytes | None,
                 mimetype: str | None = None) -> bytes:
    """Write manifest.json (canonical) and signatures/manifest.sig for a directory package.

    `top`: top-level manifest fields (entries and signature are added here).
    `meta`: per-path entry fields (`type`, `media` and any record fields); every file in
    the package must have one. Returns the canonical manifest bytes."""
    root = Path(root)
    if mimetype is not None:
        (root / "mimetype").write_bytes(mimetype.encode("ascii"))
    entries = []
    for rel in package_files(root):
        if rel not in meta:
            raise KeyError(f"no entry metadata for {rel}")
        data = (root / rel).read_bytes()
        e = dict(meta[rel])
        e.update({"path": rel, "sha256": sha256_hex(data), "bytes": len(data)})
        entries.append(e)
    m = dict(top)
    m["entries"] = entries
    if seed is not None:
        m["signature"] = signature_block(seed)
    body = canonical(m)
    (root / "manifest.json").write_bytes(body)
    sig = root / "signatures" / "manifest.sig"
    if seed is not None:
        sig.parent.mkdir(parents=True, exist_ok=True)
        sig.write_bytes(ed25519_sign(seed, body))
    elif sig.exists():
        sig.unlink()
    return body


def write_manifest_signed(root: Path, manifest: dict, seed: bytes) -> bytes:
    """Re-serialise an edited manifest and sign it (the signature block is kept as given)."""
    body = canonical(manifest)
    (Path(root) / "manifest.json").write_bytes(body)
    sig = Path(root) / "signatures" / "manifest.sig"
    sig.parent.mkdir(parents=True, exist_ok=True)
    sig.write_bytes(ed25519_sign(seed, body))
    return body
