"""Parse common manifests (pyproject.toml, package.json, Cargo.toml, etc.)."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from repocanon.utils.fs import safe_read_text


@dataclass
class ManifestData:
    """Parsed contents of a single manifest file."""

    path: str
    kind: str
    raw: dict[str, object] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    dev_dependencies: list[str] = field(default_factory=list)
    scripts: dict[str, str] = field(default_factory=dict)
    name: str | None = None


def _parse_pyproject(path: Path) -> ManifestData | None:
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    project = raw.get("project", {}) if isinstance(raw, dict) else {}
    deps: list[str] = []
    dev: list[str] = []
    if isinstance(project, dict):
        proj_deps = project.get("dependencies", [])
        if isinstance(proj_deps, list):
            deps.extend(_extract_pep508_names(proj_deps))
        opt = project.get("optional-dependencies", {})
        if isinstance(opt, dict):
            for items in opt.values():
                if isinstance(items, list):
                    dev.extend(_extract_pep508_names(items))
    poetry = raw.get("tool", {}).get("poetry", {}) if isinstance(raw, dict) else {}
    if isinstance(poetry, dict):
        for items in (poetry.get("dependencies", {}), poetry.get("group", {})):
            if isinstance(items, dict):
                deps.extend(k for k in items if isinstance(k, str) and k != "python")
    name = project.get("name") if isinstance(project, dict) else None
    return ManifestData(
        path=path.name,
        kind="pyproject",
        raw=raw if isinstance(raw, dict) else {},
        dependencies=sorted(set(deps)),
        dev_dependencies=sorted(set(dev)),
        name=name if isinstance(name, str) else None,
    )


def _extract_pep508_names(items: list[object]) -> list[str]:
    names: list[str] = []
    for entry in items:
        if not isinstance(entry, str):
            continue
        # Strip extras and version specifiers: "fastapi[all]>=0.100" -> "fastapi"
        token = entry.split(";", 1)[0].strip()
        for sep in ("[", "=", ">", "<", "~", "!", " "):
            idx = token.find(sep)
            if idx != -1:
                token = token[:idx]
        if token:
            names.append(token.lower())
    return names


def _parse_package_json(path: Path) -> ManifestData | None:
    text = safe_read_text(path)
    if text is None:
        return None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
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
    return ManifestData(
        path=path.name,
        kind="package.json",
        raw=raw,
        dependencies=deps,
        dev_dependencies=dev,
        scripts=scripts,
        name=name,
    )


def _parse_cargo(path: Path) -> ManifestData | None:
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    deps_raw = raw.get("dependencies", {}) if isinstance(raw, dict) else {}
    deps = sorted(deps_raw.keys()) if isinstance(deps_raw, dict) else []
    name = None
    pkg = raw.get("package", {}) if isinstance(raw, dict) else {}
    if isinstance(pkg, dict) and isinstance(pkg.get("name"), str):
        name = pkg["name"]
    return ManifestData(
        path=path.name,
        kind="Cargo.toml",
        raw=raw if isinstance(raw, dict) else {},
        dependencies=deps,
        name=name,
    )


def _parse_go_mod(path: Path) -> ManifestData | None:
    text = safe_read_text(path)
    if text is None:
        return None
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
            # Lines inside `require (` look like:
            #   github.com/gin-gonic/gin v1.9.1
            #   github.com/foo/bar v1.0.0 // indirect
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
    return ManifestData(
        path=path.name,
        kind="go.mod",
        dependencies=sorted(set(deps)),
        name=name,
    )


PARSERS: dict[str, Callable[[Path], ManifestData | None]] = {
    "pyproject.toml": _parse_pyproject,
    "package.json": _parse_package_json,
    "Cargo.toml": _parse_cargo,
    "go.mod": _parse_go_mod,
}


def parse_manifests(repo_path: Path, files: list[Path]) -> list[ManifestData]:
    """Parse every recognized manifest under the repo, in path order."""
    out: list[ManifestData] = []
    for f in files:
        parser = PARSERS.get(f.name)
        if not parser:
            continue
        parsed = parser(f)
        if parsed is None:
            continue
        parsed.path = f.relative_to(repo_path).as_posix()
        out.append(parsed)
    return out
