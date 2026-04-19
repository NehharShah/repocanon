"""Generate CLAUDE.md (Claude Code persistent operational memory).

CLAUDE.md intentionally diverges from AGENTS.md: it's optimized for being
quoted into a system prompt and re-read on every turn, so we strip the
verbose framework table and per-package walkthrough, keep one canonical
command per validation kind, and lean on a single-sentence "what this is"
opener instead of a multi-paragraph overview.
"""

from __future__ import annotations

from repocanon.generators.common import (
    bullet_list,
    header,
    manual_block,
    section,
)
from repocanon.models.outputs import GeneratedFile, GenerationPlan
from repocanon.models.project import CommandSet, ProjectModel
from repocanon.utils.text import join_sections


def _opener(model: ProjectModel) -> str:
    primary = model.primary_language() or "an unidentified language"
    fw = model.frameworks[0].name if model.frameworks else None
    fw_clause = f" using {fw}" if fw else ""
    topo = model.topology.value.replace("_", " ")
    return (
        f"`{model.repo_name}` is a {topo} {primary}{fw_clause} project. "
        "Treat this file as durable working memory; everything below has been "
        "inferred from manifests and file structure, not from the contents of source files."
    )


def _terse_commands(commands: CommandSet) -> str:
    """One canonical command per kind, presented as a single bullet."""
    parts: list[str] = []
    for label, items in (
        ("install", commands.install),
        ("dev", commands.dev),
        ("build", commands.build),
        ("test", commands.test),
        ("lint", commands.lint),
        ("typecheck", commands.typecheck),
    ):
        if items:
            parts.append(f"- **{label}**: `{items[0]}`")
    return "\n".join(parts)


def _rules(model: ProjectModel) -> str:
    """Single-sentence rules combining boundaries + anti-patterns + low-confidence findings."""
    items: list[str] = []
    for b in model.architecture_boundaries:
        items.append(f"{b.name.capitalize()}: {b.description}")
    items.extend(model.anti_patterns)
    return bullet_list(items)


def generate_claude(model: ProjectModel) -> GenerationPlan:
    title = f"# {model.repo_name}"
    sections = [
        title,
        header("claude"),
        section("What this is", _opener(model), level=2),
        section("Run these", _terse_commands(model.commands), level=2),
        section("Rules", _rules(model), level=2),
        section(
            "Layout",
            bullet_list([f"`{d.path}/` — {d.role}" for d in model.key_directories]),
            level=2,
        ),
        section("Manual notes", manual_block(), level=2),
    ]
    content = join_sections(sections)
    plan = GenerationPlan(target="claude")
    plan.add(
        GeneratedFile(
            path="CLAUDE.md",
            content=content,
            target="claude",
            description="Concise persistent memory for Claude Code.",
        )
    )
    return plan
