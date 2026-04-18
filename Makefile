.PHONY: install dev test lint typecheck format build clean publish-test publish demo

PY ?= python3

install:
	$(PY) -m pip install -e .

dev:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check repocanon tests

format:
	$(PY) -m ruff format repocanon tests
	$(PY) -m ruff check --fix repocanon tests

typecheck:
	$(PY) -m mypy repocanon

build: clean
	$(PY) -m build

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage

publish-test: build
	$(PY) -m twine upload --repository testpypi dist/*

publish: build
	$(PY) -m twine upload dist/*

demo:
	$(PY) -m repocanon analyze .
	$(PY) -m repocanon preview agents .
