"""Build a fast, ordered inventory of files and language statistics."""

from __future__ import annotations

import contextlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from repocanon.config import RepoCanonConfig
from repocanon.models.findings import Confidence
from repocanon.models.project import Language
from repocanon.utils.fs import walk_repo, walk_repo_via_git

# Extension → language name. Only "code" extensions get attributed to language
# file_count; configs/docs/IaC are tracked in the inventory but not promoted
# to a Language entry (they would otherwise drown out the actual code stats).
EXT_LANG: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".swift": "Swift",
    ".scala": "Scala",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".lua": "Lua",
    ".dart": "Dart",
    ".r": "R",
    ".clj": "Clojure",
    ".cljs": "Clojure",
    ".hs": "Haskell",
    ".ml": "OCaml",
    ".sol": "Solidity",
    ".zig": "Zig",
    ".nim": "Nim",
}

# Non-language files we still track for per-extension reporting (file_patterns)
# and for influencing convention detection. They never produce a Language entry.
ANCILLARY_EXTS: frozenset[str] = frozenset(
    {
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".md",
        ".rst",
        ".proto",
        ".tf",
        ".hcl",
        ".graphql",
        ".gql",
        ".ipynb",
        ".gradle",
        ".groovy",
        ".dockerfile",
    }
)


@dataclass
class FileInventory:
    files: list[Path]
    rel_paths: list[str]
    languages: list[Language]
    bytes_scanned: int
    code_bytes_scanned: int
    used_git: bool


def build_inventory(repo_path: Path, config: RepoCanonConfig) -> FileInventory:
    """Build the file inventory, preferring ``git ls-files`` when available.

    Honoring ``.gitignore`` is materially more useful than RepoCanon's own
    ignore list for real repos (data dumps, vendored deps, generated SDKs),
    so we route through git when we can and fall back to a manual walk when
    we can't (or the user opted out via config).
    """
    excludes_globs: Iterable[str] = config.scan.exclude
    includes: Iterable[str] = config.scan.include

    files: list[Path] | None = None
    used_git = False
    if config.scan.respect_gitignore:
        files = walk_repo_via_git(
            repo_path,
            extra_exclude_globs=excludes_globs,
            include_globs=includes,
            max_files=20_000,
        )
        used_git = files is not None

    if files is None:
        files = list(
            walk_repo(
                repo_path,
                extra_exclude_globs=excludes_globs,
                include_globs=includes,
                max_files=20_000,
            )
        )

    rel_paths: list[str] = []
    bytes_scanned = 0
    code_bytes_scanned = 0
    counter: Counter[str] = Counter()
    ext_by_lang: dict[str, set[str]] = {}

    for f in files:
        size = 0
        with contextlib.suppress(OSError):
            size = f.stat().st_size
        bytes_scanned += size
        rel_paths.append(f.relative_to(repo_path).as_posix())
        ext = f.suffix.lower()
        lang = EXT_LANG.get(ext)
        if lang:
            counter[lang] += 1
            ext_by_lang.setdefault(lang, set()).add(ext)
            code_bytes_scanned += size

    languages = [
        Language(
            name=name,
            file_count=count,
            primary_extensions=sorted(ext_by_lang.get(name, set())),
            confidence=_language_confidence(count),
        )
        for name, count in counter.most_common()
    ]

    return FileInventory(
        files=files,
        rel_paths=rel_paths,
        languages=languages,
        bytes_scanned=bytes_scanned,
        code_bytes_scanned=code_bytes_scanned,
        used_git=used_git,
    )


def _language_confidence(file_count: int) -> Confidence:
    """A handful of files is medium; a serious presence (>=10) is high."""
    if file_count >= 10:
        return Confidence.high
    if file_count >= 3:
        return Confidence.medium
    return Confidence.low
