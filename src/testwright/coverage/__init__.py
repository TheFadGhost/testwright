"""Coverage ingestion: third-party reports mapped onto the target tree.

Parses lcov, cobertura XML, and coverage.py JSON, normalizes every file path
onto the repository, and answers which lines and functions went untested.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..errors import TestwrightError, UsageError
from ..fsutil import read_text, to_posix
from ..model import CodeModel


@dataclass
class FileCoverage:
    """Line-level coverage for one file of a report."""

    file: str  # posix path relative to the target root
    lines_covered: set[int]
    lines_missing: set[int]
    format: str  # "lcov" | "cobertura" | "coveragepy"


@dataclass
class CoverageReport:
    """All covered files of one report, keyed by normalized posix path."""

    files: dict[str, FileCoverage]
    source_format: str


def parse_coverage(path: Path, root: Path) -> CoverageReport:
    """Sniff the format of the report at *path* and parse it against *root*."""
    text = read_text(path)
    head = text.lstrip().lower()
    if head.startswith("sf:"):
        return lcov.parse(text, path, root)
    if head.startswith(("<?xml", "<coverage")) and "cobertura" in head:
        return cobertura.parse(text, path, root)
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("files"), dict):
        return coveragepy.parse(payload, path, root)
    raise UsageError(
        f"could not recognize the coverage report format: {to_posix(path)}",
        file=str(path),
        next_step=(
            "export coverage in a supported format: lcov (coverage lcov), "
            "cobertura XML (coverage xml), or coverage.py JSON (coverage json)"
        ),
    )


def normalize_path(raw: str, root: Path) -> str:
    """Map a report's raw path onto a posix path under *root*; never raises."""
    text = to_posix(raw)
    if not text:
        return text
    exact = _exact_relpath(raw, root)
    if exact is not None:
        return exact
    parts = [p for p in text.split("/") if p not in ("", ".")]
    for i, part in enumerate(parts):
        if len(part) == 2 and part[1] == ":":
            continue
        suffix = "/".join(parts[i:])
        if not suffix or Path(suffix).is_absolute() or ".." in suffix.split("/"):
            continue
        if (root / suffix).exists():
            return suffix
    return text.lstrip("/")


def _exact_relpath(raw: str, root: Path) -> str | None:
    try:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / candidate
        rel = candidate.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return to_posix(rel)


def uncovered_lines(report: CoverageReport, rel_file: str) -> set[int]:
    """Missing line numbers for *rel_file*; empty set when the file is absent."""
    entry = report.files.get(to_posix(rel_file))
    return set(entry.lines_missing) if entry else set()


def function_coverage(model: CodeModel, report: CoverageReport) -> dict[str, float]:
    """Fraction of each function's body lines marked covered; 0.0 if unknown."""
    out: dict[str, float] = {}
    for func in model.functions:
        entry = report.files.get(func.file)
        span = func.end_line - func.line + 1
        if entry is None or span <= 0:
            out[func.id] = 0.0
            continue
        hits = sum(1 for n in entry.lines_covered if func.line <= n <= func.end_line)
        out[func.id] = hits / span
    return out


def untested_functions(model: CodeModel, report: CoverageReport) -> list[str]:
    """Ids of functions with zero covered lines inside their body range."""
    return [
        fid
        for fid, fraction in function_coverage(model, report).items()
        if fraction == 0.0
    ]


from . import cobertura  # noqa: E402
from . import coveragepy  # noqa: E402
from . import lcov  # noqa: E402
