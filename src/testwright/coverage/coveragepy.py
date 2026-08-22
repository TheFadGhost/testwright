"""coverage.py JSON parser: executed/missing line lists per file."""

from __future__ import annotations

from pathlib import Path

from . import FileCoverage, CoverageReport, normalize_path


def parse(payload: dict, report_path: Path, root: Path) -> CoverageReport:
    """Parse a decoded coverage.py JSON *payload*; tolerates missing keys."""
    files_section = payload.get("files")
    if not isinstance(files_section, dict):
        files_section = {}
    files: dict[str, FileCoverage] = {}
    for raw, info in files_section.items():
        if not isinstance(info, dict):
            info = {}
        rel = normalize_path(str(raw), root)
        files[rel] = FileCoverage(
            file=rel,
            lines_covered=_line_set(info.get("executed_lines")),
            lines_missing=_line_set(info.get("missing_lines")),
            format="coveragepy",
        )
    return CoverageReport(files=files, source_format="coveragepy")


def _line_set(value: object) -> set[int]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, int) and not isinstance(item, bool)}
