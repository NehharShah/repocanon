"""Heuristic framework, package manager, and library detection.

Rules are intentionally conservative: missing a framework is preferable to
confidently asserting one that isn't there. Each detection emits a
:class:`Finding` so the audit command can show the rationale and so the
overall confidence aggregator can weight by evidence count.
"""

from __future__ import annotations

from dataclasses import dataclass

from repocanon.analyzer.config_parse import ManifestData
from repocanon.models.findings import Confidence, Finding
from repocanon.models.project import Framework, FrameworkCategory, PackageManager


@dataclass(frozen=True)
class _Rule:
    """A single dependency-keyed framework signature."""

    name: str
    category: FrameworkCategory
    needles: tuple[str, ...]


# Ordered roughly by how strongly the dependency implies the framework.
PY_RULES: tuple[_Rule, ...] = (
    _Rule("FastAPI", FrameworkCategory.web, ("fastapi",)),
    _Rule("Django", FrameworkCategory.web, ("django",)),
    _Rule("Flask", FrameworkCategory.web, ("flask",)),
    _Rule("Starlette", FrameworkCategory.web, ("starlette",)),
    _Rule("Pyramid", FrameworkCategory.web, ("pyramid",)),
    _Rule("Tornado", FrameworkCategory.web, ("tornado",)),
    _Rule("Pydantic", FrameworkCategory.validation, ("pydantic",)),
    _Rule("attrs", FrameworkCategory.validation, ("attrs",)),
    _Rule("SQLAlchemy", FrameworkCategory.orm, ("sqlalchemy",)),
    _Rule("SQLModel", FrameworkCategory.orm, ("sqlmodel",)),
    _Rule("Tortoise ORM", FrameworkCategory.orm, ("tortoise-orm",)),
    _Rule("Alembic", FrameworkCategory.migrations, ("alembic",)),
    _Rule("Celery", FrameworkCategory.task_queue, ("celery",)),
    _Rule("Dramatiq", FrameworkCategory.task_queue, ("dramatiq",)),
    _Rule("Redis", FrameworkCategory.db, ("redis",)),
    _Rule("psycopg", FrameworkCategory.db, ("psycopg", "psycopg2", "psycopg2-binary")),
    _Rule("httpx", FrameworkCategory.runtime, ("httpx",)),
    _Rule("requests", FrameworkCategory.runtime, ("requests",)),
    _Rule("pytest", FrameworkCategory.test, ("pytest",)),
    _Rule("Hypothesis", FrameworkCategory.test, ("hypothesis",)),
    _Rule("Typer", FrameworkCategory.cli, ("typer",)),
    _Rule("Click", FrameworkCategory.cli, ("click",)),
    _Rule("Rich", FrameworkCategory.ui, ("rich",)),
    _Rule("Ruff", FrameworkCategory.lint, ("ruff",)),
    _Rule("mypy", FrameworkCategory.typecheck, ("mypy",)),
    _Rule("pyright", FrameworkCategory.typecheck, ("pyright",)),
    _Rule("Black", FrameworkCategory.format, ("black",)),
    _Rule("isort", FrameworkCategory.format, ("isort",)),
)

