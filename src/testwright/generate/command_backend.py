"""External command generation backend.

Contract for ``backend = "command:<argv>"``:

* The argv template is split with POSIX-style rules (quote-aware) and ``{root}``
  expands to the target repository path. It is executed without a shell.
* On success the command prints exactly one JSON document to stdout:
  ``{"units": [{"test_file": str, "language": str, "framework": str,
  "header_lines": [str], "tests": [{"name": str, "code": str,
  "function_id": str}]}]}``.
* Everything the command emits still passes through the same verification
  loop as the deterministic backend; nothing unverified can be written.

This is the seam for a model-backed generator: point ``command:`` at whatever
produces candidate tests, local or remote, and Testwright will hold it to the
same bar.
"""

from __future__ import annotations

import json
import shlex

from ..errors import TargetError
from ..model import CodeModel, FunctionInfo
from . import CandidateTest, GenerationUnit, GeneratorBackend


class CommandBackend(GeneratorBackend):
    name = "command"

    def __init__(self, template: str) -> None:
        self.template = template

    def generate(self, model: CodeModel, conventions, targets: list, probes: dict | None = None):
        root = model.root
        argv = shlex.split(self.template.replace("{root}", str(root)), posix=False)
        if not argv:
            raise TargetError(
                "empty command backend template",
                next_step='set backend = "command:<your generator command>"',
            )
        from ..exec_env import run_command

        res = run_command(argv, root, timeout=600)
        if res.timed_out:
            raise TargetError(
                "command backend timed out",
                next_step="make the generator finish or raise its timeout",
            )
        if not res.ok:
            raise TargetError(
                f"command backend failed with exit code {res.exit_code}",
                next_step=res.tail(5) or "run the generator manually to see its error",
            )
        try:
            doc = json.loads(res.stdout)
        except json.JSONDecodeError as exc:
            raise TargetError(
                f"command backend printed invalid JSON: {exc}",
                next_step="print one JSON document matching the documented contract",
            ) from exc
        units: list[GenerationUnit] = []
        known_ids = {f.id for f in model.functions}
        for raw in doc.get("units", []):
            tests = []
            for t in raw.get("tests", []):
                fid = t.get("function_id", "")
                if fid and fid not in known_ids:
                    continue  # refuse candidates for functions we never analyzed
                tests.append(
                    CandidateTest(
                        name=str(t.get("name", "")),
                        code=str(t.get("code", "")),
                        function_id=fid,
                    )
                )
            if not tests:
                continue
            units.append(
                GenerationUnit(
                    target_file=str(raw.get("target_file", "")),
                    test_file=str(raw.get("test_file", "test_generated.py")),
                    language=str(raw.get("language", conventions.language or "python")),
                    framework=str(raw.get("framework", conventions.framework or "")),
                    header_lines=[str(h) for h in raw.get("header_lines", [])],
                    tests=tests,
                )
            )
        return units


def parse_backend_spec(spec: str) -> GeneratorBackend | None:
    """'template' -> None (use built-ins); 'command:<argv>' -> CommandBackend."""
    if spec.startswith("command:"):
        return CommandBackend(spec[len("command:") :])
    if spec == "template":
        return None
    raise TargetError(
        f"unknown backend: {spec}",
        next_step='use "template" or "command:<generator command>"',
    )
