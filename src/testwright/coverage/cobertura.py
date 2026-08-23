"""Cobertura XML parser: per-class line hits with filename reconstruction."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ..errors import UsageError
from . import FileCoverage, CoverageReport, normalize_path


def parse(text: str, report_path: Path, root: Path) -> CoverageReport:
    """Parse cobertura *text* into a report rooted at *root*."""
    try:
        tree = ET.fromstring(text)
    except ET.ParseError as exc:
        raise UsageError(
            f"malformed cobertura XML: {exc}",
            file=str(report_path),
            next_step="regenerate the report; it is truncated or not well-formed XML",
        ) from exc

    source = _source_dir(tree)
    files: dict[str, FileCoverage] = {}
    for cls, package in _classes_with_packages(tree):
        raw = cls.get("filename") or _construct_filename(cls, package, source)
        if not raw:
            continue
        rel = normalize_path(raw, root)
        entry = files.setdefault(
            rel,
            FileCoverage(
                file=rel,
                lines_covered=set(),
                lines_missing=set(),
                format="cobertura",
            ),
        )
        for line_el in cls.iter("line"):
            number = _int_attr(line_el, "number")
            hits = _int_attr(line_el, "hits")
            if number is None or hits is None:
                continue
            if hits > 0:
                entry.lines_covered.add(number)
            else:
                entry.lines_missing.add(number)
    return CoverageReport(files=files, source_format="cobertura")


def _source_dir(tree: ET.Element) -> str:
    sources = tree.find("sources")
    if sources is not None:
        first = sources.find("source")
        if first is not None and first.text and first.text.strip():
            return first.text.strip()
    return ""


def _classes_with_packages(tree: ET.Element) -> list[tuple[ET.Element, str]]:
    pairs: list[tuple[ET.Element, str]] = []
    claimed: set[int] = set()
    for package in tree.iter("package"):
        name = package.get("name") or ""
        for cls in package.iter("class"):
            pairs.append((cls, name))
            claimed.add(id(cls))
    for cls in tree.iter("class"):
        if id(cls) not in claimed:
            pairs.append((cls, ""))
    return pairs


def _construct_filename(cls: ET.Element, package: str, source: str) -> str:
    name = (cls.get("name") or "").strip()
    if not name:
        return ""
    parts: list[str] = []
    if source:
        parts.append(source)
    if package:
        parts.extend(package.split("."))
    parts.append(name.split(".")[0] + ".py")
    return "/".join(parts)


def _int_attr(el: ET.Element, name: str) -> int | None:
    value = el.get(name)
    if value is None:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None
