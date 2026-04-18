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
from repocanon.utils.fs import walk_repo

# Extension → (language name, primary?). Primary extensions get attributed to
# language file_count; others (configs, docs) are tracked separately.
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
}


@dataclass
class FileInventory:
    files: list[Path]
    rel_paths: list[str]
    languages: list[Language]
    bytes_scanned: int


def build_inventory(repo_path: Path, config: RepoCanonConfig) -> FileInventory:
    excludes_globs: Iterable[str] = config.scan.exclude
    includes: Iterable[str] = config.scan.include
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
    counter: Counter[str] = Counter()
    ext_by_lang: dict[str, set[str]] = {}

    for f in files:
        with contextlib.suppress(OSError):
            bytes_scanned += f.stat().st_size
        rel_paths.append(f.relative_to(repo_path).as_posix())
        ext = f.suffix.lower()
        lang = EXT_LANG.get(ext)
        if lang:
            counter[lang] += 1
            ext_by_lang.setdefault(lang, set()).add(ext)

    languages = [
        Language(
            name=name,
            file_count=count,
            primary_extensions=sorted(ext_by_lang.get(name, set())),
            confidence=Confidence.high if count >= 3 else Confidence.medium,
        )
        for name, count in counter.most_common()
    ]

    return FileInventory(
        files=files,
        rel_paths=rel_paths,
        languages=languages,
        bytes_scanned=bytes_scanned,
    )
