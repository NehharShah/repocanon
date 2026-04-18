.PHONY: install dev test lint typecheck

install:
	python -m pip install -e ".[dev]"

dev:
	uvicorn app.main:app --reload

test:
	pytest

lint:
	ruff check app tests

typecheck:
	mypy app
