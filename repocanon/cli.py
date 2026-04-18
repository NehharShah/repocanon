"""Typer-based CLI entry point for ``repocanon``."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

import typer

from repocanon import __version__
from repocanon.analyzer import analyze_repo
from repocanon.config import (
    VALID_TARGETS,
    config_path,
    load_config,
    project_model_path,
    write_default_config,
)
from repocanon.generators import (
    generate_agents,
    generate_claude,
    generate_copilot,
    generate_cursor,
)
from repocanon.models.outputs import GenerationPlan
from repocanon.models.project import ProjectModel
from repocanon.output.diff import diff_models
from repocanon.output.preview import preview_plan
from repocanon.output.write_files import write_plan
from repocanon.report.audit import print_audit
from repocanon.report.summarize import print_summary
from repocanon.utils.fs import ensure_dir
from repocanon.utils.logging import console, error, info, ok, warn

app = typer.Typer(
    name="repocanon",
    help="Analyze a local repository and generate AI-readable project context files.",
    no_args_is_help=True,
    add_completion=False,
)


class Target(StrEnum):
    agents = "agents"
    claude = "claude"
    copilot = "copilot"
    cursor = "cursor"
    all = "all"


_GENERATORS = {
    "agents": generate_agents,
    "claude": generate_claude,
    "copilot": generate_copilot,
    "cursor": generate_cursor,
}


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"repocanon {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """RepoCanon: turn a repo into canonical AI-readable project context."""


def _resolve_repo(path: Path) -> Path:
    repo = path.resolve()
    if not repo.exists() or not repo.is_dir():
        error(f"Not a directory: {repo}")
        raise typer.Exit(code=2)
    return repo


def _save_model(model: ProjectModel, repo: Path) -> Path:
    out = project_model_path(repo)
    ensure_dir(out.parent)
    out.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    return out


def _load_saved_model(repo: Path) -> ProjectModel | None:
    path = project_model_path(repo)
    if not path.exists():
        return None
    raw = json.loads(path.read_text("utf-8"))
    return ProjectModel.model_validate(raw)


@app.command()
def analyze(
    path: Path = typer.Argument(Path("."), help="Repository root to analyze."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress the human summary."),
) -> None:
    """Analyze a repository and persist a normalized project model."""
    repo = _resolve_repo(path)
    info(f"Scanning {repo}…")
    cfg = load_config(repo)
    model = analyze_repo(repo, cfg)
    saved = _save_model(model, repo)
    ok(f"Saved project model to {saved.relative_to(repo)}")
    if not quiet:
        print_summary(model)


def _gather_targets(target: Target) -> list[str]:
    if target is Target.all:
        return list(VALID_TARGETS)
    return [target.value]


def _build_plans(model: ProjectModel, targets: list[str], repo: Path) -> list[GenerationPlan]:
    plans: list[GenerationPlan] = []
    for t in targets:
        gen = _GENERATORS[t]
        # Pass existing root file content when relevant (single-file targets).
        existing = ""
        if t == "agents":
            p = repo / "AGENTS.md"
            existing = p.read_text("utf-8") if p.exists() else ""
        elif t == "claude":
            p = repo / "CLAUDE.md"
            existing = p.read_text("utf-8") if p.exists() else ""
        plans.append(gen(model, existing))
    return plans


@app.command()
def generate(
    target: Target = typer.Argument(Target.all, help="Which target(s) to generate."),
    path: Path = typer.Argument(Path("."), help="Repository root."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Don't write files; just report what would change."
    ),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", help="Write generated files under this directory instead of the repo root."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite without preserving manual sections."),
) -> None:
    """Generate AI context files from the saved (or fresh) project model."""
    repo = _resolve_repo(path)
    cfg = load_config(repo)
    model = _load_saved_model(repo)
    if model is None:
        info("No saved model found; running analyze first.")
        model = analyze_repo(repo, cfg)
        _save_model(model, repo)

    targets = _gather_targets(target)
    plans = _build_plans(model, targets, repo)
    for plan in plans:
        results = write_plan(
            plan,
            repo,
            output_dir=output_dir,
            dry_run=dry_run,
            force=force,
            safe_overwrite=cfg.generate.safe_overwrite,
        )
        for r in results:
            try:
                rel = r.path.relative_to((output_dir or repo).resolve())
            except ValueError:
                rel = r.path
            prefix = "would " if dry_run else ""
            ok(f"{prefix}{r.action}: {rel} ({r.bytes_written} bytes)")


@app.command()
def preview(
    target: Target = typer.Argument(Target.all, help="Which target(s) to preview."),
    path: Path = typer.Argument(Path("."), help="Repository root."),
) -> None:
    """Print generated output to the terminal without writing anything."""
    repo = _resolve_repo(path)
    cfg = load_config(repo)
    model = _load_saved_model(repo) or analyze_repo(repo, cfg)
    targets = _gather_targets(target)
    for plan in _build_plans(model, targets, repo):
        preview_plan(plan)


@app.command()
def audit(
    path: Path = typer.Argument(Path("."), help="Repository root."),
) -> None:
    """Show inferred conventions, rationale, and confidence levels."""
    repo = _resolve_repo(path)
    cfg = load_config(repo)
    model = _load_saved_model(repo) or analyze_repo(repo, cfg)
    print_audit(model)


@app.command()
def diff(
    path: Path = typer.Argument(Path("."), help="Repository root."),
) -> None:
    """Compare the current scan with the saved model."""
    repo = _resolve_repo(path)
    cfg = load_config(repo)
    saved = _load_saved_model(repo)
    if saved is None:
        warn("No saved model to compare against. Run `repocanon analyze .` first.")
        raise typer.Exit(code=1)
    fresh = analyze_repo(repo, cfg)
    d = diff_models(saved, fresh)
    if not d.has_meaningful_changes:
        ok("No meaningful changes since last analyze.")
        return
    info(f"Files: {d.file_count_delta:+d}")
    if d.languages_added:
        info(f"Languages added: {', '.join(d.languages_added)}")
    if d.languages_removed:
        info(f"Languages removed: {', '.join(d.languages_removed)}")
    if d.frameworks_added:
        info(f"Frameworks added: {', '.join(d.frameworks_added)}")
    if d.frameworks_removed:
        info(f"Frameworks removed: {', '.join(d.frameworks_removed)}")
    if d.commands_changed:
        info("Commands changed.")
    if d.regeneration_recommended():
        warn("Regeneration recommended: run `repocanon generate all .`")


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Repository root."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing config file."),
) -> None:
    """Create a local RepoCanon config at .repocanon/config.toml."""
    repo = _resolve_repo(path)
    try:
        written = write_default_config(repo, force=force)
    except FileExistsError:
        warn(f"Config already exists at {config_path(repo).relative_to(repo)} (use --force to overwrite).")
        raise typer.Exit(code=1) from None
    ok(f"Wrote {written.relative_to(repo)}")


if __name__ == "__main__":  # pragma: no cover
    app()
