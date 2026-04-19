"""CLI smoke tests via Typer's CliRunner."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from repocanon.cli import app
from repocanon.config import config_path, project_model_path

runner = CliRunner()


def _copy(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst)


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "repocanon" in result.stdout


def test_analyze_writes_model(tmp_path: Path, fastapi_repo: Path) -> None:
    repo = tmp_path / "repo"
    _copy(fastapi_repo, repo)
    result = runner.invoke(app, ["analyze", str(repo), "--quiet"])
    assert result.exit_code == 0, result.stdout
    assert project_model_path(repo).exists()


def test_analyze_json_emits_full_model(tmp_path: Path, fastapi_repo: Path) -> None:
    repo = tmp_path / "repo"
    _copy(fastapi_repo, repo)
    result = runner.invoke(app, ["analyze", str(repo), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["repo_name"]
    assert "languages" in payload
    assert payload["schema_version"] >= 2


def test_generate_all_creates_outputs(tmp_path: Path, nextjs_repo: Path) -> None:
    repo = tmp_path / "repo"
    _copy(nextjs_repo, repo)
    result = runner.invoke(app, ["analyze", str(repo), "--quiet"])
    assert result.exit_code == 0
    result = runner.invoke(app, ["generate", str(repo)])
    assert result.exit_code == 0, result.stdout
    assert (repo / "AGENTS.md").exists()
    assert (repo / "CLAUDE.md").exists()
    assert (repo / ".github" / "copilot-instructions.md").exists()
    assert (repo / ".cursor" / "rules" / "project-overview.mdc").exists()


def test_generate_specific_targets(tmp_path: Path, fastapi_repo: Path) -> None:
    repo = tmp_path / "repo"
    _copy(fastapi_repo, repo)
    runner.invoke(app, ["analyze", str(repo), "--quiet"])
    result = runner.invoke(app, ["generate", str(repo), "-t", "agents", "-t", "claude"])
    assert result.exit_code == 0, result.stdout
    assert (repo / "AGENTS.md").exists()
    assert (repo / "CLAUDE.md").exists()
    assert not (repo / ".github" / "copilot-instructions.md").exists()


def test_generate_dry_run_writes_nothing(tmp_path: Path, fastapi_repo: Path) -> None:
    repo = tmp_path / "repo"
    _copy(fastapi_repo, repo)
    result = runner.invoke(app, ["generate", str(repo), "--dry-run", "-t", "agents"])
    assert result.exit_code == 0, result.stdout
    assert not (repo / "AGENTS.md").exists()
    # --dry-run must not persist the project model either.
    assert not project_model_path(repo).exists()


def test_init_writes_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0
    cfg = config_path(tmp_path)
    assert cfg.exists()
    assert "[generate]" in cfg.read_text("utf-8")

    again = runner.invoke(app, ["init", str(tmp_path)])
    assert again.exit_code == 1


def test_audit_runs(tmp_path: Path, monorepo_repo: Path) -> None:
    repo = tmp_path / "repo"
    _copy(monorepo_repo, repo)
    result = runner.invoke(app, ["audit", str(repo)])
    assert result.exit_code == 0
    assert "Audit" in result.stdout


def test_audit_json(tmp_path: Path, fastapi_repo: Path) -> None:
    repo = tmp_path / "repo"
    _copy(fastapi_repo, repo)
    result = runner.invoke(app, ["audit", str(repo), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "findings" in payload


def test_diff_reports_no_changes(tmp_path: Path, fastapi_repo: Path) -> None:
    repo = tmp_path / "repo"
    _copy(fastapi_repo, repo)
    runner.invoke(app, ["analyze", str(repo), "--quiet"])
    result = runner.invoke(app, ["diff", str(repo)])
    assert result.exit_code == 0
    assert "No meaningful changes" in result.stdout


def test_preview_runs(tmp_path: Path, fastapi_repo: Path) -> None:
    repo = tmp_path / "repo"
    _copy(fastapi_repo, repo)
    runner.invoke(app, ["analyze", str(repo), "--quiet"])
    result = runner.invoke(app, ["preview", str(repo), "-t", "agents"])
    assert result.exit_code == 0
    assert "AGENTS.md" in result.stdout


def test_list_targets(tmp_path: Path) -> None:
    result = runner.invoke(app, ["list-targets"])
    assert result.exit_code == 0
    for name in ("agents", "claude", "copilot", "cursor", "all"):
        assert name in result.stdout


def test_clean_removes_generated(tmp_path: Path, fastapi_repo: Path) -> None:
    repo = tmp_path / "repo"
    _copy(fastapi_repo, repo)
    runner.invoke(app, ["analyze", str(repo), "--quiet"])
    runner.invoke(app, ["generate", str(repo), "-t", "agents"])
    assert (repo / "AGENTS.md").exists()
    result = runner.invoke(app, ["clean", str(repo), "-t", "agents"])
    assert result.exit_code == 0
    assert not (repo / "AGENTS.md").exists()


def test_clean_skips_user_authored_files(tmp_path: Path, fastapi_repo: Path) -> None:
    repo = tmp_path / "repo"
    _copy(fastapi_repo, repo)
    runner.invoke(app, ["analyze", str(repo), "--quiet"])
    (repo / "AGENTS.md").write_text("hand-written\n", encoding="utf-8")
    result = runner.invoke(app, ["clean", str(repo), "-t", "agents"])
    assert result.exit_code == 0
    assert (repo / "AGENTS.md").exists()


def test_corrupt_model_recovers(tmp_path: Path, fastapi_repo: Path) -> None:
    repo = tmp_path / "repo"
    _copy(fastapi_repo, repo)
    project_model_path(repo).parent.mkdir(parents=True, exist_ok=True)
    project_model_path(repo).write_text("{not-json", encoding="utf-8")
    result = runner.invoke(app, ["audit", str(repo)])
    assert result.exit_code == 0
    assert "corrupt" in result.stdout.lower() or "Audit" in result.stdout
