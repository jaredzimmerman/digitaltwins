// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//
// prsn-ts CLI:
//   canon <input.json>        strict-parse, canonical-serialize, print SHA-256 hex
//   build <out.prsn>          write the fixed interop test package, signed
//   verify <file.prsn|dir>    container + hashes + signature verification
//   vectors <conformance-dir> run the v1 conformance vector suites

import { readFile, writeFile, stat } from "node:fs/promises";
import { parseJson, canonicalBytes, JsonError } from "./json.js";
import { sha256Hex } from "./bytes.js";
import { PrsnPackage, buildInteropPackage } from "./package.js";
import { runVectors } from "./vectors.js";

function fail(message: string): never {
  process.stderr.write(`error: ${message}\n`);
  process.exit(1);
}

async function cmdCanon(input: string): Promise<void> {
  let data: Uint8Array;
  try {
    data = new Uint8Array(await readFile(input));
  } catch (e) {
    fail(`cannot read ${input}: ${(e as Error).message}`);
  }
  let bytes: Uint8Array;
  try {
    bytes = canonicalBytes(parseJson(data!));
  } catch (e) {
    if (e instanceof JsonError) fail(`invalid JSON: ${e.message}`);
    throw e;
  }
  process.stdout.write(sha256Hex(bytes!) + "\n");
}

async function cmdBuild(out: string): Promise<void> {
  const { zip, publicKeyB64, keyId } = buildInteropPackage();
  try {
    await writeFile(out, zip);
  } catch (e) {
    fail(`cannot write ${out}: ${(e as Error).message}`);
  }
  process.stdout.write(`public_key=${publicKeyB64} key_id=${keyId}\n`);
}

async function cmdVerify(target: string): Promise<void> {
  let pkg: PrsnPackage;
  try {
    pkg = await PrsnPackage.open(target);
  } catch (e) {
    fail(`cannot open ${target}: ${(e as Error).message}`);
  }
  const r = pkg!.verifyIntegrity();
  if (!r.ok) {
    for (const i of r.issues) {
      process.stderr.write(`[${i.rule}] ${i.message}\n`);
    }
    process.exit(1);
  }
  process.stdout.write("VERIFY OK\n");
  process.stdout.write(r.signed ? `signed key_id=${r.keyId}\n` : "unsigned\n");
  if (r.downgradedOrigins > 0 || r.downgradedEvidence > 0) {
    process.stdout.write(
      `note: tier downgrade applied (signer not trusted): ` +
        `${r.downgradedOrigins} origin(s), ${r.downgradedEvidence} evidence move(s)\n`,
    );
  }
}

async function cmdVectors(conformanceDir: string): Promise<void> {
  let st: { isDirectory(): boolean };
  try {
    st = await stat(conformanceDir);
  } catch {
    fail(`no such directory: ${conformanceDir}`);
  }
  if (!st!.isDirectory()) fail(`not a directory: ${conformanceDir}`);
  const suites = await runVectors(conformanceDir);
  let anyFail = false;
  for (const s of suites) {
    process.stdout.write(`${s.name}: ${s.passed} passed, ${s.failed} failed\n`);
    for (const f of s.failures) process.stdout.write(`    FAIL ${f}\n`);
    if (s.failed > 0) anyFail = true;
  }
  if (anyFail) process.exit(1);
}

async function main(): Promise<void> {
  const [, , cmd, arg] = process.argv;
  switch (cmd) {
    case "canon":
      if (!arg) fail("usage: canon <input.json>");
      await cmdCanon(arg);
      break;
    case "build":
      if (!arg) fail("usage: build <out.prsn>");
      await cmdBuild(arg);
      break;
    case "verify":
      if (!arg) fail("usage: verify <file.prsn|dir>");
      await cmdVerify(arg);
      break;
    case "vectors":
      if (!arg) fail("usage: vectors <conformance-dir>");
      await cmdVectors(arg);
      break;
    default:
      process.stderr.write(
        "usage: prsn-ts <canon|build|verify|vectors> [args]\n" +
          "  canon <input.json>        strict-parse, canonicalize, print SHA-256 hex\n" +
          "  build <out.prsn>          write the fixed interop test package (signed)\n" +
          "  verify <file.prsn|dir>    verify container, hashes, signature\n" +
          "  vectors <conformance-dir> run the v1 conformance vector suites\n",
      );
      process.exit(2);
  }
}

// Only run the CLI when executed directly, not when imported (e.g. by tests).
const isMain = typeof require !== "undefined" && require.main === module;
if (isMain) {
  main().catch((e) => {
    process.stderr.write(`error: ${(e as Error).message}\n`);
    process.exit(1);
  });
}
