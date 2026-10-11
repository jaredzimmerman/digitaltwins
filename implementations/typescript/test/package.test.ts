// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  parseJson,
  canonicalJson,
  canonicalBytes,
  compareCodePoints,
  JsonError,
} from "../src/json.js";
import { parseZip, readMemberData, writeZip, ZIP_STORED, ZIP_DEFLATED } from "../src/zip.js";
import { sha256Hex } from "../src/bytes.js";
import { PrsnPackage, PrsnBuilder, generateKey } from "../src/package.js";
import { buildInteropPackage } from "../src/package.js";

const enc = new TextEncoder();

function localHeader(buf: Uint8Array, offset: number) {
  const u16 = (o: number) => buf[o] | (buf[o + 1] << 8);
  const u32 = (o: number) =>
    buf[o] | (buf[o + 1] << 8) | (buf[o + 2] << 16) | buf[o + 3] * 0x1000000;
  return {
    sig: u32(offset),
    method: u16(offset + 8),
    nameLen: u16(offset + 26),
    extraLen: u16(offset + 28),
    compLen: u32(offset + 18),
  };
}

describe("ZIP writer byte layout", () => {
  it("writes mimetype first, STORED, no extra field, exact bytes", async () => {
    const { zip } = buildInteropPackage();
    const h = localHeader(zip, 0);
    assert.equal(h.sig, 0x04034b50);
    assert.equal(h.method, ZIP_STORED);
    assert.equal(h.extraLen, 0);
    assert.equal(h.nameLen, 8);
    const name = new TextDecoder().decode(zip.subarray(30, 30 + h.nameLen));
    assert.equal(name, "mimetype");
    const data = zip.subarray(30 + h.nameLen, 30 + h.nameLen + h.compLen);
    assert.equal(new TextDecoder().decode(data), "application/vnd.prsn+zip");
  });

  it("member order follows the fixed interop order", () => {
    const { zip } = buildInteropPackage();
    const names = parseZip(zip).map((m) => m.name);
    assert.deepEqual(names, [
      "mimetype",
      "manifest.json",
      "person.json",
      "face/samples/f-0001.bin",
      "voice/samples/s-0001.bin",
      "signatures/manifest.sig",
    ]);
  });

  it("round-trips member data through the reader", () => {
    const { zip } = buildInteropPackage();
    const members = parseZip(zip);
    const byName = new Map(members.map((m) => [m.name, m]));
    const face = readMemberData(zip, byName.get("face/samples/f-0001.bin")!);
    assert.equal(new TextDecoder().decode(face), "hello prsn");
    const voice = readMemberData(zip, byName.get("voice/samples/s-0001.bin")!);
    assert.equal(new TextDecoder().decode(voice), "voice sample");
    assert.equal(byName.get("signatures/manifest.sig")!.compSize, 64);
  });
});

describe("canonical JSON edge cases", () => {
  it("sorts keys by code point, not UTF-16 code units", () => {
    // U+1F600 vs U+E000: UTF-16 order would put U+1F600 (D83D) first;
    // code-point order puts U+E000 first.
    const v = parseJson(enc.encode('{"\\ud83d\\ude00":1,"\\ue000":2}'));
    assert.equal(canonicalJson(v), '{"":2,"😀":1}');
    assert.ok(compareCodePoints("😀", "") > 0);
    assert.ok(compareCodePoints("", "😀") < 0);
  });

  it("keeps int64 integers exact and renders doubles like Number.prototype.toString", () => {
    assert.equal(canonicalJson(parseJson(enc.encode("9007199254740993"))), "9007199254740993");
    assert.equal(canonicalJson(parseJson(enc.encode("9223372036854775807"))), "9223372036854775807");
    assert.equal(canonicalJson(parseJson(enc.encode("-0.0"))), "0");
    assert.equal(canonicalJson(parseJson(enc.encode("1e-7"))), "1e-7");
  });

  it("rejects strictness violations", () => {
    for (const bad of [
      '{"a":1,"a":2}',
      '"\\ud800"',
      "[1,2,]",
      "01",
      "+1",
      ".5",
      "1.",
      "1e",
      "NaN",
      "--1",
      "{} x",
      "",
      "//c\n1",
      '"\\x41"',
    ]) {
      assert.throws(() => parseJson(enc.encode(bad)), JsonError, bad);
    }
    assert.throws(() => parseJson(new Uint8Array([0x22, 0xc0, 0xaf, 0x22])), JsonError); // overlong
    assert.throws(() => parseJson(new Uint8Array([0xef, 0xbb, 0xbf, 0x7b, 0x7d])), JsonError); // BOM
  });
});

