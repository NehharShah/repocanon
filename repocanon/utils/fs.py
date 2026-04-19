"""Filesystem helpers: safe walking with sensible default ignores and globs.

Two scanning strategies are available:

- ``walk_repo`` walks the filesystem with the project's default exclude rules.
- ``walk_repo_via_git`` shells out to ``git ls-files`` so that ``.gitignore``
  is honored exactly as Git itself does. This is preferred whenever the repo
  is a Git working tree because it matches what users actually consider "code"
  in their repo (no generated SDKs, vendored deps, data dumps, etc.).
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

# Conservative defaults. Used when the repo is not a Git checkout, or when the
# user explicitly opts out of the git-aware walker via config.
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

# IMPORTANT: do NOT add "*.lock" here. Lockfiles such as yarn.lock, uv.lock,
# Cargo.lock, and bun.lockb are the canonical signal that distinguishes one
# package manager from another, and the framework/package-manager detection
# layer needs them in the file inventory.
DEFAULT_EXCLUDE_GLOBS: tuple[str, ...] = (
    "*.pyc",
    "*.pyo",
    "*.so",
    "*.dylib",
    "*.dll",
    "*.class",
    "*.jar",
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


def is_git_repo(root: Path) -> bool:
    """Return True if ``root`` is inside a Git working tree."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_tracked_files(root: Path) -> list[Path] | None:
    """Return absolute paths of files Git considers part of the repo.

    Includes tracked files plus untracked-but-not-ignored files, which is
    exactly the set a user would expect a "fresh" tool to consider. Returns
    ``None`` when ``root`` isn't a Git repo or git isn't available.
    """
    if not is_git_repo(root):
        return None
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    paths: list[Path] = []
    for chunk in result.stdout.split(b"\0"):
        if not chunk:
            continue
        try:
            rel = chunk.decode("utf-8")
        except UnicodeDecodeError:
            continue
        paths.append(root / rel)
    return paths


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


def walk_repo_via_git(
    root: Path,
    *,
    extra_exclude_dirs: Iterable[str] = (),
    extra_exclude_globs: Iterable[str] = (),
    include_globs: Iterable[str] = (),
    max_files: int | None = None,
) -> list[Path] | None:
    """Like ``walk_repo`` but defers to ``git ls-files`` for traversal.

    Returns ``None`` when ``root`` isn't a Git repo, signalling that the
    caller should fall back to ``walk_repo``. Even when Git provides the
    initial list, we still apply the user's include/exclude globs so the
    config remains the final filter.
    """
    files = git_tracked_files(root)
    if files is None:
        return None

    excludes = set(extra_exclude_dirs)
    glob_excludes = list(DEFAULT_EXCLUDE_GLOBS) + list(extra_exclude_globs)
    include_list = list(include_globs)

    out: list[Path] = []
    for path in sorted(files, key=lambda p: p.as_posix()):
        if not path.is_file():
            continue
        rel = path.relative_to(root.resolve()).as_posix()
        # Honor user-extended directory excludes even when git would track them.
        if any(part in excludes for part in rel.split("/")):
            continue
        if matches_any_glob(rel, glob_excludes):
            continue
        if include_list and not matches_any_glob(rel, include_list):
            continue
        out.append(path)
        if max_files is not None and len(out) >= max_files:
            break
    return out


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


def safe_yaml_load(path: Path) -> Any | None:
    """Best-effort YAML load. Returns ``None`` on any failure.

    Imported lazily so the rest of the package keeps working even if PyYAML
    isn't installed (we declare it as a hard dep, but defensive imports here
    make life easier for downstream users running mixed environments).
    """
    try:
        import yaml
    except ImportError:
        return None
    text = safe_read_text(path)
    if text is None:
        return None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None
