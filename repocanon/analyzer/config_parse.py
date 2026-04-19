"""Parse common manifests across the supported language ecosystems.

Every parser is best-effort: a malformed manifest yields ``None`` plus a
warning ``Finding`` so callers can surface the parse failure to the user
rather than silently dropping detection signal.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from repocanon.models.findings import Confidence, Finding
from repocanon.utils.fs import safe_read_text, safe_yaml_load


class ManifestData(BaseModel):
    """Parsed contents of a single manifest file.

    Lives as a Pydantic model (rather than a plain dataclass) so it shares the
    validation/serialization conventions used everywhere else in the codebase.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: str
    kind: str
    raw: dict[str, object] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    dev_dependencies: list[str] = Field(default_factory=list)
    scripts: dict[str, str] = Field(default_factory=dict)
    name: str | None = None
    package_manager_hint: str | None = Field(
        default=None,
        description=(
            "Authoritative package manager when the manifest declares one (e.g. "
            "package.json's `packageManager` field)."
        ),
    )
    declared_tools: list[str] = Field(
        default_factory=list,
        description=(
            "Tools that are *configured* (have their own [tool.x] table or config "
            "file), as opposed to merely installed. Used to distinguish "
            "'ruff is in deps' from 'ruff is the chosen linter'."
        ),
    )
    workspace_globs: list[str] = Field(
        default_factory=list,
        description="Workspace member globs, e.g. 'apps/*' from package.json.",
    )


def _parse_pyproject(path: Path) -> tuple[ManifestData | None, list[Finding]]:
    findings: list[Finding] = []
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        findings.append(_parse_warning(path, "pyproject.toml", exc))
        return None, findings

    project = raw.get("project", {}) if isinstance(raw, dict) else {}
    deps: list[str] = []
    dev: list[str] = []
    scripts: dict[str, str] = {}
    if isinstance(project, dict):
        proj_deps = project.get("dependencies", [])
        if isinstance(proj_deps, list):
            deps.extend(_extract_pep508_names(proj_deps))
        opt = project.get("optional-dependencies", {})
        if isinstance(opt, dict):
            for items in opt.values():
                if isinstance(items, list):
                    dev.extend(_extract_pep508_names(items))
        proj_scripts = project.get("scripts", {})
        if isinstance(proj_scripts, dict):
            for k, v in proj_scripts.items():
                if isinstance(k, str) and isinstance(v, str):
                    scripts[k] = v

    # PEP 735 dependency-groups (e.g. [dependency-groups].dev = [...]).
    dep_groups = raw.get("dependency-groups", {}) if isinstance(raw, dict) else {}
    if isinstance(dep_groups, dict):
        for items in dep_groups.values():
            if isinstance(items, list):
                dev.extend(_extract_pep508_names(items))

    # Poetry / poetry groups.
    poetry = raw.get("tool", {}).get("poetry", {}) if isinstance(raw, dict) else {}
    if isinstance(poetry, dict):
        poetry_deps = poetry.get("dependencies", {})
        if isinstance(poetry_deps, dict):
            deps.extend(k for k in poetry_deps if isinstance(k, str) and k != "python")
        groups = poetry.get("group", {})
        if isinstance(groups, dict):
            for group in groups.values():
                if isinstance(group, dict):
                    g_deps = group.get("dependencies", {})
                    if isinstance(g_deps, dict):
                        dev.extend(k for k in g_deps if isinstance(k, str) and k != "python")

    # Tools that are *configured*, not just present as deps.
    tools_table = raw.get("tool", {}) if isinstance(raw, dict) else {}
    declared_tools: list[str] = []
    if isinstance(tools_table, dict):
        declared_tools = sorted(k for k in tools_table if isinstance(k, str))

    name = project.get("name") if isinstance(project, dict) else None
    return (
        ManifestData(
            path=path.name,
            kind="pyproject",
            raw=raw if isinstance(raw, dict) else {},
            dependencies=sorted(set(deps)),
            dev_dependencies=sorted(set(dev)),
            scripts=scripts,
            name=name if isinstance(name, str) else None,
            declared_tools=declared_tools,
        ),
        findings,
    )


_PEP508_RE = re.compile(r"^[A-Za-z0-9_.\-]+")


def _extract_pep508_names(items: list[object]) -> list[str]:
    """Pull bare distribution names out of a list of PEP 508 requirement strings."""
    names: list[str] = []
    for entry in items:
        if not isinstance(entry, str):
            continue
        token = entry.split(";", 1)[0].strip()
        token = token.split("@", 1)[0].strip()  # url-style: 'pkg @ git+...'
        match = _PEP508_RE.match(token)
        if match:
            names.append(match.group(0).lower())
    return names


