#!/usr/bin/env bash
# Run RepoCanon against each fixture repo and print previews. Useful for screenshots.
set -euo pipefail

cd "$(dirname "$0")/.."

for fx in tests/fixtures/*/; do
  echo
  echo "================================================================"
  echo "  $fx"
  echo "================================================================"
  python -m repocanon analyze "$fx"
  python -m repocanon audit "$fx"
  python -m repocanon preview "$fx" -t agents
done
