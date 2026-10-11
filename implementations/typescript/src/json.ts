// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//
// Strict RFC 8259 JSON parser and canonical JSON serializer for .prsn.
// See spec/prsn.md, "Canonical JSON".
//
// The AST keeps integers and doubles distinct: an integer token that fits a
// signed 64-bit integer becomes a JsonInt (bigint, exact); every other number
// token becomes a JsonFloat (IEEE-754 double, correctly rounded).

/** A JSON integer: exact, backed by bigint. */
export interface JsonInt {
  readonly ikind: "int";
  readonly value: bigint;
}

/** A JSON non-integer number: an IEEE-754 double. */
export interface JsonFloat {
  readonly ikind: "float";
  readonly value: number;
}

/** A JSON object. Entries are kept in insertion (parse) order. */
export interface JsonObject {
  readonly ikind: "object";
  readonly entries: Array<[string, JsonValue]>;
}

export type JsonValue =
  | null
  | boolean
  | string
  | JsonInt
  | JsonFloat
  | JsonValue[]
  | JsonObject;

export class JsonError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "JsonError";
  }
}

// ---------------------------------------------------------------------------
// constructors / accessors
// ---------------------------------------------------------------------------

export function jInt(value: number | bigint): JsonValue {
  return { ikind: "int", value: BigInt(value) };
}

export function jFloat(value: number): JsonValue {
  return { ikind: "float", value };
}

export function jStr(value: string): JsonValue {
  return value;
}

export function jArr(...items: JsonValue[]): JsonValue {
  return items;
}

export function jObj(...pairs: Array<[string, JsonValue]>): JsonObject {
  return { ikind: "object", entries: pairs };
}

export function isJInt(v: unknown): v is JsonInt {
  return typeof v === "object" && v !== null && (v as JsonInt).ikind === "int";
}

export function isJFloat(v: unknown): v is JsonFloat {
  return typeof v === "object" && v !== null && (v as JsonFloat).ikind === "float";
}

export function isJObject(v: unknown): v is JsonObject {
  return typeof v === "object" && v !== null && (v as JsonObject).ikind === "object";
}

export function isJArray(v: unknown): v is JsonValue[] {
  return Array.isArray(v);
}

/** Look up a field of a JsonObject; undefined when absent. */
export function objGet(o: JsonObject, key: string): JsonValue | undefined {
  for (const [k, v] of o.entries) {
    if (k === key) return v;
  }
  return undefined;
}

export function asString(v: JsonValue | undefined): string | undefined {
  return typeof v === "string" ? v : undefined;
}

export function asBool(v: JsonValue | undefined): boolean | undefined {
  return typeof v === "boolean" ? v : undefined;
}

export function asInt(v: JsonValue | undefined): bigint | undefined {
  return isJInt(v) ? v.value : undefined;
}

export function asFloat(v: JsonValue | undefined): number | undefined {
  return isJFloat(v) ? v.value : undefined;
}

/** Deep structural equality. Object key order is ignored; array order matters. */export function jsonEqual(a: JsonValue, b: JsonValue): boolean {
  if (a === null || b === null) return a === b;
  if (typeof a === "boolean" || typeof b === "boolean") return a === b;
  if (typeof a === "string" || typeof b === "string") return a === b;
  if (isJInt(a) || isJInt(b)) return isJInt(a) && isJInt(b) && a.value === b.value;
  if (isJFloat(a) || isJFloat(b)) return isJFloat(a) && isJFloat(b) && a.value === b.value;
  if (isJArray(a) || isJArray(b)) {
    return (
      isJArray(a) &&
      isJArray(b) &&
      a.length === b.length &&
      a.every((x, i) => jsonEqual(x, (b as JsonValue[])[i]))
    );
  }
  if (isJObject(a) || isJObject(b)) {
    if (!isJObject(a) || !isJObject(b) || a.entries.length !== b.entries.length) return false;
    return a.entries.every(([k, v]) => {
      const w = objGet(b, k);
      return w !== undefined && jsonEqual(v, w);
    });
  }
  return false;
}

