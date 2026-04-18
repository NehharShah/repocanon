# Sample RepoCanon outputs

These are the actual files RepoCanon produces when run against the bundled fixture repos under [`tests/fixtures/`](../../tests/fixtures). They're committed verbatim so you can browse what the output looks like before installing anything.

Inside each directory:

- `AGENTS.md` — Codex-style operational manual.
- `CLAUDE.md` — Terse Claude Code persistent memory.
- `dot-github/` — Renamed from `.github/` so it shows up in GitHub's web UI.
  - `copilot-instructions.md` — Repo-wide Copilot custom instructions.
  - `instructions/*.instructions.md` — Path-scoped Copilot instructions.
- `dot-cursor/` — Renamed from `.cursor/`.
  - `rules/*.mdc` — Cursor project rules, split into focused files.

The dotfile directories are renamed to `dot-github/` and `dot-cursor/` only here; the actual generator writes to `.github/` and `.cursor/`.

To regenerate these locally:

```bash
make demo
```
