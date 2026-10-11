// Copyright 2026 Jared Zimmerman
// SPDX-License-Identifier: Apache-2.0
//
// SHA-256 helpers (one-shot and streaming).

import { createHash, type Hash } from "node:crypto";

export function sha256Hex(data: Uint8Array | string): string {
  return createHash("sha256").update(data).digest("hex");
}

export function sha256Bytes(data: Uint8Array | string): Uint8Array {
  return createHash("sha256").update(data).digest();
}

/** Streaming SHA-256; feed uneven chunks, then digest. */
export class Sha256Stream {
  private h: Hash = createHash("sha256");
  update(chunk: Uint8Array): this {
    this.h.update(chunk);
    return this;
  }
  hex(): string {
    return this.h.digest("hex");
  }
  bytes(): Uint8Array {
    return this.h.digest();
  }
}