def _parse_package_json(path: Path) -> tuple[ManifestData | None, list[Finding]]:
    findings: list[Finding] = []
    text = safe_read_text(path)
    if text is None:
        return None, findings
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        findings.append(_parse_warning(path, "package.json", exc))
        return None, findings
    if not isinstance(raw, dict):
        return None, findings

    raw_deps = raw.get("dependencies", {})
    raw_dev = raw.get("devDependencies", {})
    deps = sorted(raw_deps) if isinstance(raw_deps, dict) else []
    dev = sorted(raw_dev) if isinstance(raw_dev, dict) else []
    scripts_raw = raw.get("scripts", {})
    scripts = (
        {k: v for k, v in scripts_raw.items() if isinstance(k, str) and isinstance(v, str)}
        if isinstance(scripts_raw, dict)
        else {}
    )
    name = raw.get("name") if isinstance(raw.get("name"), str) else None

    # `packageManager: "pnpm@9.0.0"` is the canonical signal — use it directly
    # when present. We strip the version pin.
    pm_field = raw.get("packageManager")
    pm_hint: str | None = None
    if isinstance(pm_field, str) and "@" in pm_field:
        pm_hint = pm_field.split("@", 1)[0].strip().lower() or None
    elif isinstance(pm_field, str) and pm_field.strip():
        pm_hint = pm_field.strip().lower()

    workspaces_field = raw.get("workspaces")
    workspace_globs: list[str] = []
    if isinstance(workspaces_field, list):
        workspace_globs = [w for w in workspaces_field if isinstance(w, str)]
    elif isinstance(workspaces_field, dict):
        packages = workspaces_field.get("packages")
        if isinstance(packages, list):
            workspace_globs = [w for w in packages if isinstance(w, str)]

    return (
        ManifestData(
            path=path.name,
            kind="package.json",
            raw=raw,
            dependencies=deps,
            dev_dependencies=dev,
            scripts=scripts,
            name=name,
            package_manager_hint=pm_hint,
            workspace_globs=workspace_globs,
        ),
        findings,
    )


def _parse_cargo(path: Path) -> tuple[ManifestData | None, list[Finding]]:
    findings: list[Finding] = []
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        findings.append(_parse_warning(path, "Cargo.toml", exc))
        return None, findings
    deps_raw = raw.get("dependencies", {}) if isinstance(raw, dict) else {}
    dev_raw = raw.get("dev-dependencies", {}) if isinstance(raw, dict) else {}
    deps = sorted(deps_raw.keys()) if isinstance(deps_raw, dict) else []
    dev = sorted(dev_raw.keys()) if isinstance(dev_raw, dict) else []
    workspace = raw.get("workspace", {}) if isinstance(raw, dict) else {}
    workspace_globs: list[str] = []
    if isinstance(workspace, dict):
        members = workspace.get("members", [])
        if isinstance(members, list):
            workspace_globs = [m for m in members if isinstance(m, str)]
        ws_deps = workspace.get("dependencies", {})
        if isinstance(ws_deps, dict):
            deps.extend(ws_deps.keys())
            deps = sorted(set(deps))
    name: str | None = None
    pkg = raw.get("package", {}) if isinstance(raw, dict) else {}
    if isinstance(pkg, dict) and isinstance(pkg.get("name"), str):
        name = pkg["name"]
    return (
        ManifestData(
            path=path.name,
            kind="Cargo.toml",
            raw=raw if isinstance(raw, dict) else {},
            dependencies=deps,
            dev_dependencies=dev,
            name=name,
            workspace_globs=workspace_globs,
        ),
        findings,
    )


def _parse_go_mod(path: Path) -> tuple[ManifestData | None, list[Finding]]:
    findings: list[Finding] = []
    text = safe_read_text(path)
    if text is None:
        return None, findings
    name: str | None = None
    deps: list[str] = []
    in_require_block = False
    for raw_line in text.splitlines():
        # Strip inline comments and surrounding whitespace.
        line = raw_line.split("//", 1)[0].strip()
        if not line:
            continue
        if line.startswith("module "):
            name = line.split(" ", 1)[1].strip().strip('"')
            continue
        if in_require_block:
            if line.startswith(")"):
                in_require_block = False
                continue
            token = line.split()[0] if line.split() else ""
            if token and not token.startswith(")"):
                deps.append(token)
            continue
        if line.startswith("require ("):
            in_require_block = True
            continue
        if line.startswith("require "):
            tail = line[len("require ") :].strip()
            if tail and not tail.startswith("("):
                token = tail.split(" ", 1)[0]
                if token:
                    deps.append(token)
    return (
        ManifestData(
            path=path.name,
            kind="go.mod",
            dependencies=sorted(set(deps)),
            name=name,
        ),
        findings,
    )


