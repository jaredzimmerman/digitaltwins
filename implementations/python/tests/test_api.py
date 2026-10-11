# Copyright 2026 Jared Zimmerman
# SPDX-License-Identifier: Apache-2.0
"""Public API behaviour: keys, builder, tier trust, person mapping, refusals."""

import io
import zipfile

import pytest

from prsn import (
    ActionKeyError,
    Builder,
    JSONError,
    PrsnError,
    action_key,
    apply_tier_downgrade,
    canonical,
    dumps,
    generate_key,
    key_id,
    keypair_from_seed,
    map_legacy_person,
    open_package,
    parse,
    preimage,
    public_key_from_seed,
)
from prsn import keys as keys_mod
from prsn.cli import build_fixed_package


def _pkg_bytes(**kw):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", b"application/vnd.prsn+zip")
        z.writestr("manifest.json", kw.get("manifest", b'{"format":"prsn","version":1,"entries":[]}'))
    buf.seek(0)
    return buf.read()


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return p


# -- canonical JSON edge cases beyond the vectors --------------------------- #


def test_parse_rejects_bom_and_controls():
    with pytest.raises(JSONError):
        parse(b"\xef\xbb\xbf{}")
    with pytest.raises(JSONError):
        parse('"\x01"')


def test_duplicate_keys_rejected_at_depth():
    with pytest.raises(JSONError):
        parse('{"a": {"x": 1, "x": 2}}')
    with pytest.raises(JSONError):
        parse('[{"k": 1}, {"k": 1, "k": 2}]')


def test_int64_boundaries():
    assert parse("9223372036854775807") == 2**63 - 1
    assert parse("-9223372036854775808") == -(2**63)
    assert isinstance(parse("9223372036854775808"), float)
    assert dumps(2**63 - 1) == "9223372036854775807"


def test_float_layout_spot_checks():
    assert dumps(0.000001) == "0.000001"
    assert dumps(1e21) == "1e+21"
    assert dumps(1e-7) == "1e-7"
    assert dumps(-0.0) == "0"
    assert dumps(12.5) == "12.5"
    assert dumps(100.0) == "100"
    with pytest.raises(JSONError):
        dumps(float("nan"))
    with pytest.raises(JSONError):
        dumps(float("inf"))


def test_key_sort_is_code_point_order():
    assert dumps({"é": 1, "z": 2, "😀": 3}) == '{"z":2,"é":1,"😀":3}'


# -- keys -------------------------------------------------------------------- #


def test_keygen_and_key_id():
    kp = generate_key()
    assert len(kp.seed) == 32 and len(kp.public_key) == 32
    assert kp.key_id == key_id(kp.public_key) == key_id(public_key_from_seed(kp.seed))
    assert len(kp.key_id) == 16
    sig = keys_mod.sign(kp.seed, b"msg")
    assert len(sig) == 64
    assert keys_mod.verify(kp.public_key, b"msg", sig)
    assert not keys_mod.verify(kp.public_key, b"msg!", sig)
    # deterministic
    assert keys_mod.sign(kp.seed, b"msg") == sig


def test_rfc8032_test_vector():
    seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    pub = public_key_from_seed(seed)
    assert pub.hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    assert key_id(pub) == "21fe31dfa154a261"


# -- action_key --------------------------------------------------------------- #


def test_action_key_minimal():
    d = {"family": "f", "recipe": {"id": "r", "version": "1"}}
    assert action_key(d) == "sha256:" + __import__("hashlib").sha256(preimage(d)).hexdigest()
    pre = preimage(d).decode()
    assert '"models":[]' in pre and '"inputs":[]' in pre and '"params":{}' in pre


def test_action_key_rejections():
    for bad in [
        {"recipe": {"id": "r", "version": "1"}},  # no family
        {"family": "f", "recipe": {"id": "r"}},  # no recipe.version
        {"family": "f", "recipe": {"id": "r", "version": "1"}, "params": [1]},
        {"family": "f", "recipe": {"id": "r", "version": "1"}, "models": [{"key": "k"}]},
        {"family": "f", "recipe": {"id": "r", "version": "1"}, "inputs": [{"role": "x"}]},
    ]:
        with pytest.raises(ActionKeyError):
            action_key(bad)


# -- tier downgrade trust ----------------------------------------------------- #


def test_downgrade_trusted_untouched():
    entries = [{"path": "p", "origin": {"tier": "enrolled"}, "evidence": {"enrolled": 3.0}}]
    assert apply_tier_downgrade(entries, True) == entries
    # input not mutated
    assert entries[0]["origin"]["tier"] == "enrolled"


def test_open_applies_downgrade_only_when_untrusted(tmp_path):
    out = tmp_path / "t.prsn"
    kp = keypair_from_seed(bytes(range(32)))
    build_fixed_package(out, seed=kp.seed)
    untrusted = open_package(out, trusted_keys=[])
    assert not untrusted.trusted
    trusted = open_package(out, trusted_keys=[kp.key_id])
    assert trusted.trusted
    # interop fixture is already imported-tier: nothing changes either way
    assert untrusted.list_entries() == trusted.list_entries()


# -- person mapping ------------------------------------------------------------ #


def test_map_legacy_person():
    got = map_legacy_person(
        {"id": "x", "name": "N", "ids": {"a": "1"}, "links": {"h": "https://e/"}}
    )
    assert got["display_name"] == "N" and "name" not in got
    assert got["ids"] == [{"scheme": "a", "value": "1"}]
    assert got["links"] == [{"rel": "h", "href": "https://e/"}]


# -- refusals ------------------------------------------------------------------ #


def test_refuse_duplicate_member(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", b"application/vnd.prsn+zip")
        z.writestr("manifest.json", b'{"format":"prsn","version":1,"entries":[]}')
        z.writestr("manifest.json", b'{"format":"prsn","version":1,"entries":[]}')
    p = _write(tmp_path, "dup.prsn", buf.getvalue())
    with pytest.raises(PrsnError) as ei:
        open_package(p)
    assert ei.value.rule == "container"


def test_refuse_version_too_new(tmp_path):
    man = canonical({"format": "prsn", "version": 2, "entries": []})
    p = _write(tmp_path, "v2.prsn", _pkg_bytes(manifest=man))
    with pytest.raises(PrsnError) as ei:
        open_package(p)
    assert ei.value.rule == "version"


def test_read_entry_bytes_rejects_unlisted(tmp_path):
    out = tmp_path / "i.prsn"
    build_fixed_package(out, seed=bytes(range(32)))
    pkg = open_package(out)
    with pytest.raises(PrsnError):
        pkg.read_entry_bytes("nope.bin")


def test_builder_unsigned_package(tmp_path):
    b = Builder(generator="t", created="2026-10-10T00:00:00Z")
    b.set_person({"id": "urn:uuid:1", "display_name": "T", "aliases": [], "ids": [], "links": []})
    b.add_entry("face/samples/a.bin", "org.prsn.face.sample", "application/octet-stream",
                b"data", origin={"tier": "observed"})
    out = tmp_path / "u.prsn"
    assert b.write_zip(out) is None
    pkg = open_package(out)
    assert not pkg.signature.present
    assert pkg.read_entry_bytes("face/samples/a.bin") == b"data"
