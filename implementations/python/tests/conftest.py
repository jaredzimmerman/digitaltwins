# Copyright 2026 Jared Zimmerman
# SPDX-License-Identifier: Apache-2.0
"""Pytest configuration: locate the spec repo's conformance directory."""

import os
from pathlib import Path

import pytest

# implementations/python/tests -> repo root -> prsn/conformance
DEFAULT_CONFORMANCE = Path(__file__).resolve().parents[3] / "prsn" / "conformance"


@pytest.fixture(scope="session")
def conformance_dir() -> Path:
    d = Path(os.environ.get("PRSN_CONFORMANCE_DIR", DEFAULT_CONFORMANCE))
    if not (d / "json" / "canonical.json").exists():
        pytest.skip(f"conformance vectors not found at {d}")
    return d
