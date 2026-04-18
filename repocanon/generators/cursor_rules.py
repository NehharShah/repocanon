"""Generate Cursor project rules under .cursor/rules/.

Cursor reads ``.mdc`` files with a small frontmatter block. We split the
guidance into focused files so users (and Cursor) can ignore or refine each
piece independently.
"""

from __future__ import annotations

from repocanon.generators.common import (
    boundaries_block,
    commands_block,
    conventions_block,
    directories_block,
    frameworks_block,
    languages_block,
    overview_paragraph,
    package_managers_block,
    section,
)
from repocanon.models.outputs import GeneratedFile, GenerationPlan
from repocanon.models.project import DirectoryRole, ProjectModel
from repocanon.utils.text import bullet_list, join_sections


def _frontmatter(description: str, *, globs: str | None = None, always: bool = False) -> str:
    lines = ["---", f"description: {description}"]
    if globs:
        lines.append(f"globs: {globs}")
    lines.append(f"alwaysApply: {'true' if always else 'false'}")
    lines.append("---")
    return "\n".join(lines)


def _rule(
    name: str,
    body: str,
    description: str,
    *,
    globs: str | None = None,
    always: bool = False,
) -> GeneratedFile:
    content = join_sections(
        [
            _frontmatter(description, globs=globs, always=always),
            f"# {name}",
            body,
        ]
    )
    return GeneratedFile(
        path=f".cursor/rules/{name}.mdc",
        content=content,
        target="cursor",
        description=description,
    )


def _project_overview(model: ProjectModel) -> GeneratedFile:
    body = join_sections(
        [
            section("What this repo is", overview_paragraph(model), level=2),
            section("Languages", languages_block(model.languages), level=2),
            section("Frameworks", frameworks_block(model.frameworks), level=2),
            section("Package managers", package_managers_block(model.package_managers), level=2),
            section("Layout", directories_block(model.key_directories), level=2),
        ]
    )
    return _rule(
        "project-overview",
        body,
        description="High-level orientation for this repo.",
        always=True,
    )


def _commands(model: ProjectModel) -> GeneratedFile:
    body = join_sections(
        [
            section("Run these for validation", commands_block(model.commands), level=2),
            section(
                "Reporting",
                "When you finish a change, mention which commands you ran and their result. "
                "If you skipped one, say why.",
                level=2,
            ),
        ]
    )
    return _rule(
        "commands-and-validation",
        body,
        description="Commands to run for build, test, lint, and typecheck.",
        always=True,
    )


def _conventions(model: ProjectModel) -> GeneratedFile:
    body = join_sections(
        [
            section(
                "Code style",
                conventions_block([*model.conventions, *model.naming_conventions]),
                level=2,
            ),
            section("Avoid", bullet_list(model.anti_patterns), level=2),
        ]
    )
    return _rule(
        "code-style-and-conventions",
        body,
        description="Style and naming rules inferred from the codebase.",
        globs="**/*",
    )


def _boundaries(model: ProjectModel) -> GeneratedFile:
    body = join_sections(
        [
            section("Boundaries", boundaries_block(model), level=2),
            section("Uncertainty", bullet_list(model.uncertainty_notes), level=2),
        ]
    )
    return _rule(
        "architecture-boundaries",
        body,
        description="Module and package boundaries to respect.",
        always=True,
    )


def _scoped_for_directory(model: ProjectModel, d: DirectoryRole) -> GeneratedFile:
    body = join_sections(
        [
            section(
                f"`{d.path}/` — {d.role}",
                d.rationale or f"Scope-specific guidance for `{d.path}/`.",
                level=2,
            ),
            section(
                "Pointers",
                "Mirror the conventions used in neighboring files inside this directory. "
                "If a pattern looks new, prefer extending an existing module over creating a parallel one.",
                level=2,
            ),
        ]
    )
    safe_name = d.path.strip("/").replace("/", "-").lower() or "root"
    return _rule(
        f"scope-{safe_name}",
        body,
        description=f"Scope-specific guidance for {d.path}/.",
        globs=f"{d.path}/**",
    )


def generate_cursor(model: ProjectModel, existing: str = "") -> GenerationPlan:
    plan = GenerationPlan(target="cursor")
    plan.add(_project_overview(model))
    if not model.commands.is_empty():
        plan.add(_commands(model))
    if model.conventions or model.naming_conventions or model.anti_patterns:
        plan.add(_conventions(model))
    if model.architecture_boundaries or model.uncertainty_notes:
        plan.add(_boundaries(model))

    scope_roles = {
        "source",
        "frontend",
        "backend",
        "api surface",
        "applications (monorepo)",
        "packages (monorepo)",
    }
    # Limit scoped files to the most informative directories.
    for d in model.key_directories[:5]:
        if d.role in scope_roles:
            plan.add(_scoped_for_directory(model, d))

    return plan
