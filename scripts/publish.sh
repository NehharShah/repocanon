#!/usr/bin/env bash
# Convenience wrapper around the publish steps documented in PUBLISHING.md.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Running pre-flight checks"
make lint
make typecheck
make test

echo "==> Building distributions"
make build

echo "==> Publishing to PyPI"
python -m twine upload dist/*
