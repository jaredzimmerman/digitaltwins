// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//
// Minimal ZIP reader and writer for .prsn.
//
// The reader parses the central directory (order-preserving, so duplicate
// member names are visible) and each member's local header, and supports
// STORED and DEFLATE members plus ZIP64. The writer gives byte-exact control
// over local headers: the `mimetype` member is written first, STORED, with no
// extra field, as the spec requires.
//
// Only what .prsn needs is implemented; ZIP encryption is never used.

import { inflateRawSync, deflateRawSync, crc32 } from "node:zlib";

export const ZIP_STORED = 0;
export const ZIP_DEFLATED = 8;

export class ZipError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ZipError";
  }
}

export interface ZipMember {
  /** Member name, in central-directory order. */
  name: string;
  method: number;
  /** Extra-field length in the LOCAL header. */
  localExtraLen: number;
  /** Extra-field length in the CENTRAL directory header. */
  centralExtraLen: number;
  compSize: number;
  uncompSize: number;
  localHeaderOffset: number;
  dataOffset: number;
}

function u16(buf: Uint8Array, o: number): number {
  return buf[o] | (buf[o + 1] << 8);
}

function u32(buf: Uint8Array, o: number): number {
  return (
    buf[o] |
    (buf[o + 1] << 8) |
    (buf[o + 2] << 16) |
    (buf[o + 3] * 0x1000000)
  );
}

function u64(buf: Uint8Array, o: number): bigint {
  const lo = BigInt(u32(buf, o));
  const hi = BigInt(u32(buf, o + 4));
  return (hi << 32n) | lo;
}

/** Parse a ZIP64 extra field (id 0x0001); returns [uncomp, comp, localOffset]. */
function parseZip64Extra(extra: Uint8Array): Array<bigint | undefined> {
  let o = 0;
  const out: Array<bigint | undefined> = [undefined, undefined, undefined];
  while (o + 4 <= extra.length) {
    const id = u16(extra, o);
    const len = u16(extra, o + 2);
    o += 4;
    if (id === 0x0001) {
      let p = o;
      const take = (): bigint => {
        const v = u64(extra, p);
        p += 8;
        return v;
      };
      if (len >= 8) out[0] = take();
      if (len >= 16) out[1] = take();
      if (len >= 24) out[2] = take();
    }
    o += len;
  }
  return out;
}

interface CentralEntry {
  name: string;
  method: number;
  centralExtraLen: number;
  compSize: bigint;
  uncompSize: bigint;
  localHeaderOffset: bigint;
}

