"""Generation backends.

A backend turns FunctionInfo objects into candidate tests. Every candidate
must still survive the verification loop downstream; backends cannot bypass it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class CandidateTest:
    name: str
    code: str
    function_id: str
    mutation_validated: bool = False


@dataclass
class GenerationUnit:
    """Everything needed to render one new test module."""

    target_file: str
    test_file: str
    language: str
    framework: str
    header_lines: list[str] = field(default_factory=list)
    tests: list[CandidateTest] = field(default_factory=list)

    def render(self) -> str:
        parts: list[str] = []
        parts.extend(self.header_lines)
        body = "\n\n\n".join(t.code.rstrip() for t in self.tests)
        head = "\n".join(parts).rstrip("\n")
        if head:
            return head + "\n\n\n" + body + "\n"
        return body + "\n"


class GeneratorBackend(ABC):
    """Produces GenerationUnits for ranked targets.

    Implementations receive the analyzed model plus per-function probe results
    (when execution was granted) and emit candidate tests for the chosen
    framework. Backends never write files; the pipeline does that after
    verification.
    """

    name: str = "backend"

    @abstractmethod
    def generate(
        self,
        model,
        conventions,
        targets: list,
        probes: dict,
    ) -> list[GenerationUnit]:
        ...
