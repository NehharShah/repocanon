"""Generate GitHub Copilot custom instruction files.

Copilot reads ``.github/copilot-instructions.md`` for repo-wide guidance and
also picks up path-scoped ``.github/instructions/*.instructions.md`` files.
We always emit the repo-wide file and conditionally emit a path-scoped file
for each directory whose role implies different rules from the rest of the
repo (tests, monorepo packages, Go internal packages, database migrations).

We deliberately do not include the static "When unsure / Mirror existing
patterns" boilerplate that earlier versions emitted — every line here is
grounded in something the analyzer found in this repo.
"""

from __future__ import annotations

from repocanon.generators.common import (
    boundaries_block,
    commands_block,
    conventions_block,
    frameworks_block,
    header,
    overview_paragraph,
    section,
)
from repocanon.models.outputs import GeneratedFile, GenerationPlan
from repocanon.models.project import ProjectModel, RoleKind, TopologyKind
from repocanon.utils.text import bullet_list, join_sections


def _repo_wide(model: ProjectModel) -> GeneratedFile:
    sections = [
        f"# Copilot instructions for {model.repo_name}",
        header("copilot"),
        section("Project context", overview_paragraph(model), level=2),
        section("Frameworks and tools", frameworks_block(model.frameworks), level=2),
        section(
            "Commands Copilot should suggest",
            commands_block(model.commands, terse=True),
            level=2,
        ),
        section(
            "Conventions to follow",
            conventions_block([*model.conventions, *model.naming_conventions]),
            level=2,
        ),
        section("Boundaries to respect", boundaries_block(model), level=2),
        section("Avoid", bullet_list(model.anti_patterns), level=2),
    ]
    return GeneratedFile(
        path=".github/copilot-instructions.md",
        content=join_sections(sections),
        target="copilot",
        description="Repository-wide Copilot custom instructions.",
    )


def _scoped_file(
    *,
    glob: str,
    file_path: str,
    title: str,
    body: str,
    description: str,
) -> GeneratedFile:
    sections = [
        "---",
        f'applyTo: "{glob}"',
        "---",
        header("copilot"),
        section(title, body, level=2),
    ]
    return GeneratedFile(
        path=file_path,
        content=join_sections(sections),
        target="copilot",
        description=description,
    )


def _path_scoped(model: ProjectModel) -> list[GeneratedFile]:
    """Emit small path-scoped instruction files when the structure warrants it."""
    out: list[GeneratedFile] = []
    by_kind: dict[RoleKind, list[str]] = {}
    for dir_role in model.key_directories:
        by_kind.setdefault(dir_role.role_kind, []).append(dir_role.path)

    for path in by_kind.get(RoleKind.test, []):
        out.append(
            _scoped_file(
                glob=f"{path}/**",
                file_path=f".github/instructions/{path}.instructions.md",
                title=f"Test code in `{path}/`",
                body=(
                    "Match the assertion style and fixture patterns used by neighboring "
                    f"tests under `{path}/`. New tests must be deterministic, not depend on "
                    "external services, and not write outside the test's tmp directory."
                ),
                description=f"Path-scoped instructions for {path}/.",
            )
        )

    if model.topology is TopologyKind.monorepo:
        monorepo_paths = by_kind.get(RoleKind.monorepo_packages, []) + by_kind.get(
            RoleKind.monorepo_libs, []
        )
        for path in monorepo_paths:
            out.append(
                _scoped_file(
                    glob=f"{path}/**",
                    file_path=f".github/instructions/{path}.instructions.md",
                    title=f"Shared packages under `{path}/`",
                    body=(
                        "Each package owns its own dependencies. Do not import from another "
                        "package's internals; only consume the package's exported entry point."
                    ),
                    description=f"Path-scoped instructions for {path}/.",
                )
            )

    if model.topology is TopologyKind.multi_binary:
        for path in by_kind.get(RoleKind.internal, []):
            out.append(
                _scoped_file(
                    glob=f"{path}/**",
                    file_path=f".github/instructions/{path}.instructions.md",
                    title=f"Go internal/ visibility (`{path}/`)",
                    body=(
                        f"Code under `{path}/` is private to this module — Go enforces it at "
                        "compile time. Treat it as private API: callers under `cmd/` and within "
                        "`internal/` are fine, but do not export it via `pkg/` casually."
                    ),
                    description=f"Path-scoped instructions for {path}/.",
                )
            )

    for path in by_kind.get(RoleKind.migrations, []):
        out.append(
            _scoped_file(
                glob=f"{path}/**",
                file_path=f".github/instructions/{path}.instructions.md",
                title=f"Append-only migrations in `{path}/`",
                body=(
                    f"Files under `{path}/` are historical. Do not edit them. Add a new "
                    "migration revision instead and let the migration tool stitch it in."
                ),
                description=f"Path-scoped instructions for {path}/.",
            )
        )

    return out


def generate_copilot(model: ProjectModel) -> GenerationPlan:
    plan = GenerationPlan(target="copilot")
    plan.add(_repo_wide(model))
    for f in _path_scoped(model):
        plan.add(f)
    return plan