/** Deep clone of a JsonValue. */
export function jsonClone(v: JsonValue): JsonValue {
  if (v === null || typeof v === "boolean" || typeof v === "string") return v;
  if (isJInt(v)) return { ikind: "int", value: v.value };
  if (isJFloat(v)) return { ikind: "float", value: v.value };
  if (isJArray(v)) return v.map(jsonClone);
  return { ikind: "object", entries: v.entries.map(([k, x]) => [k, jsonClone(x)] as [string, JsonValue]) };
}

/**
 * Convert the AST to plain JavaScript values (objects, arrays, primitives).
 * Integers that fit a double become numbers; larger ones become strings —
 * for vector navigation only, not for hashing.
 */
export function toPlain(v: JsonValue): unknown {
  if (v === null || typeof v === "boolean" || typeof v === "string") return v;
  if (isJInt(v)) {
    const n = v.value;
    return n >= BigInt(Number.MIN_SAFE_INTEGER) && n <= BigInt(Number.MAX_SAFE_INTEGER)
      ? Number(n)
      : n.toString();
  }
  if (isJFloat(v)) return v.value;
  if (isJArray(v)) return v.map(toPlain);
  const out: Record<string, unknown> = {};
  for (const [k, x] of v.entries) out[k] = toPlain(x);
  return out;
}

// ---------------------------------------------------------------------------
// strict parser
// ---------------------------------------------------------------------------

const INT64_MIN = -(1n << 63n);
const INT64_MAX = (1n << 63n) - 1n;

function isDigit(ch: string): boolean {
  return ch >= "0" && ch <= "9";
}

function isHex(ch: string): boolean {
  return (
    (ch >= "0" && ch <= "9") ||
    (ch >= "a" && ch <= "f") ||
    (ch >= "A" && ch <= "F")
  );
}

class Parser {
  private i = 0;
  constructor(private readonly s: string) {}

  private err(msg: string): never {
    throw new JsonError(`${msg} at offset ${this.i}`);
  }

  private ws(): void {
    while (this.i < this.s.length) {
      const c = this.s[this.i];
      if (c === " " || c === "\t" || c === "\n" || c === "\r") this.i++;
      else break;
    }
  }

  value(): JsonValue {
    if (this.i >= this.s.length) this.err("unexpected end of input");
    const c = this.s[this.i];
    if (c === "{") return this.object();
    if (c === "[") return this.array();
    if (c === '"') return this.string();
    if (this.s.startsWith("true", this.i)) {
      this.i += 4;
      return true;
    }
    if (this.s.startsWith("false", this.i)) {
      this.i += 5;
      return false;
    }
    if (this.s.startsWith("null", this.i)) {
      this.i += 4;
      return null;
    }
    if (c === "-" || isDigit(c)) return this.number();
    this.err(`unexpected character ${JSON.stringify(c)}`);
  }

  private object(): JsonObject {
    this.i++; // {
    const entries: Array<[string, JsonValue]> = [];
    const seen = new Set<string>();
    this.ws();
    if (this.s[this.i] === "}") {
      this.i++;
      return { ikind: "object", entries };
    }
    for (;;) {
      this.ws();
      if (this.i >= this.s.length || this.s[this.i] !== '"') this.err("expected object key");
      const k = this.string();
      if (seen.has(k)) this.err(`duplicate object key ${JSON.stringify(k)}`);
      seen.add(k);
      this.ws();
      if (this.i >= this.s.length || this.s[this.i] !== ":") this.err("expected ':'");
      this.i++;
      this.ws();
      entries.push([k, this.value()]);
      this.ws();
      if (this.s[this.i] === ",") {
        this.i++;
        continue;
      }
      if (this.s[this.i] === "}") {
        this.i++;
        return { ikind: "object", entries };
      }
      this.err("expected ',' or '}'");
    }
  }

