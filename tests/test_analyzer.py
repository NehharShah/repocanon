"""End-to-end tests for the analyzer pipeline."""

from __future__ import annotations

from pathlib import Path

from repocanon.analyzer import analyze_repo
from repocanon.config import RepoCanonConfig
from repocanon.models.project import TestLayout, TopologyKind


def _names(items) -> set[str]:  # type: ignore[no-untyped-def]
    return {i.name for i in items}


def test_fastapi_repo_inference(fastapi_repo: Path) -> None:
    model = analyze_repo(fastapi_repo, RepoCanonConfig())

    assert model.repo_name == "fastapi-app"
    assert model.primary_language() == "Python"
    assert model.topology is TopologyKind.single_package

    fws = _names(model.frameworks)
    assert "FastAPI" in fws
    assert "Pydantic" in fws
    assert "SQLAlchemy" in fws
    assert "Alembic" in fws
    assert "pytest" in fws

    assert any(c.startswith("python -m pip install") for c in model.commands.install)
    assert "pytest" in model.commands.test
    assert any("ruff" in c for c in model.commands.lint)
    assert any("mypy" in c for c in model.commands.typecheck)
    # The Makefile defines a 'dev' target that runs uvicorn; we accept either
    # the make-level command or a directly captured uvicorn invocation.
    assert model.commands.dev, "expected at least one dev command"

    assert model.test_layout in {TestLayout.centralized, TestLayout.colocated, TestLayout.mixed}
    assert any("alembic" in n.lower() or "migrations" in n.lower() for n in model.anti_patterns)


def test_nextjs_repo_inference(nextjs_repo: Path) -> None:
    model = analyze_repo(nextjs_repo, RepoCanonConfig())

    assert model.repo_name == "nextjs-app"
    fws = _names(model.frameworks)
    assert {"Next.js", "React", "TypeScript"}.issubset(fws)
    assert "Tailwind CSS" in fws
    assert "Vitest" in fws or "Playwright" in fws

    assert "npm run dev" in model.commands.dev
    assert "npm run build" in model.commands.build
    assert "npm run test" in model.commands.test
    assert any("typecheck" in c or "tsc" in c for c in model.commands.typecheck)

    assert any(c.value.lower().startswith("app router") for c in model.naming_conventions) or any(
        d.path == "app" for d in model.key_directories
    )


def test_monorepo_inference(monorepo_repo: Path) -> None:
    model = analyze_repo(monorepo_repo, RepoCanonConfig())

    assert model.topology is TopologyKind.monorepo
    package_set = set(model.monorepo_packages)
    assert "apps/web" in package_set
    assert "packages/ui" in package_set
    assert "packages/utils" in package_set

    pms = {pm.name for pm in model.package_managers}
    assert "pnpm" in pms

    fws = _names(model.frameworks)
    assert "Next.js" in fws
    assert "Turborepo" in fws

    assert any(b.name == "package isolation" for b in model.architecture_boundaries)
