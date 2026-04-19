"""Stable hashing helpers used by the diff command."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path


def fingerprint_paths(root: Path, paths: Iterable[Path]) -> str:
    """Cheap structural fingerprint of a set of paths, anchored at ``root``.

    Paths are reduced to their POSIX form relative to ``root`` before hashing
    so that moving the repository on disk does not change the fingerprint.
    Files outside ``root`` (which should not happen in practice) fall back to
    their absolute POSIX representation.
    """
    root_resolved = root.resolve()
    rels: list[str] = []
    for p in paths:
        try:
            rels.append(p.resolve().relative_to(root_resolved).as_posix())
        except ValueError:
            rels.append(p.resolve().as_posix())
    rels.sort()
    return hashlib.sha256("\n".join(rels).encode("utf-8")).hexdigest()
