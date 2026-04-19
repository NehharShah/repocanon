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


def test_version_matches_installed_metadata() -> None:
    """Catch the bug where __init__.__version__ drifts from pyproject.toml."""
    from importlib.metadata import version

    import repocanon

    assert repocanon.__version__ == version("repocanon"), (
        f"repocanon.__version__ ({repocanon.__version__}) does not match installed "
        f"package metadata ({version('repocanon')}). Did you forget to bump one of "
        "them, or did the package not get reinstalled after a version change?"
    )
