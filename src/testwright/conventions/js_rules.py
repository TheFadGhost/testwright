"""JavaScript convention rules: jest/vitest/mocha, __tests__ layout, asserts."""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path

from ..fsutil import read_text
from ..model import CodeModel
from . import Conventions

SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".tmp"}

TEST_NAME_PATTERNS = (
    "*.test.js",
    "*.spec.js",
    "*.test.jsx",
    "*.spec.jsx",
    "*.test.ts",
    "*.spec.ts",
    "*.test.tsx",
    "*.spec.tsx",
    "*.test.mjs",
    "*.test.cjs",
)

_FRAMEWORK_PRIORITY = ("jest", "vitest", "mocha")


def _nearest_package_json(start: Path) -> Path | None:
    for cand in (start, *start.parents):
        candidate = cand / "package.json"
        if candidate.is_file():
            return candidate
    return None


def _framework_from_package_json(pj_path: Path) -> str | None:
    try:
        data = json.loads(read_text(pj_path))
    except (OSError, ValueError):
        return None
    deps: set[str] = set()
    for section in ("devDependencies", "dependencies"):
        deps.update(data.get(section, {}).keys())
    for framework in _FRAMEWORK_PRIORITY:
        # exact dependency names only: substring matches would let packages
        # like esbuild-jest masquerade as the project's runner
        if framework in deps:
            return framework
    return None


def _framework_from_config_files(root: Path) -> str | None:
    checks = {
        "jest": ("jest.config.js", "jest.config.ts", "jest.config.mjs", "jest.config.cjs"),
        "vitest": ("vitest.config.ts", "vitest.config.js", "vitest.config.mts"),
    }
    for framework, names in checks.items():
        if any((root / name).is_file() for name in names):
            return framework
    return None


def _find_test_files(root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in sorted(os.walk(root)):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fname in sorted(filenames):
            if fnmatch.fnmatch(fname, "*.test.*") or fnmatch.fnmatch(fname, "*.spec.*"):
                rel = (Path(dirpath) / fname).relative_to(root).as_posix()
                if any(fnmatch.fnmatch(fname, pat) for pat in TEST_NAME_PATTERNS):
                    found.append(rel)
    return found


def _suffix_ext(test_rel: str) -> str:
    """Tail of a test filename after the stem: 'math.test.js' -> '.test.js'."""
    name = test_rel.rsplit("/", 1)[-1]
    return name[name.index(".") :]


def detect_javascript(root: Path, model: CodeModel) -> Conventions:
    """Detect conventions from package.json, config files, and existing tests."""
    evidence: list[str] = []

    pj = _nearest_package_json(root)
    framework: str | None = None
    if pj is not None:
        rel_pj = pj.relative_to(root).as_posix() if pj.is_relative_to(root) else pj.name
        evidence.append(f"found {rel_pj}")
        framework = _framework_from_package_json(pj)
        if framework:
            evidence.append(f"{framework} present in package.json dependencies")
    else:
        evidence.append("no package.json found walking up from target root")

    if framework is None:
        framework = _framework_from_config_files(root)
        if framework:
            evidence.append(f"{framework} configuration file at project root")

    test_files = _find_test_files(root)
    uses_expect = False
    uses_node_assert = False
    uses_before_each = False
    tests_dir_files: list[str] = []
    adjacent_files: list[str] = []

    for rel in test_files:
        text = read_text(root / rel)
        if "expect(" in text:
            uses_expect = True
        if (
            "require('assert')" in text
            or 'require("assert")' in text
            or "import assert" in text
            or 'from "assert"' in text
            or "from 'assert'" in text
        ):
            uses_node_assert = True
        if "beforeEach(" in text:
            uses_before_each = True
        parts = rel.split("/")
        if "__tests__" in parts[:-1]:
            tests_dir_files.append(rel)
        else:
            adjacent_files.append(rel)

    layout = "__tests__" if tests_dir_files else ("adjacent" if adjacent_files else "unknown")
    pattern = ""
    if tests_dir_files:
        first = tests_dir_files[0]
        parent = "/".join(first.split("/")[:-2])
        pattern = "{dir}/__tests__/{stem}" + _suffix_ext(first)
        evidence.append(
            f"{len(tests_dir_files)} test file(s) live in __tests__ directories"
        )
        if parent:
            evidence.append(f"test tree mirrors sources under {parent}")
    elif adjacent_files:
        first = adjacent_files[0]
        parts = first.split("/")
        stem = parts[-1].partition(".")[0]
        source_sibling = any(
            mod.file.rsplit("/", 1)[0] == "/".join(parts[:-1])
            and mod.file.rsplit("/", 1)[-1].partition(".")[0] == stem
            for mod in model.modules.values()
            if mod.language == "javascript"
        )
        if source_sibling:
            layout = "adjacent"
            evidence.append(f"{parts[-1]} sits next to {stem} source using '{_suffix_ext(first)}' naming")
            pattern = "{dir}/{stem}" + _suffix_ext(first)

    for rel in test_files[:3]:
        evidence.append(f"found {rel}")

    if uses_expect:
        assertion_style = "chai_expect"
    elif uses_node_assert:
        assertion_style = "node_assert"
    else:
        assertion_style = "none"

    fixture_style = "before_each" if uses_before_each else "none"

    if not test_files:
        evidence.append("no existing javascript test files found; defaults assumed")

    return Conventions(
        language="javascript",
        framework=framework,
        layout=layout,
        test_file_pattern=pattern or "{dir}/{stem}.test.js",
        assertion_style=assertion_style,
        fixture_style=fixture_style,
        name_style="camelCase",
        evidence=evidence,
    )
