"""Allow ``python -m repocanon ...`` to run the CLI."""

from repocanon.cli import app

if __name__ == "__main__":  # pragma: no cover
    app()