function parseCentralDirectory(buf: Uint8Array): CentralEntry[] {
  // Find the end-of-central-directory record: scan the last 64 KiB + 22 bytes.
  const scanStart = Math.max(0, buf.length - 65558);
  let eocd = -1;
  for (let i = buf.length - 22; i >= scanStart; i--) {
    if (u32(buf, i) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  let cdOffset: bigint;
  let cdCount: bigint;
  if (eocd >= 0) {
    cdCount = BigInt(u16(buf, eocd + 10));
    cdOffset = BigInt(u32(buf, eocd + 16));
  } else {
    // Try the ZIP64 EOCD locator.
    let locator = -1;
    for (let i = buf.length - 22; i >= scanStart; i--) {
      if (u32(buf, i) === 0x07064b50) {
        locator = i;
        break;
      }
    }
    if (locator < 0) throw new ZipError("no end-of-central-directory record");
    const eocd64 = u64(buf, locator + 8);
    if (eocd64 > BigInt(Number.MAX_SAFE_INTEGER)) throw new ZipError("ZIP64 EOCD offset too large");
    const o = Number(eocd64);
    if (u32(buf, o) !== 0x06064b50) throw new ZipError("bad ZIP64 end-of-central-directory");
    cdCount = u64(buf, o + 32);
    cdOffset = u64(buf, o + 48);
  }
  if (cdOffset > BigInt(Number.MAX_SAFE_INTEGER)) throw new ZipError("central directory offset too large");

  const entries: CentralEntry[] = [];
  let o = Number(cdOffset);
  for (let n = 0n; n < cdCount; n++) {
    if (u32(buf, o) !== 0x02014b50) throw new ZipError(`bad central directory entry ${n}`);
    const method = u16(buf, o + 10);
    let compSize = BigInt(u32(buf, o + 20));
    let uncompSize = BigInt(u32(buf, o + 24));
    const nameLen = u16(buf, o + 28);
    const extraLen = u16(buf, o + 30);
    const commentLen = u16(buf, o + 32);
    let localHeaderOffset = BigInt(u32(buf, o + 42));
    const nameBytes = buf.subarray(o + 46, o + 46 + nameLen);
    const extra = buf.subarray(o + 46 + nameLen, o + 46 + nameLen + extraLen);
    const name = new TextDecoder("utf-8", { fatal: false }).decode(nameBytes);
    if (
      compSize === 0xffffffffn ||
      uncompSize === 0xffffffffn ||
      localHeaderOffset === 0xffffffffn
    ) {
      const [zUncomp, zComp, zLocal] = parseZip64Extra(extra);
      if (compSize === 0xffffffffn && zComp !== undefined) compSize = zComp;
      if (uncompSize === 0xffffffffn && zUncomp !== undefined) uncompSize = zUncomp;
      if (localHeaderOffset === 0xffffffffn && zLocal !== undefined) localHeaderOffset = zLocal;
    }
    entries.push({ name, method, centralExtraLen: extraLen, compSize, uncompSize, localHeaderOffset });
    o += 46 + nameLen + extraLen + commentLen;
  }
  return entries;
}

/**
 * Parse a ZIP archive into its members, in central-directory order.
 * Throws ZipError on structural problems.
 */
export function parseZip(buf: Uint8Array): ZipMember[] {
  const central = parseCentralDirectory(buf);
  return central.map((c) => {
    if (c.localHeaderOffset > BigInt(Number.MAX_SAFE_INTEGER)) {
      throw new ZipError(`local header offset too large for ${c.name}`);
    }
    const lo = Number(c.localHeaderOffset);
    if (u32(buf, lo) !== 0x04034b50) throw new ZipError(`bad local header for ${c.name}`);
    const method = u16(buf, lo + 8);
    let compSize = BigInt(u32(buf, lo + 18));
    let uncompSize = BigInt(u32(buf, lo + 22));
    const nameLen = u16(buf, lo + 26);
    const extraLen = u16(buf, lo + 28);
    if (compSize === 0xffffffffn || uncompSize === 0xffffffffn) {
      const extra = buf.subarray(lo + 30 + nameLen, lo + 30 + nameLen + extraLen);
      const [zUncomp, zComp] = parseZip64Extra(extra);
      if (compSize === 0xffffffffn && zComp !== undefined) compSize = zComp;
      if (uncompSize === 0xffffffffn && zUncomp !== undefined) uncompSize = zUncomp;
    }
    const dataOffset = lo + 30 + nameLen + extraLen;
    const toNum = (v: bigint, what: string): number => {
      if (v > BigInt(Number.MAX_SAFE_INTEGER)) throw new ZipError(`${what} too large for ${c.name}`);
      return Number(v);
    };
    // Writers using data descriptors leave zero sizes in the local header;
    // fall back to the central directory sizes then.
    if (compSize === 0n && c.compSize !== 0n) compSize = c.compSize;
    if (uncompSize === 0n && c.uncompSize !== 0n) uncompSize = c.uncompSize;
    return {
      name: c.name,
      method,
      localExtraLen: extraLen,
      centralExtraLen: c.centralExtraLen,
      compSize: toNum(compSize, "compressed size"),
      uncompSize: toNum(uncompSize, "uncompressed size"),
      localHeaderOffset: lo,
      dataOffset,
    };
  });
}

/** Read (and decompress) a member's data. Only STORED and DEFLATE are supported. */
export function readMemberData(buf: Uint8Array, m: ZipMember): Uint8Array {
  const comp = buf.subarray(m.dataOffset, m.dataOffset + m.compSize);
  if (comp.length !== m.compSize) throw new ZipError(`truncated data for ${m.name}`);
  if (m.method === ZIP_STORED) return comp.slice();
  if (m.method === ZIP_DEFLATED) {
    const out = inflateRawSync(comp);
    if (out.length !== m.uncompSize) {
      throw new ZipError(`size mismatch after inflate for ${m.name}`);
    }
    return new Uint8Array(out.buffer, out.byteOffset, out.byteLength);
  }
  throw new ZipError(`unsupported compression method ${m.method} for ${m.name}`);
}

// ---------------------------------------------------------------------------
// writer
// ---------------------------------------------------------------------------

export interface ZipEntryInput {
  name: string;
  data: Uint8Array;
  method: typeof ZIP_STORED | typeof ZIP_DEFLATED;
}

const FIXED_DOS_TIME = 0; // 00:00:00
const FIXED_DOS_DATE = ((2026 - 1980) << 9) | (10 << 5) | 10; // 2026-10-10

function pushU16(out: number[], v: number): void {
  out.push(v & 0xff, (v >>> 8) & 0xff);
}

function pushU32(out: number[], v: number): void {
  out.push(v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff);
}

/**
 * Write a ZIP archive. Member order is exactly the input order; local headers
 * carry no extra field. No ZIP64 is emitted (writers use it only when needed).
 */
export function writeZip(entries: ZipEntryInput[]): Uint8Array {
  const chunks: Uint8Array[] = [];
  const central: number[] = [];
  let offset = 0;

  for (const e of entries) {
    const nameBytes = new TextEncoder().encode(e.name);
    const body = e.method === ZIP_STORED ? e.data : deflateRawSync(e.data, { level: 9 });
    const crc = crc32(e.data) >>> 0;
    const compLen = body.length;
    const fileLen = e.data.length;

    const lh: number[] = [];
    pushU32(lh, 0x04034b50); // local file header signature
    pushU16(lh, 20); // version needed
    pushU16(lh, 0); // flags
    pushU16(lh, e.method);
    pushU16(lh, FIXED_DOS_TIME);
    pushU16(lh, FIXED_DOS_DATE);
    pushU32(lh, crc);
    pushU32(lh, compLen);
    pushU32(lh, fileLen);
    pushU16(lh, nameBytes.length);
    pushU16(lh, 0); // extra field length: none

    const header = new Uint8Array(lh);
    chunks.push(header, nameBytes, body);

    const ch: number[] = [];
    pushU32(ch, 0x02014b50); // central directory signature
    pushU16(ch, 20); // version made by
    pushU16(ch, 20); // version needed
    pushU16(ch, 0); // flags
    pushU16(ch, e.method);
    pushU16(ch, FIXED_DOS_TIME);
    pushU16(ch, FIXED_DOS_DATE);
    pushU32(ch, crc);
    pushU32(ch, compLen);
    pushU32(ch, fileLen);
    pushU16(ch, nameBytes.length);
    pushU16(ch, 0); // extra length
    pushU16(ch, 0); // comment length
    pushU16(ch, 0); // disk number
    pushU16(ch, 0); // internal attrs
    pushU32(ch, 0); // external attrs
    pushU32(ch, offset); // local header offset
    central.push(...ch, ...nameBytes);

    offset += header.length + nameBytes.length + body.length;
  }

  const cdStart = offset;
  const cdBytes = new Uint8Array(central);
  chunks.push(cdBytes);
  offset += cdBytes.length;

  const eocd: number[] = [];
  pushU32(eocd, 0x06054b50);
  pushU16(eocd, 0); // disk number
  pushU16(eocd, 0); // cd start disk
  pushU16(eocd, entries.length);
  pushU16(eocd, entries.length);
  pushU32(eocd, cdBytes.length);
  pushU32(eocd, cdStart);
  pushU16(eocd, 0); // comment length
  chunks.push(new Uint8Array(eocd));

  const total = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Uint8Array(total);
  let p = 0;
  for (const c of chunks) {
    out.set(c, p);
    p += c.length;
  }
  return out;
}
