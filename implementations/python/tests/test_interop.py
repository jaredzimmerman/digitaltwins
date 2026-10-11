# Copyright 2026 Jared Zimmerman
# SPDX-License-Identifier: Apache-2.0
"""Build -> byte-inspect -> verify -> round-trip for the fixed interop package."""

import struct
import zipfile

import pytest

from prsn import keys, open_package
from prsn.cli import FIXED_MEMBER_ORDER, build_fixed_package

EXPECTED_PERSON = (
    b'{"aliases":[],"display_name":"Interop Test",'
    b'"id":"urn:uuid:3b1f2a4c-9d5e-4f6a-8b7c-1d2e3f4a5b6c","ids":[],"links":[]}'
)


@pytest.fixture()
def built_prsn(tmp_path):
    out = tmp_path / "interop.prsn"
    seed = bytes(range(32))
    keypair = build_fixed_package(out, seed=seed)
    return out, keypair, seed


def test_member_order_and_compression(built_prsn):
    out, _, _ = built_prsn
    with zipfile.ZipFile(out) as z:
        names = [i.filename for i in z.infolist()]
        assert names == FIXED_MEMBER_ORDER
        methods = {i.filename: i.compress_type for i in z.infolist()}
        assert methods["mimetype"] == zipfile.ZIP_STORED
        assert methods["manifest.json"] == zipfile.ZIP_DEFLATED
        assert methods["signatures/manifest.sig"] == zipfile.ZIP_STORED


def test_mimetype_first_local_header(built_prsn):
    """Byte-inspect: mimetype is the first local header, method 0, no extra
    field, exact content bytes."""
    out, _, _ = built_prsn
    raw = out.read_bytes()
    assert raw[0:4] == b"PK\x03\x04"
    assert struct.unpack("<H", raw[8:10])[0] == 0  # method: STORED
    assert struct.unpack("<H", raw[26:28])[0] == 8  # file name length
    assert struct.unpack("<H", raw[28:30])[0] == 0  # extra field length
    assert raw[30:38] == b"mimetype"
    size = struct.unpack("<I", raw[18:22])[0]
    assert raw[38 : 38 + size] == b"application/vnd.prsn+zip"


def test_fixed_package_contents(built_prsn):
    out, _, _ = built_prsn
    with zipfile.ZipFile(out) as z:
        assert z.read("person.json") == EXPECTED_PERSON
        assert z.read("face/samples/f-0001.bin") == b"hello prsn"
        assert z.read("voice/samples/s-0001.bin") == b"voice sample"
        assert len(z.read("signatures/manifest.sig")) == 64
        m = z.read("manifest.json").decode()
    assert '"format":"prsn"' in m and '"version":1' in m and '"spec":"1.1"' in m
    assert '"created":"2026-10-10T00:00:00Z"' in m
    assert '"generator":"prsn-py 0.1.0"' in m
    # entries sorted by path in UTF-8 byte order
    assert m.index("face/samples/f-0001.bin") < m.index('"path":"person.json"') < m.index(
        "voice/samples/s-0001.bin"
    )


def test_signature_verifies_with_built_key(built_prsn):
    out, keypair, seed = built_prsn
    pkg = open_package(out)
    assert pkg.signature.present and pkg.signature.verified
    assert pkg.signature.key_id == keypair.key_id
    # independent check with a raw verify over the canonical manifest
    with zipfile.ZipFile(out) as z:
        body = z.read("manifest.json")
        sig = z.read("signatures/manifest.sig")
    assert keys.verify(keypair.public_key, body, sig)
    assert pkg.manifest["signature"]["public_key"] == keypair.public_key_b64


def test_round_trip_entry_bytes(built_prsn):
    out, _, _ = built_prsn
    pkg = open_package(out)
    pkg.verify_integrity()
    assert pkg.read_entry_bytes("face/samples/f-0001.bin") == b"hello prsn"
    assert pkg.read_entry_bytes("voice/samples/s-0001.bin") == b"voice sample"
    assert pkg.read_entry_bytes("person.json") == EXPECTED_PERSON
    assert [e["path"] for e in pkg.list_entries()] == [
        "face/samples/f-0001.bin",
        "person.json",
        "voice/samples/s-0001.bin",
    ]


def test_deterministic_build_same_seed_same_bytes(tmp_path):
    a, b = tmp_path / "a.prsn", tmp_path / "b.prsn"
    seed = bytes(range(32))
    build_fixed_package(a, seed=seed)
    build_fixed_package(b, seed=seed)
    assert a.read_bytes() == b.read_bytes()  # Ed25519 is deterministic
