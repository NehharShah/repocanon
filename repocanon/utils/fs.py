"""Filesystem helpers: safe walking with sensible default ignores and globs."""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterable, Iterator
from pathlib import Path

# Conservative defaults. Users can extend via .repocanon/config.toml.
DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "node_modules",
        ".next",
        ".nuxt",
        ".turbo",
        ".cache",
        "dist",
        "build",
        "target",
        ".gradle",
        ".tox",
        "coverage",
        "htmlcov",
        ".repocanon",
        ".DS_Store",
    }
)

DEFAULT_EXCLUDE_GLOBS: tuple[str, ...] = (
    "*.pyc",
    "*.pyo",
    "*.so",
    "*.dylib",
    "*.dll",
    "*.class",
    "*.jar",
    "*.lock",
    "*.log",
    "*.min.js",
    "*.min.css",
    "*.map",
    ".env*",
)

# Files we never read as text even if they pass the directory filter.
BINARY_HINT_EXTS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".mp3",
        ".mp4",
        ".mov",
        ".avi",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".bin",
        ".pyc",
        ".pyo",
        ".so",
        ".dylib",
        ".dll",
        ".class",
        ".jar",
    }
)


def is_excluded_dir(name: str, extra: Iterable[str] = ()) -> bool:
    return name in DEFAULT_EXCLUDE_DIRS or name in set(extra)


def matches_any_glob(rel_path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(rel_path, p) for p in patterns)


def walk_repo(
    root: Path,
    *,
    extra_exclude_dirs: Iterable[str] = (),
    extra_exclude_globs: Iterable[str] = (),
    include_globs: Iterable[str] = (),
    follow_symlinks: bool = False,
    max_files: int | None = None,
) -> Iterator[Path]:
    """Yield files under ``root`` filtered by the default + caller-provided rules.

    Yields absolute paths. Order is stable (sorted within each directory).
    """
    root = root.resolve()
    excludes = set(extra_exclude_dirs)
    glob_excludes = list(DEFAULT_EXCLUDE_GLOBS) + list(extra_exclude_globs)
    include_list = list(include_globs)
    yielded = 0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        dirnames[:] = sorted(d for d in dirnames if not is_excluded_dir(d, excludes))
        for fname in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, fname), root)
            if matches_any_glob(rel, glob_excludes):
                continue
            if include_list and not matches_any_glob(rel, include_list):
                continue
            yield Path(dirpath) / fname
            yielded += 1
            if max_files is not None and yielded >= max_files:
                return


def safe_read_text(path: Path, *, max_bytes: int = 512 * 1024) -> str | None:
    """Read a small text file. Returns None for binaries or large files."""
    if path.suffix.lower() in BINARY_HINT_EXTS:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > max_bytes:
        return None
    try:
        with path.open("rb") as fh:
            data = fh.read(max_bytes)
        if b"\x00" in data:
            return None
        return data.decode("utf-8", errors="replace")
    except OSError:
        return None


def relative_to(root: Path, path: Path) -> str:
    """Return a POSIX-style relative path from root, or absolute if outside root."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
