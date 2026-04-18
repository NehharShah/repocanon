"""Render a Rich-styled summary of the analyzed project model."""

from __future__ import annotations

from rich.table import Table

from repocanon.models.project import ProjectModel
from repocanon.utils.logging import console


def print_summary(model: ProjectModel) -> None:
    console.rule(f"[title]{model.repo_name}[/title]")
    console.print(
        f"Topology: [info]{model.topology.value}[/info]"
        f" · Files scanned: [info]{model.file_count}[/info]"
        f" · Confidence: [info]{model.overall_confidence():.2f}[/info]"
    )

    if model.languages:
        t = Table(title="Languages", show_header=True, header_style="title")
        t.add_column("Language")
        t.add_column("Files", justify="right")
        for lang in model.languages[:8]:
            t.add_row(lang.name, str(lang.file_count))
        console.print(t)

    if model.frameworks:
        t = Table(title="Frameworks", show_header=True, header_style="title")
        t.add_column("Name")
        t.add_column("Category")
        t.add_column("Confidence")
        for fw in model.frameworks[:12]:
            t.add_row(fw.name, fw.category, fw.confidence.value)
        console.print(t)

    if model.commands and not model.commands.is_empty():
        t = Table(title="Commands", show_header=True, header_style="title")
        t.add_column("Group")
        t.add_column("Command")
        for label, items in (
            ("install", model.commands.install),
            ("dev", model.commands.dev),
            ("build", model.commands.build),
            ("test", model.commands.test),
            ("lint", model.commands.lint),
            ("format", model.commands.format),
            ("typecheck", model.commands.typecheck),
        ):
            for cmd in items:
                t.add_row(label, cmd)
        console.print(t)

    if model.key_directories:
        t = Table(title="Key directories", show_header=True, header_style="title")
        t.add_column("Path")
        t.add_column("Role")
        for d in model.key_directories[:12]:
            t.add_row(f"{d.path}/", d.role)
        console.print(t)

    if model.uncertainty_notes:
        console.print("[warn]Uncertainty:[/warn]")
        for note in model.uncertainty_notes:
            console.print(f"  - {note}")
