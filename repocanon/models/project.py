"""Strongly typed project model produced by the analyzer.

The model is intentionally a thin, JSON-serializable representation. All
inference lives in ``repocanon.analyzer``; the model only stores facts and
their associated confidence/evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from repocanon.models.findings import Confidence, Finding


class Language(BaseModel):
    name: str
    file_count: int = 0
    primary_extensions: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.high


class Framework(BaseModel):
    name: str
    category: str = Field(description="e.g. 'web', 'orm', 'frontend', 'cli', 'test'.")
    evidence: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.medium


class PackageManager(BaseModel):
    name: str = Field(description="e.g. pip, uv, poetry, npm, pnpm, yarn, cargo.")
    manifest: str = Field(description="Repo-relative path to manifest file.")
    confidence: Confidence = Confidence.high


class CommandSet(BaseModel):
    """Concrete commands a contributor or AI agent should run."""

    install: list[str] = Field(default_factory=list)
    build: list[str] = Field(default_factory=list)
    dev: list[str] = Field(default_factory=list)
    test: list[str] = Field(default_factory=list)
    lint: list[str] = Field(default_factory=list)
    format: list[str] = Field(default_factory=list)
    typecheck: list[str] = Field(default_factory=list)
    extras: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Other named scripts we found but couldn't classify.",
    )

    def is_empty(self) -> bool:
        return not any(
            (
                self.install,
                self.build,
                self.dev,
                self.test,
                self.lint,
                self.format,
                self.typecheck,
                self.extras,
            )
        )


class DirectoryRole(BaseModel):
    """A directory inside the repo and what we believe lives there."""

    path: str = Field(description="POSIX path relative to repo root.")
    role: str = Field(description="e.g. 'source', 'tests', 'docs', 'frontend'.")
    rationale: str = ""
    confidence: Confidence = Confidence.medium


class TestLayout(StrEnum):
    colocated = "colocated"
    centralized = "centralized"
    mixed = "mixed"
    unknown = "unknown"


class TopologyKind(StrEnum):
    single_package = "single_package"
    monorepo = "monorepo"
    multi_root = "multi_root"
    unknown = "unknown"


class Convention(BaseModel):
    """An inferred convention with rationale.

    Conventions show up directly in generated outputs. We keep them small and
    quotable so they read well inside Markdown bullets.
    """

    name: str
    value: str
    rationale: str = ""
    confidence: Confidence = Confidence.medium


class ArchitectureBoundary(BaseModel):
    name: str = Field(description="Short label, e.g. 'frontend/backend split'.")
    description: str
    confidence: Confidence = Confidence.medium


class ProjectModel(BaseModel):
    """The single canonical view of the repo that all generators consume."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    schema_version: int = 1
    repo_name: str
    repo_path: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    languages: list[Language] = Field(default_factory=list)
    frameworks: list[Framework] = Field(default_factory=list)
    package_managers: list[PackageManager] = Field(default_factory=list)
    commands: CommandSet = Field(default_factory=CommandSet)

    topology: TopologyKind = TopologyKind.unknown
    monorepo_packages: list[str] = Field(default_factory=list)
    key_directories: list[DirectoryRole] = Field(default_factory=list)

    test_layout: TestLayout = TestLayout.unknown
    file_patterns: list[str] = Field(default_factory=list)
    naming_conventions: list[Convention] = Field(default_factory=list)
    conventions: list[Convention] = Field(default_factory=list)

    architecture_boundaries: list[ArchitectureBoundary] = Field(default_factory=list)
    preferred_libraries: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)

    findings: list[Finding] = Field(default_factory=list)

    file_count: int = 0
    bytes_scanned: int = 0
    structural_fingerprint: str = ""

    def overall_confidence(self) -> float:
        """Average confidence score across all findings; 0.0 when empty."""
        if not self.findings:
            return 0.0
        return sum(f.confidence.score for f in self.findings) / len(self.findings)

    def primary_language(self) -> str | None:
        if not self.languages:
            return None
        return max(self.languages, key=lambda lang: lang.file_count).name
