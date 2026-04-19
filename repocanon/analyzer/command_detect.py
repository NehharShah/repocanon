"""Extract install/build/test/lint commands from manifests and task runners.

Two layers of detection:

- :func:`detect_commands` aggregates root-level commands across the repo.
- :func:`commands_for_manifest` extracts commands attributable to a single
  manifest, used by the topology layer to attach per-package commands to
  monorepo entries.

The classifier is order-aware: tokens like ``publish``, ``release``, and
``deploy`` win against ``test``/``build``/``dev`` so that scripts named
``publish-test`` or ``deploy-prod`` don't get bucketed as test or dev. The
``start`` token is treated as Dev only when no separate ``dev`` script
exists, since most ecosystems use ``start`` for production servers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from repocanon.analyzer.config_parse import ManifestData
from repocanon.models.findings import Confidence, Finding
from repocanon.models.project import CommandSet, PackageManager
from repocanon.utils.fs import safe_read_text

# Tokens that strongly signal release/deploy/publish surfaces. They win over
# any other classifier so 'publish-test' isn't bucketed as a test command.
_RELEASE_TOKENS: frozenset[str] = frozenset(
    {
        "publish",
        "release",
        "deploy",
        "ship",
        "tag",
        "docker",
        "image",
        "push",
        "upload",
    }
)

_TEST_KEYS: frozenset[str] = frozenset({"test", "tests", "pytest", "vitest", "jest", "spec"})
_LINT_KEYS: frozenset[str] = frozenset({"lint", "eslint", "ruff", "flake", "biome"})
_FORMAT_KEYS: frozenset[str] = frozenset({"format", "fmt", "prettier"})
_TYPECHECK_KEYS: frozenset[str] = frozenset({"typecheck", "tsc", "mypy", "type-check", "pyright"})
_BUILD_KEYS: frozenset[str] = frozenset({"build", "compile", "bundle"})
_DEV_KEYS: frozenset[str] = frozenset({"dev", "serve", "watch", "run"})


def _tokens(name: str) -> set[str]:
    """Split a script/target name into lowercase tokens for keyword matching."""
    n = name.lower()
    for sep in ("-", "_", ":", ".", "/"):
        n = n.replace(sep, " ")
    return {t for t in n.split() if t}


def _classify(
    name: str,
    command: str,
    cs: CommandSet,
    *,
    has_dev_script: bool,
) -> bool:
    """Bucket a single named script. Returns True when it landed somewhere.

    Precedence is deliberate: release/publish/deploy beats every code-action
    bucket, then we try the more specific tool tokens (test/lint/format/
    typecheck) before the broader build/dev tokens. The ``start`` token only
    counts as Dev when the package doesn't already define a dedicated ``dev``
    script — otherwise it almost always means "production start server."
    """
    toks = _tokens(name)

    # Release-y scripts go straight to extras so they don't pollute the
    # routine validation buckets.
    if toks & _RELEASE_TOKENS:
        cs.extras.setdefault("release", []).append(command)
        return True

    classifier_order: tuple[tuple[frozenset[str], list[str]], ...] = (
        (_TEST_KEYS, cs.test),
        (_LINT_KEYS, cs.lint),
        (_FORMAT_KEYS, cs.format),
        (_TYPECHECK_KEYS, cs.typecheck),
        (_BUILD_KEYS, cs.build),
        (_DEV_KEYS, cs.dev),
    )
    for keys, bucket in classifier_order:
        if toks & keys:
            bucket.append(command)
            return True
    if "start" in toks:
        bucket = cs.dev if not has_dev_script else cs.extras.setdefault("scripts", [])
        bucket.append(command)
        return True
    return False


def _from_npm_scripts(
    manifest: ManifestData, package_manager: str | None
) -> tuple[CommandSet, list[Finding]]:
    cs = CommandSet()
    findings: list[Finding] = []
    runner = package_manager or "npm"
    runner_cmd = "npm run" if runner == "npm" else f"{runner} run"
    runner_install = {
        "npm": "npm install",
        "pnpm": "pnpm install",
        "yarn": "yarn",
        "bun": "bun install",
    }.get(runner, "npm install")

    if manifest.scripts:
        cs.install.append(runner_install)
        findings.append(
            Finding(
                kind="command",
                subject="install",
                rationale=f"Default install command for {runner}.",
                evidence=[manifest.path],
                confidence=Confidence.high,
            )
        )

    has_dev = "dev" in manifest.scripts
    for name, cmd in manifest.scripts.items():
        invocation = f"{runner_cmd} {name}"
        if not _classify(name, invocation, cs, has_dev_script=has_dev):
            cs.extras.setdefault("scripts", []).append(f"{name}: {cmd}")
        findings.append(
            Finding(
                kind="command",
                subject=name,
                rationale=f"npm script in {manifest.path}.",
                evidence=[f"{name}: {cmd}"],
                confidence=Confidence.high,
            )
        )
    return cs, findings


def _from_pyproject(
    manifest: ManifestData, package_manager: str | None
) -> tuple[CommandSet, list[Finding]]:
    cs = CommandSet()
    findings: list[Finding] = []
    pm = package_manager or "pip"

    if pm == "uv":
        cs.install.append("uv sync")
    elif pm == "poetry":
        cs.install.append("poetry install")
    else:
        cs.install.append("python -m pip install -e .")

    deps = {d.lower() for d in (*manifest.dependencies, *manifest.dev_dependencies)}
    declared_tools = {t.lower() for t in manifest.declared_tools}

    if "pytest" in deps or "pytest" in declared_tools:
        cs.test.append("pytest")
    if "ruff" in deps or "ruff" in declared_tools:
        cs.lint.append("ruff check .")
        cs.format.append("ruff format .")
    if "mypy" in deps or "mypy" in declared_tools:
        cs.typecheck.append("mypy .")
    if "pyright" in deps or "pyright" in declared_tools:
        cs.typecheck.append("pyright")
    if "black" in deps or "black" in declared_tools:
        cs.format.append("black .")

    # `[project.scripts]` exposes installable console entry points. Surface
    # them so AI agents know the binary names users actually invoke.
    if manifest.scripts:
        for name in sorted(manifest.scripts):
            cs.extras.setdefault("entry-points", []).append(name)

    findings.append(
        Finding(
            kind="command",
            subject="install",
            rationale=f"Inferred install command for {pm}.",
            evidence=[manifest.path],
            confidence=Confidence.high,
        )
    )
    return cs, findings


def _from_requirements(
    manifest: ManifestData,
) -> tuple[CommandSet, list[Finding]]:
    cs = CommandSet()
    findings: list[Finding] = []
    cs.install.append(f"python -m pip install -r {manifest.path}")
    deps = {d.lower() for d in (*manifest.dependencies, *manifest.dev_dependencies)}
    if "pytest" in deps:
        cs.test.append("pytest")
    if "ruff" in deps:
        cs.lint.append("ruff check .")
        cs.format.append("ruff format .")
    if "mypy" in deps:
        cs.typecheck.append("mypy .")
    if "black" in deps:
        cs.format.append("black .")
    findings.append(
        Finding(
            kind="command",
            subject="install",
            rationale=f"requirements file at {manifest.path}.",
            evidence=[manifest.path],
            confidence=Confidence.medium,
        )
    )
    return cs, findings


_MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?!=)")


def _from_makefile(path: Path) -> tuple[CommandSet, list[Finding]]:
    cs = CommandSet()
    findings: list[Finding] = []
    text = safe_read_text(path)
    if text is None:
        return cs, findings
    targets: list[str] = []
    for line in text.splitlines():
        m = _MAKE_TARGET_RE.match(line)
        if not m:
            continue
        target = m.group(1)
        if target in {".PHONY", "default", "all"}:
            continue
        targets.append(target)
    has_dev = "dev" in targets
    for target in targets:
        invocation = f"make {target}"
        if not _classify(target, invocation, cs, has_dev_script=has_dev):
            cs.extras.setdefault("make", []).append(target)
        findings.append(
            Finding(
                kind="command",
                subject=target,
                rationale="Make target discovered.",
                evidence=[f"Makefile: {target}"],
                confidence=Confidence.medium,
            )
        )
    return cs, findings


_JUSTFILE_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*(?:\([^)]*\))?\s*:")


def _from_justfile(path: Path) -> tuple[CommandSet, list[Finding]]:
    cs = CommandSet()
    findings: list[Finding] = []
    text = safe_read_text(path)
    if text is None:
        return cs, findings
    targets: list[str] = []
    for line in text.splitlines():
        m = _JUSTFILE_RE.match(line)
        if not m or line.lstrip().startswith("#"):
            continue
        targets.append(m.group(1))
    has_dev = "dev" in targets
    for target in targets:
        invocation = f"just {target}"
        if not _classify(target, invocation, cs, has_dev_script=has_dev):
            cs.extras.setdefault("just", []).append(target)
        findings.append(
            Finding(
                kind="command",
                subject=target,
                rationale="just recipe discovered.",
                evidence=[f"Justfile: {target}"],
                confidence=Confidence.medium,
            )
        )
    return cs, findings


def _from_taskfile(path: Path) -> tuple[CommandSet, list[Finding]]:
    """Parse a Taskfile.yml without requiring it to be valid YAML semantics."""
    from repocanon.utils.fs import safe_yaml_load

    cs = CommandSet()
    findings: list[Finding] = []
    raw = safe_yaml_load(path)
    if not isinstance(raw, dict):
        return cs, findings
    tasks_raw = raw.get("tasks")
    if not isinstance(tasks_raw, dict):
        return cs, findings
    targets = sorted(k for k in tasks_raw if isinstance(k, str))
    has_dev = "dev" in targets
    for target in targets:
        invocation = f"task {target}"
        if not _classify(target, invocation, cs, has_dev_script=has_dev):
            cs.extras.setdefault("task", []).append(target)
        findings.append(
            Finding(
                kind="command",
                subject=target,
                rationale="Taskfile entry discovered.",
                evidence=[f"Taskfile: {target}"],
                confidence=Confidence.medium,
            )
        )
    return cs, findings


_TOX_ENV_RE = re.compile(r"^\[testenv:([A-Za-z0-9_.-]+)\]")


def _from_tox(path: Path) -> tuple[CommandSet, list[Finding]]:
    cs = CommandSet()
    findings: list[Finding] = []
    text = safe_read_text(path)
    if text is None:
        return cs, findings
    envs: list[str] = []
    for line in text.splitlines():
        match = _TOX_ENV_RE.match(line.strip())
        if match:
            envs.append(match.group(1))
    if "[testenv]" in text or envs:
        cs.test.append("tox")
        for env in envs:
            cs.extras.setdefault("tox", []).append(env)
        findings.append(
            Finding(
                kind="command",
                subject="tox",
                rationale="tox.ini detected.",
                evidence=[path.name],
                confidence=Confidence.medium,
            )
        )
    return cs, findings


def _from_noxfile(path: Path) -> tuple[CommandSet, list[Finding]]:
    cs = CommandSet()
    findings: list[Finding] = []
    text = safe_read_text(path)
    if text is None:
        return cs, findings
    sessions = re.findall(r"@nox\.session[^\n]*\ndef\s+([A-Za-z0-9_]+)", text)
    if sessions:
        cs.test.append("nox")
        for s in sessions:
            cs.extras.setdefault("nox", []).append(s)
        findings.append(
            Finding(
                kind="command",
                subject="nox",
                rationale="noxfile.py with sessions detected.",
                evidence=[path.name],
                confidence=Confidence.medium,
            )
        )
    return cs, findings


def commands_for_manifest(
    manifest: ManifestData,
    package_manager: str | None,
) -> tuple[CommandSet, list[Finding]]:
    """Extract commands attributable to a single manifest (no Makefile etc.)."""
    if manifest.kind == "package.json":
        return _from_npm_scripts(manifest, package_manager)
    if manifest.kind == "pyproject":
        return _from_pyproject(manifest, package_manager)
    if manifest.kind in {"requirements.txt", "Pipfile", "setup.cfg", "setup.py"}:
        return _from_requirements(manifest)
    if manifest.kind == "Cargo.toml":
        cs = CommandSet()
        cs.install.append("cargo build")
        cs.test.append("cargo test")
        cs.build.append("cargo build --release")
        return cs, []
    if manifest.kind == "go.mod":
        cs = CommandSet()
        cs.build.append("go build ./...")
        cs.test.append("go test ./...")
        return cs, []
    return CommandSet(), []


def _docker_commands(manifests: list[ManifestData]) -> CommandSet:
    cs = CommandSet()
    has_dockerfile = any(m.kind == "Dockerfile" for m in manifests)
    has_compose = any(m.kind == "docker-compose" for m in manifests)
    if has_compose:
        cs.dev.append("docker compose up")
        cs.extras.setdefault("docker", []).append("docker compose down")
    if has_dockerfile and not has_compose:
        cs.build.append("docker build .")
    return cs


def detect_commands(
    repo_path: Path,
    files: Iterable[Path],
    manifests: list[ManifestData],
    package_managers: list[PackageManager],
) -> tuple[CommandSet, list[Finding]]:
    """Return a CommandSet aggregated across all root-level sources.

    Per-package commands inside a monorepo are attached to each
    :class:`Package` separately by the topology layer; nested manifests do
    *not* leak their scripts into the root command set here.
    """
    cs = CommandSet()
    findings: list[Finding] = []

    pm_for_kind: dict[str, str] = {}
    for pm in package_managers:
        if pm.manifest.endswith("pyproject.toml"):
            pm_for_kind["pyproject"] = pm.name
        elif pm.manifest.endswith("package.json"):
            pm_for_kind["package.json"] = pm.name

    # Only ingest *root-level* manifests into the global command set. Anything
    # nested belongs to a sub-package.
    for m in manifests:
        is_root = "/" not in m.path
        if not is_root:
            continue
        if m.kind == "package.json":
            sub_cs, sub_f = _from_npm_scripts(m, pm_for_kind.get("package.json"))
        elif m.kind == "pyproject":
            sub_cs, sub_f = _from_pyproject(m, pm_for_kind.get("pyproject"))
        elif m.kind in {"requirements.txt", "Pipfile", "setup.cfg", "setup.py"}:
            sub_cs, sub_f = _from_requirements(m)
        elif m.kind == "Cargo.toml":
            sub_cs = CommandSet()
            sub_cs.install.append("cargo build")
            sub_cs.test.append("cargo test")
            sub_cs.build.append("cargo build --release")
            sub_f = [
                Finding(
                    kind="command",
                    subject="cargo",
                    rationale="Cargo.toml present.",
                    evidence=[m.path],
                    confidence=Confidence.high,
                )
            ]
        elif m.kind == "go.mod":
            sub_cs = CommandSet()
            sub_cs.build.append("go build ./...")
            sub_cs.test.append("go test ./...")
            sub_f = [
                Finding(
                    kind="command",
                    subject="go",
                    rationale="go.mod present.",
                    evidence=[m.path],
                    confidence=Confidence.high,
                )
            ]
        else:
            continue
        cs.merge(sub_cs)
        findings.extend(sub_f)

    # Task runners (only root-level: a Justfile in apps/web is that package's
    # business). We use the same "is at repo root" rule as for manifests.
    for f in files:
        rel = f.relative_to(repo_path).as_posix()
        if "/" in rel:
            continue
        if f.name in {"Makefile", "makefile", "GNUmakefile"}:
            sub_cs, sub_f = _from_makefile(f)
            cs.merge(sub_cs)
            findings.extend(sub_f)
        elif f.name in {"Justfile", "justfile"}:
            sub_cs, sub_f = _from_justfile(f)
            cs.merge(sub_cs)
            findings.extend(sub_f)
        elif f.name in {"Taskfile.yml", "Taskfile.yaml"}:
            sub_cs, sub_f = _from_taskfile(f)
            cs.merge(sub_cs)
            findings.extend(sub_f)
        elif f.name == "tox.ini":
            sub_cs, sub_f = _from_tox(f)
            cs.merge(sub_cs)
            findings.extend(sub_f)
        elif f.name == "noxfile.py":
            sub_cs, sub_f = _from_noxfile(f)
            cs.merge(sub_cs)
            findings.extend(sub_f)

    cs.merge(_docker_commands(manifests))

    return cs, findings
