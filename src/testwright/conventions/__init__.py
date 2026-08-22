"""Project convention detection: how this repository names and writes tests.

Detectors inspect existing test files, config files, and the analyzed
CodeModel to infer framework, layout, assertion style, and naming so that
generated tests blend in with what is already there. Evidence lines record
the human-readable reasons behind every decision.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from pathlib import Path

from ..fsutil import to_posix
from ..model import CodeModel


@dataclass
class Conventions:
    """The inferred testing conventions of a target repository."""

    language: str  # "python"|"javascript"
    framework: str | None = None  # python: "pytest"|"unittest"; js: "jest"|"vitest"|"mocha"|None
    layout: str = "unknown"  # "adjacent"|"mirrored"|"__tests__"|"unknown"
    test_file_pattern: str = ""  # e.g. "tests/test_{stem}.py" or "{dir}/__tests__/{stem}.test.js"
    assertion_style: str = "none"  # "plain_assert"|"unittest_assert"|"chai_expect"|"node_assert"|"none"
    fixture_style: str = "none"  # "fixtures"|"setup_methods"|"before_each"|"none"
    name_style: str = "snake_case"  # "snake_case"|"camelCase"
    evidence: list[str] = field(default_factory=list)


def test_file_path(conv: Conventions, source_rel: str) -> str:
    """Render *conv*'s pattern for a source file's relative posix path."""
    rel = to_posix(source_rel)
    stem = posixpath.basename(rel)
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    parent_dirs = posixpath.dirname(rel)
    out = conv.test_file_pattern
    for token in ("{parent_dirs}", "{dir}"):
        out = out.replace(token, parent_dirs)
    out = out.replace("{stem}", stem)
    return to_posix(posixpath.normpath(out))


def _module_language_counts(model: CodeModel) -> dict[str, int]:
    counts = {"python": 0, "javascript": 0}
    for mod in model.modules.values():
        if mod.language in counts:
            counts[mod.language] += 1
    return counts


def detect(root: Path, model: CodeModel) -> Conventions:
    """Detect conventions for *root*, preferring the language with more modules."""
    from . import js_rules, python_rules  # noqa: PLC0415

    counts = _module_language_counts(model)
    present = [lang for lang, n in counts.items() if n > 0]
    if not present:
        return Conventions(
            language="python",
            evidence=["no analyzable modules in model; defaults assumed"],
        )
    primary = max(present, key=lambda lang: counts[lang])
    results = {
        "python": python_rules.detect_python(root, model) if counts["python"] else None,
        "javascript": (
            js_rules.detect_javascript(root, model)
            if counts["javascript"]
            else None
        ),
    }
    conv = results[primary]
    assert conv is not None
    merged_evidence = list(conv.evidence)
    for lang in present:
        if lang == primary:
            continue
        other = results[lang]
        assert other is not None
        merged_evidence.extend(f"{lang}: {line}" for line in other.evidence)
    conv.evidence = merged_evidence
    return conv
