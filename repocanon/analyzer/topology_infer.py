"""Infer repository topology, the role of each top-level directory, and per-package metadata."""

from __future__ import annotations

import fnmatch
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from repocanon.analyzer.command_detect import commands_for_manifest
from repocanon.analyzer.config_parse import ManifestData
from repocanon.analyzer.framework_detect import (
    GO_RULES,
    JS_RULES,
    PY_RULES,
    RUST_RULES,
    _Rule,
)
from repocanon.models.findings import Confidence, Finding
from repocanon.models.project import (
    ArchitectureBoundary,
    DirectoryRole,
    Framework,
    Package,
    PackageManager,
    RoleKind,
    TopologyKind,
)

# (label, RoleKind). The label is what users see; RoleKind drives generator
# decisions. Order doesn't matter; longest match wins where multiple fire.
_ROLE_HINTS: dict[str, tuple[str, RoleKind]] = {
    "src": ("source", RoleKind.source),
    "lib": ("library", RoleKind.source),
    "app": ("application source", RoleKind.source),
    "apps": ("applications (monorepo)", RoleKind.monorepo_apps),
    "packages": ("packages (monorepo)", RoleKind.monorepo_packages),
    "libs": ("shared libraries (monorepo)", RoleKind.monorepo_libs),
    "services": ("services", RoleKind.monorepo_services),
    "tests": ("tests", RoleKind.test),
    "test": ("tests", RoleKind.test),
    "__tests__": ("tests", RoleKind.test),
    "spec": ("tests", RoleKind.test),
    "docs": ("documentation", RoleKind.docs),
    "doc": ("documentation", RoleKind.docs),
    "scripts": ("scripts", RoleKind.scripts),
    "tools": ("developer tooling", RoleKind.scripts),
    "examples": ("examples", RoleKind.examples),
    "frontend": ("frontend", RoleKind.frontend),
    "web": ("frontend", RoleKind.frontend),
    "client": ("frontend", RoleKind.frontend),
    "ui": ("frontend", RoleKind.frontend),
    "backend": ("backend", RoleKind.backend),
    "server": ("backend", RoleKind.backend),
    "api": ("api surface", RoleKind.api),
    "routes": ("api routes", RoleKind.api),
    "controllers": ("controllers", RoleKind.backend),
    "handlers": ("request handlers", RoleKind.backend),
    "models": ("domain models", RoleKind.source),
    "schemas": ("schemas", RoleKind.source),
    "migrations": ("database migrations", RoleKind.migrations),
    "alembic": ("database migrations", RoleKind.migrations),
    "prisma": ("database schema (prisma)", RoleKind.db),
    "db": ("database", RoleKind.db),
    "infra": ("infrastructure", RoleKind.infra),
    "deploy": ("deployment", RoleKind.deployment),
    "deployments": ("deployment", RoleKind.deployment),
    "ops": ("operations", RoleKind.infra),
    "config": ("configuration", RoleKind.config),
    "configs": ("configuration", RoleKind.config),
    "public": ("static assets", RoleKind.static_assets),
    "static": ("static assets", RoleKind.static_assets),
    "assets": ("static assets", RoleKind.static_assets),
    "fixtures": ("test fixtures", RoleKind.fixtures),
    # Go-idiomatic layout
    "cmd": ("binary entry points (Go cmd/)", RoleKind.binaries),
    "internal": ("internal-only Go packages (not importable externally)", RoleKind.internal),
    "pkg": ("publicly importable Go packages", RoleKind.pkg),
}


def _role_for_dir(name: str) -> tuple[str, RoleKind] | None:
    return _ROLE_HINTS.get(name.lower())


