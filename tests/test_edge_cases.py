"""Negative and edge-case tests covering bugs called out in code review."""

from __future__ import annotations

from pathlib import Path

from repocanon.analyzer import analyze_repo
from repocanon.analyzer.command_detect import _classify
from repocanon.analyzer.config_parse import ManifestData, parse_manifests
from repocanon.analyzer.conventions_infer import (
    _classify_ts_stem,
    infer_naming_conventions,
)
from repocanon.config import RepoCanonConfig
from repocanon.models.project import (
    CommandSet,
    Framework,
    FrameworkCategory,
    TopologyKind,
)


def test_empty_repo_does_not_crash(tmp_path: Path) -> None:
    """An empty directory should produce a model with sensible defaults."""
    model = analyze_repo(tmp_path, RepoCanonConfig())
    assert model.repo_name == tmp_path.name
    assert model.topology in {TopologyKind.unknown, TopologyKind.single_package}
    assert model.languages == []
    assert model.frameworks == []
    assert model.commands.is_empty()


def test_malformed_pyproject_emits_warning(tmp_path: Path) -> None:
    """A broken pyproject.toml must surface a parse-warning Finding instead of crashing."""
    (tmp_path / "pyproject.toml").write_text("this is not [valid toml\n", encoding="utf-8")
    model = analyze_repo(tmp_path, RepoCanonConfig())
    parse_warnings = [f for f in model.findings if f.kind == "parse-warning"]
    assert any("pyproject" in f.subject.lower() for f in parse_warnings), (
        "expected a parse-warning Finding for the broken pyproject.toml"
    )


def test_requirements_only_repo_extracts_install_and_pytest(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "fastapi==0.110.0\npytest>=8\nruff\n",
        encoding="utf-8",
    )
    model = analyze_repo(tmp_path, RepoCanonConfig())
    assert any("requirements.txt" in c for c in model.commands.install)
    assert "pytest" in model.commands.test
    assert any("ruff" in c for c in model.commands.lint)
    fws = {fw.name for fw in model.frameworks}
    assert "FastAPI" in fws


def test_lockfile_drives_yarn_detection(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"y","dependencies":{"react":"19"}}',
        encoding="utf-8",
    )
    (tmp_path / "yarn.lock").write_text("# yarn lockfile\n", encoding="utf-8")
    model = analyze_repo(tmp_path, RepoCanonConfig())
    pms = {pm.name for pm in model.package_managers}
    assert "yarn" in pms, f"expected yarn detection, got {pms}"


