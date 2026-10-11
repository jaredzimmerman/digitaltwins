# Copyright 2026 Jared Zimmerman
# SPDX-License-Identifier: Apache-2.0
"""Strict RFC 8259 JSON parsing and canonical JSON serialisation.

Canonical form (spec/prsn.md, "Canonical JSON"):
  - no whitespace between tokens, UTF-8 output
  - object keys sorted by Unicode code point (= UTF-8 byte order)
  - minimal string escapes; non-ASCII written literally
  - integers in exact decimal; doubles as shortest round-trip digits laid out
    like ECMAScript ``Number.prototype.toString``

The standard library ``json`` module is deliberately NOT used here: it accepts
lone surrogates, duplicate keys, NaN/Infinity and non-shortest floats, all of
which this format refuses.
"""

from __future__ import annotations

import math


class JSONError(ValueError):
    """Raised when input is not strict RFC 8259 JSON, or a value cannot be
    serialised to canonical form."""


_WS = " \t\n\r"
_DIGITS = "0123456789"
_HEX = "0123456789abcdefABCDEF"
_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
_SHORT_ESCAPES = {0x08: "\\b", 0x09: "\\t", 0x0A: "\\n", 0x0C: "\\f", 0x0D: "\\r"}
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def parse(data: bytes | str):
    """Strict-parse ``data`` (bytes or str) as RFC 8259 JSON.

    Refuses: invalid UTF-8 (overlong forms, encoded surrogates, truncation), a
    leading byte-order mark, raw U+0000-U+001F inside strings, unknown escapes,
    lone or mis-paired surrogate escapes, duplicate object keys at any depth,
    comments, NaN/Infinity, a leading ``+``, leading zeros, ``.5``, ``1.``,
    ``1e``, trailing commas, trailing content, empty input, and number tokens
    whose value overflows a double.

    An integer token (no fraction, no exponent) that fits a signed 64-bit
    integer becomes an exact ``int``; any other number token becomes an
    IEEE-754 double (correctly rounded; underflow reads as zero).
    """
    if isinstance(data, bytes):
        if data.startswith(b"\xef\xbb\xbf"):
            raise JSONError("byte-order mark")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise JSONError(f"invalid UTF-8: {e}") from None
    elif isinstance(data, str):
        text = data
        if text.startswith("\ufeff"):
            raise JSONError("byte-order mark")
        for ch in text:
            if 0xD800 <= ord(ch) <= 0xDFFF:
                raise JSONError("lone surrogate in input")
    else:
        raise TypeError(f"parse() needs bytes or str, not {type(data).__name__}")

    p = _Parser(text)
    p.skip_ws()
    if p.i >= len(text):
        raise JSONError("empty input")
    value = p.parse_value()
    p.skip_ws()
    if p.i != len(text):
        raise JSONError(f"trailing content at offset {p.i}")
    return value


