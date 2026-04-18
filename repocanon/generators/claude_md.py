"""Generate CLAUDE.md (Claude Code persistent operational memory)."""

from __future__ import annotations

from repocanon.generators.common import (
    boundaries_block,
    commands_block,
    conventions_block,
    directories_block,
    header,
    manual_block,
    overview_paragraph,
    section,
)
from repocanon.models.outputs import GeneratedFile, GenerationPlan
from repocanon.models.project import ProjectModel
from repocanon.utils.text import bullet_list, join_sections


def generate_claude(model: ProjectModel, existing: str = "") -> GenerationPlan:
    title = f"# {model.repo_name}"
    overview = section("Overview", overview_paragraph(model), level=2)
    must_run = section("Must run", commands_block(model.commands, terse=True), level=2)
    layout = section("Layout", directories_block(model.key_directories), level=2)
    convs = section(
        "Conventions",
        conventions_block([*model.conventions, *model.naming_conventions]),
        level=2,
    )
    bounds = section("Boundaries", boundaries_block(model), level=2)
    avoid = section("Avoid", bullet_list(model.anti_patterns), level=2)
    uncert = section("Uncertain", bullet_list(model.uncertainty_notes), level=2)

    sections = [
        title,
        header("claude"),
        overview,
        must_run,
        layout,
        convs,
        bounds,
        avoid,
        uncert,
        section("Manual notes", manual_block(existing), level=2),
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
