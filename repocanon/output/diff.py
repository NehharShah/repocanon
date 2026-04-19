"""Compare a fresh scan against the saved project model."""

from __future__ import annotations

from dataclasses import dataclass, field

from repocanon.models.project import CommandSet, ProjectModel


@dataclass
class CommandDiff:
    """Per-bucket added/removed commands between two CommandSets."""

    bucket: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)


@dataclass
class ModelDiff:
    """Coarse diff between two ProjectModel snapshots."""

    fingerprint_changed: bool
    file_count_delta: int
    languages_added: list[str]
    languages_removed: list[str]
    frameworks_added: list[str]
    frameworks_removed: list[str]
    command_diffs: list[CommandDiff]
    packages_added: list[str]
    packages_removed: list[str]

    @property
    def commands_changed(self) -> bool:
        return any(d.changed for d in self.command_diffs)

    @property
    def has_meaningful_changes(self) -> bool:
        return any(
            (
                self.fingerprint_changed,
                self.languages_added,
                self.languages_removed,
                self.frameworks_added,
                self.frameworks_removed,
                self.commands_changed,
                self.packages_added,
                self.packages_removed,
            )
        )

    def regeneration_recommended(self) -> bool:
        return self.has_meaningful_changes


def diff_models(old: ProjectModel, new: ProjectModel) -> ModelDiff:
    old_langs = {lang.name for lang in old.languages}
    new_langs = {lang.name for lang in new.languages}
    old_fws = {fw.name for fw in old.frameworks}
    new_fws = {fw.name for fw in new.frameworks}
    old_pkgs = {p.path for p in old.monorepo_packages}
    new_pkgs = {p.path for p in new.monorepo_packages}
    return ModelDiff(
        fingerprint_changed=old.structural_fingerprint != new.structural_fingerprint,
        file_count_delta=new.file_count - old.file_count,
        languages_added=sorted(new_langs - old_langs),
        languages_removed=sorted(old_langs - new_langs),
        frameworks_added=sorted(new_fws - old_fws),
        frameworks_removed=sorted(old_fws - new_fws),
        command_diffs=_diff_commands(old.commands, new.commands),
        packages_added=sorted(new_pkgs - old_pkgs),
        packages_removed=sorted(old_pkgs - new_pkgs),
    )


def _diff_commands(old: CommandSet, new: CommandSet) -> list[CommandDiff]:
    out: list[CommandDiff] = []
    for bucket in ("install", "build", "dev", "test", "lint", "format", "typecheck"):
        old_items = list(getattr(old, bucket))
        new_items = list(getattr(new, bucket))
        added = [c for c in new_items if c not in old_items]
        removed = [c for c in old_items if c not in new_items]
        if added or removed:
            out.append(CommandDiff(bucket=bucket, added=added, removed=removed))
    return out
