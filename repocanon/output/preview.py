"""Pretty-print generated files to the terminal without writing them."""

from __future__ import annotations

from rich.panel import Panel
from rich.syntax import Syntax

from repocanon.models.outputs import GenerationPlan
from repocanon.utils.logging import console


def preview_plan(plan: GenerationPlan) -> None:
    if not plan.files:
        console.print(f"[muted]No files generated for target '{plan.target}'.[/muted]")
        return
    for f in plan.files:
        body = Syntax(
            f.content,
            "markdown",
            theme="ansi_dark",
            word_wrap=True,
            line_numbers=False,
        )
        console.print(
            Panel(
                body,
                title=f"[title]{f.path}[/title]",
                subtitle=f"[muted]{f.size_bytes()} bytes · {plan.target}[/muted]",
                border_style="cyan",
            )
        )
