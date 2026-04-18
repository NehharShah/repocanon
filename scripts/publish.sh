#!/usr/bin/env bash
# Convenience wrapper: pre-flight checks, build, then publish to PyPI.
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
