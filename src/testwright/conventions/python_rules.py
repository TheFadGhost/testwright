"""Python convention rules: pytest/unittest frameworks, layout, fixtures."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from ..fsutil import read_text
from ..model import CodeModel
from . import Conventions

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tmp", ".tox"}
EXCLUDED_PATH_PARTS = {"site-packages", "node_modules", ".venv", "venv", "dist", "build"}

TEST_NAME_PATTERNS = ("test_*.py", "*_test.py")
TEST_DIR_NAMES = {"tests", "test"}

_ASSERT_CALL_RE = re.compile(r"\bself\.assert\w+\s*\(")
_SETUP_TEARDOWN_RE = re.compile(r"^\s*def\s+(setUp|tearDown|setUpClass|tearDownClass)\s*\(", re.MULTILINE)
_TEST_FUNC_RE = re.compile(r"^\s*def\s+(?:test_\w+|\w+_test)\s*\(", re.MULTILINE)
_PLAIN_ASSERT_RE = re.compile(r"^\s*assert\s+", re.MULTILINE)


def is_test_path(rel_posix: str) -> bool:
    """True when *rel_posix* looks like a Python test file location."""
    parts = rel_posix.split("/")
    if not parts[-1].endswith(".py"):
        return False
    if any(part in EXCLUDED_PATH_PARTS for part in parts):
        return False
    if any(fnmatch.fnmatch(parts[-1], pat) for pat in TEST_NAME_PATTERNS):
        return True
    return any(part in TEST_DIR_NAMES for part in parts[:-1])


def _base_stem(test_rel: str) -> str:
    name = test_rel.rsplit("/", 1)[-1]
    stem = name[: -len(".py")]
    if stem.startswith("test_"):
        return stem[len("test_") :]
    if stem.endswith("_test"):
        return stem[: -len("_test")]
    return stem


def _find_test_files(root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in sorted(os.walk(root)):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fname in sorted(filenames):
            p = Path(dirpath) / fname
            rel = p.relative_to(root).as_posix()
            if is_test_path(rel):
                found.append(rel)
    return found


def _pytest_config_present(root: Path) -> bool:
    if (root / "pytest.ini").is_file():
        return True
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and "[tool.pytest.ini_options]" in read_text(pyproject):
        return True
    setup_cfg = root / "setup.cfg"
    if setup_cfg.is_file() and "[tool:pytest]" in read_text(setup_cfg):
        return True
    return False


def _source_stems_by_dir(model: CodeModel) -> dict[tuple[str, ...], set[str]]:
    out: dict[tuple[str, ...], set[str]] = {}
    for mod in model.modules.values():
        if mod.language != "python":
            continue
        parts = tuple(mod.file.split("/"))
        if is_test_path(mod.file):
            continue
        out.setdefault(parts[:-1], set()).add(parts[-1][: -len(".py")])
    return out


def _classify_layout(
    test_files: list[str],
    sources: dict[tuple[str, ...], set[str]],
) -> tuple[str, str]:
    """Return (layout, pattern) inferred from where test files sit vs sources."""
    adjacent: list[tuple[str, bool]] = []  # (rel, uses_trailing _test suffix)
    nested_mirrored: list[str] = []
    flat_tests: list[str] = []

    def _tests_root(parent_parts: list[str]) -> int | None:
        for i, part in enumerate(parent_parts):
            if part in TEST_DIR_NAMES:
                return i
        return None

    for rel in test_files:
        parts = rel.split("/")
        parent = parts[:-1]
        base = _base_stem(rel)
        if base in sources.get(tuple(parent), set()):
            adjacent.append((rel, rel.endswith("_test.py")))
            continue
        idx = _tests_root(parent)
        if idx is None:
            continue  # test-named file outside any tests dir; ignore for layout
        if len(parent) - 1 > idx and tuple(parent[idx + 1 :]) in sources:
            nested_mirrored.append(rel)
        else:
            flat_tests.append(rel)

    if adjacent:
        pattern = (
            "{dir}/{stem}_test.py"
            if any(suffix for _, suffix in adjacent)
            else "{dir}/test_{stem}.py"
        )
        return "adjacent", pattern
    if nested_mirrored:
        root_name = nested_mirrored[0].split("/")[_tests_root(nested_mirrored[0].split("/")[:-1])]
        return "mirrored", f"{root_name}/{{parent_dirs}}/test_{{stem}}.py"
    if flat_tests:
        parts = flat_tests[0].split("/")
        root_name = parts[0] if parts[0] in TEST_DIR_NAMES else parts[_tests_root(parts[:-1])]
        return "mirrored", f"{root_name}/test_{{stem}}.py"
    return "unknown", ""


def detect_python(root: Path, model: CodeModel) -> Conventions:
    """Detect conventions from existing Python test files and config."""
    evidence: list[str] = []
    test_files = _find_test_files(root)

    imports_pytest = False
    uses_unittest = False
    has_assert_method_calls = False
    has_plain_assert = False
    has_fixture_decorator = False
    has_setup_methods = False

    for rel in test_files:
        try:
            text = read_text(root / rel)
        except OSError:
            continue
        if re.search(r"^\s*import pytest\b|^\s*from pytest\b", text, re.MULTILINE):
            imports_pytest = True
        if re.search(r"^\s*import unittest\b|^\s*from unittest\b", text, re.MULTILINE):
            uses_unittest = True
        if re.search(r"class\s+\w+\s*\([^)]*TestCase\)", text):
            uses_unittest = True
        if _ASSERT_CALL_RE.search(text):
            has_assert_method_calls = True
        if _TEST_FUNC_RE.search(text) and _PLAIN_ASSERT_RE.search(text):
            has_plain_assert = True
        if "@pytest.fixture" in text or "pytest.fixture(" in text:
            has_fixture_decorator = True
        if _SETUP_TEARDOWN_RE.search(text):
            has_setup_methods = True
        if "pytest.raises" in text:
            evidence.append(f"found {rel} using pytest.raises")

    framework: str | None = None
    config_present = _pytest_config_present(root)
    if imports_pytest:
        framework = "pytest"
        evidence.append("test files import pytest directly")
    elif uses_unittest:
        framework = "unittest"
        evidence.append("test files subclass TestCase / import unittest")
    elif has_plain_assert and config_present:
        framework = "pytest"
        evidence.append("plain asserts in test functions plus pytest configuration")
    elif has_plain_assert:
        framework = None
        evidence.append("plain asserts found but no pytest or unittest signals")

    layout, pattern = _classify_layout(test_files, _source_stems_by_dir(model))
    if test_files:
        for rel in test_files[:3]:
            evidence.append(f"found {rel}")
        if layout == "adjacent":
            evidence.append("test files sit next to their sources")
        elif layout == "mirrored":
            evidence.append("test files live in a tests/ directory")

    if has_assert_method_calls:
        assertion_style = "unittest_assert"
    elif has_plain_assert:
        assertion_style = "plain_assert"
    else:
        assertion_style = "none"

    if has_fixture_decorator:
        fixture_style = "fixtures"
    elif has_setup_methods:
        fixture_style = "setup_methods"
    else:
        fixture_style = "none"

    if not test_files:
        evidence.append("no existing python test files found; defaults assumed")

    return Conventions(
        language="python",
        framework=framework,
        layout=layout,
        test_file_pattern=pattern or "tests/test_{stem}.py",
        assertion_style=assertion_style,
        fixture_style=fixture_style,
        name_style="snake_case",
        evidence=evidence,
    )