class _Parser:
    def __init__(self, text: str):
        self.s = text
        self.i = 0

    def error(self, msg: str) -> JSONError:
        return JSONError(f"{msg} at offset {self.i}")

    def skip_ws(self) -> None:
        s = self.s
        while self.i < len(s) and s[self.i] in _WS:
            self.i += 1

    def parse_value(self):
        s = self.s
        if self.i >= len(s):
            raise self.error("unexpected end of input")
        c = s[self.i]
        if c == "{":
            return self.parse_object()
        if c == "[":
            return self.parse_array()
        if c == '"':
            return self.parse_string()
        if c == "t":
            if s.startswith("true", self.i):
                self.i += 4
                return True
            raise self.error("invalid literal")
        if c == "f":
            if s.startswith("false", self.i):
                self.i += 5
                return False
            raise self.error("invalid literal")
        if c == "n":
            if s.startswith("null", self.i):
                self.i += 4
                return None
            raise self.error("invalid literal")
        if c == "-" or c in _DIGITS:
            return self.parse_number()
        raise self.error(f"unexpected character {c!r}")

    def parse_object(self):
        self.i += 1  # consume '{'
        out: dict = {}
        self.skip_ws()
        if self.i < len(self.s) and self.s[self.i] == "}":
            self.i += 1
            return out
        while True:
            self.skip_ws()
            if self.i >= len(self.s) or self.s[self.i] != '"':
                raise self.error("expected string key")
            key = self.parse_string()
            if key in out:
                raise self.error(f"duplicate key {key!r}")
            self.skip_ws()
            if self.i >= len(self.s) or self.s[self.i] != ":":
                raise self.error("expected ':'")
            self.i += 1
            self.skip_ws()
            out[key] = self.parse_value()
            self.skip_ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
                continue
            if self.i < len(self.s) and self.s[self.i] == "}":
                self.i += 1
                return out
            raise self.error("expected ',' or '}'")

    def parse_array(self):
        self.i += 1  # consume '['
        out: list = []
        self.skip_ws()
        if self.i < len(self.s) and self.s[self.i] == "]":
            self.i += 1
            return out
        while True:
            self.skip_ws()
            out.append(self.parse_value())
            self.skip_ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
                continue
            if self.i < len(self.s) and self.s[self.i] == "]":
                self.i += 1
                return out
            raise self.error("expected ',' or ']'")

    def _hex4(self) -> int:
        h = self.s[self.i : self.i + 4]
        if len(h) != 4 or any(c not in _HEX for c in h):
            raise self.error("bad \\u escape")
        self.i += 4
        return int(h, 16)

    def parse_string(self) -> str:
        self.i += 1  # consume opening quote
        s = self.s
        buf: list[str] = []
        while True:
            if self.i >= len(s):
                raise self.error("unterminated string")
            c = s[self.i]
            if c == '"':
                self.i += 1
                return "".join(buf)
            if ord(c) < 0x20:
                raise self.error("raw control character in string")
            if c != "\\":
                buf.append(c)
                self.i += 1
                continue
            self.i += 1
            if self.i >= len(s):
                raise self.error("unterminated escape")
            e = s[self.i]
            self.i += 1
            if e in _SIMPLE_ESCAPES:
                buf.append(_SIMPLE_ESCAPES[e])
            elif e == "u":
                cp = self._hex4()
                if 0xD800 <= cp <= 0xDBFF:
                    if not s.startswith("\\u", self.i):
                        raise self.error("lone high surrogate")
                    self.i += 2
                    lo = self._hex4()
                    if not 0xDC00 <= lo <= 0xDFFF:
                        raise self.error("mis-paired surrogate")
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                elif 0xDC00 <= cp <= 0xDFFF:
                    raise self.error("lone low surrogate")
                buf.append(chr(cp))
            else:
                raise self.error(f"unknown escape \\{e}")

    def parse_number(self):
        s = self.s
        j = self.i
        if s[j] == "-":
            j += 1
        if j >= len(s) or s[j] not in _DIGITS:
            raise self.error("bad number")
        if s[j] == "0":
            j += 1
            if j < len(s) and s[j] in _DIGITS:
                raise self.error("leading zero")
        else:
            while j < len(s) and s[j] in _DIGITS:
                j += 1
        is_int = True
        if j < len(s) and s[j] == ".":
            is_int = False
            j += 1
            if j >= len(s) or s[j] not in _DIGITS:
                raise self.error("bad fraction")
            while j < len(s) and s[j] in _DIGITS:
                j += 1
        if j < len(s) and s[j] in "eE":
            is_int = False
            j += 1
            if j < len(s) and s[j] in "+-":
                j += 1
            if j >= len(s) or s[j] not in _DIGITS:
                raise self.error("bad exponent")
            while j < len(s) and s[j] in _DIGITS:
                j += 1
        token = s[self.i : j]
        self.i = j
        if is_int:
            n = int(token)
            if _INT64_MIN <= n <= _INT64_MAX:
                return n
        # Any other number token is an IEEE-754 double, correctly rounded.
        # float() on a decimal string is correctly rounded in CPython;
        # underflow reads as zero, overflow raises below.
        try:
            f = float(token)
        except ValueError:
            raise self.error(f"bad number {token!r}") from None
        if math.isinf(f):
            raise self.error(f"number {token!r} overflows a double")
        return f


def _format_double(x: float) -> str:
    """Shortest round-trip digits laid out like ECMAScript Number.toString.

    With digits d1..dk and value 0.d1..dk * 10**n:
      k <= n <= 21  -> digits then n-k zeros
      0 < n <= 21   -> point inside the digits
      -6 < n <= 0   -> "0." then -n zeros then digits
      else          -> d1[.d2..dk]e<+->(n-1)
    """
    if math.isnan(x) or math.isinf(x):
        raise JSONError("NaN and Infinity cannot be serialised")
    if x == 0.0:
        return "0"  # covers -0.0 as well
    neg = x < 0
    s = repr(-x if neg else x)  # shortest round-trip digits
    if "e" in s:
        mant, exp = s.split("e")
    else:
        mant, exp = s, "0"
    if "." in mant:
        ip, fp = mant.split(".")
    else:
        ip, fp = mant, ""
    digits = ip + fp
    n = len(ip) + int(exp)
    while len(digits) > 1 and digits[0] == "0":
        digits = digits[1:]
        n -= 1
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
        out = (
            digits[0]
            + ("." + digits[1:] if k > 1 else "")
            + "e"
            + ("+" if e >= 0 else "-")
            + str(abs(e))
        )
    return ("-" if neg else "") + out


def _dump_string(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif o in _SHORT_ESCAPES:
            out.append(_SHORT_ESCAPES[o])
        elif o < 0x20:
            out.append(f"\\u{o:04x}")
        elif 0xD800 <= o <= 0xDFFF:
            raise JSONError("lone surrogate cannot be serialised")
        else:
            out.append(ch)  # '/', U+007F, U+2028/2029, all non-ASCII: literal
    out.append('"')
    return "".join(out)


def dumps(value) -> str:
    """Serialise ``value`` to canonical JSON text."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)  # exact decimal; -0 is already int 0
    if isinstance(value, float):
        return _format_double(value)
    if isinstance(value, str):
        return _dump_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(dumps(x) for x in value) + "]"
    if isinstance(value, dict):
        for k in value:
            if not isinstance(k, str):
                raise JSONError("object keys must be strings")
        return (
            "{"
            + ",".join(
                _dump_string(k) + ":" + dumps(value[k]) for k in sorted(value)
            )
            + "}"
        )
    raise JSONError(f"cannot serialise {type(value).__name__}")


def canonical(value) -> bytes:
    """Canonical JSON bytes (UTF-8) of ``value``."""
    return dumps(value).encode("utf-8")