def test_uv_lock_drives_uv_detection(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "u"\nversion = "0.1.0"\ndependencies = ["pydantic"]\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("# uv\n", encoding="utf-8")
    model = analyze_repo(tmp_path, RepoCanonConfig())
    pms = {pm.name for pm in model.package_managers}
    assert "uv" in pms, f"expected uv detection, got {pms}"


def test_classify_publish_test_is_release_not_test() -> None:
    """`publish-test` must not be classified as a Test command."""
    cs = CommandSet()
    classified = _classify("publish-test", "make publish-test", cs, has_dev_script=False)
    assert classified is True
    assert "make publish-test" not in cs.test
    assert cs.extras.get("release") == ["make publish-test"]


def test_classify_npm_start_is_dev_only_without_dev_script() -> None:
    """`start` should be Dev only when there's no dedicated dev script."""
    cs1 = CommandSet()
    _classify("start", "npm run start", cs1, has_dev_script=False)
    assert "npm run start" in cs1.dev

    cs2 = CommandSet()
    _classify("start", "npm run start", cs2, has_dev_script=True)
    assert "npm run start" not in cs2.dev
    assert "npm run start" in cs2.extras.get("scripts", [])


def test_monorepo_nested_scripts_attach_to_packages(monorepo_repo: Path) -> None:
    """Nested package.json scripts must NOT pollute the root CommandSet."""
    model = analyze_repo(monorepo_repo, RepoCanonConfig())
    nested_dev_in_root = any("apps/web" in c for c in model.commands.dev)
    assert not nested_dev_in_root, "Nested scripts leaked into root commands."

    web_pkg = next(p for p in model.monorepo_packages if p.path == "apps/web")
    assert web_pkg.commands.dev or web_pkg.commands.build, (
        "Expected the per-package CommandSet for apps/web to carry its own scripts."
    )


def test_python_init_does_not_drag_snake_case_ratio() -> None:
    """`__init__.py` and `__main__.py` should be excluded from the snake_case sample."""
    paths = [
        "pkg/foo_bar.py",
        "pkg/baz_qux.py",
        "pkg/spam_eggs.py",
        "pkg/ham.py",
        "pkg/widget.py",
        "pkg/__init__.py",
        "pkg/__main__.py",
    ]
    conventions = infer_naming_conventions(paths, [])
    py = next((c for c in conventions if c.name == "Python file naming"), None)
    assert py is not None
    assert "snake_case" in py.value


def test_typescript_lowercase_routes_not_called_camelcase() -> None:
    """A `page.tsx`-shaped repo must not be reported as camelCase."""
    paths = [
        "app/page.tsx",
        "app/layout.tsx",
        "app/loading.tsx",
        "app/error.tsx",
        "app/not-found.tsx",
        "app/route.ts",
    ]
    conventions = infer_naming_conventions(paths, [])
    ts_routes = [c for c in conventions if c.name == "TypeScript route files"]
    if ts_routes:
        assert "camelCase" not in ts_routes[0].value
        assert ts_routes[0].value in {"lowercase", "kebab-case"}


def test_classify_ts_stem_distinguishes_lower_from_camel() -> None:
    assert _classify_ts_stem("page") == "lower"
    assert _classify_ts_stem("useFoo") == "camel"
    assert _classify_ts_stem("Button") == "pascal"
    assert _classify_ts_stem("not-found") == "kebab"


def test_typescript_pascal_components_are_recognized() -> None:
    paths = [
        "components/Button.tsx",
        "components/Card.tsx",
        "components/Modal.tsx",
        "components/Header.tsx",
        "components/Footer.tsx",
    ]
    conventions = infer_naming_conventions(
        paths, [Framework(name="React", category=FrameworkCategory.frontend)]
    )
    components = [c for c in conventions if c.name == "TypeScript components"]
    assert components, "expected a TypeScript components convention"
    assert "PascalCase" in components[0].value


def test_no_frameworks_for_below_threshold_files() -> None:
    """Below the minimum-files threshold we should NOT fabricate a TS naming rule."""
    paths = ["scripts/build.js", "scripts/lint.js"]
    conventions = infer_naming_conventions(paths, [])
    assert not any(c.name.startswith("TypeScript") for c in conventions)


def test_parse_manifests_propagates_warning(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[broken\n", encoding="utf-8")
    parsed, findings = parse_manifests(tmp_path, [tmp_path / "pyproject.toml"])
    assert parsed == []
    assert any(f.kind == "parse-warning" for f in findings)


def test_manifest_kind_is_pydantic() -> None:
    """Smoke check that ManifestData round-trips as JSON."""
    m = ManifestData(path="pyproject.toml", kind="pyproject", dependencies=["pydantic"])
    payload = m.model_dump_json()
    restored = ManifestData.model_validate_json(payload)
    assert restored.dependencies == ["pydantic"]


def test_lockfile_cargo_drives_cargo_pm(tmp_path: Path) -> None:
    """Cargo.lock should not be silently filtered out by the *.lock glob."""
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )
    (tmp_path / "Cargo.lock").write_text("# locked\n", encoding="utf-8")
    model = analyze_repo(tmp_path, RepoCanonConfig())
    pms = {pm.name for pm in model.package_managers}
    assert "cargo" in pms