def _parse_go_work(path: Path) -> tuple[ManifestData | None, list[Finding]]:
    """Parse a Go workspace file (``go.work``) for ``use`` directives."""
    text = safe_read_text(path)
    if text is None:
        return None, []
    members: list[str] = []
    in_use_block = False
    for raw_line in text.splitlines():
        line = raw_line.split("//", 1)[0].strip()
        if not line:
            continue
        if in_use_block:
            if line.startswith(")"):
                in_use_block = False
                continue
            members.append(line)
            continue
        if line.startswith("use ("):
            in_use_block = True
            continue
        if line.startswith("use "):
            tail = line[len("use ") :].strip()
            if tail and not tail.startswith("("):
                members.append(tail)
    return (
        ManifestData(
            path=path.name,
            kind="go.work",
            workspace_globs=[m for m in members if m],
        ),
        [],
    )


_REQ_LINE_RE = re.compile(r"^[A-Za-z0-9_.\-]+")


def _parse_requirements_txt(path: Path) -> tuple[ManifestData | None, list[Finding]]:
    """Parse a pip ``requirements.txt`` (best-effort).

    Recognizes name-only lines, version pins, ``-r other.txt`` includes (kept
    as evidence but not followed), and the ``-e .`` editable self-install.
    """
    text = safe_read_text(path)
    if text is None:
        return None, []
    deps: list[str] = []
    is_dev = "dev" in path.name.lower() or "test" in path.name.lower()
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        # Drop env markers and URLs.
        token = line.split(";", 1)[0].strip()
        token = token.split("@", 1)[0].strip()
        match = _REQ_LINE_RE.match(token)
        if match:
            deps.append(match.group(0).lower())
    deps = sorted(set(deps))
    return (
        ManifestData(
            path=path.name,
            kind="requirements.txt",
            dependencies=[] if is_dev else deps,
            dev_dependencies=deps if is_dev else [],
        ),
        [],
    )


def _parse_setup_cfg(path: Path) -> tuple[ManifestData | None, list[Finding]]:
    """Parse a setup.cfg ``[options]`` block for install_requires."""
    text = safe_read_text(path)
    if text is None:
        return None, []
    import configparser

    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        return None, [_parse_warning(path, "setup.cfg", exc)]
    deps: list[str] = []
    dev: list[str] = []
    name: str | None = None
    if parser.has_section("metadata"):
        candidate = parser.get("metadata", "name", fallback=None)
        if candidate:
            name = candidate.strip()
    if parser.has_section("options"):
        ireq = parser.get("options", "install_requires", fallback="")
        deps.extend(_extract_pep508_names([ln for ln in ireq.splitlines()]))
    if parser.has_section("options.extras_require"):
        for _, value in parser.items("options.extras_require"):
            dev.extend(_extract_pep508_names([ln for ln in value.splitlines()]))
    return (
        ManifestData(
            path=path.name,
            kind="setup.cfg",
            dependencies=sorted(set(deps)),
            dev_dependencies=sorted(set(dev)),
            name=name,
        ),
        [],
    )


def _parse_setup_py(path: Path) -> tuple[ManifestData | None, list[Finding]]:
    """Tiny best-effort scrape of setup.py (no exec; just regex)."""
    text = safe_read_text(path)
    if text is None:
        return None, []
    name_match = re.search(r"name\s*=\s*['\"]([A-Za-z0-9_.\-]+)['\"]", text)
    install_block = re.search(r"install_requires\s*=\s*\[([^\]]*)\]", text, re.DOTALL)
    deps: list[str] = []
    if install_block:
        for chunk in re.findall(r"['\"]([^'\"]+)['\"]", install_block.group(1)):
            deps.extend(_extract_pep508_names([chunk]))
    extras_block = re.search(r"extras_require\s*=\s*\{([^}]*)\}", text, re.DOTALL)
    dev: list[str] = []
    if extras_block:
        for chunk in re.findall(r"['\"]([^'\"]+)['\"]", extras_block.group(1)):
            dev.extend(_extract_pep508_names([chunk]))
    return (
        ManifestData(
            path=path.name,
            kind="setup.py",
            dependencies=sorted(set(deps)),
            dev_dependencies=sorted(set(dev)),
            name=name_match.group(1) if name_match else None,
        ),
        [],
    )