  private array(): JsonValue[] {
    this.i++; // [
    const out: JsonValue[] = [];
    this.ws();
    if (this.s[this.i] === "]") {
      this.i++;
      return out;
    }
    for (;;) {
      this.ws();
      out.push(this.value());
      this.ws();
      if (this.s[this.i] === ",") {
        this.i++;
        continue;
      }
      if (this.s[this.i] === "]") {
        this.i++;
        return out;
      }
      this.err("expected ',' or ']'");
    }
  }

  private hex4(): number {
    const h = this.s.slice(this.i, this.i + 4);
    if (h.length !== 4 || ![...h].every(isHex)) this.err("bad \\u escape");
    this.i += 4;
    return parseInt(h, 16);
  }

  private string(): string {
    this.i++; // opening quote
    let out = "";
    for (;;) {
      if (this.i >= this.s.length) this.err("unterminated string");
      const cp = this.s.codePointAt(this.i)!;
      const ch = String.fromCodePoint(cp);
      const w = cp > 0xffff ? 2 : 1; // UTF-16 code units for this code point
      if (ch === '"') {
        this.i += w;
        return out;
      }
      if (cp < 0x20) this.err("raw control character in string");
      if (ch !== "\\") {
        out += ch;
        this.i += w;
        continue;
      }
      this.i++;
      if (this.i >= this.s.length) this.err("unterminated escape");
      const e = this.s[this.i];
      this.i++;
      switch (e) {
        case '"': out += '"'; break;
        case "\\": out += "\\"; break;
        case "/": out += "/"; break;
        case "b": out += "\b"; break;
        case "f": out += "\f"; break;
        case "n": out += "\n"; break;
        case "r": out += "\r"; break;
        case "t": out += "\t"; break;
        case "u": {
          const hi = this.hex4();
          if (hi >= 0xd800 && hi <= 0xdbff) {
            if (!this.s.startsWith("\\u", this.i)) this.err("lone high surrogate escape");
            this.i += 2;
            const lo = this.hex4();
            if (lo < 0xdc00 || lo > 0xdfff) this.err("mis-paired surrogate escape");
            out += String.fromCodePoint(0x10000 + ((hi - 0xd800) << 10) + (lo - 0xdc00));
          } else if (hi >= 0xdc00 && hi <= 0xdfff) {
            this.err("lone low surrogate escape");
          } else {
            out += String.fromCodePoint(hi);
          }
          break;
        }
        default:
          this.err(`unknown escape \\${e}`);
      }
    }
  }

  private number(): JsonValue {
    const s = this.s;
    let j = this.i;
    if (s[j] === "-") j++;
    if (j >= s.length || !isDigit(s[j])) this.err("bad number");
    if (s[j] === "0") {
      j++;
      if (j < s.length && isDigit(s[j])) this.err("leading zero");
    } else {
      while (j < s.length && isDigit(s[j])) j++;
    }
    let isInt = true;
    if (s[j] === ".") {
      isInt = false;
      j++;
      if (j >= s.length || !isDigit(s[j])) this.err("bad fraction");
      while (j < s.length && isDigit(s[j])) j++;
    }
    if (s[j] === "e" || s[j] === "E") {
      isInt = false;
      j++;
      if (s[j] === "+" || s[j] === "-") j++;
      if (j >= s.length || !isDigit(s[j])) this.err("bad exponent");
      while (j < s.length && isDigit(s[j])) j++;
    }
    const tok = s.slice(this.i, j);
    this.i = j;
    if (isInt) {
      const n = BigInt(tok);
      if (n >= INT64_MIN && n <= INT64_MAX) return { ikind: "int", value: n };
    }
    const f = Number(tok); // correctly rounded decimal -> double; underflow -> 0
    if (!Number.isFinite(f)) throw new JsonError(`number ${tok} overflows a double`);
    return { ikind: "float", value: f };
  }

  parseTop(): JsonValue {
    this.ws();
    if (this.i >= this.s.length) throw new JsonError("empty input");
    const v = this.value();
    this.ws();
    if (this.i !== this.s.length) throw new JsonError(`trailing content at offset ${this.i}`);
    return v;
  }
}

