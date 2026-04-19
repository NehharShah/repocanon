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
    package_paths = {p.path for p in model.monorepo_packages}
    assert "apps/web" in package_paths
    assert "packages/ui" in package_paths
    assert "packages/utils" in package_paths

    pms = {pm.name for pm in model.package_managers}
    assert "pnpm" in pms

    fws = _names(model.frameworks)
    assert "Next.js" in fws
    assert "Turborepo" in fws

    assert any(b.name == "package isolation" for b in model.architecture_boundaries)


def test_go_multi_binary_inference(go_repo: Path) -> None:
    """Patch B + C: Go cmd/<bin>/main.go fan-out + go.mod block-form parsing + GO_RULES."""
    model = analyze_repo(go_repo, RepoCanonConfig())

    assert model.repo_name == "github.com/example/go-app"
    assert model.primary_language() == "Go"

    # Patch B: topology should be multi_binary, not single_package, even though
    # there's a single root go.mod.
    assert model.topology is TopologyKind.multi_binary, (
        f"expected multi_binary, got {model.topology}"
    )
    assert sorted(p.path for p in model.monorepo_packages) == ["cmd/api", "cmd/worker"]

    # Patch B: cmd/, internal/, pkg/ should all surface as recognized roles.
    dir_paths = {d.path: d.role for d in model.key_directories}
    assert "cmd" in dir_paths
    assert "internal" in dir_paths
    assert "pkg" in dir_paths
    assert "Go" in dir_paths["cmd"] or "binary" in dir_paths["cmd"]
    assert "internal" in dir_paths["internal"].lower()

    # Patch B: binary-isolation + Go internal-visibility boundaries.
    boundary_names = {b.name for b in model.architecture_boundaries}
    assert "binary isolation" in boundary_names
    assert "Go internal/ visibility" in boundary_names

    # Patch C: block-form `require ( ... )` parsed correctly.
    fws = _names(model.frameworks)
    assert "Gin" in fws
    assert "Cobra" in fws
    assert "Viper" in fws
    assert "GORM" in fws
    assert "sqlx" in fws
    assert "go-ethereum" in fws
    assert "Testify" in fws
    assert "zap" in fws

    # Make targets discovered.
    assert any("go build" in c or "make build" in c for c in model.commands.build)
    assert any("go test" in c or "make test" in c for c in model.commands.test)


def test_go_repo_does_not_infer_javascript_naming_convention(go_repo: Path) -> None:
    """Patch A: a Go-only repo must not surface a TS/JS naming convention."""
    model = analyze_repo(go_repo, RepoCanonConfig())

    convention_names = {c.name for c in model.naming_conventions}
    assert "TypeScript file naming" not in convention_names
    assert "Python file naming" not in convention_names