def _parse_pipfile(path: Path) -> tuple[ManifestData | None, list[Finding]]:
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return None, [_parse_warning(path, "Pipfile", exc)]
    deps_raw = raw.get("packages", {}) if isinstance(raw, dict) else {}
    dev_raw = raw.get("dev-packages", {}) if isinstance(raw, dict) else {}
    deps = sorted(k for k in deps_raw if isinstance(k, str)) if isinstance(deps_raw, dict) else []
    dev = sorted(k for k in dev_raw if isinstance(k, str)) if isinstance(dev_raw, dict) else []
    return (
        ManifestData(
            path=path.name,
            kind="Pipfile",
            raw=raw if isinstance(raw, dict) else {},
            dependencies=deps,
            dev_dependencies=dev,
        ),
        [],
    )


def _parse_pnpm_workspace(path: Path) -> tuple[ManifestData | None, list[Finding]]:
    raw = safe_yaml_load(path)
    if not isinstance(raw, dict):
        return None, []
    packages = raw.get("packages")
    if not isinstance(packages, list):
        return None, []
    return (
        ManifestData(
            path=path.name,
            kind="pnpm-workspace.yaml",
            workspace_globs=[p for p in packages if isinstance(p, str)],
        ),
        [],
    )


def _parse_simple_json_workspace(kind: str) -> Callable[[Path], tuple[ManifestData | None, list[Finding]]]:
    """Build a parser for monorepo JSON files like ``nx.json`` / ``turbo.json``."""

    def _inner(path: Path) -> tuple[ManifestData | None, list[Finding]]:
        text = safe_read_text(path)
        if text is None:
            return None, []
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            return None, [_parse_warning(path, kind, exc)]
        if not isinstance(raw, dict):
            return None, []
        return (
            ManifestData(path=path.name, kind=kind, raw=raw),
            [],
        )

    return _inner


def _parse_dockerfile(path: Path) -> tuple[ManifestData | None, list[Finding]]:
    text = safe_read_text(path)
    if text is None:
        return None, []
    return (
        ManifestData(path=path.name, kind="Dockerfile", raw={"content": text}),
        [],
    )


def _parse_docker_compose(path: Path) -> tuple[ManifestData | None, list[Finding]]:
    raw = safe_yaml_load(path)
    if raw is None:
        return None, []
    return (
        ManifestData(
            path=path.name,
            kind="docker-compose",
            raw=raw if isinstance(raw, dict) else {},
        ),
        [],
    )


PARSERS: dict[str, Callable[[Path], tuple[ManifestData | None, list[Finding]]]] = {
    "pyproject.toml": _parse_pyproject,
    "package.json": _parse_package_json,
    "Cargo.toml": _parse_cargo,
    "go.mod": _parse_go_mod,
    "go.work": _parse_go_work,
    "requirements.txt": _parse_requirements_txt,
    "requirements-dev.txt": _parse_requirements_txt,
    "requirements_dev.txt": _parse_requirements_txt,
    "requirements-test.txt": _parse_requirements_txt,
    "dev-requirements.txt": _parse_requirements_txt,
    "test-requirements.txt": _parse_requirements_txt,
    "setup.cfg": _parse_setup_cfg,
    "setup.py": _parse_setup_py,
    "Pipfile": _parse_pipfile,
    "pnpm-workspace.yaml": _parse_pnpm_workspace,
    "pnpm-workspace.yml": _parse_pnpm_workspace,
    "nx.json": _parse_simple_json_workspace("nx.json"),
    "turbo.json": _parse_simple_json_workspace("turbo.json"),
    "lerna.json": _parse_simple_json_workspace("lerna.json"),
    "rush.json": _parse_simple_json_workspace("rush.json"),
    "Dockerfile": _parse_dockerfile,
    "docker-compose.yml": _parse_docker_compose,
    "docker-compose.yaml": _parse_docker_compose,
    "compose.yml": _parse_docker_compose,
    "compose.yaml": _parse_docker_compose,
}


def parse_manifests(repo_path: Path, files: list[Path]) -> tuple[list[ManifestData], list[Finding]]:
    """Parse every recognized manifest under the repo, in path order.

    Returns the parsed manifests together with any warning Findings produced
    by parse failures so the orchestrator can attach them to the model.
    """
    out: list[ManifestData] = []
    findings: list[Finding] = []
    for f in files:
        parser = PARSERS.get(f.name)
        if not parser:
            continue
        parsed, parser_findings = parser(f)
        findings.extend(parser_findings)
        if parsed is None:
            continue
        parsed.path = f.relative_to(repo_path).as_posix()
        out.append(parsed)
    return out, findings


def _parse_warning(path: Path, kind: str, exc: Exception) -> Finding:
    return Finding(
        kind="parse-warning",
        subject=path.name,
        rationale=f"Failed to parse {kind} ({type(exc).__name__}): {exc}",
        evidence=[path.name],
        confidence=Confidence.low,
    )
