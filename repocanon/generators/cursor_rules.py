"""Generate Cursor project rules under .cursor/rules/.

Cursor reads ``.mdc`` files with a small frontmatter block. Each rule is one
of two shapes:

- ``alwaysApply: true`` — applied to every request, no globs.
- ``alwaysApply: false`` with ``globs:`` — applied only when the agent is
  editing files matching the globs.

The two are mutually exclusive: setting both ``alwaysApply: true`` *and*
``globs:`` is a configuration mistake (Cursor will treat the globs as a
no-op or, worse, ignore the rule). We never emit that combination.

We also avoid the generic "Mirror the conventions used in neighboring
files" boilerplate from earlier versions: every rule body either contains
something the analyzer actually inferred, or the rule is omitted.
"""

from __future__ import annotations

from repocanon.generators.common import (
    boundaries_block,
    commands_block,
    conventions_block,
    directories_block,
    frameworks_block,
    header,
    languages_block,
    overview_paragraph,
    package_managers_block,
    preferred_libraries_block,
    section,
)
from repocanon.models.outputs import GeneratedFile, GenerationPlan
from repocanon.models.project import ProjectModel, RoleKind
from repocanon.utils.text import bullet_list, join_sections


def _frontmatter(description: str, *, globs: str | None = None) -> str:
    """Produce a Cursor frontmatter block, choosing alwaysApply vs globs sanely."""
    lines = ["---", f"description: {description}"]
    if globs:
        lines.append(f"globs: {globs}")
        lines.append("alwaysApply: false")
    else:
        lines.append("alwaysApply: true")
    lines.append("---")
    return "\n".join(lines)


def _rule(
    name: str,
    body: str,
    description: str,
    *,
    globs: str | None = None,
) -> GeneratedFile:
    content = join_sections(
        [
            _frontmatter(description, globs=globs),
            header("cursor"),
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
            section("Preferred libraries", preferred_libraries_block(model.preferred_libraries), level=2),
        ]
    )
    return _rule(
        "project-overview",
        body,
        description="High-level orientation for this repo.",
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
    # Style rules are inherently global (apply to every file you write).
    return _rule(
        "code-style-and-conventions",
        body,
        description="Style and naming rules inferred from the codebase.",
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
    )


_SCOPE_BODIES: dict[RoleKind, str] = {
    RoleKind.test: (
        "Match the assertion style and fixture patterns of neighboring tests in "
        "this directory. Tests must be deterministic and must not reach the network."
    ),
    RoleKind.migrations: (
        "Existing files in this directory are historical and append-only. "
        "Do not edit them — generate a new revision instead."
    ),
    RoleKind.internal: (
        "Code in this directory is private to the Go module. Treat it as private "
        "API; never widen visibility by re-exporting from `pkg/`."
    ),
    RoleKind.binaries: (
        "Each subdirectory is a separate Go binary entry point. Shared code lives "
        "in `internal/` or `pkg/`, not in another binary's directory."
    ),
    RoleKind.monorepo_packages: (
        "Each subpackage owns its own dependencies and exports. Do not reach into "
        "another subpackage's internals; consume its public entry point only."
    ),
    RoleKind.monorepo_apps: (
        "Each app is independently buildable and deployable. Avoid coupling apps to "
        "each other at the source level — share via packages/."
    ),
    RoleKind.monorepo_libs: (
        "These libraries are shared across the monorepo. Public surface area should "
        "be stable; treat changes as contracts."
    ),
    RoleKind.monorepo_services: (
        "Each service is independently deployable. Cross-service calls go over the "
        "network, not via direct imports."
    ),
}


def _scoped_for_directory(role_kind: RoleKind, paths: list[str]) -> GeneratedFile | None:
    body = _SCOPE_BODIES.get(role_kind)
    if not body or not paths:
        return None
    safe_name = role_kind.value.replace("_", "-")
    paths_md = bullet_list([f"`{p}/`" for p in paths])
    full_body = join_sections(
        [
            section("Applies to", paths_md, level=2),
            section("Rule", body, level=2),
        ]
    )
    glob = ",".join(f"{p}/**" for p in paths)
    return _rule(
        f"scope-{safe_name}",
        full_body,
        description=f"Scope-specific guidance for {role_kind.value} directories.",
        globs=glob,
    )


def generate_cursor(model: ProjectModel) -> GenerationPlan:
    plan = GenerationPlan(target="cursor")
    plan.add(_project_overview(model))
    if not model.commands.is_empty():
        plan.add(_commands(model))
    if model.conventions or model.naming_conventions or model.anti_patterns:
        plan.add(_conventions(model))
    if model.architecture_boundaries or model.uncertainty_notes:
        plan.add(_boundaries(model))

    by_kind: dict[RoleKind, list[str]] = {}
    for d in model.key_directories:
        if d.role_kind in _SCOPE_BODIES:
            by_kind.setdefault(d.role_kind, []).append(d.path)

    for role_kind, paths in sorted(by_kind.items(), key=lambda kv: kv[0].value):
        rule = _scoped_for_directory(role_kind, paths)
        if rule is not None:
            plan.add(rule)

    return plan