JS_RULES: tuple[_Rule, ...] = (
    _Rule("Next.js", FrameworkCategory.web, ("next",)),
    _Rule("React", FrameworkCategory.frontend, ("react",)),
    _Rule("Vue", FrameworkCategory.frontend, ("vue",)),
    _Rule("Svelte", FrameworkCategory.frontend, ("svelte",)),
    _Rule("Angular", FrameworkCategory.frontend, ("@angular/core",)),
    _Rule("Solid", FrameworkCategory.frontend, ("solid-js",)),
    _Rule("Express", FrameworkCategory.web, ("express",)),
    _Rule("NestJS", FrameworkCategory.web, ("@nestjs/core",)),
    _Rule("Fastify", FrameworkCategory.web, ("fastify",)),
    _Rule("Hono", FrameworkCategory.web, ("hono",)),
    _Rule("Remix", FrameworkCategory.web, ("@remix-run/react",)),
    _Rule("Astro", FrameworkCategory.web, ("astro",)),
    _Rule("Vite", FrameworkCategory.build, ("vite",)),
    _Rule("Webpack", FrameworkCategory.build, ("webpack",)),
    _Rule("Rollup", FrameworkCategory.build, ("rollup",)),
    _Rule("esbuild", FrameworkCategory.build, ("esbuild",)),
    _Rule("Turborepo", FrameworkCategory.monorepo, ("turbo",)),
    _Rule("Nx", FrameworkCategory.monorepo, ("nx",)),
    _Rule("Jest", FrameworkCategory.test, ("jest",)),
    _Rule("Vitest", FrameworkCategory.test, ("vitest",)),
    _Rule("Playwright", FrameworkCategory.test, ("@playwright/test", "playwright")),
    _Rule("Cypress", FrameworkCategory.test, ("cypress",)),
    _Rule("ESLint", FrameworkCategory.lint, ("eslint",)),
    _Rule("Biome", FrameworkCategory.lint, ("@biomejs/biome",)),
    _Rule("Prettier", FrameworkCategory.format, ("prettier",)),
    _Rule("TypeScript", FrameworkCategory.language_tooling, ("typescript",)),
    _Rule("Tailwind CSS", FrameworkCategory.ui, ("tailwindcss",)),
    _Rule("Prisma", FrameworkCategory.orm, ("prisma", "@prisma/client")),
    _Rule("Drizzle", FrameworkCategory.orm, ("drizzle-orm",)),
    _Rule("tRPC", FrameworkCategory.api, ("@trpc/server",)),
    _Rule("Zod", FrameworkCategory.validation, ("zod",)),
)

GO_RULES: tuple[_Rule, ...] = (
    _Rule("Gin", FrameworkCategory.web, ("github.com/gin-gonic/gin",)),
    _Rule("Echo", FrameworkCategory.web, ("github.com/labstack/echo/v4", "github.com/labstack/echo")),
    _Rule("Fiber", FrameworkCategory.web, ("github.com/gofiber/fiber/v2", "github.com/gofiber/fiber")),
    _Rule("Chi", FrameworkCategory.web, ("github.com/go-chi/chi/v5", "github.com/go-chi/chi")),
    _Rule("Gorilla Mux", FrameworkCategory.web, ("github.com/gorilla/mux",)),
    _Rule("gRPC", FrameworkCategory.rpc, ("google.golang.org/grpc",)),
    _Rule("Protobuf", FrameworkCategory.serialization, ("google.golang.org/protobuf",)),
    _Rule("Cobra", FrameworkCategory.cli, ("github.com/spf13/cobra",)),
    _Rule("Viper", FrameworkCategory.config, ("github.com/spf13/viper",)),
    _Rule("urfave/cli", FrameworkCategory.cli, ("github.com/urfave/cli/v2", "github.com/urfave/cli")),
    _Rule("GORM", FrameworkCategory.orm, ("gorm.io/gorm",)),
    _Rule("sqlx", FrameworkCategory.db, ("github.com/jmoiron/sqlx",)),
    _Rule("ent", FrameworkCategory.orm, ("entgo.io/ent",)),
    _Rule("sqlc", FrameworkCategory.db, ("github.com/sqlc-dev/sqlc", "github.com/kyleconroy/sqlc")),
    _Rule(
        "pgx",
        FrameworkCategory.db,
        ("github.com/jackc/pgx/v5", "github.com/jackc/pgx/v4", "github.com/jackc/pgx"),
    ),
    _Rule("zap", FrameworkCategory.logging, ("go.uber.org/zap",)),
    _Rule("zerolog", FrameworkCategory.logging, ("github.com/rs/zerolog",)),
    _Rule("OpenTelemetry", FrameworkCategory.observability, ("go.opentelemetry.io/otel",)),
    _Rule(
        "Prometheus client",
        FrameworkCategory.observability,
        ("github.com/prometheus/client_golang",),
    ),
    _Rule("Testify", FrameworkCategory.test, ("github.com/stretchr/testify",)),
    _Rule("Ginkgo", FrameworkCategory.test, ("github.com/onsi/ginkgo/v2", "github.com/onsi/ginkgo")),
    _Rule("Gomega", FrameworkCategory.test, ("github.com/onsi/gomega",)),
    _Rule("go-ethereum", FrameworkCategory.blockchain, ("github.com/ethereum/go-ethereum",)),
    _Rule("Cosmos SDK", FrameworkCategory.blockchain, ("github.com/cosmos/cosmos-sdk",)),
    _Rule(
        "Tendermint/CometBFT",
        FrameworkCategory.blockchain,
        ("github.com/cometbft/cometbft", "github.com/tendermint/tendermint"),
    ),
    _Rule("NATS", FrameworkCategory.messaging, ("github.com/nats-io/nats.go",)),
    _Rule(
        "Sarama (Kafka)",
        FrameworkCategory.messaging,
        ("github.com/IBM/sarama", "github.com/Shopify/sarama"),
    ),
    _Rule("Asynq", FrameworkCategory.task_queue, ("github.com/hibiken/asynq",)),
)

