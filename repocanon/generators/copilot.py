"""Generate GitHub Copilot custom instruction files.

Copilot reads ``.github/copilot-instructions.md`` for repo-wide guidance and
also picks up path-scoped ``.github/instructions/*.instructions.md`` files.
We always emit the repo-wide file and conditionally emit a small set of
path-scoped files when the topology suggests they will be useful.
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
from repocanon.models.project import ProjectModel, TopologyKind
from repocanon.utils.text import bullet_list, join_sections


def _repo_wide(model: ProjectModel) -> GeneratedFile:
    sections = [
        f"# Copilot instructions for {model.repo_name}",
        header("copilot"),
        section("Project context", overview_paragraph(model), level=2),
        section("Frameworks and tools", frameworks_block(model.frameworks), level=2),
        section("Commands Copilot should suggest", commands_block(model.commands, terse=True), level=2),
        section(
            "Conventions to follow",
            conventions_block([*model.conventions, *model.naming_conventions]),
            level=2,
        ),
        section("Boundaries to respect", boundaries_block(model), level=2),
        section("Avoid", bullet_list(model.anti_patterns), level=2),
        section(
            "When unsure",
            "Prefer asking a clarifying question over inventing repo-specific behavior. "
            "Mirror existing patterns from neighboring files instead of introducing new ones.",
            level=2,
        ),
    ]
    return GeneratedFile(
        path=".github/copilot-instructions.md",
        content=join_sections(sections),
        target="copilot",
        description="Repository-wide Copilot custom instructions.",
    )


def _path_scoped(model: ProjectModel) -> list[GeneratedFile]:
    """Emit small path-scoped instruction files when the structure warrants it."""
    out: list[GeneratedFile] = []
    dir_paths = {d.path for d in model.key_directories}

    if "tests" in dir_paths or "test" in dir_paths:
        out.append(
            GeneratedFile(
                path=".github/instructions/tests.instructions.md",
                content=join_sections(
                    [
                        "---",
                        'applyTo: "tests/**"',
                        "---",
                        header("copilot"),
                        section(
                            "Test code conventions",
                            "Follow the existing test layout. Match assertion style and fixture "
                            "patterns from neighboring tests; keep new tests deterministic and fast.",
                            level=2,
                        ),
                    ]
                ),
                target="copilot",
                description="Path-scoped instructions for tests/.",
            )
        )

    if model.topology is TopologyKind.monorepo and "packages" in dir_paths:
        out.append(
            GeneratedFile(
                path=".github/instructions/packages.instructions.md",
                content=join_sections(
                    [
                        "---",
                        'applyTo: "packages/**"',
                        "---",
                        header("copilot"),
                        section(
                            "Shared package conventions",
                            "Each package owns its own dependencies. Do not import from another "
                            "package's internals; export through the package's public entry point.",
                            level=2,
                        ),
                    ]
                ),
                target="copilot",
                description="Path-scoped instructions for packages/.",
            )
        )

    return out


def generate_copilot(model: ProjectModel, existing: str = "") -> GenerationPlan:
    plan = GenerationPlan(target="copilot")
    plan.add(_repo_wide(model))
    for f in _path_scoped(model):
        plan.add(f)
    return plan
