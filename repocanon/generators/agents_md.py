"""Generate AGENTS.md (Codex-style operational instructions).

AGENTS.md is the verbose "how to operate this repo as a contributor" doc:
full command lists, every framework, all conventions, every boundary, and
the uncertainty notes that should make agents pause. CLAUDE.md is a
deliberately-terser cousin used as persistent memory; the two should look
materially different on disk.
"""

from __future__ import annotations

from repocanon.generators.common import (
    header,
    manual_block,
    section,
    standard_sections,
)
from repocanon.models.outputs import GeneratedFile, GenerationPlan
from repocanon.models.project import ProjectModel
from repocanon.utils.text import join_sections


def generate_agents(model: ProjectModel) -> GenerationPlan:
    title = f"# {model.repo_name} — AGENTS.md"

    sections = [
        title,
        header("agents"),
        *standard_sections(model),
        section(
            "Validation expectations",
            "Run lint, typecheck, and tests before claiming a change is complete. "
            "If any tool is undefined for this repo, say so explicitly rather than skipping it.",
            level=2,
        ),
        section("Manual notes", manual_block(), level=2),
    ]

    content = join_sections(sections)
    plan = GenerationPlan(target="agents")
    plan.add(
        GeneratedFile(
            path="AGENTS.md",
            content=content,
            target="agents",
            description="Codex-style operational manual.",
        )
    )
    return plan
