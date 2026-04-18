"""Stable hashing helpers used by the diff command and snapshot tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    """Return the SHA-256 of a file in lowercase hex."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_hash(payload: Any) -> str:
    """Hash a JSON-serializable structure deterministically."""
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def fingerprint_paths(paths: Iterable[Path]) -> str:
    """Cheap structural fingerprint of a set of paths (sorted, hashed)."""
    items = sorted(str(p) for p in paths)
    return hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest()
