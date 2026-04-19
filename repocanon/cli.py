"""Typer-based CLI entry point for ``repocanon``.

CLI conventions:

- ``path`` is always a positional argument (defaulting to ``.``) so the most
  common invocations stay short: ``repocanon analyze``, ``repocanon audit``.
- Targets are specified via ``--target`` / ``-t`` and may be repeated; the
  default is "all". This avoids the awkward ``generate <target> <path>``
  ordering of earlier versions.
- Every command supports ``--json`` for machine-readable output where it
  makes sense (analyze, audit, diff, list-targets).
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from repocanon import __version__
from repocanon.analyzer import analyze_repo
from repocanon.config import (
    VALID_TARGETS,
    ConfigError,
    RepoCanonConfig,
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
from repocanon.output.write_files import remove_generated, write_plan
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


def _safe_load_config(repo: Path) -> RepoCanonConfig:
    try:
        return load_config(repo)
    except ConfigError as exc:
        error(str(exc))
        raise typer.Exit(code=2) from None


def _save_model(model: ProjectModel, repo: Path) -> Path:
    out = project_model_path(repo)
    ensure_dir(out.parent)
    out.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    return out


def _load_saved_model(repo: Path) -> ProjectModel | None:
    """Load the cached project model, with a friendly error when corrupt."""
    path = project_model_path(repo)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text("utf-8"))
        return ProjectModel.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        warn(
            f"Saved model at {path.relative_to(repo)} is corrupt or from an older "
            f"schema ({exc.__class__.__name__}). Re-running analyze."
        )
        return None


def _run_analyze(repo: Path, cfg: RepoCanonConfig, *, show_progress: bool) -> ProjectModel:
    if not show_progress:
        return analyze_repo(repo, cfg)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Analyzing", total=None)

        def _on_step(label: str) -> None:
            progress.update(task, description=label)

        return analyze_repo(repo, cfg, progress=_on_step)


def _resolve_targets(targets: list[str] | None) -> list[str]:
    if not targets:
        return list(VALID_TARGETS)
    out: list[str] = []
    for t in targets:
        if t == "all":
            out.extend(VALID_TARGETS)
        elif t in VALID_TARGETS:
            out.append(t)
        else:
            valid = ", ".join([*VALID_TARGETS, "all"])
            raise typer.BadParameter(f"Unknown target {t!r}. Choose from: {valid}")
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def _build_plans(model: ProjectModel, targets: list[str]) -> list[GenerationPlan]:
    return [_GENERATORS[t](model) for t in targets]


def _validate_output_dir(repo: Path, output_dir: Path | None) -> Path | None:
    """Resolve ``--output-dir`` and reject paths that try to escape via ``..``."""
    if output_dir is None:
        return None
    resolved = output_dir.resolve()
    return resolved


@app.command()
def analyze(
    path: Path = typer.Argument(Path("."), help="Repository root to analyze."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress the human summary."),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the full project model as JSON to stdout."
    ),
) -> None:
    """Analyze a repository and persist a normalized project model."""
    repo = _resolve_repo(path)
    cfg = _safe_load_config(repo)
    if not json_output:
        info(f"Scanning {repo}…")
    model = _run_analyze(repo, cfg, show_progress=not (quiet or json_output))
    saved = _save_model(model, repo)
    if json_output:
        typer.echo(model.model_dump_json(indent=2))
        return
    ok(f"Saved project model to {saved.relative_to(repo)}")
    if not quiet:
        print_summary(model)


@app.command()
def generate(
    path: Path = typer.Argument(Path("."), help="Repository root."),
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="Target to generate (repeatable). Choices: agents, claude, copilot, cursor, all.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Don't write files; just report what would change. Skips persisting the project model.",
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Write generated files under this directory instead of the repo root.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite without preserving manual sections."
    ),
) -> None:
    """Generate AI context files from the saved (or fresh) project model."""
    repo = _resolve_repo(path)
    cfg = _safe_load_config(repo)
    out_base = _validate_output_dir(repo, output_dir)

    model = _load_saved_model(repo)
    if model is None:
        if not dry_run:
            info("No saved model found; running analyze first.")
        model = _run_analyze(repo, cfg, show_progress=not dry_run)
        if not dry_run:
            _save_model(model, repo)

    targets = _resolve_targets(target)
    plans = _build_plans(model, targets)
    for plan in plans:
        results = write_plan(
            plan,
            repo,
            output_dir=out_base,
            dry_run=dry_run,
            force=force,
            safe_overwrite=cfg.generate.safe_overwrite,
        )
        for r in results:
            try:
                rel = r.path.relative_to((out_base or repo).resolve())
            except ValueError:
                rel = r.path
            prefix = "would " if dry_run else ""
            ok(f"{prefix}{r.action}: {rel} ({r.bytes_written} bytes)")


@app.command()
def preview(
    path: Path = typer.Argument(Path("."), help="Repository root."),
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="Target to preview (repeatable). Choices: agents, claude, copilot, cursor, all.",
    ),
) -> None:
    """Print generated output to the terminal without writing anything."""
    repo = _resolve_repo(path)
    cfg = _safe_load_config(repo)
    model = _load_saved_model(repo) or _run_analyze(repo, cfg, show_progress=True)
    targets = _resolve_targets(target)
    for plan in _build_plans(model, targets):
        preview_plan(plan)


@app.command()
def audit(
    path: Path = typer.Argument(Path("."), help="Repository root."),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the audit data as JSON to stdout."
    ),
) -> None:
    """Show inferred conventions, rationale, and confidence levels."""
    repo = _resolve_repo(path)
    cfg = _safe_load_config(repo)
    model = _load_saved_model(repo) or _run_analyze(repo, cfg, show_progress=not json_output)
    if json_output:
        payload = {
            "repo_name": model.repo_name,
            "overall_confidence": model.overall_confidence(),
            "findings": [f.model_dump() for f in model.findings],
            "anti_patterns": list(model.anti_patterns),
            "uncertainty_notes": list(model.uncertainty_notes),
        }
        typer.echo(json.dumps(payload, indent=2, default=str))
        return
    print_audit(model)


@app.command()
def diff(
    path: Path = typer.Argument(Path("."), help="Repository root."),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the diff as JSON to stdout."
    ),
) -> None:
    """Compare the current scan with the saved model."""
    repo = _resolve_repo(path)
    cfg = _safe_load_config(repo)
    saved = _load_saved_model(repo)
    if saved is None:
        warn("No saved model to compare against. Run `repocanon analyze` first.")
        raise typer.Exit(code=1)
    fresh = _run_analyze(repo, cfg, show_progress=not json_output)
    d = diff_models(saved, fresh)

    if json_output:
        payload = {
            "fingerprint_changed": d.fingerprint_changed,
            "file_count_delta": d.file_count_delta,
            "languages_added": d.languages_added,
            "languages_removed": d.languages_removed,
            "frameworks_added": d.frameworks_added,
            "frameworks_removed": d.frameworks_removed,
            "packages_added": d.packages_added,
            "packages_removed": d.packages_removed,
            "commands": [
                {"bucket": cd.bucket, "added": cd.added, "removed": cd.removed}
                for cd in d.command_diffs
            ],
            "regeneration_recommended": d.regeneration_recommended(),
        }
        typer.echo(json.dumps(payload, indent=2))
        return

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
    if d.packages_added:
        info(f"Packages added: {', '.join(d.packages_added)}")
    if d.packages_removed:
        info(f"Packages removed: {', '.join(d.packages_removed)}")
    for cd in d.command_diffs:
        if cd.added:
            info(f"Commands +{cd.bucket}: {', '.join(f'`{c}`' for c in cd.added)}")
        if cd.removed:
            info(f"Commands -{cd.bucket}: {', '.join(f'`{c}`' for c in cd.removed)}")
    if d.regeneration_recommended():
        warn("Regeneration recommended: run `repocanon generate`")


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
        warn(
            f"Config already exists at {config_path(repo).relative_to(repo)} "
            "(use --force to overwrite)."
        )
        raise typer.Exit(code=1) from None
    ok(f"Wrote {written.relative_to(repo)}")


@app.command("list-targets")
def list_targets() -> None:
    """List the targets that ``generate`` and ``preview`` understand."""
    rows = [
        ("agents", "AGENTS.md — verbose Codex-style operational manual."),
        ("claude", "CLAUDE.md — terse persistent memory for Claude Code."),
        ("copilot", ".github/copilot-instructions.md (+ path-scoped files)."),
        ("cursor", ".cursor/rules/*.mdc (project-overview, scope-* rules)."),
        ("all", "Run every target above."),
    ]
    for name, desc in rows:
        console.print(f"  [info]{name}[/info]  — {desc}")


@app.command()
def clean(
    path: Path = typer.Argument(Path("."), help="Repository root."),
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="Target to clean (repeatable). Default: all.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="List files that would be removed without deleting them."
    ),
) -> None:
    """Remove generated files for the given target(s).

    Only files containing RepoCanon's header marker are removed, so user-
    authored files at the same path are never deleted.
    """
    repo = _resolve_repo(path)
    cfg = _safe_load_config(repo)
    model = _load_saved_model(repo) or _run_analyze(repo, cfg, show_progress=not dry_run)
    targets = _resolve_targets(target)
    plans = _build_plans(model, targets)
    file_paths = [f.path for plan in plans for f in plan.files]
    removed = remove_generated(file_paths, repo, dry_run=dry_run)
    if not removed:
        info("No generated files matched.")
        return
    for r in removed:
        try:
            rel = r.relative_to(repo)
        except ValueError:
            rel = r
        prefix = "would remove " if dry_run else "removed "
        ok(f"{prefix}{rel}")


if __name__ == "__main__":  # pragma: no cover
    app()
