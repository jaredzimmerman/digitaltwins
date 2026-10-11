# Copyright 2026 Jared Zimmerman
# SPDX-License-Identifier: Apache-2.0
"""CLI smoke tests: canon, build, verify, vectors."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PRSN = [sys.executable, "-m", "prsn"]


def run(*args, cwd=None):
    return subprocess.run(PRSN + list(args), capture_output=True, text=True, cwd=cwd)


def test_canon_ok(tmp_path):
    p = tmp_path / "in.json"
    p.write_text('{ "b" : 1 , "a" : [1, 2] }')
    r = run("canon", str(p))
    assert r.returncode == 0
    assert r.stdout.strip() == "94a786c3662bc7beeb598efa7d8cb58d7bea25d6c275ea9785a0230ff1f8c2ba"


def test_canon_rejects_invalid(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"a": 01}')
    r = run("canon", str(p))
    assert r.returncode != 0
    assert r.stderr


def test_build_and_verify(tmp_path):
    out = tmp_path / "t.prsn"
    r = run("build", str(out))
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("public_key=") and " key_id=" in r.stdout
    r = run("verify", str(out))
    assert r.returncode == 0, r.stderr
    assert "VERIFY OK" in r.stdout
    assert "signed key_id=" in r.stdout


def test_verify_rejects_tampered(tmp_path):
    import zipfile

    out = tmp_path / "t.prsn"
    assert run("build", str(out)).returncode == 0
    # flip a byte inside the detached signature member
    with zipfile.ZipFile(out) as z:
        members = [(i.filename, z.read(i.filename)) for i in z.infolist()]
    tampered = [
        (name, bytes(b[:10] + bytes([b[10] ^ 0xFF]) + b[11:]) if name == "signatures/manifest.sig" else b)
        for name, b in members
    ]
    with zipfile.ZipFile(out, "w") as z:
        for name, data in tampered:
            z.writestr(name, data)
    r = run("verify", str(out))
    assert r.returncode != 0
    assert "VERIFY OK" not in r.stdout
    assert "signature" in r.stderr


def test_verify_directory_package(tmp_path):
    # unpack the fixed package layout as a directory and verify it
    import zipfile

    out = tmp_path / "t.prsn"
    assert run("build", str(out)).returncode == 0
    d = tmp_path / "pkgdir"
    with zipfile.ZipFile(out) as z:
        z.extractall(d)
    (d / "mimetype").unlink()  # directory form does not require it
    r = run("verify", str(d))
    assert r.returncode == 0, r.stderr
    assert "VERIFY OK" in r.stdout


def test_vectors_cli(conformance_dir):
    r = run("vectors", str(conformance_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TOTAL:" in r.stdout
    assert ", 0 failed" in r.stdout
