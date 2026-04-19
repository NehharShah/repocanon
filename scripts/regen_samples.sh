#!/usr/bin/env bash
# Regenerate docs/samples/<fixture>/ for every fixture in tests/fixtures/.
# Generated files are written into the fixture, copied into docs/samples/
# (with .cursor/ → dot-cursor/ and .github/ → dot-github/ so they don't
# render as hidden in browsers), then cleaned out of the fixture.
set -euo pipefail

cd "$(dirname "$0")/.."

REPOCANON=${REPOCANON:-python -m repocanon}

regen_one() {
  local fx_path="$1"
  local fx_name
  fx_name="$(basename "$fx_path")"
  local out_dir="docs/samples/$fx_name"

  echo "→ regenerating $out_dir"

  $REPOCANON generate "$fx_path" --force >/dev/null

  rm -rf "$out_dir"
  mkdir -p "$out_dir"

  for f in AGENTS.md CLAUDE.md; do
    [[ -f "$fx_path/$f" ]] && cp "$fx_path/$f" "$out_dir/$f"
  done

  if [[ -d "$fx_path/.cursor" ]]; then
    mkdir -p "$out_dir/dot-cursor"
    cp -R "$fx_path/.cursor/." "$out_dir/dot-cursor/"
  fi

  if [[ -d "$fx_path/.github" ]]; then
    mkdir -p "$out_dir/dot-github"
    cp -R "$fx_path/.github/." "$out_dir/dot-github/"
  fi

  $REPOCANON clean "$fx_path" >/dev/null || true
  rm -rf "$fx_path/.repocanon" "$fx_path/.cursor" "$fx_path/.github"
  rm -f "$fx_path/AGENTS.md" "$fx_path/CLAUDE.md"
}

for fx in tests/fixtures/*/; do
  regen_one "${fx%/}"
done

echo "✓ docs/samples regenerated"
