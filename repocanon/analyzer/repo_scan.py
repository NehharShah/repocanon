"""Top-level orchestrator: turn a repo path into a ProjectModel."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from repocanon.analyzer.command_detect import detect_commands
from repocanon.analyzer.config_parse import ManifestData, parse_manifests
from repocanon.analyzer.conventions_infer import (
    infer_anti_patterns_and_uncertainty,
    infer_general_conventions,
    infer_naming_conventions,
    infer_test_layout,
)
from repocanon.analyzer.file_inventory import build_inventory
from repocanon.analyzer.framework_detect import detect_frameworks, detect_package_managers
from repocanon.analyzer.topology_infer import file_pattern_summary, infer_topology
from repocanon.config import RepoCanonConfig, load_config
from repocanon.models.findings import Confidence, Finding
from repocanon.models.project import ProjectModel
from repocanon.utils.hashing import fingerprint_paths


def analyze_repo(
    repo_path: Path,
    config: RepoCanonConfig | None = None,
    *,
    progress: Callable[[str], None] | None = None,
) -> ProjectModel:
    """Run the full deterministic analysis pipeline.

    The pipeline is intentionally a straight line: each stage consumes only
    what previous stages produced, which keeps the data dependencies legible
    and makes individual stages easy to test. ``progress`` is invoked with a
    short status string after each stage so callers can render a progress
    bar without coupling the analyzer to any rendering library.
    """
    repo_path = repo_path.resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        raise NotADirectoryError(repo_path)

    cfg = config or load_config(repo_path)
    findings: list[Finding] = []

    def _step(label: str) -> None:
        if progress is not None:
            progress(label)

    _step("Indexing files")
    inv = build_inventory(repo_path, cfg)

    _step("Parsing manifests")
    manifests, parse_findings = parse_manifests(repo_path, inv.files)
    findings.extend(parse_findings)
    file_names = {Path(p).name for p in inv.rel_paths}

    _step("Detecting frameworks")
    frameworks, fw_findings = detect_frameworks(manifests)
    findings.extend(fw_findings)
    pkg_mgrs, pm_findings = detect_package_managers(manifests, file_names)
    findings.extend(pm_findings)

    _step("Extracting commands")
    commands, cmd_findings = detect_commands(repo_path, inv.files, manifests, pkg_mgrs)
    findings.extend(cmd_findings)

    _step("Inferring topology")
    topology, packages, dirs, boundaries, topo_findings = infer_topology(
        repo_path, inv.rel_paths, manifests
    )
    findings.extend(topo_findings)

    _step("Inferring conventions")
    test_layout, test_finding = infer_test_layout(inv.rel_paths)
    findings.append(test_finding)
    naming = infer_naming_conventions(inv.rel_paths, frameworks)
    conventions = infer_general_conventions(inv.rel_paths, manifests, frameworks)
    anti_patterns, uncertainty = infer_anti_patterns_and_uncertainty(
        inv.rel_paths, manifests, frameworks
    )

    _step("Finalizing model")
    file_patterns = file_pattern_summary(inv.rel_paths)
    preferred_libs = _preferred_libraries(manifests)

    name = cfg.project.name or _infer_repo_name(repo_path, manifests)

    findings.append(
        Finding(
            kind="inventory",
            subject="files",
            rationale=(
                f"Indexed {inv.code_bytes_scanned} code bytes ({inv.bytes_scanned} total) "
                f"across {len(inv.files)} files"
                f"{' (via git ls-files)' if inv.used_git else ' (via filesystem walk)'}."
            ),
            evidence=[],
            confidence=Confidence.high,
        )
    )

    return ProjectModel(
        repo_name=name,
        repo_path=str(repo_path),
        languages=inv.languages,
        frameworks=frameworks,
        package_managers=pkg_mgrs,
        commands=commands,
        topology=topology,
        monorepo_packages=packages,
        key_directories=dirs,
        test_layout=test_layout,
        file_patterns=file_patterns,
        naming_conventions=naming,
        conventions=conventions,
        architecture_boundaries=boundaries,
        preferred_libraries=preferred_libs,
        anti_patterns=anti_patterns,
        uncertainty_notes=uncertainty,
        findings=findings,
        file_count=len(inv.files),
        bytes_scanned=inv.bytes_scanned,
        code_bytes_scanned=inv.code_bytes_scanned,
        structural_fingerprint=fingerprint_paths(repo_path, inv.files),
    )


def _infer_repo_name(repo_path: Path, manifests: list[ManifestData]) -> str:
    for m in manifests:
        if m.name:
            return m.name
    return repo_path.name


def _preferred_libraries(manifests: list[ManifestData]) -> list[str]:
    """Deduped, capped list of declared dependencies.

    Only counts root-level manifests (a monorepo's nested manifests get their
    own framework/package lists per :class:`Package`). Capped at 30 so the
    list reads as a quick-glance summary rather than a dump.
    """
    seen: set[str] = set()
    out: list[str] = []
    for m in manifests:
        if "/" in m.path:
            continue
        for dep in (*m.dependencies, *m.dev_dependencies):
            key = dep.lower()
            if key in seen or not key:
                continue
            seen.add(key)
            out.append(dep)
            if len(out) >= 30:
                return out
    return out
