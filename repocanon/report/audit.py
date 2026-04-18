"""Render an inference audit: rationale and confidence behind every guess."""

from __future__ import annotations

from rich.table import Table

from repocanon.models.findings import Confidence, Finding
from repocanon.models.project import ProjectModel
from repocanon.utils.logging import console
from repocanon.utils.text import truncate

_CONFIDENCE_COLOR = {
    Confidence.high: "ok",
    Confidence.medium: "info",
    Confidence.low: "warn",
}


def print_audit(model: ProjectModel) -> None:
    console.rule(f"[title]Audit · {model.repo_name}[/title]")

    by_kind: dict[str, list[Finding]] = {}
    for f in model.findings:
        by_kind.setdefault(f.kind, []).append(f)

    for kind in sorted(by_kind.keys()):
        t = Table(title=kind, show_header=True, header_style="title")
        t.add_column("Subject", style="bold")
        t.add_column("Rationale")
        t.add_column("Confidence")
        for f in by_kind[kind]:
            color = _CONFIDENCE_COLOR.get(f.confidence, "info")
            t.add_row(
                f.subject,
                truncate(f.rationale, 200),
                f"[{color}]{f.confidence.value}[/{color}]",
            )
        console.print(t)

    weak = [f for f in model.findings if f.confidence is Confidence.low]
    if weak:
        console.print("[warn]Items needing manual review:[/warn]")
        for f in weak:
            console.print(f"  - {f.kind}/{f.subject}: {truncate(f.rationale, 160)}")
    if model.uncertainty_notes:
        console.print("[warn]Uncertainty notes:[/warn]")
        for note in model.uncertainty_notes:
            console.print(f"  - {note}")
