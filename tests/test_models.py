"""Sanity checks on the Pydantic models."""

from __future__ import annotations

from repocanon.models.findings import Confidence, Finding
from repocanon.models.project import (
    CommandSet,
    Language,
    ProjectModel,
    TestLayout,
    TopologyKind,
)


def test_command_set_is_empty_default() -> None:
    assert CommandSet().is_empty()


def test_command_set_not_empty_when_populated() -> None:
    assert not CommandSet(test=["pytest"]).is_empty()


def test_project_model_round_trip_json() -> None:
    model = ProjectModel(
        repo_name="demo",
        repo_path="/tmp/demo",
        languages=[Language(name="Python", file_count=3)],
        topology=TopologyKind.single_package,
        test_layout=TestLayout.centralized,
        findings=[Finding(kind="x", subject="y", rationale="z", confidence=Confidence.high)],
    )
    payload = model.model_dump_json()
    restored = ProjectModel.model_validate_json(payload)
    assert restored.repo_name == "demo"
    assert restored.primary_language() == "Python"
    assert 0.99 < restored.overall_confidence() <= 1.0


def test_overall_confidence_zero_when_no_findings() -> None:
    model = ProjectModel(repo_name="x", repo_path=".")
    assert model.overall_confidence() == 0.0
