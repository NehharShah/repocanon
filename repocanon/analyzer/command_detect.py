"""Extract install/build/test/lint commands from manifests and Makefiles."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from repocanon.analyzer.config_parse import ManifestData
from repocanon.models.findings import Confidence, Finding
from repocanon.models.project import CommandSet, PackageManager
from repocanon.utils.fs import safe_read_text

# Heuristic keyword buckets used to classify npm/pyproject/Makefile script names.
_TEST_KEYS = ("test", "tests", "pytest", "vitest", "jest", "spec")
_LINT_KEYS = ("lint", "eslint", "ruff", "flake")
_FORMAT_KEYS = ("format", "fmt", "prettier")
_TYPECHECK_KEYS = ("typecheck", "tsc", "mypy", "type-check")
_BUILD_KEYS = ("build", "compile", "bundle")
_DEV_KEYS = ("dev", "start", "serve", "watch", "run")


def _tokens(name: str) -> set[str]:
    """Split a script/target name into lowercase tokens for keyword matching."""
    n = name.lower()
    for sep in ("-", "_", ":", "."):
        n = n.replace(sep, " ")
    return {t for t in n.split() if t}


def _classify(name: str, command: str, cs: CommandSet) -> bool:
    """Bucket a single named script. Returns True when it landed somewhere.

    We tokenize on common separators so that 'publish-test' or 'pre:lint'
    aren't accidentally bucketed by substring match. The first matching
    bucket wins; order reflects how strongly each keyword implies its bucket.
    """
    toks = _tokens(name)
    for keys, bucket in (
        (_TEST_KEYS, cs.test),
        (_LINT_KEYS, cs.lint),
        (_FORMAT_KEYS, cs.format),
        (_TYPECHECK_KEYS, cs.typecheck),
        (_BUILD_KEYS, cs.build),
        (_DEV_KEYS, cs.dev),
    ):
        if toks & set(keys):
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

    for name, cmd in manifest.scripts.items():
        invocation = f"{runner_cmd} {name}"
        if not _classify(name, invocation, cs):
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
            rationale=f"Inferred install command for {pm}.",
            evidence=[manifest.path],
            confidence=Confidence.high,
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
    for line in text.splitlines():
        m = _MAKE_TARGET_RE.match(line)
        if not m:
            continue
        target = m.group(1)
        if target in {".PHONY", "default", "all"}:
            continue
        invocation = f"make {target}"
        if not _classify(target, invocation, cs):
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


def _merge(into: CommandSet, other: CommandSet) -> None:
    for attr in ("install", "build", "dev", "test", "lint", "format", "typecheck"):
        existing = getattr(into, attr)
        for cmd in getattr(other, attr):
            if cmd not in existing:
                existing.append(cmd)
    for k, vs in other.extras.items():
        bucket = into.extras.setdefault(k, [])
        for v in vs:
            if v not in bucket:
                bucket.append(v)


def detect_commands(
    repo_path: Path,
    files: Iterable[Path],
    manifests: list[ManifestData],
    package_managers: list[PackageManager],
) -> tuple[CommandSet, list[Finding]]:
    """Return a CommandSet aggregated across all known sources."""
    cs = CommandSet()
    findings: list[Finding] = []

    pm_for_kind: dict[str, str] = {}
    for pm in package_managers:
        if pm.manifest.endswith("pyproject.toml"):
            pm_for_kind["pyproject"] = pm.name
        elif pm.manifest.endswith("package.json"):
            pm_for_kind["package.json"] = pm.name

    for m in manifests:
        if m.kind == "package.json":
            sub_cs, sub_f = _from_npm_scripts(m, pm_for_kind.get("package.json"))
            _merge(cs, sub_cs)
            findings.extend(sub_f)
        elif m.kind == "pyproject":
            sub_cs, sub_f = _from_pyproject(m, pm_for_kind.get("pyproject"))
            _merge(cs, sub_cs)
            findings.extend(sub_f)
        elif m.kind == "Cargo.toml":
            cs.install.append("cargo build")
            cs.test.append("cargo test")
            cs.build.append("cargo build --release")
        elif m.kind == "go.mod":
            cs.build.append("go build ./...")
            cs.test.append("go test ./...")

    for f in files:
        if f.name in {"Makefile", "makefile", "GNUmakefile"}:
            sub_cs, sub_f = _from_makefile(f)
            _merge(cs, sub_cs)
            findings.extend(sub_f)

    return cs, findings