/**
 * Strict RFC 8259 parse with the extra refusals of spec/prsn.md:
 * invalid UTF-8, BOM, raw control characters, unknown escapes, lone or
 * mis-paired surrogate escapes, duplicate keys at any depth, comments,
 * NaN/Infinity, leading +, leading zeros, `.5`, `1.`, `1e`, trailing commas,
 * trailing content, empty input, and number tokens overflowing a double.
 */
export function parseJson(data: Uint8Array | string): JsonValue {
  let text: string;
  if (typeof data === "string") {
    text = data;
  } else {
    if (data.length >= 3 && data[0] === 0xef && data[1] === 0xbb && data[2] === 0xbf) {
      throw new JsonError("byte-order mark");
    }
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(data);
    } catch {
      throw new JsonError("invalid UTF-8");
    }
  }
  if (text.startsWith("﻿")) throw new JsonError("byte-order mark");
  for (const ch of text) {
    const cp = ch.codePointAt(0)!;
    if (cp >= 0xd800 && cp <= 0xdfff) throw new JsonError("lone surrogate in input");
  }
  return new Parser(text).parseTop();
}

// ---------------------------------------------------------------------------
// canonical serializer
// ---------------------------------------------------------------------------

/**
 * Compare two strings by Unicode code point. This is NOT JavaScript's default
 * UTF-16 code-unit order: for non-BMP characters (e.g. U+1F600 vs U+E000) the
 * two orders differ, and the spec requires code-point order.
 */
export function compareCodePoints(a: string, b: string): number {
  const ai = a[Symbol.iterator]();
  const bi = b[Symbol.iterator]();
  for (;;) {
    const an = ai.next();
    const bn = bi.next();
    if (an.done && bn.done) return 0;
    if (an.done) return -1;
    if (bn.done) return 1;
    const ac = an.value.codePointAt(0)!;
    const bc = bn.value.codePointAt(0)!;
    if (ac !== bc) return ac - bc;
  }
}

const SHORT_ESCAPES: Record<number, string> = {
  0x08: "\\b",
  0x09: "\\t",
  0x0a: "\\n",
  0x0c: "\\f",
  0x0d: "\\r",
};

function escapeString(s: string): string {
  let out = '"';
  for (const ch of s) {
    const cp = ch.codePointAt(0)!;
    if (ch === '"') out += '\\"';
    else if (ch === "\\") out += "\\\\";
    else if (cp < 0x20) out += SHORT_ESCAPES[cp] ?? `\\u${cp.toString(16).padStart(4, "0")}`;
    else out += ch; // everything else literal: `/`, U+007F, U+2028/29, all non-ASCII
  }
  return out + '"';
}

function serialize(v: JsonValue): string {
  if (v === null) return "null";
  if (v === true) return "true";
  if (v === false) return "false";
  if (typeof v === "string") return escapeString(v);
  if (isJInt(v)) return v.value.toString();
  if (isJFloat(v)) {
    if (!Number.isFinite(v.value)) {
      throw new JsonError("NaN and Infinity cannot be serialised");
    }
    // ECMAScript Number.prototype.toString: shortest round-trip digits in the
    // exact layout the spec requires. (-0).toString() === "0".
    return String(v.value);
  }
  if (isJArray(v)) return `[${v.map(serialize).join(",")}]`;
  if (isJObject(v)) {
    const sorted = [...v.entries].sort((a, b) => compareCodePoints(a[0], b[0]));
    return `{${sorted.map(([k, x]) => `${escapeString(k)}:${serialize(x)}`).join(",")}}`;
  }
  throw new JsonError(`cannot serialise value of type ${typeof v}`);
}

/** Canonical JSON text: no whitespace, keys sorted by code point, UTF-8 output. */
export function canonicalJson(v: JsonValue): string {
  return serialize(v);
}

/** Canonical JSON as UTF-8 bytes (the form that is hashed and signed). */
export function canonicalBytes(v: JsonValue): Uint8Array {
  return new TextEncoder().encode(serialize(v));
}
