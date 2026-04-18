"""Compare a fresh scan against the saved project model."""

from __future__ import annotations

from dataclasses import dataclass

from repocanon.models.project import ProjectModel


@dataclass
class ModelDiff:
    """Coarse diff between two ProjectModel snapshots."""

    fingerprint_changed: bool
    file_count_delta: int
    languages_added: list[str]
    languages_removed: list[str]
    frameworks_added: list[str]
    frameworks_removed: list[str]
    commands_changed: bool

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
            )
        )

    def regeneration_recommended(self) -> bool:
        return self.has_meaningful_changes


def diff_models(old: ProjectModel, new: ProjectModel) -> ModelDiff:
    old_langs = {lang.name for lang in old.languages}
    new_langs = {lang.name for lang in new.languages}
    old_fws = {fw.name for fw in old.frameworks}
    new_fws = {fw.name for fw in new.frameworks}
    return ModelDiff(
        fingerprint_changed=old.structural_fingerprint != new.structural_fingerprint,
        file_count_delta=new.file_count - old.file_count,
        languages_added=sorted(new_langs - old_langs),
        languages_removed=sorted(old_langs - new_langs),
        frameworks_added=sorted(new_fws - old_fws),
        frameworks_removed=sorted(old_fws - new_fws),
        commands_changed=old.commands.model_dump() != new.commands.model_dump(),
    )
