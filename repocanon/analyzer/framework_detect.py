"""Heuristic framework, package manager, and library detection.

These rules are intentionally conservative: missing a framework is preferable
to confidently asserting one that isn't there. Each detection emits a Finding
so the audit command can show the rationale.
"""

from __future__ import annotations

from dataclasses import dataclass

from repocanon.analyzer.config_parse import ManifestData
from repocanon.models.findings import Confidence, Finding
from repocanon.models.project import Framework, PackageManager


@dataclass
class _Rule:
    """A single dependency-keyed framework signature."""

    name: str
    category: str
    needles: tuple[str, ...]


# Ordered roughly by how strongly the dependency implies the framework.
PY_RULES: tuple[_Rule, ...] = (
    _Rule("FastAPI", "web", ("fastapi",)),
    _Rule("Django", "web", ("django",)),
    _Rule("Flask", "web", ("flask",)),
    _Rule("Starlette", "web", ("starlette",)),
    _Rule("Pydantic", "validation", ("pydantic",)),
    _Rule("SQLAlchemy", "orm", ("sqlalchemy",)),
    _Rule("SQLModel", "orm", ("sqlmodel",)),
    _Rule("Alembic", "migrations", ("alembic",)),
    _Rule("Celery", "task-queue", ("celery",)),
    _Rule("pytest", "test", ("pytest",)),
    _Rule("Typer", "cli", ("typer",)),
    _Rule("Click", "cli", ("click",)),
    _Rule("Rich", "ui", ("rich",)),
    _Rule("Ruff", "lint", ("ruff",)),
    _Rule("mypy", "typecheck", ("mypy",)),
    _Rule("Black", "format", ("black",)),
)

JS_RULES: tuple[_Rule, ...] = (
    _Rule("Next.js", "web", ("next",)),
    _Rule("React", "frontend", ("react",)),
    _Rule("Vue", "frontend", ("vue",)),
    _Rule("Svelte", "frontend", ("svelte",)),
    _Rule("Angular", "frontend", ("@angular/core",)),
    _Rule("Express", "web", ("express",)),
    _Rule("NestJS", "web", ("@nestjs/core",)),
    _Rule("Fastify", "web", ("fastify",)),
    _Rule("Remix", "web", ("@remix-run/react",)),
    _Rule("Vite", "build", ("vite",)),
    _Rule("Webpack", "build", ("webpack",)),
    _Rule("Turborepo", "monorepo", ("turbo",)),
    _Rule("Nx", "monorepo", ("nx",)),
    _Rule("Jest", "test", ("jest",)),
    _Rule("Vitest", "test", ("vitest",)),
    _Rule("Playwright", "test", ("@playwright/test", "playwright")),
    _Rule("Cypress", "test", ("cypress",)),
    _Rule("ESLint", "lint", ("eslint",)),
    _Rule("Prettier", "format", ("prettier",)),
    _Rule("TypeScript", "language-tooling", ("typescript",)),
    _Rule("Tailwind CSS", "ui", ("tailwindcss",)),
    _Rule("Prisma", "orm", ("prisma", "@prisma/client")),
    _Rule("Drizzle", "orm", ("drizzle-orm",)),
    _Rule("tRPC", "api", ("@trpc/server",)),
    _Rule("Zod", "validation", ("zod",)),
)

