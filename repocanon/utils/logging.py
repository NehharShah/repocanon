"""Centralized Rich-based console for all CLI output."""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

_THEME = Theme(
    {
        "info": "cyan",
        "muted": "dim",
        "ok": "green",
        "warn": "yellow",
        "err": "bold red",
        "title": "bold",
    }
)

console: Console = Console(theme=_THEME, highlight=False)
err_console: Console = Console(theme=_THEME, stderr=True, highlight=False)


def info(msg: str) -> None:
    console.print(f"[info]·[/info] {msg}")


def ok(msg: str) -> None:
    console.print(f"[ok]✓[/ok] {msg}")


def warn(msg: str) -> None:
    err_console.print(f"[warn]![/warn] {msg}")


def error(msg: str) -> None:
    err_console.print(f"[err]✗[/err] {msg}")
