# RepoCanon

> Generate repo-specific AI context for Codex, Claude Code, Copilot, and Cursor.

[![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://pypi.org/project/repocanon/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Turn any repository into canonical AI-readable project context.

RepoCanon is a Python CLI that analyzes a local codebase and generates project-specific instruction files for AI coding tools from a single internal repo model.

Instead of manually maintaining separate context for different tools, RepoCanon infers your repo’s structure, commands, conventions, and boundaries, then generates outputs such as:

- `AGENTS.md`
- `CLAUDE.md`
- Copilot repository instructions
- Cursor project rules

The goal is simple: make AI coding tools behave like they already understand your repo.

## Why RepoCanon

AI coding tools are useful, but they usually guess:

- where things live
- how the repo is structured
- which commands to run
- what patterns are preferred
- what boundaries should not be crossed

RepoCanon reduces that guesswork by turning repo-specific knowledge into maintainable instruction files.

## What it does

RepoCanon:

- analyzes a local repository
- detects languages, frameworks, commands, and topology
- infers conventions and architectural boundaries
- builds a normalized project model
- generates tool-specific AI context files from that model

RepoCanon is deterministic-first. It does not require an LLM to work.

## Supported targets

- Codex via `AGENTS.md`
- Claude Code via `CLAUDE.md`
- GitHub Copilot via `.github/copilot-instructions.md` (and optional path-scoped files)
- Cursor via `.cursor/rules/*.mdc`

## Installation

```bash
pip install repocanon
```

Requires Python 3.11+.

## Quickstart

```bash
# 1. Analyze the current repo and persist a normalized model.
repocanon analyze .

# 2. Inspect what was inferred and how confident RepoCanon is.
repocanon audit .

# 3. Preview generated outputs without touching the filesystem.
repocanon preview all .

# 4. Write the generated files into the repo.
repocanon generate all .
```

You can also generate one target at a time:

```bash
repocanon generate agents .
repocanon generate claude .
repocanon generate copilot .
repocanon generate cursor .
```

## Example outputs

A real run produces files like:

```text
AGENTS.md
CLAUDE.md
.cursor/rules/project-overview.mdc
.cursor/rules/commands-and-validation.mdc
.cursor/rules/code-style-and-conventions.mdc
.cursor/rules/architecture-boundaries.mdc
.github/copilot-instructions.md
.github/instructions/tests.instructions.md
```

See [`docs/samples/`](docs/samples) for sample generated files from the bundled fixture repos.

## How it works

RepoCanon has three layers:

### 1. Repo analysis

It scans the local repo and extracts:

- languages
- frameworks
- package managers
- commands
- configs
- directory structure
- file patterns

### 2. Convention inference

It infers patterns such as:

- test layout (centralized vs colocated)
- frontend/backend split
- monorepo structure (apps/packages/libs/services)
- architectural boundaries
- naming conventions
- preferred libraries
- common anti-pattern risks (e.g. editing existing migrations)

### 3. Target generation

It maps one normalized project model into tool-specific outputs.

That means the same repo understanding can be reused across multiple AI coding tools.

## Design principles

- deterministic first
- local-first (no telemetry, no network calls)
- tool-agnostic core
- small, readable outputs
- no generic filler — every section is grounded in repo facts
- explicit uncertainty when confidence is low
- human-editable generated files (sections between `<!-- repocanon:manual:* -->` markers survive regeneration)

## Commands

### `repocanon analyze [PATH]`

Analyze the repository and write a normalized model to:

```text
.repocanon/project-model.json
```

### `repocanon generate [target] [PATH]`

Generate output for one target or all targets.

Supported targets:

- `agents`
- `claude`
- `copilot`
- `cursor`
- `all`

Useful flags:

- `--dry-run`
- `--output-dir`
- `--force`

### `repocanon preview [target] [PATH]`

Print generated output to the terminal without writing files.

### `repocanon audit [PATH]`

Show inferred conventions, rationale, and confidence levels.

### `repocanon diff [PATH]`

Compare the current repo scan with the saved model and report meaningful changes.

### `repocanon init [PATH]`

Create a local RepoCanon config file at `.repocanon/config.toml`.

## Configuration

RepoCanon stores project config in:

```text
.repocanon/config.toml
```

Example:

```toml
[project]
name = "my-repo"

[scan]
include = ["src/**", "app/**", "packages/**"]
exclude = ["node_modules/**", ".next/**", "dist/**", "build/**"]

[generate]
targets = ["agents", "claude", "copilot", "cursor"]
safe_overwrite = true
```

## Architecture overview

```
repocanon/
├── analyzer/    # deterministic repo scanning + inference
├── models/      # Pydantic v2 project model
├── generators/  # one module per AI target
├── output/      # writers, preview, diff
├── report/      # audit + summary tables
└── cli.py       # Typer entry point
```

The analyzer is a straight pipeline: file inventory → manifest parsing → framework/package-manager detection → command extraction → topology + conventions → final `ProjectModel`. Generators only consume that model — they never touch the filesystem.

## Limitations

RepoCanon is inference-based. It can detect a lot, but not everything.

It may be less accurate when:

- the repo is highly unconventional
- conventions are implicit rather than visible in files
- commands live outside standard manifests
- architecture is unclear from structure alone

When confidence is low, RepoCanon says so rather than inventing detail.

## Roadmap

- more framework detectors (Django, Rails, .NET, Spring, etc.)
- stronger monorepo inference (Bazel, Pants, Nx graph)
- better path-scoped output generation
- safer merge/update behavior for edited generated files
- optional LLM-assisted summarization (off by default)
- additional target formats

## Why not just write these files manually?

You can. But in practice:

- they drift out of date
- they are inconsistent across tools
- they are often generic
- they rarely reflect the actual repo structure

RepoCanon keeps those files grounded in the codebase.

## How RepoCanon maps one repo model to multiple AI coding tools

RepoCanon is intentionally a many-to-one-to-many pipeline:

```
repo files ─┐                              ┌─► AGENTS.md            (Codex)
            ├─► analyzer ─► ProjectModel ──┼─► CLAUDE.md            (Claude Code)
manifests  ─┘                              ├─► copilot-instructions (Copilot)
                                           └─► .cursor/rules/*.mdc  (Cursor)
```

The analyzer collapses everything it sees into a single normalized `ProjectModel` (Pydantic v2). That model is the only thing target generators read; they never touch the filesystem. This gives RepoCanon two important properties:

1. **One source of truth.** Languages, frameworks, commands, conventions, anti-patterns, and architecture boundaries all live in one place. Adding a new target means writing a new generator that consumes the same model — not re-implementing detection.
2. **Idiomatic outputs per tool.** Each generator picks the parts of the model that make sense for its target and renders them in that tool's idiom: a verbose AGENTS.md for Codex, a terse CLAUDE.md for Claude Code, a repo-wide instructions file (plus optional path-scoped ones) for Copilot, and a small set of focused `.mdc` rule files for Cursor.

The same model also powers `audit`, `diff`, and `preview`, so you can verify what RepoCanon inferred before any file is written.

## Contributing

Contributions are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for local setup, tests, and development workflow.

## Publishing

Maintainers: see [`PUBLISHING.md`](PUBLISHING.md) for the PyPI release checklist.

## License

MIT
