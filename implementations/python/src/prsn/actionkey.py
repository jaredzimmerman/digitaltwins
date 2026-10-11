# Copyright 2026 Jared Zimmerman
# SPDX-License-Identifier: Apache-2.0
"""R1 ``action_key`` (spec/derivation-recipes.md).

``action_key`` = ``"sha256:" + hex(SHA-256(canonical JSON of the preimage))``.

Preimage::

    {"family":  derivation.family,
     "recipe":  {"id": derivation.recipe.id, "version": derivation.recipe.version},
     "models":  [derivation.models[].sha256 ...]  sorted by UTF-8 bytes, duplicates kept,
     "params":  derivation.params                 ({} when absent or null),
     "inputs":  [resolved input ...]              sorted by UTF-8 bytes of each one's
                                                  canonical JSON}

A resolved input keeps only the keys ``capture``/``cache``/``sha256``/``role``/
``select`` (whichever are present) and drops everything else (``look``,
``era``, an entry's ``entry`` path, unknown keys). ``models`` or ``inputs``
absent or null mean ``[]``.

A derivation has NO key when: an input lacks a single string content hash,
``family`` or ``recipe.version`` is missing, a model lacks ``sha256``, or
``params`` is a non-object.
"""

from __future__ import annotations

import hashlib

from .canonical import canonical

_INPUT_KEYS = ("capture", "cache", "sha256", "role", "select")
_CONTENT_HASH_KEYS = ("capture", "cache", "sha256")


class ActionKeyError(ValueError):
    """Raised when a derivation has no action key."""


def preimage(derivation: dict) -> bytes:
    """Canonical JSON bytes of the R1 preimage. Raises ActionKeyError when the
    derivation has no key."""
    if not isinstance(derivation, dict):
        raise ActionKeyError("derivation must be an object")
    if not isinstance(derivation.get("family"), str):
        raise ActionKeyError("derivation.family is missing")
    recipe = derivation.get("recipe")
    if (
        not isinstance(recipe, dict)
        or not isinstance(recipe.get("id"), str)
        or not isinstance(recipe.get("version"), str)
    ):
        raise ActionKeyError("derivation.recipe.id and derivation.recipe.version are required")

    models: list[str] = []
    for m in derivation.get("models") or []:
        if not isinstance(m, dict) or not isinstance(m.get("sha256"), str):
            raise ActionKeyError("a model without sha256")
        models.append(m["sha256"])

    params = derivation.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ActionKeyError("derivation.params must be an object")

    resolved: list[dict] = []
    for inp in derivation.get("inputs") or []:
        if not isinstance(inp, dict):
            raise ActionKeyError("an input must be an object")
        present = [k for k in _CONTENT_HASH_KEYS if k in inp]
        if len(present) != 1 or not isinstance(inp[present[0]], str):
            raise ActionKeyError("an input needs exactly one string content hash")
        resolved.append({k: v for k, v in inp.items() if k in _INPUT_KEYS})
    resolved.sort(key=lambda d: canonical(d))

    pre = {
        "family": derivation["family"],
        "recipe": {"id": recipe["id"], "version": recipe["version"]},
        "models": sorted(models, key=lambda s: s.encode("utf-8")),
        "params": params,
        "inputs": resolved,
    }
    return canonical(pre)


def action_key(derivation: dict) -> str:
    """``"sha256:" + hex(SHA-256(preimage))``. Raises ActionKeyError when the
    derivation has no key."""
    return "sha256:" + hashlib.sha256(preimage(derivation)).hexdigest()
