"""Strongly typed project model produced by the analyzer.

The model is intentionally a thin, JSON-serializable representation. All
inference lives in ``repocanon.analyzer``; the model only stores facts and
their associated confidence/evidence. Where the analyzer chooses from a
finite set of values (framework category, directory role kind, topology
flavor) those choices are exposed here as enums so generators can branch on
them without string matching.
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


class FrameworkCategory(StrEnum):
    """Coarse category for detected frameworks/libraries.

    These map to distinct kinds of architectural concerns and let generators
    branch on category rather than literal name (e.g. surface "ORM" guidance
    only when an ORM was detected).
    """

    web = "web"
    frontend = "frontend"
    api = "api"
    rpc = "rpc"
    cli = "cli"
    config = "config"
    orm = "orm"
    db = "db"
    migrations = "migrations"
    validation = "validation"
    serialization = "serialization"
    runtime = "runtime"
    test = "test"
    lint = "lint"
    format = "format"  # type: ignore[assignment]
    typecheck = "typecheck"
    build = "build"
    monorepo = "monorepo"
    task_queue = "task-queue"
    messaging = "messaging"
    logging = "logging"
    observability = "observability"
    ui = "ui"
    blockchain = "blockchain"
    language_tooling = "language-tooling"
    container = "container"
    iac = "iac"
    other = "other"


class Framework(BaseModel):
    name: str
    category: FrameworkCategory = Field(
        default=FrameworkCategory.other,
        description="Coarse category for the framework/library.",
    )
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

    def merge(self, other: CommandSet) -> None:
        """In-place merge of another CommandSet, deduping each bucket."""
        for attr in ("install", "build", "dev", "test", "lint", "format", "typecheck"):
            existing = getattr(self, attr)
            for cmd in getattr(other, attr):
                if cmd not in existing:
                    existing.append(cmd)
        for k, vs in other.extras.items():
            bucket = self.extras.setdefault(k, [])
            for v in vs:
                if v not in bucket:
                    bucket.append(v)


class RoleKind(StrEnum):
    """Coarse kind label for a directory's role in the repo."""

    source = "source"
    test = "test"
    docs = "docs"
    scripts = "scripts"
    config = "config"
    infra = "infra"
    deployment = "deployment"
    frontend = "frontend"
    backend = "backend"
    api = "api"
    db = "db"
    migrations = "migrations"
    monorepo_packages = "monorepo_packages"
    monorepo_apps = "monorepo_apps"
    monorepo_libs = "monorepo_libs"
    monorepo_services = "monorepo_services"
    examples = "examples"
    fixtures = "fixtures"
    static_assets = "static_assets"
    binaries = "binaries"
    internal = "internal"
    pkg = "pkg"
    other = "other"


class DirectoryRole(BaseModel):
    """A directory inside the repo and what we believe lives there."""

    path: str = Field(description="POSIX path relative to repo root.")
    role: str = Field(description="Human-readable label for the role.")
    role_kind: RoleKind = Field(
        default=RoleKind.other,
        description="Programmatic classification of the role.",
    )
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
    multi_binary = "multi_binary"
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


class Package(BaseModel):
    """A distinct sub-package in a monorepo or a multi-binary layout.

    Each package carries its own commands and frameworks so generators can
    surface "from `apps/web/`, run `pnpm dev`" instead of dumping every script
    in the repo into one undifferentiated bucket.
    """

    name: str = Field(description="Display name (e.g. '@scope/web' or 'cmd/api').")
    path: str = Field(description="POSIX path to the package root, relative to repo.")
    manifest: str = Field(description="POSIX path to the defining manifest.")
    package_manager: str | None = None
    frameworks: list[Framework] = Field(default_factory=list)
    commands: CommandSet = Field(default_factory=CommandSet)


class ProjectModel(BaseModel):
    """The single canonical view of the repo that all generators consume."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    schema_version: int = 2
    repo_name: str
    repo_path: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    languages: list[Language] = Field(default_factory=list)
    frameworks: list[Framework] = Field(default_factory=list)
    package_managers: list[PackageManager] = Field(default_factory=list)
    commands: CommandSet = Field(default_factory=CommandSet)

    topology: TopologyKind = TopologyKind.unknown
    monorepo_packages: list[Package] = Field(
        default_factory=list,
        description=(
            "One entry per sub-package detected in a monorepo or multi-binary layout. "
            "Each entry has its own commands and frameworks."
        ),
    )
    key_directories: list[DirectoryRole] = Field(default_factory=list)

    test_layout: TestLayout = TestLayout.unknown
    file_patterns: list[str] = Field(default_factory=list)
    naming_conventions: list[Convention] = Field(default_factory=list)
    conventions: list[Convention] = Field(default_factory=list)

    architecture_boundaries: list[ArchitectureBoundary] = Field(default_factory=list)
    preferred_libraries: list[str] = Field(
        default_factory=list,
        description=(
            "Capped list of declared dependencies, surfaced in generated outputs as "
            "'Preferred libraries'. Drawn from manifest dependencies, deduped."
        ),
    )
    anti_patterns: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)

    findings: list[Finding] = Field(default_factory=list)

    file_count: int = 0
    bytes_scanned: int = 0
    code_bytes_scanned: int = 0
    structural_fingerprint: str = ""

    def overall_confidence(self) -> float:
        """Average evidence-weighted confidence across all findings."""
        if not self.findings:
            return 0.0
        return sum(f.weighted_score for f in self.findings) / len(self.findings)

    def primary_language(self) -> str | None:
        if not self.languages:
            return None
        return max(self.languages, key=lambda lang: lang.file_count).name
