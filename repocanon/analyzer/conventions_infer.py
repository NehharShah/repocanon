"""Heuristic convention inference: test layout, naming, anti-patterns."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from repocanon.analyzer.config_parse import ManifestData
from repocanon.models.findings import Confidence, Finding
from repocanon.models.project import Convention, Framework, TestLayout

MIN_FILES_FOR_NAMING_CONVENTION = 5

# Stems we ignore when computing naming-style ratios. These are dunder /
# routing convention files that have nothing to do with the team's chosen
# style for module names.
_PY_DUNDER_STEMS: frozenset[str] = frozenset({"__init__", "__main__"})
_TS_ROUTE_STEMS: frozenset[str] = frozenset(
    {"page", "layout", "loading", "error", "not-found", "route", "head", "default", "template"}
)


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


def _is_snake_case(stem: str) -> bool:
    return bool(stem) and "-" not in stem and stem.islower() and " " not in stem


_PASCAL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_CAMEL_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")


def _classify_ts_stem(stem: str) -> str:
    """Return one of {'pascal', 'camel', 'kebab', 'lower', 'other'}.

    Crucially, a stem like "page" or "utils" matches *neither* camelCase nor
    PascalCase — it's just lowercase. The previous heuristic miscounted
    these as camelCase because it only checked ``stem[0].islower()``.
    """
    if not stem:
        return "other"
    if "-" in stem:
        return "kebab" if _KEBAB_RE.match(stem) else "other"
    if _PASCAL_RE.match(stem):
        return "pascal"
    if any(c.isupper() for c in stem) and _CAMEL_RE.match(stem):
        return "camel"
    if stem.islower():
        return "lower"
    return "other"


def infer_naming_conventions(
    rel_paths: Iterable[str], frameworks: list[Framework]
) -> list[Convention]:
    out: list[Convention] = []
    paths = list(rel_paths)
    py_files = [
        p
        for p in paths
        if p.endswith(".py") and Path(p).stem not in _PY_DUNDER_STEMS
    ]
    if len(py_files) >= MIN_FILES_FOR_NAMING_CONVENTION:
        snake = sum(1 for p in py_files if _is_snake_case(Path(p).stem))
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

    # Bucket TS/JS by directory class so that the answer can be "PascalCase
    # for components, lowercase for routes" instead of one false winner.
    ts_files = [p for p in paths if p.endswith((".ts", ".tsx", ".js", ".jsx"))]
    if len(ts_files) >= MIN_FILES_FOR_NAMING_CONVENTION:
        components: list[str] = []
        hooks: list[str] = []
        routes: list[str] = []
        general: list[str] = []
        for p in ts_files:
            stem = Path(p).stem
            posix = p.lower()
            if "components/" in posix:
                components.append(stem)
            elif "hooks/" in posix or stem.startswith("use") and len(stem) > 3 and stem[3].isupper():
                hooks.append(stem)
            elif (
                "/app/" in posix
                or posix.startswith("app/")
                or "/pages/" in posix
                or posix.startswith("pages/")
                or stem in _TS_ROUTE_STEMS
            ):
                routes.append(stem)
            else:
                general.append(stem)

        out.extend(_ts_convention_for(components, label="TypeScript components", min_required=3))
        out.extend(_ts_convention_for(hooks, label="TypeScript hooks", min_required=3))
        out.extend(_ts_convention_for(routes, label="TypeScript route files", min_required=3))
        if not components and not hooks and not routes:
            # Mixed buckets — only emit if the *general* bucket is dominated
            # by a single style (>70%) so we don't fabricate a winner.
            out.extend(_ts_convention_for(general, label="TypeScript files", min_required=5, threshold=0.7))

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


def _ts_convention_for(
    stems: list[str], *, label: str, min_required: int, threshold: float = 0.6
) -> list[Convention]:
    if len(stems) < min_required:
        return []
    counts = {
        "pascal": 0,
        "camel": 0,
        "kebab": 0,
        "lower": 0,
    }
    for stem in stems:
        kind = _classify_ts_stem(stem)
        if kind in counts:
            counts[kind] += 1
    total = sum(counts.values())
    if total == 0:
        return []
    winner, n = max(counts.items(), key=lambda kv: kv[1])
    ratio = n / total
    if ratio < threshold:
        return []
    name_for_winner = {
        "pascal": "PascalCase",
        "camel": "camelCase",
        "kebab": "kebab-case",
        "lower": "lowercase",
    }[winner]
    return [
        Convention(
            name=label,
            value=f"{name_for_winner}",
            rationale=f"{int(ratio * 100)}% of {len(stems)} files use {name_for_winner}.",
            confidence=Confidence.medium,
        )
    ]


def infer_general_conventions(
    rel_paths: Iterable[str],
    manifests: list[ManifestData],
    frameworks: list[Framework],
) -> list[Convention]:
    out: list[Convention] = []
    paths = list(rel_paths)
    fw_names = {fw.name for fw in frameworks}
    file_set = set(paths)

    pyproject_manifests = [m for m in manifests if m.kind == "pyproject"]
    has_pyproject = bool(pyproject_manifests)
    declared_tools = {t.lower() for m in pyproject_manifests for t in m.declared_tools}

    if "Ruff" in fw_names:
        configured = "ruff" in declared_tools
        out.append(
            Convention(
                name="Python lint/format",
                value="Ruff",
                rationale=(
                    "[tool.ruff] configured in pyproject.toml."
                    if configured
                    else "Ruff installed as a dependency (no [tool.ruff] section)."
                ),
                confidence=Confidence.high if configured else Confidence.medium,
            )
        )
    if "mypy" in fw_names:
        configured = "mypy" in declared_tools
        out.append(
            Convention(
                name="Python type checking",
                value="mypy",
                rationale=(
                    "[tool.mypy] configured in pyproject.toml."
                    if configured
                    else "mypy installed as a dependency (no [tool.mypy] section)."
                ),
                confidence=Confidence.high if configured else Confidence.medium,
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

    if has_pyproject and any(m.kind == "Dockerfile" for m in manifests):
        out.append(
            Convention(
                name="Container build",
                value="Dockerfile at repo root",
                rationale="Dockerfile present.",
                confidence=Confidence.high,
            )
        )

    return out


_LICENSE_NAME_RE = re.compile(r"^(license|licence|copying|copyright)(\.[a-z0-9]+)?$", re.IGNORECASE)
_README_NAME_RE = re.compile(r"^readme(\.[a-z0-9]+)?$", re.IGNORECASE)


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

    if any(p.endswith(".env") and not p.endswith(".env.example") for p in paths):
        anti.append("Never commit `.env` files; they may contain secrets.")

    if "Alembic" in fw_names or any(p.startswith("alembic/") for p in paths):
        anti.append(
            "Do not edit existing Alembic migrations; create a new revision (`alembic revision -m '…'`)."
        )

    if any(p.startswith("migrations/") for p in paths):
        anti.append("Do not edit historical files in `migrations/`; add a new migration instead.")

    if not any(_LICENSE_NAME_RE.match(Path(p).name) for p in paths):
        uncertainty.append("No LICENSE file detected — license intent is unclear.")

    # Use a strict regex against the *file name only*, anchored to a dot or
    # end-of-string, so 'OLD_README.md' doesn't satisfy the README check.
    if not any(_README_NAME_RE.match(Path(p).name) for p in paths):
        uncertainty.append("No README detected — high-level intent is hard to infer.")

    return anti, uncertainty
