"""Honest progress reporting.

Phases with unknown duration print a single line. Once a count is known, items
print as ``[i/n] subject``. No percentage bars, nothing that can stall at 99%.
In non-TTY mode only phase completions are printed.
"""

from __future__ import annotations

import sys

from . import color


class Progress:
    def __init__(self, quiet: bool = False, verbose: bool = False) -> None:
        self.quiet = quiet
        self.verbose = verbose
        self._stream = sys.stderr
        self._last_was_item = False

    def phase(self, message: str) -> None:
        if self.quiet:
            return
        if self._last_was_item:
            self._stream.write("\n")
        self._stream.write(color.accent(message) + "\n")
        self._last_was_item = False

    def item(self, index: int, total: int, subject: str) -> None:
        if self.quiet or not self.verbose:
            return
        self._stream.write(f"[{index}/{total}] {subject}\n")
        self._last_was_item = True

    def line(self, message: str) -> None:
        if self.quiet:
            return
        if self._last_was_item:
            self._stream.write("\n")
            self._last_was_item = False
        self._stream.write(message + "\n")

    def detail(self, message: str) -> None:
        if self.quiet or not self.verbose:
            return
        self._stream.write(color.muted(f"  {message}") + "\n")
