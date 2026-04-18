"""Target-specific output generators that share one ProjectModel."""

from repocanon.generators.agents_md import generate_agents
from repocanon.generators.claude_md import generate_claude
from repocanon.generators.copilot import generate_copilot
from repocanon.generators.cursor_rules import generate_cursor

__all__ = [
    "generate_agents",
    "generate_claude",
    "generate_copilot",
    "generate_cursor",
]