describe("package round-trip", () => {
  it("build -> verify -> extract bytes", async () => {
    const { zip, keyId } = buildInteropPackage();
    const pkg = PrsnPackage.fromZipBytes(zip);
    const r = pkg.verifyIntegrity();
    assert.ok(r.ok, JSON.stringify(r.issues));
    assert.equal(r.signed, true);
    assert.equal(r.keyId, keyId);
    assert.equal(r.trusted, false); // fresh key is not in the trusted set
    const entries = pkg.listEntries();
    assert.deepEqual(
      entries.map((e) => e.path),
      ["face/samples/f-0001.bin", "person.json", "voice/samples/s-0001.bin"],
    );
    assert.equal(new TextDecoder().decode(pkg.readEntryBytes("face/samples/f-0001.bin")), "hello prsn");
    assert.equal(new TextDecoder().decode(pkg.readEntryBytes("voice/samples/s-0001.bin")), "voice sample");
    const person = pkg.person() as unknown as { display_name: string };
    assert.ok(person !== null);
  });

  it("accepts the legacy mimetype on read", async () => {
    const builder = new PrsnBuilder({ created: "2026-10-10T00:00:00Z" });
    const kp = generateKey();
    builder.setPerson(
      parseJson(enc.encode('{"id":"urn:uuid:3b1f2a4c-9d5e-4f6a-8b7c-1d2e3f4a5b6c","display_name":"X","aliases":[],"ids":[],"links":[]}')),
    );
    const { manifestBytes, signature } = builder.buildManifest(kp.seed);
    const personBytes = canonicalBytes(
      parseJson(enc.encode('{"id":"urn:uuid:3b1f2a4c-9d5e-4f6a-8b7c-1d2e3f4a5b6c","display_name":"X","aliases":[],"ids":[],"links":[]}')),
    );
    const zip = writeZip([
      { name: "mimetype", data: enc.encode("application/vnd.museli.prsn+zip"), method: ZIP_STORED },
      { name: "manifest.json", data: manifestBytes, method: ZIP_DEFLATED },
      { name: "person.json", data: personBytes, method: ZIP_DEFLATED },
      { name: "signatures/manifest.sig", data: signature!, method: ZIP_STORED },
    ]);
    const pkg = PrsnPackage.fromZipBytes(zip);
    assert.deepEqual(pkg.containerIssues, []);
    const r = pkg.verifyIntegrity();
    assert.ok(r.ok, JSON.stringify(r.issues));
    assert.equal(r.signed, true);
  });

  it("directory packages verify too", async () => {
    const dir = mkdtempSync(join(tmpdir(), "prsn-ts-"));
    const builder = new PrsnBuilder({ generator: "prsn-ts 0.1.0", created: "2026-10-10T00:00:00Z" });
    const kp = generateKey();
    builder.setPerson(
      parseJson(enc.encode('{"id":"urn:uuid:3b1f2a4c-9d5e-4f6a-8b7c-1d2e3f4a5b6c","display_name":"Interop Test","aliases":[],"ids":[],"links":[]}')),
    );
    builder.addEntry("face/samples/f-0001.bin", enc.encode("hello prsn"), {
      type: "org.prsn.face.sample",
      media: "application/octet-stream",
      fields: {},
    });
    await builder.writeDir(dir, kp.seed);
    const pkg = await PrsnPackage.open(dir);
    const r = pkg.verifyIntegrity();
    assert.ok(r.ok, JSON.stringify(r.issues));
    assert.equal(r.signed, true);
    assert.equal(new TextDecoder().decode(pkg.readEntryBytes("face/samples/f-0001.bin")), "hello prsn");
  });

  it("a trusted signer keeps tiers; an untrusted one downgrades", async () => {
    const { zip } = buildInteropPackage();
    // signer's key is unknown -> downgrade applies (no top tiers in fixture, so no-op here)
    const pkg = PrsnPackage.fromZipBytes(zip);
    assert.equal(pkg.isTrustedSigner(), false);
    // trust the fixture's own key -> trusted
    const keyId = pkg.verifyIntegrity().keyId!;
    const trusted = PrsnPackage.fromZipBytes(zip, [keyId]);
    assert.equal(trusted.isTrustedSigner(), true);
  });

  it("detects tampering", async () => {
    const { zip } = buildInteropPackage();
    const bad = new Uint8Array(zip);
    // flip a byte inside the deflated face sample payload region (last bytes of file area)
    bad[bad.length - 100] ^= 1;
    const pkg = PrsnPackage.fromZipBytes(bad);
    const r = pkg.verifyIntegrity();
    assert.equal(r.ok, false);
    assert.ok(r.issues.some((i) => i.rule === "manifest-hash" || i.rule === "signature"));
  });

  it("unsigned packages verify as unsigned", async () => {
    const builder = new PrsnBuilder({ created: "2026-10-10T00:00:00Z" });
    builder.setPerson(
      parseJson(enc.encode('{"id":"urn:uuid:3b1f2a4c-9d5e-4f6a-8b7c-1d2e3f4a5b6c","display_name":"X","aliases":[],"ids":[],"links":[]}')),
    );
    const zip = builder.buildZip(); // no seed -> unsigned
    const pkg = PrsnPackage.fromZipBytes(zip);
    const r = pkg.verifyIntegrity();
    assert.ok(r.ok, JSON.stringify(r.issues));
    assert.equal(r.signed, false);
    assert.equal(r.keyId, null);
  });
});

describe("sha256", () => {
  it("matches the empty-string vector", () => {
    assert.equal(
      sha256Hex(new Uint8Array()),
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
  });
});
