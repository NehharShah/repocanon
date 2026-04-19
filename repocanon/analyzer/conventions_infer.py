"""Heuristic convention inference: test layout, naming, anti-patterns."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from repocanon.analyzer.config_parse import ManifestData
from repocanon.models.findings import Confidence, Finding
from repocanon.models.project import Convention, Framework, TestLayout

MIN_FILES_FOR_NAMING_CONVENTION = 5


def infer_test_layout(rel_paths: Iterable[str]) -> tuple[TestLayout, Finding]:
    centralized = 0
    colocated = 0
    for rel in rel_paths:
        name = Path(rel).name.lower()
        head = rel.split("/", 1)[0]
        is_test = (
            name.startswith("test_")
            or name.endswith("_test.go")
            or name.endswith(".test.ts")
            or name.endswith(".test.tsx")
            or name.endswith(".test.js")
            or name.endswith(".test.jsx")
            or name.endswith(".spec.ts")
            or name.endswith(".spec.tsx")
            or name.endswith(".spec.js")
        )
        if not is_test:
            continue
        if head in {"tests", "test", "__tests__", "spec"}:
            centralized += 1
        else:
            colocated += 1

    if centralized + colocated == 0:
        return TestLayout.unknown, Finding(
            kind="convention",
            subject="test_layout",
            rationale="No test files detected.",
            confidence=Confidence.low,
        )
    if colocated == 0:
        layout = TestLayout.centralized
        rationale = f"All {centralized} test files live under a top-level tests directory."
        conf = Confidence.high
    elif centralized == 0:
        layout = TestLayout.colocated
        rationale = f"All {colocated} test files live next to source modules."
        conf = Confidence.high
    elif centralized > colocated * 3:
        layout = TestLayout.centralized
        rationale = f"{centralized} centralized tests vs {colocated} colocated."
        conf = Confidence.medium
    elif colocated > centralized * 3:
        layout = TestLayout.colocated
        rationale = f"{colocated} colocated tests vs {centralized} centralized."
        conf = Confidence.medium
    else:
        layout = TestLayout.mixed
        rationale = f"Mixed: {centralized} centralized, {colocated} colocated."
        conf = Confidence.medium

    return layout, Finding(
        kind="convention",
        subject="test_layout",
        rationale=rationale,
        confidence=conf,
    )


def infer_naming_conventions(
    rel_paths: Iterable[str], frameworks: list[Framework]
) -> list[Convention]:
    out: list[Convention] = []
    paths = list(rel_paths)
    py_files = [p for p in paths if p.endswith(".py")]
    if len(py_files) >= MIN_FILES_FOR_NAMING_CONVENTION:
        snake = sum(1 for p in py_files if "-" not in Path(p).stem and Path(p).stem.islower())
        ratio = snake / len(py_files)
        if ratio > 0.85:
            out.append(
                Convention(
                    name="Python file naming",
                    value="snake_case modules",
                    rationale=f"{int(ratio * 100)}% of Python files follow snake_case.",
                    confidence=Confidence.high,
                )
            )

    ts_files = [p for p in paths if p.endswith((".ts", ".tsx", ".js", ".jsx"))]
    if len(ts_files) >= MIN_FILES_FOR_NAMING_CONVENTION:
        kebab = sum(1 for p in ts_files if "-" in Path(p).stem)
        camel = sum(
            1
            for p in ts_files
            if Path(p).stem and Path(p).stem[0].islower() and "-" not in Path(p).stem
        )
        pascal = sum(1 for p in ts_files if Path(p).stem and Path(p).stem[0].isupper())
        total = len(ts_files)
        if pascal / total > 0.5:
            out.append(
                Convention(
                    name="TypeScript file naming",
                    value="PascalCase for component files",
                    rationale=f"{int(pascal / total * 100)}% of TS/JS files start with an uppercase letter.",
                    confidence=Confidence.medium,
                )
            )
        elif kebab / total > 0.5:
            out.append(
                Convention(
                    name="TypeScript file naming",
                    value="kebab-case modules",
                    rationale=f"{int(kebab / total * 100)}% of TS/JS files use kebab-case.",
                    confidence=Confidence.medium,
                )
            )
        elif camel / total > 0.5:
            out.append(
                Convention(
                    name="TypeScript file naming",
                    value="camelCase modules",
                    rationale=f"{int(camel / total * 100)}% of TS/JS files use camelCase.",
                    confidence=Confidence.medium,
                )
            )

    fw_names = {fw.name for fw in frameworks}
    if "Next.js" in fw_names and any(p.startswith("app/") for p in paths):
        out.append(
            Convention(
                name="Next.js routing",
                value="App Router under app/",
                rationale="Top-level app/ directory is present alongside Next.js dependency.",
                confidence=Confidence.medium,
            )
        )
    elif "Next.js" in fw_names and any(p.startswith("pages/") for p in paths):
        out.append(
            Convention(
                name="Next.js routing",
                value="Pages Router under pages/",
                rationale="Top-level pages/ directory is present alongside Next.js dependency.",
                confidence=Confidence.medium,
            )
        )
    return out


def infer_general_conventions(
    rel_paths: Iterable[str],
    manifests: list[ManifestData],
    frameworks: list[Framework],
) -> list[Convention]:
    out: list[Convention] = []
    paths = list(rel_paths)
    fw_names = {fw.name for fw in frameworks}
    file_set = set(paths)

    has_pyproject = any(m.kind == "pyproject" for m in manifests)
    if has_pyproject and "Ruff" in fw_names:
        out.append(
            Convention(
                name="Python lint/format",
                value="Ruff",
                rationale="Ruff configured in pyproject.toml or installed as a dev dep.",
                confidence=Confidence.high,
            )
        )
    if has_pyproject and "mypy" in fw_names:
        out.append(
            Convention(
                name="Python type checking",
                value="mypy",
                rationale="mypy installed.",
                confidence=Confidence.high,
            )
        )

    if "TypeScript" in fw_names or any(p == "tsconfig.json" for p in paths):
        out.append(
            Convention(
                name="JS/TS language",
                value="TypeScript-first",
                rationale="TypeScript dependency or tsconfig.json detected.",
                confidence=Confidence.high,
            )
        )

    if any(p.endswith(".pre-commit-config.yaml") for p in paths):
        out.append(
            Convention(
                name="Git hooks",
                value="pre-commit hooks active",
                rationale=".pre-commit-config.yaml present.",
                confidence=Confidence.high,
            )
        )

    if ".editorconfig" in file_set:
        out.append(
            Convention(
                name="Editor settings",
                value=".editorconfig is the source of truth",
                rationale=".editorconfig file present at repo root.",
                confidence=Confidence.high,
            )
        )

    if any(p.startswith(".github/workflows/") for p in paths):
        out.append(
            Convention(
                name="CI",
                value="GitHub Actions",
                rationale=".github/workflows/ directory present.",
                confidence=Confidence.high,
            )
        )

    return out


def infer_anti_patterns_and_uncertainty(
    rel_paths: Iterable[str], manifests: list[ManifestData], frameworks: list[Framework]
) -> tuple[list[str], list[str]]:
    anti: list[str] = []
    uncertainty: list[str] = []

    paths = list(rel_paths)
    fw_names = {fw.name for fw in frameworks}

    if any(p == "requirements.txt" for p in paths) and any(m.kind == "pyproject" for m in manifests):
        anti.append(
            "Avoid editing both requirements.txt and pyproject.toml — pick one as the source of truth."
        )

    if any(p.endswith(".env") for p in paths):
        anti.append("Never commit `.env` files; they may contain secrets.")

    if "Alembic" in fw_names or any(p.startswith("alembic/") for p in paths):
        anti.append(
            "Do not edit existing Alembic migrations; create a new revision (`alembic revision -m '…'`)."
        )

    if any(p.startswith("migrations/") for p in paths):
        anti.append("Do not edit historical files in `migrations/`; add a new migration instead.")

    if not any(p.endswith("LICENSE") or p.endswith("LICENSE.md") for p in paths):
        uncertainty.append("No LICENSE file detected — license intent is unclear.")

    if not any("README" in Path(p).name for p in paths):
        uncertainty.append("No README detected — high-level intent is hard to infer.")

    return anti, uncertainty