def infer_topology(
    repo_path: Path,
    rel_paths: Iterable[str],
    manifests: list[ManifestData],
) -> tuple[TopologyKind, list[Package], list[DirectoryRole], list[ArchitectureBoundary], list[Finding]]:
    findings: list[Finding] = []

    rel_paths = list(rel_paths)
    top_dirs = _top_level_dirs(rel_paths)

    monorepo_signals: list[str] = []
    workspace_globs: list[str] = []

    package_jsons = [m for m in manifests if m.kind == "package.json"]
    pyprojects = [m for m in manifests if m.kind == "pyproject"]
    cargos = [m for m in manifests if m.kind == "Cargo.toml"]
    go_works = [m for m in manifests if m.kind == "go.work"]
    pnpm_workspaces = [m for m in manifests if m.kind in {"pnpm-workspace.yaml"}]
    json_workspace_signals = [
        m for m in manifests if m.kind in {"nx.json", "turbo.json", "lerna.json", "rush.json"}
    ]

    for m in package_jsons:
        if m.path == "package.json" and m.workspace_globs:
            monorepo_signals.append("package.json `workspaces`")
            workspace_globs.extend(m.workspace_globs)
    for m in pnpm_workspaces:
        monorepo_signals.append(f"`{m.path}`")
        workspace_globs.extend(m.workspace_globs)
    for m in json_workspace_signals:
        monorepo_signals.append(f"`{m.path}`")
    for m in go_works:
        monorepo_signals.append(f"`{m.path}` (Go workspace)")
        workspace_globs.extend(m.workspace_globs)
    for m in cargos:
        if m.path == "Cargo.toml" and m.workspace_globs:
            monorepo_signals.append("Cargo `[workspace] members`")
            workspace_globs.extend(m.workspace_globs)

    nested_pkg = [m for m in package_jsons if m.path != "package.json"]
    nested_py = [m for m in pyprojects if m.path != "pyproject.toml"]
    nested_cargo = [m for m in cargos if m.path != "Cargo.toml"]
    nested_manifests = nested_pkg + nested_py + nested_cargo

    has_apps_or_packages = any(d in {"apps", "packages", "libs", "services"} for d in top_dirs)
    if has_apps_or_packages and not monorepo_signals:
        monorepo_signals.append("apps/packages/libs/services directories present")

    # Go multi-binary detection: cmd/<name>/main.go for ≥2 names.
    go_binaries: list[str] = []
    if "cmd" in top_dirs:
        cmd_subdirs: dict[str, bool] = {}
        for rel in rel_paths:
            parts = rel.split("/")
            if len(parts) >= 3 and parts[0] == "cmd" and parts[-1].endswith(".go"):
                cmd_subdirs.setdefault(parts[1], False)
                if parts[-1] == "main.go":
                    cmd_subdirs[parts[1]] = True
        go_binaries = sorted(name for name, has_main in cmd_subdirs.items() if has_main)

    has_go_module = any(m.kind == "go.mod" for m in manifests)

    packages: list[Package] = []
    pm_by_manifest = {m.path: _package_manager_for(m) for m in manifests}

    if monorepo_signals or nested_manifests:
        topology = TopologyKind.monorepo
        for m in nested_manifests:
            cs, _ = commands_for_manifest(m, pm_by_manifest.get(m.path))
            packages.append(
                Package(
                    name=m.name or Path(m.path).parent.as_posix(),
                    path=Path(m.path).parent.as_posix(),
                    manifest=m.path,
                    package_manager=pm_by_manifest.get(m.path),
                    frameworks=_frameworks_for(m),
                    commands=cs,
                )
            )
        # If we have only signals + workspace globs but no nested manifest yet
        # parsed, fall through to a synthetic package per glob that matches a
        # real directory.
        if not packages and workspace_globs:
            for glob in workspace_globs:
                for top in sorted(top_dirs):
                    if fnmatch.fnmatch(top + "/anything", glob.rstrip("/") + "/anything"):
                        packages.append(
                            Package(
                                name=top,
                                path=top,
                                manifest="",
                                package_manager=None,
                            )
                        )
        findings.append(
            Finding(
                kind="topology",
                subject="monorepo",
                rationale="; ".join(monorepo_signals or ["multiple manifests under subdirectories"]),
                evidence=[p.path for p in packages] or sorted(top_dirs),
                confidence=Confidence.high if monorepo_signals else Confidence.medium,
            )
        )
    elif has_go_module and len(go_binaries) >= 2:
        topology = TopologyKind.multi_binary
        for name in go_binaries:
            packages.append(
                Package(
                    name=f"cmd/{name}",
                    path=f"cmd/{name}",
                    manifest="go.mod",
                    package_manager="go-modules",
                )
            )
        findings.append(
            Finding(
                kind="topology",
                subject="multi_binary",
                rationale=(
                    f"Go module with {len(go_binaries)} binaries under cmd/: "
                    f"{', '.join(go_binaries)}."
                ),
                evidence=[f"cmd/{name}/main.go" for name in go_binaries],
                confidence=Confidence.high,
            )
        )
    elif manifests:
        topology = TopologyKind.single_package
        findings.append(
            Finding(
                kind="topology",
                subject="single_package",
                rationale="Single root manifest and no workspace markers.",
                evidence=[m.path for m in manifests if "/" not in m.path],
                confidence=Confidence.high,
            )
        )
    else:
        topology = TopologyKind.unknown

    key_dirs = _build_key_directories(top_dirs, manifests, rel_paths)
    boundaries = _infer_boundaries(top_dirs, packages, topology)

    return topology, packages, key_dirs, boundaries, findings


