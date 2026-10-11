// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//
// Ed25519 (RFC 8032) via @noble/curves: deterministic signing, key derivation,
// key ids. Keys are per install: a 32-byte seed generated locally.

import { randomBytes } from "node:crypto";
import { ed25519 } from "@noble/curves/ed25519.js";
import { sha256Hex } from "./bytes.js";

export interface KeyPair {
  /** 32-byte seed (the private key). */
  seed: Uint8Array;
  /** Raw 32-byte public key. */
  publicKey: Uint8Array;
  /** Standard base64 with padding of the raw public key (manifest form). */
  publicKeyB64: string;
  /** First 16 hex chars of SHA-256(raw public key). */
  keyId: string;
}

/** Generate a fresh Ed25519 key pair from 32 random bytes. */
export function generateKey(): KeyPair {
  const seed = randomBytes(32);
  return keyPairFromSeed(seed);
}

/** Derive the key pair from an explicit 32-byte seed. */
export function keyPairFromSeed(seed: Uint8Array): KeyPair {
  if (seed.length !== 32) throw new Error("Ed25519 seed must be 32 bytes");
  const publicKey = ed25519.getPublicKey(seed);
  const publicKeyB64 = Buffer.from(publicKey).toString("base64");
  return { seed, publicKey, publicKeyB64, keyId: keyIdOf(publicKey) };
}

/** key_id = first 16 hex chars of SHA-256(raw public key). */
export function keyIdOf(publicKey: Uint8Array): string {
  if (publicKey.length !== 32) throw new Error("Ed25519 public key must be 32 bytes");
  return sha256Hex(publicKey).slice(0, 16);
}

/** Decode a manifest `public_key` (standard base64, padded) to raw bytes. */
export function decodePublicKey(b64: string): Uint8Array {
  let raw: Buffer;
  try {
    raw = Buffer.from(b64, "base64");
  } catch {
    throw new Error("public_key is not valid base64");
  }
  if (raw.length !== 32) throw new Error("public_key is not 32 bytes");
  // Reject non-canonical encodings (whitespace etc.): re-encode must match.
  if (raw.toString("base64") !== b64.replace(/\s+/g, "")) {
    throw new Error("public_key is not canonical base64");
  }
  return new Uint8Array(raw);
}

/** Deterministic RFC 8032 signature over msg. */
export function edSign(seed: Uint8Array, msg: Uint8Array): Uint8Array {
  return ed25519.sign(msg, seed);
}

/** Verify; false on any failure (bad lengths, bad signature, exceptions). */
export function edVerify(publicKey: Uint8Array, msg: Uint8Array, sig: Uint8Array): boolean {
  try {
    if (publicKey.length !== 32 || sig.length !== 64) return false;
    return ed25519.verify(sig, msg, publicKey);
  } catch {
    return false;
  }
}
