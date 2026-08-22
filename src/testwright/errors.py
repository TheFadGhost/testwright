"""Testwright error hierarchy and the standard error shape.

Every user-facing failure raises a TestwrightError carrying an actionable next
step. The CLI renders these in the DESIGN.md error shape:

    error: <message>
      file: <path>          (when applicable)
      function: <name>      (when applicable)
      next step: <instruction>
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TestwrightError(Exception):
    message: str
    file: str | None = None
    function: str | None = None
    next_step: str | None = None
    hint: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def render(self) -> str:
        lines = [f"error: {self.message}"]
        if self.file:
            lines.append(f"  file: {self.file}")
        if self.function:
            lines.append(f"  function: {self.function}")
        for h in self.hint:
            lines.append(f"  {h}")
        if self.next_step:
            lines.append(f"  next step: {self.next_step}")
        return "\n".join(lines)


class UsageError(TestwrightError):
    """Bad flags, bad config, bad paths. Exit code 1."""


class TargetError(TestwrightError):
    """The target repository cannot be processed as asked. Exit code 2."""


class RunnerNotFoundError(TargetError):
    """No test runner could be located or inferred."""


class SafetyViolation(TestwrightError):
    """An operation would modify something it must not."""