RUST_RULES: tuple[_Rule, ...] = (
    _Rule("Axum", FrameworkCategory.web, ("axum",)),
    _Rule("Actix", FrameworkCategory.web, ("actix-web",)),
    _Rule("Rocket", FrameworkCategory.web, ("rocket",)),
    _Rule("Tokio", FrameworkCategory.runtime, ("tokio",)),
    _Rule("Serde", FrameworkCategory.serialization, ("serde",)),
    _Rule("Clap", FrameworkCategory.cli, ("clap",)),
)


# Frameworks that are also tools that *must* be configured (not just installed)
# to actually shape the repo. We promote them to "high" only when there's a
# corresponding [tool.x] table or config file.
_NEEDS_CONFIG: frozenset[str] = frozenset({"Ruff", "mypy", "pyright", "Black", "isort"})


def _apply_rules(
    rules: tuple[_Rule, ...],
    deps: set[str],
    evidence_path: str,
    declared_tools: set[str],
) -> list[Framework]:
    found: list[Framework] = []
    for rule in rules:
        for needle in rule.needles:
            if needle.lower() in deps:
                # Default to medium for a single dependency match; bumped to
                # high downstream when at least one extra signal corroborates
                # it (multiple needles, configured tool, etc.).
                tool_key = rule.name.lower()
                base_conf = (
                    Confidence.high
                    if rule.name not in _NEEDS_CONFIG
                    else (Confidence.high if tool_key in declared_tools else Confidence.medium)
                )
                found.append(
                    Framework(
                        name=rule.name,
                        category=rule.category,
                        evidence=[f"{evidence_path}: {needle}"],
                        confidence=base_conf,
                    )
                )
                break
    return found


def detect_frameworks(
    manifests: list[ManifestData],
) -> tuple[list[Framework], list[Finding]]:
    frameworks: dict[str, Framework] = {}
    findings: list[Finding] = []

    for m in manifests:
        deps = {d.lower() for d in (*m.dependencies, *m.dev_dependencies)}
        declared = {t.lower() for t in m.declared_tools}
        if m.kind == "pyproject" or m.kind in {
            "requirements.txt",
            "setup.cfg",
            "setup.py",
            "Pipfile",
        }:
            rules = PY_RULES
        elif m.kind == "package.json":
            rules = JS_RULES
        elif m.kind == "Cargo.toml":
            rules = RUST_RULES
        elif m.kind == "go.mod":
            rules = GO_RULES
        else:
            continue
        for fw in _apply_rules(rules, deps, m.path, declared):
            existing = frameworks.get(fw.name)
            if existing is None:
                frameworks[fw.name] = fw
            else:
                existing.evidence.extend(e for e in fw.evidence if e not in existing.evidence)
                if fw.confidence is Confidence.high:
                    existing.confidence = Confidence.high
            findings.append(
                Finding(
                    kind="framework",
                    subject=fw.name,
                    rationale=f"Dependency match in {m.path}.",
                    evidence=fw.evidence,
                    confidence=fw.confidence,
                )
            )

    # Promote frameworks with multiple corroborating evidence pieces to high.
    for fw in frameworks.values():
        if len(fw.evidence) >= 2 and fw.confidence is Confidence.medium:
            fw.confidence = Confidence.high

    # Detect containerization signals from Dockerfile / docker-compose.
    docker_files = [m for m in manifests if m.kind in {"Dockerfile", "docker-compose"}]
    if docker_files:
        evidence = [m.path for m in docker_files]
        if "Docker" not in frameworks:
            frameworks["Docker"] = Framework(
                name="Docker",
                category=FrameworkCategory.container,
                evidence=evidence,
                confidence=Confidence.high if len(docker_files) >= 2 else Confidence.medium,
            )
            findings.append(
                Finding(
                    kind="framework",
                    subject="Docker",
                    rationale="Dockerfile / docker-compose detected.",
                    evidence=evidence,
                    confidence=frameworks["Docker"].confidence,
                )
            )

    return list(frameworks.values()), findings