def _frameworks_for(m: ManifestData) -> list[Framework]:
    """Apply the same framework rules used by the global detector to a single manifest."""
    if m.kind == "package.json":
        rules: tuple[_Rule, ...] = JS_RULES
    elif m.kind == "pyproject":
        rules = PY_RULES
    elif m.kind == "Cargo.toml":
        rules = RUST_RULES
    elif m.kind == "go.mod":
        rules = GO_RULES
    else:
        return []
    deps = {d.lower() for d in (*m.dependencies, *m.dev_dependencies)}
    out: list[Framework] = []
    for rule in rules:
        for needle in rule.needles:
            if needle.lower() in deps:
                out.append(
                    Framework(
                        name=rule.name,
                        category=rule.category,
                        evidence=[f"{m.path}: {needle}"],
                        confidence=Confidence.high,
                    )
                )
                break
    return out


def _package_manager_for(m: ManifestData) -> str | None:
    if m.kind == "pyproject":
        if isinstance(m.raw, dict):
            tool = m.raw.get("tool", {})
            if isinstance(tool, dict) and "poetry" in tool:
                return "poetry"
        return "pip"
    if m.kind == "package.json":
        return m.package_manager_hint or "npm"
    if m.kind == "Cargo.toml":
        return "cargo"
    if m.kind == "go.mod":
        return "go-modules"
    if m.kind == "Pipfile":
        return "pipenv"
    return None


def _build_key_directories(
    top_dirs: set[str],
    manifests: list[ManifestData],
    rel_paths: list[str],
) -> list[DirectoryRole]:
    out: list[DirectoryRole] = []
    seen: set[str] = set()

    for name in sorted(top_dirs):
        hint = _role_for_dir(name)
        if hint is None:
            continue
        label, kind = hint
        out.append(
            DirectoryRole(
                path=name,
                role=label,
                role_kind=kind,
                rationale=f"Recognized top-level directory '{name}'.",
                confidence=Confidence.high,
            )
        )
        seen.add(name)

    # Source-package detection: any top-level directory matching a manifest's
    # declared name (Python wheel package, Go module last segment, etc.) and
    # containing source files counts as the source root.
    candidate_names = _source_package_candidates(manifests)
    for top in sorted(top_dirs - seen):
        if top in candidate_names and _has_source_files(top, rel_paths):
            out.append(
                DirectoryRole(
                    path=top,
                    role="source",
                    role_kind=RoleKind.source,
                    rationale=(
                        f"Inferred from manifest package name; '{top}/' contains source files."
                    ),
                    confidence=Confidence.medium,
                )
            )
            seen.add(top)
    return out


