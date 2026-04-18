"""User-facing configuration loaded from ``.repocanon/config.toml``.

We intentionally keep this small. Most behavior is inferred; config only
exists to let users override include/exclude globs and pick targets.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

CONFIG_DIR_NAME = ".repocanon"
CONFIG_FILE_NAME = "config.toml"
PROJECT_MODEL_FILE_NAME = "project-model.json"

VALID_TARGETS: tuple[str, ...] = ("agents", "claude", "copilot", "cursor")

DEFAULT_CONFIG_TEXT = """# RepoCanon project configuration. Safe to edit by hand.

[project]
# Optional override of the inferred repo name.
# name = "my-repo"

[scan]
# Globs evaluated relative to the repo root.
# Empty 'include' means: scan everything not matched by 'exclude'.
include = []
exclude = [
  "node_modules/**",
  ".next/**",
  "dist/**",
  "build/**",
  ".venv/**",
  "venv/**",
]

[generate]
targets = ["agents", "claude", "copilot", "cursor"]
# When true, generated files preserve a manual section between RepoCanon markers.
safe_overwrite = true
"""


class ProjectConfig(BaseModel):
    name: str | None = None


class ScanConfig(BaseModel):
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class GenerateConfig(BaseModel):
    targets: list[str] = Field(default_factory=lambda: list(VALID_TARGETS))
    safe_overwrite: bool = True


class RepoCanonConfig(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    scan: ScanConfig = Field(default_factory=ScanConfig)
    generate: GenerateConfig = Field(default_factory=GenerateConfig)


def config_dir(repo_path: Path) -> Path:
    return repo_path / CONFIG_DIR_NAME


def config_path(repo_path: Path) -> Path:
    return config_dir(repo_path) / CONFIG_FILE_NAME


def project_model_path(repo_path: Path) -> Path:
    return config_dir(repo_path) / PROJECT_MODEL_FILE_NAME


def load_config(repo_path: Path) -> RepoCanonConfig:
    """Load config from ``.repocanon/config.toml`` or return defaults."""
    cfg_path = config_path(repo_path)
    if not cfg_path.exists():
        return RepoCanonConfig()
    with cfg_path.open("rb") as fh:
        raw = tomllib.load(fh)
    return RepoCanonConfig.model_validate(raw)


def write_default_config(repo_path: Path, *, force: bool = False) -> Path:
    """Create ``.repocanon/config.toml`` with sensible defaults.

    Returns the path written. Raises FileExistsError when the file already
    exists and ``force`` is False.
    """
    cfg_path = config_path(repo_path)
    if cfg_path.exists() and not force:
        raise FileExistsError(cfg_path)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return cfg_path
