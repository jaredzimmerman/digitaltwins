# Copyright 2026 Jared Zimmerman
# SPDX-License-Identifier: Apache-2.0
"""Every v1-relevant conformance vector suite must pass with zero failures."""

import pytest

from prsn.vectors import run_suites

SUITE_NAMES = [
    "json",
    "sha256",
    "action_key",
    "ed25519",
    "manifest",
    "tiers",
    "container",
    "prsn",
    "examples",
]


def _results(conformance_dir):
    return dict((name, result) for name, result in run_suites(conformance_dir))


@pytest.mark.parametrize("suite", SUITE_NAMES)
def test_suite_passes(conformance_dir, suite):
    passed, failed, bad = _results(conformance_dir)[suite]
    assert failed == 0, f"{suite}: {failed} failures: {bad}"
    assert passed > 0, f"{suite}: no vectors ran"


def test_total_vector_count(conformance_dir):
    results = _results(conformance_dir)
    total = sum(p for _, (p, _, _) in results.items())
    # 94 json + 10 sha256 + 17 action_key + 4 ed25519 + 1 manifest + 5 tiers
    # + 8 container + 33 prsn + 1 examples
    assert total == 173, f"expected 173 vector checks, ran {total}"