def _source_package_candidates(manifests: list[ManifestData]) -> set[str]:
    out: set[str] = set()
    for m in manifests:
        if m.kind == "pyproject" and isinstance(m.raw, dict):
            for entry in _hatch_wheel_packages(m.raw):
                out.add(entry.strip("/").split("/")[0])
            if m.name:
                normalized = re.sub(r"[-_.]+", "_", m.name.lower())
                out.add(normalized)
                out.add(m.name.lower())
                out.add(m.name)
        elif m.kind in {"go.mod", "package.json"} and m.name:
            out.add(m.name.split("/")[-1])
        elif m.kind == "Cargo.toml" and m.name:
            out.add(m.name.replace("-", "_"))
            out.add(m.name)
    return out


def _hatch_wheel_packages(raw: dict[str, object]) -> list[str]:
    """Walk a pyproject's nested tool.hatch.build.targets.wheel.packages safely.

    Each level may be missing or a non-dict; we return [] in any unexpected
    shape rather than raising, so a malformed pyproject can't crash topology
    inference.
    """
    cursor: object = raw
    for key in ("tool", "hatch", "build", "targets", "wheel", "packages"):
        if not isinstance(cursor, dict):
            return []
        cursor = cursor.get(key, {})
    if not isinstance(cursor, list):
        return []
    return [c for c in cursor if isinstance(c, str)]


_SOURCE_EXTS: frozenset[str] = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".rb", ".java", ".kt"}
)


def _has_source_files(top: str, rel_paths: list[str]) -> bool:
    count = 0
    for rel in rel_paths:
        if not rel.startswith(top + "/"):
            continue
        if any(rel.endswith(ext) for ext in _SOURCE_EXTS):
            count += 1
            if count >= 3:
                return True
    return False


def _top_level_dirs(rel_paths: Iterable[str]) -> set[str]:
    dirs: set[str] = set()
    for rel in rel_paths:
        head = rel.split("/", 1)[0]
        if head and "." not in head[0:1] and "/" in rel:
            dirs.add(head)
    return dirs


def _infer_boundaries(
    top_dirs: set[str], packages: list[Package], topology: TopologyKind
) -> list[ArchitectureBoundary]:
    out: list[ArchitectureBoundary] = []
    if {"frontend", "backend"}.issubset(top_dirs):
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
        # Surface the actual top-level monorepo container in the description
        # instead of the generic "apps/, packages/, libs/ or services/" string.
        roots = sorted({p.path.split("/", 1)[0] for p in packages if "/" in p.path})
        roots_str = ", ".join(f"`{r}/`" for r in roots) if roots else "monorepo packages"
        out.append(
            ArchitectureBoundary(
                name="package isolation",
                description=(
                    f"Each package under {roots_str} owns its own dependencies and "
                    "should not reach into another package's internals."
                ),
                confidence=Confidence.medium,
            )
        )
    if topology is TopologyKind.multi_binary and packages:
        out.append(
            ArchitectureBoundary(
                name="binary isolation",
                description=(
                    "Each cmd/<binary> directory is a separate program. Shared code belongs "
                    "in internal/ or pkg/, not in another binary's directory."
                ),
                confidence=Confidence.high,
            )
        )
    if "internal" in top_dirs:
        out.append(
            ArchitectureBoundary(
                name="Go internal/ visibility",
                description=(
                    "Packages under internal/ are only importable from this module. "
                    "Treat them as private API; do not promote to pkg/ casually."
                ),
                confidence=Confidence.high,
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


# Re-export PackageManager so tests/import paths stay backward compatible.
__all__ = [
    "PackageManager",
    "file_pattern_summary",
    "infer_topology",
]
