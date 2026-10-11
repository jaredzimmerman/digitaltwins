# Copyright 2026 Jared Zimmerman
# SPDX-License-Identifier: Apache-2.0
"""The ``prsn`` command line: canon, build, verify, vectors."""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

from . import keys
from .canonical import JSONError, canonical, parse
from .package import Builder, PrsnError, open_package, sha256_hex
from .vectors import run_suites

# The fixed interop test package (identical semantics across implementations).
FIXED_CREATED = "2026-10-10T00:00:00Z"
FIXED_GENERATOR = "prsn-py 0.1.0"
FIXED_PERSON = {
    "id": "urn:uuid:3b1f2a4c-9d5e-4f6a-8b7c-1d2e3f4a5b6c",
    "display_name": "Interop Test",
    "aliases": [],
    "ids": [],
    "links": [],
}
FIXED_ORIGIN = {"tier": "imported", "how": "interop-fixture", "at": FIXED_CREATED}
FIXED_MEMBER_ORDER = [
    "mimetype",
    "manifest.json",
    "person.json",
    "face/samples/f-0001.bin",
    "voice/samples/s-0001.bin",
    "signatures/manifest.sig",
]


def cmd_canon(path: str) -> int:
    """Strict-parse, canonical-serialise, print the SHA-256 of the bytes."""
    try:
        value = parse(Path(path).read_bytes())
    except (JSONError, OSError) as e:
        print(f"canon: error: {e}", file=sys.stderr)
        return 1
    print(sha256_hex(canonical(value)))
    return 0


def build_fixed_package(dest: str | Path, seed: bytes | None = None) -> keys.KeyPair | None:
    """Write the fixed interop test package, optionally signed."""
    b = Builder(generator=FIXED_GENERATOR, created=FIXED_CREATED)
    b.set_person(dict(FIXED_PERSON))
    b.add_entry(
        "face/samples/f-0001.bin",
        "org.prsn.face.sample",
        "application/octet-stream",
        b"hello prsn",
        origin=dict(FIXED_ORIGIN),
    )
    b.add_entry(
        "voice/samples/s-0001.bin",
        "org.prsn.voice.sample",
        "application/octet-stream",
        b"voice sample",
        origin=dict(FIXED_ORIGIN),
    )
    return b.write_zip(dest, seed=seed, member_order=FIXED_MEMBER_ORDER)


def cmd_build(out: str) -> int:
    """Write the fixed test package signed with a fresh key."""
    keypair = build_fixed_package(out, seed=secrets.token_bytes(32))
    assert keypair is not None
    print(f"public_key={keypair.public_key_b64} key_id={keypair.key_id}")
    return 0


def cmd_verify(path: str) -> int:
    """Full integrity verification of a .prsn ZIP or directory package."""
    try:
        pkg = open_package(path, trusted_keys=[])
    except PrsnError as e:
        print(f"verify: error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"verify: error: {e}", file=sys.stderr)
        return 1
    print("VERIFY OK")
    if pkg.signature.present and pkg.signature.verified:
        print(f"signed key_id={pkg.signature.key_id}")
    elif pkg.signature.present:
        print("signed (unverified algorithm)")
    else:
        print("unsigned")
    for note in pkg.notes:
        print(f"note: {note.message}")
    return 0


def cmd_vectors(conformance_dir: str) -> int:
    """Run all v1-relevant conformance vector suites."""
    total_pass, total_fail = 0, 0
    for name, (passed, failed, bad) in run_suites(Path(conformance_dir)):
        print(f"{name}: {passed} passed, {failed} failed")
        for label in bad:
            print(f"    FAIL: {label}")
        total_pass += passed
        total_fail += failed
    print(f"TOTAL: {total_pass} passed, {total_fail} failed")
    return 1 if total_fail else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="prsn", description="Reader/writer for .prsn digital-twin files")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_canon = sub.add_parser("canon", help="canonicalise JSON and print its SHA-256")
    p_canon.add_argument("input", help="input JSON file")

    p_build = sub.add_parser("build", help="write the fixed interop test package")
    p_build.add_argument("out", help="output .prsn path")

    p_verify = sub.add_parser("verify", help="verify a .prsn file or directory package")
    p_verify.add_argument("path", help=".prsn file or directory")

    p_vectors = sub.add_parser("vectors", help="run the conformance vector suites")
    p_vectors.add_argument("conformance_dir", help="prsn/conformance directory")

    args = ap.parse_args(argv)
    if args.cmd == "canon":
        return cmd_canon(args.input)
    if args.cmd == "build":
        return cmd_build(args.out)
    if args.cmd == "verify":
        return cmd_verify(args.path)
    if args.cmd == "vectors":
        return cmd_vectors(args.conformance_dir)
    ap.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
