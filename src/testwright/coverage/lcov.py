"""LCOV tracefile parser: SF/DA sections, LF and CRLF line endings."""

from __future__ import annotations

from pathlib import Path

from . import FileCoverage, CoverageReport, normalize_path


def parse(text: str, report_path: Path, root: Path) -> CoverageReport:
    """Parse lcov *text*; sections outside *root* are skipped silently."""
    files: dict[str, FileCoverage] = {}
    raw: str | None = None
    covered: set[int] = set()
    missing: set[int] = set()

    def flush() -> None:
        nonlocal raw, covered, missing
        if raw:
            rel = normalize_path(raw, root)
            if rel and (root / rel).exists():
                entry = files.setdefault(
                    rel,
                    FileCoverage(
                        file=rel,
                        lines_covered=set(),
                        lines_missing=set(),
                        format="lcov",
                    ),
                )
                entry.lines_covered |= covered
                entry.lines_missing |= missing
        raw = None
        covered = set()
        missing = set()

    for line in text.splitlines():
        if line.startswith("SF:"):
            flush()
            raw = line[len("SF:") :].strip()
        elif line.startswith("DA:") and raw:
            fields = line[len("DA:") :].split(",")
            if len(fields) < 2:
                continue
            try:
                lineno = int(fields[0].strip())
                hits = int(fields[1].strip())
            except ValueError:
                continue
            (covered if hits > 0 else missing).add(lineno)
        elif line.strip() == "end_of_record":
            flush()
    flush()
    return CoverageReport(files=files, source_format="lcov")
