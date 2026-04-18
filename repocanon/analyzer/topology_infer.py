"""Infer repository topology and the role of each top-level directory."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from repocanon.analyzer.config_parse import ManifestData
from repocanon.models.findings import Confidence, Finding
from repocanon.models.project import (
    ArchitectureBoundary,
    DirectoryRole,
    TopologyKind,
)

# Directory name → coarse role label. Order doesn't matter; longest match wins
# only when multiple rules fire (handled by _role_for_dir's priority list).
_ROLE_HINTS: dict[str, str] = {
    "src": "source",
    "lib": "library",
    "app": "application",
    "apps": "applications (monorepo)",
    "packages": "packages (monorepo)",
    "libs": "shared libraries (monorepo)",
    "services": "services",
    "tests": "tests",
    "test": "tests",
    "__tests__": "tests",
    "spec": "tests",
    "docs": "documentation",
    "doc": "documentation",
    "scripts": "scripts",
    "tools": "developer tooling",
    "examples": "examples",
    "frontend": "frontend",
    "web": "frontend",
    "client": "frontend",
    "ui": "frontend",
    "backend": "backend",
    "server": "backend",
    "api": "api surface",
    "routes": "api routes",
    "controllers": "controllers",
    "handlers": "request handlers",
    "models": "domain models",
    "schemas": "schemas",
    "migrations": "database migrations",
    "alembic": "database migrations",
    "prisma": "database schema (prisma)",
    "db": "database",
    "infra": "infrastructure",
    "deploy": "deployment",
    "ops": "operations",
    "config": "configuration",
    "configs": "configuration",
    "public": "static assets",
    "static": "static assets",
    "assets": "static assets",
    "fixtures": "test fixtures",
}


def _role_for_dir(name: str) -> str | None:
    return _ROLE_HINTS.get(name.lower())


def infer_topology(
    repo_path: Path,
    rel_paths: Iterable[str],
    manifests: list[ManifestData],
) -> tuple[TopologyKind, list[str], list[DirectoryRole], list[ArchitectureBoundary], list[Finding]]:
    findings: list[Finding] = []

    top_dirs = _top_level_dirs(rel_paths)

    monorepo_packages: list[str] = []
    monorepo_signals: list[str] = []

    package_jsons = [m for m in manifests if m.kind == "package.json"]
    pyprojects = [m for m in manifests if m.kind == "pyproject"]

    for m in package_jsons:
        if m.path == "package.json" and isinstance(m.raw, dict):
            workspaces = m.raw.get("workspaces")
            if workspaces:
                monorepo_signals.append("package.json workspaces")

    nested_pkg = [m for m in package_jsons if m.path != "package.json"]
    nested_py = [m for m in pyprojects if m.path != "pyproject.toml"]
    monorepo_packages.extend(sorted({Path(m.path).parent.as_posix() for m in nested_pkg}))
    monorepo_packages.extend(sorted({Path(m.path).parent.as_posix() for m in nested_py}))
    monorepo_packages = sorted({p for p in monorepo_packages if p and p != "."})

    has_apps_or_packages = any(d in {"apps", "packages", "libs", "services"} for d in top_dirs)
    if has_apps_or_packages:
        monorepo_signals.append("apps/packages/libs/services directories present")

    if monorepo_packages or monorepo_signals:
        topology = TopologyKind.monorepo
        findings.append(
            Finding(
                kind="topology",
                subject="monorepo",
                rationale="; ".join(monorepo_signals or ["multiple manifests under subdirectories"]),
                evidence=monorepo_packages or sorted(top_dirs),
                confidence=Confidence.high if monorepo_signals else Confidence.medium,
            )
        )
    elif manifests:
        topology = TopologyKind.single_package
        findings.append(
            Finding(
                kind="topology",
                subject="single_package",
                rationale="Single root manifest and no workspace markers.",
                evidence=[m.path for m in manifests],
                confidence=Confidence.high,
            )
        )
    else:
        topology = TopologyKind.unknown

    key_dirs: list[DirectoryRole] = []
    for name in sorted(top_dirs):
        role = _role_for_dir(name)
        if role:
            key_dirs.append(
                DirectoryRole(
                    path=name,
                    role=role,
                    rationale=f"Recognized top-level directory '{name}'.",
                    confidence=Confidence.high,
                )
            )

    boundaries = _infer_boundaries(top_dirs, monorepo_packages, topology)

    return topology, monorepo_packages, key_dirs, boundaries, findings


def _top_level_dirs(rel_paths: Iterable[str]) -> set[str]:
    dirs: set[str] = set()
    for rel in rel_paths:
        head = rel.split("/", 1)[0]
        # Require an actual directory (i.e. contains '/') and skip dotfiles at root.
        if head and "." not in head[0:1] and "/" in rel:
            dirs.add(head)
    return dirs


def _infer_boundaries(
    top_dirs: set[str], packages: list[str], topology: TopologyKind
) -> list[ArchitectureBoundary]:
    out: list[ArchitectureBoundary] = []
    if {"frontend", "backend"} & top_dirs and len({"frontend", "backend"} & top_dirs) == 2:
        out.append(
            ArchitectureBoundary(
                name="frontend/backend split",
                description=(
                    "Top-level 'frontend' and 'backend' directories should not import "
                    "from each other."
                ),
                confidence=Confidence.high,
            )
        )
    elif {"client", "server"}.issubset(top_dirs):
        out.append(
            ArchitectureBoundary(
                name="client/server split",
                description="Top-level 'client' and 'server' directories own their own deps and code.",
                confidence=Confidence.high,
            )
        )
    if "api" in top_dirs and ({"web", "frontend"} & top_dirs):
        out.append(
            ArchitectureBoundary(
                name="api vs web boundary",
                description="API code and frontend code live in separate top-level trees.",
                confidence=Confidence.medium,
            )
        )
    if topology is TopologyKind.monorepo and packages:
        out.append(
            ArchitectureBoundary(
                name="package isolation",
                description=(
                    "Each package under apps/, packages/, libs/ or services/ owns its own "
                    "dependencies and should not reach into another package's internals."
                ),
                confidence=Confidence.medium,
            )
        )
    if "migrations" in top_dirs or "alembic" in top_dirs:
        out.append(
            ArchitectureBoundary(
                name="database migrations are append-only",
                description="Existing migration files should not be edited; create a new revision instead.",
                confidence=Confidence.medium,
            )
        )
    return out


def file_pattern_summary(rel_paths: Iterable[str]) -> list[str]:
    """Surface a few of the most common file shapes in the repo."""
    counter: Counter[str] = Counter()
    by_dir: dict[str, Counter[str]] = defaultdict(Counter)
    for rel in rel_paths:
        suffix = Path(rel).suffix.lower()
        if not suffix:
            continue
        counter[suffix] += 1
        head = rel.split("/", 1)[0] if "/" in rel else "."
        by_dir[head][suffix] += 1

    summaries: list[str] = []
    for ext, count in counter.most_common(6):
        if count < 2:
            continue
        summaries.append(f"{count} `{ext}` files")
    return summaries
