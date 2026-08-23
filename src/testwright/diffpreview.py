"""Unified diff preview rendering with markers that survive without colour."""

from __future__ import annotations

import difflib

from . import color


def render_diff(rel_path: str, content: str, context: int = 3) -> str:
    """A new file rendered as a fully-added unified diff."""
    lines = content.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    diff = difflib.unified_diff(
        [],
        lines,
        fromfile="/dev/null",
        tofile=f"b/{rel_path}",
        n=context,
        lineterm="",
    )
    out_lines = list(diff)
    rendered: list[str] = []
    for line in out_lines:
        text = line.rstrip("\n")
        if text.startswith("+") and not text.startswith("+++"):
            rendered.append(color.success(text))
        elif text.startswith("-") and not text.startswith("---"):
            rendered.append(color.error(text))
        elif text.startswith("@@"):
            rendered.append(color.accent(text))
        else:
            rendered.append(text)
    return "\n".join(rendered)