GO_RULES: tuple[_Rule, ...] = (
    # web frameworks
    _Rule("Gin", "web", ("github.com/gin-gonic/gin",)),
    _Rule("Echo", "web", ("github.com/labstack/echo/v4", "github.com/labstack/echo")),
    _Rule("Fiber", "web", ("github.com/gofiber/fiber/v2", "github.com/gofiber/fiber")),
    _Rule("Chi", "web", ("github.com/go-chi/chi/v5", "github.com/go-chi/chi")),
    _Rule("Gorilla Mux", "web", ("github.com/gorilla/mux",)),
    # gRPC / protobuf
    _Rule("gRPC", "rpc", ("google.golang.org/grpc",)),
    _Rule("Protobuf", "serialization", ("google.golang.org/protobuf",)),
    # CLI
    _Rule("Cobra", "cli", ("github.com/spf13/cobra",)),
    _Rule("Viper", "config", ("github.com/spf13/viper",)),
    _Rule("urfave/cli", "cli", ("github.com/urfave/cli/v2", "github.com/urfave/cli")),
    # ORM / DB
    _Rule("GORM", "orm", ("gorm.io/gorm",)),
    _Rule("sqlx", "db", ("github.com/jmoiron/sqlx",)),
    _Rule("ent", "orm", ("entgo.io/ent",)),
    _Rule("sqlc", "db", ("github.com/sqlc-dev/sqlc", "github.com/kyleconroy/sqlc")),
    _Rule("pgx", "db", ("github.com/jackc/pgx/v5", "github.com/jackc/pgx/v4", "github.com/jackc/pgx")),
    # logging / observability
    _Rule("zap", "logging", ("go.uber.org/zap",)),
    _Rule("zerolog", "logging", ("github.com/rs/zerolog",)),
    _Rule("OpenTelemetry", "observability", ("go.opentelemetry.io/otel",)),
    _Rule("Prometheus client", "observability", ("github.com/prometheus/client_golang",)),
    # test
    _Rule("Testify", "test", ("github.com/stretchr/testify",)),
    _Rule("Ginkgo", "test", ("github.com/onsi/ginkgo/v2", "github.com/onsi/ginkgo")),
    _Rule("Gomega", "test", ("github.com/onsi/gomega",)),
    # web3 / blockchain
    _Rule("go-ethereum", "blockchain", ("github.com/ethereum/go-ethereum",)),
    _Rule("Cosmos SDK", "blockchain", ("github.com/cosmos/cosmos-sdk",)),
    _Rule(
        "Tendermint/CometBFT",
        "blockchain",
        ("github.com/cometbft/cometbft", "github.com/tendermint/tendermint"),
    ),
    # async / messaging
    _Rule("NATS", "messaging", ("github.com/nats-io/nats.go",)),
    _Rule("Sarama (Kafka)", "messaging", ("github.com/IBM/sarama", "github.com/Shopify/sarama")),
    _Rule("Asynq", "task-queue", ("github.com/hibiken/asynq",)),
)

RUST_RULES: tuple[_Rule, ...] = (
    _Rule("Axum", "web", ("axum",)),
    _Rule("Actix", "web", ("actix-web",)),
    _Rule("Rocket", "web", ("rocket",)),
    _Rule("Tokio", "runtime", ("tokio",)),
    _Rule("Serde", "serialization", ("serde",)),
    _Rule("Clap", "cli", ("clap",)),
)


def _apply_rules(
    rules: tuple[_Rule, ...], deps: set[str], evidence_path: str
) -> list[Framework]:
    found: list[Framework] = []
    for rule in rules:
        for needle in rule.needles:
            if needle.lower() in deps:
                found.append(
                    Framework(
                        name=rule.name,
                        category=rule.category,
                        evidence=[f"{evidence_path}: {needle}"],
                        confidence=Confidence.high,
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
        if m.kind == "pyproject":
            rules = PY_RULES
        elif m.kind == "package.json":
            rules = JS_RULES
        elif m.kind == "Cargo.toml":
            rules = RUST_RULES
        elif m.kind == "go.mod":
            rules = GO_RULES
        else:
            continue
        for fw in _apply_rules(rules, deps, m.path):
            existing = frameworks.get(fw.name)
            if existing is None:
                frameworks[fw.name] = fw
            else:
                existing.evidence.extend(e for e in fw.evidence if e not in existing.evidence)
            findings.append(
                Finding(
                    kind="framework",
                    subject=fw.name,
                    rationale=f"Dependency match in {m.path}.",
                    evidence=fw.evidence,
                    confidence=fw.confidence,
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
            if "pnpm-lock.yaml" in file_names:
                name = "pnpm"
            elif "yarn.lock" in file_names:
                name = "yarn"
            elif "bun.lockb" in file_names:
                name = "bun"
            else:
                name = "npm"
            pms.append(PackageManager(name=name, manifest=m.path, confidence=Confidence.high))
            findings.append(
                Finding(
                    kind="package-manager",
                    subject=name,
                    rationale=f"Detected from {m.path} and lockfile.",
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
