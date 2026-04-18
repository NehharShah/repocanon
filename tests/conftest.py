"""Shared fixtures for RepoCanon tests."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_ROOT = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fastapi_repo() -> Path:
    return FIXTURES_ROOT / "fastapi_app"


@pytest.fixture(scope="session")
def nextjs_repo() -> Path:
    return FIXTURES_ROOT / "nextjs_app"


@pytest.fixture(scope="session")
def monorepo_repo() -> Path:
    return FIXTURES_ROOT / "monorepo"