def detect_package_managers(
    manifests: list[ManifestData], file_names: set[str]
) -> tuple[list[PackageManager], list[Finding]]:
    pms: list[PackageManager] = []
    findings: list[Finding] = []

    for m in manifests:
        if m.kind == "pyproject":
            tool = m.raw.get("tool", {}) if isinstance(m.raw, dict) else {}
            if isinstance(tool, dict) and "poetry" in tool:
                name = "poetry"
            elif "uv.lock" in file_names:
                name = "uv"
            elif "Pipfile.lock" in file_names:
                name = "pipenv"
            else:
                name = "pip"
            pms.append(PackageManager(name=name, manifest=m.path, confidence=Confidence.high))
            findings.append(
                Finding(
                    kind="package-manager",
                    subject=name,
                    rationale=f"Detected from {m.path}.",
                    evidence=[m.path],
                    confidence=Confidence.high,
                )
            )
        elif m.kind == "package.json":
            # Authoritative `packageManager` field beats lockfile heuristics.
            if m.package_manager_hint in {"npm", "pnpm", "yarn", "bun"}:
                assert m.package_manager_hint is not None
                name = m.package_manager_hint
                rationale = f"`packageManager` field in {m.path}."
            elif "pnpm-lock.yaml" in file_names:
                name = "pnpm"
                rationale = "pnpm-lock.yaml present."
            elif "yarn.lock" in file_names:
                name = "yarn"
                rationale = "yarn.lock present."
            elif "bun.lockb" in file_names or "bun.lock" in file_names:
                name = "bun"
                rationale = "bun lockfile present."
            elif "package-lock.json" in file_names:
                name = "npm"
                rationale = "package-lock.json present."
            else:
                name = "npm"
                rationale = "Defaulted to npm; no lockfile or packageManager field."
            pms.append(PackageManager(name=name, manifest=m.path, confidence=Confidence.high))
            findings.append(
                Finding(
                    kind="package-manager",
                    subject=name,
                    rationale=rationale,
                    evidence=[m.path],
                    confidence=Confidence.high,
                )
            )
        elif m.kind == "Cargo.toml":
            pms.append(PackageManager(name="cargo", manifest=m.path))
            findings.append(
                Finding(
                    kind="package-manager",
                    subject="cargo",
                    rationale="Cargo.toml present.",
                    evidence=[m.path],
                    confidence=Confidence.high,
                )
            )
        elif m.kind == "go.mod":
            pms.append(PackageManager(name="go-modules", manifest=m.path))
            findings.append(
                Finding(
                    kind="package-manager",
                    subject="go-modules",
                    rationale="go.mod present.",
                    evidence=[m.path],
                    confidence=Confidence.high,
                )
            )
        elif m.kind in {"requirements.txt", "setup.cfg", "setup.py"}:
            # Only emit when no pyproject already established the manager.
            if not any(pm.name in {"pip", "uv", "poetry", "pipenv"} for pm in pms):
                pms.append(PackageManager(name="pip", manifest=m.path))
                findings.append(
                    Finding(
                        kind="package-manager",
                        subject="pip",
                        rationale=f"{m.kind} present without pyproject.",
                        evidence=[m.path],
                        confidence=Confidence.medium,
                    )
                )
        elif m.kind == "Pipfile":
            if not any(pm.name == "pipenv" for pm in pms):
                pms.append(PackageManager(name="pipenv", manifest=m.path))
                findings.append(
                    Finding(
                        kind="package-manager",
                        subject="pipenv",
                        rationale="Pipfile present.",
                        evidence=[m.path],
                        confidence=Confidence.high,
                    )
                )

    # Dedup on (name, manifest); keep stable order.
    seen: set[tuple[str, str]] = set()
    deduped: list[PackageManager] = []
    for pm in pms:
        key = (pm.name, pm.manifest)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(pm)
    return deduped, findings
