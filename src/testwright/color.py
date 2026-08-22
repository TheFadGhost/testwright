"""Colour handling: one token table, applied centrally.

Colour is enabled only when stdout is a TTY, NO_COLOR is unset, and --no-color
was not passed. Only the standard 16-colour codes from DESIGN.md are used. No
module other than this one emits ANSI escapes.
"""

from __future__ import annotations

import os
import sys

RESET = "\x1b[0m"

# DESIGN.md token table: token -> (dark theme code, light theme code)
_TOKENS = {
    "accent": ("36", "34"),
    "success": ("32", "32"),
    "warning": ("33", "33"),
    "error": ("31", "31"),
    "muted": ("37", "30"),
}

_theme = "dark"
_enabled = False


def configure(no_color_flag: bool = False, force_tty: bool | None = None) -> None:
    """Decide whether colour is on, and which theme to use."""
    global _enabled, _theme
    if no_color_flag or "NO_COLOR" in os.environ:
        _enabled = False
        return
    stream = sys.stdout
    tty = force_tty if force_tty is not None else stream.isatty()
    _enabled = bool(tty) and hasattr(stream, "isatty")
    if not _enabled:
        return
    term = os.environ.get("TERM", "")
    # Light-terminal heuristic: common light-background TERM variants and the
    # COLORFGBG convention used by several terminal emulators.
    colorfgbg = os.environ.get("COLORFGBG", "")
    if colorfgbg:
        try:
            bg = int(colorfgbg.split(";")[-1])
            _theme = "light" if bg in (6, 7) else "dark"
        except ValueError:
            _theme = "dark"
    elif term.endswith("-m") or "light" in term:
        _theme = "light"


def enabled() -> bool:
    return _enabled


def paint(token: str, text: str) -> str:
    """Wrap text in the token's escape when colour is on; identity otherwise."""
    if not _enabled or token not in _TOKENS:
        return text
    idx = 0 if _theme == "dark" else 1
    return f"\x1b[{_TOKENS[token][idx]}m{text}{RESET}"


def accent(t: str) -> str:
    return paint("accent", t)


def success(t: str) -> str:
    return paint("success", t)


def warning(t: str) -> str:
    return paint("warning", t)


def error(t: str) -> str:
    return paint("error", t)


def muted(t: str) -> str:
    return paint("muted", t)
