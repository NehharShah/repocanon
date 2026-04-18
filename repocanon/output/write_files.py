"""Write generated files to disk, optionally preserving manual edits."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repocanon.generators.common import (
    MANUAL_BEGIN,
    MANUAL_END,
    split_manual_block,
)
from repocanon.models.outputs import GeneratedFile, GenerationPlan


@dataclass
class WriteResult:
    path: Path
    action: str  # "created" | "updated" | "skipped"
    bytes_written: int


def _merge_manual_block(new_content: str, existing_content: str) -> str:
    """Replace the manual block in ``new_content`` with the user's prior contents."""
    if MANUAL_BEGIN not in new_content or MANUAL_END not in new_content:
        return new_content
    prior = split_manual_block(existing_content)
    if not prior:
        return new_content
    start = new_content.index(MANUAL_BEGIN) + len(MANUAL_BEGIN)
    end = new_content.index(MANUAL_END)
    return new_content[:start] + f"\n{prior}\n" + new_content[end:]


def write_plan(
    plan: GenerationPlan,
    repo_path: Path,
    *,
    output_dir: Path | None = None,
    dry_run: bool = False,
    force: bool = False,
    safe_overwrite: bool = True,
) -> list[WriteResult]:
    """Materialize a GenerationPlan to disk.

    - ``dry_run``: log only, do not write.
    - ``force``: overwrite without trying to preserve manual blocks.
    - ``safe_overwrite``: when a destination already contains a manual block,
      keep its contents. Has no effect when ``force`` is True.
    """
    base = (output_dir or repo_path).resolve()
    results: list[WriteResult] = []

    for f in plan.files:
        target_path = base / f.path
        existing = target_path.read_text("utf-8") if target_path.exists() else ""
        action: str
        content = f.content
        if existing:
            if force:
                action = "updated"
            elif safe_overwrite:
                content = _merge_manual_block(f.content, existing)
                action = "updated" if content != existing else "skipped"
            else:
                action = "updated"
        else:
            action = "created"

        if not dry_run and action != "skipped":
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")

        results.append(
            WriteResult(
                path=target_path,
                action=action,
                bytes_written=len(content.encode("utf-8")) if action != "skipped" else 0,
            )
        )
    return results


def materialize_files(
    files: list[GeneratedFile], repo_path: Path
) -> dict[str, str]:
    """Helper for tests: turn a list of files into a {rel_path: content} map."""
    return {f.path: f.content for f in files}
