"""Text helpers used by generators."""

from __future__ import annotations

from collections.abc import Iterable


def bullet_list(items: Iterable[str], prefix: str = "- ") -> str:
    """Render an iterable as a markdown bullet list, deduped, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        norm = item.strip()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(f"{prefix}{norm}")
    return "\n".join(out)


def section(title: str, body: str, level: int = 2) -> str:
    """Render a markdown section, omitting it entirely when the body is empty."""
    body = body.rstrip()
    if not body:
        return ""
    return f"{'#' * level} {title}\n\n{body}\n"


def join_sections(sections: Iterable[str]) -> str:
    """Join non-empty sections with a single blank line between them."""
    rendered = [s.rstrip() for s in sections if s and s.strip()]
    return "\n\n".join(rendered) + "\n"


def truncate(text: str, limit: int = 240) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
