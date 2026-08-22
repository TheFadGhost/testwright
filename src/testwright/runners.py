"""Test runner discovery and invocation for target repositories."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .errors import RunnerNotFoundError, TestwrightError
from .exec_env import RunResult, run_command

_PY_RUNNERS = ("pytest", "unittest")
_JS_RUNNERS = ("jest", "vitest", "mocha")


@dataclass
class TestRunner:
    language: str
    name: str  # pytest|unittest|jest|vitest|mocha
    kind: str = "process"

    def describe(self) -> str:
        return f"{self.language}/{self.name}"


def _python_has_module(module: str) -> bool:
    res = run_command(["python", "-c", f"import {module}"], cwd=Path.cwd(), timeout=30)
    return res.ok


def detect_python_runner(root: Path, config: Config) -> TestRunner | None:
    override = config.languages.get("python")
    if override and override.test_command:
        return TestRunner("python", "custom")
    if _python_has_module("pytest"):
        return TestRunner("python", "pytest")
    return TestRunner("python", "unittest")


def detect_js_runner(root: Path, config: Config) -> TestRunner | None:
    pkg_path = root / "package.json"
    if not pkg_path.is_file():
        return None
    try:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    deps: dict[str, str] = {}
    deps.update(pkg.get("dependencies", {}) or {})
    deps.update(pkg.get("devDependencies", {}) or {})
    for runner in _JS_RUNNERS:
        if runner in deps:
            if shutil.which("npx") is None:
                raise RunnerNotFoundError(
                    f"{runner} is declared in package.json but npx was not found",
                    file="package.json",
                    next_step="install Node.js so that npx is on PATH",
                )
            return TestRunner("javascript", runner)
    return None


def detect_runner(root: Path, config: Config, language: str) -> TestRunner | None:
    if language == "python":
        return detect_python_runner(root, config)
    if language == "javascript":
        return detect_js_runner(root, config)
    return None


def require_runner(root: Path, config: Config, language: str) -> TestRunner:
    runner = detect_runner(root, config, language)
    if runner is None:
        if language == "python":
            raise RunnerNotFoundError(
                "could not find a way to run Python tests",
                next_step="install pytest (pip install pytest) or set "
                "[languages.python] test_command in testwright.toml",
            )
        raise RunnerNotFoundError(
            "could not find a JavaScript test runner for this project",
            file="package.json",
            next_step="install jest or vitest as a dev dependency, or set "
            "[languages.javascript] test_command in testwright.toml",
        )
    return runner


def run_python_tests(
    root: Path,
    runner: TestRunner,
    extra_args: list[str] | None = None,
    timeout: float = 120.0,
    coverage: bool = False,
) -> RunResult:
    if runner.name == "custom":
        override = config_override_command(root, "python")
        argv = override + (extra_args or [])
        return run_command(argv, root, timeout=timeout)
    if runner.name == "pytest":
        argv = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        if coverage:
            argv = ["python", "-m", "coverage", "run", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        argv += extra_args or []
        return run_command(argv, root, timeout=timeout)
    # unittest: discover from the repo
    argv = ["python", "-m", "unittest", "discover", "-q"]
    if coverage:
        argv = ["python", "-m", "coverage", "run", "-m", "unittest", "discover", "-q"]
    return run_command(argv, root, timeout=timeout)


def run_js_tests(root: Path, runner: TestRunner, timeout: float = 120.0) -> RunResult:
    if runner.name == "custom":
        override = config_override_command(root, "javascript")
        return run_command(override, root, timeout=timeout)
    if runner.name == "jest":
        return run_command(["npx.cmd" if needs_cmd() else "npx", "jest", "--ci", "--silent"], root, timeout=timeout)
    if runner.name == "vitest":
        return run_command(["npx.cmd" if needs_cmd() else "npx", "vitest", "run", "--silent"], root, timeout=timeout)
    return run_command(["npx.cmd" if needs_cmd() else "npx", "mocha"], root, timeout=timeout)


def needs_cmd() -> bool:
    import sys

    return sys.platform == "win32"


def config_override_command(root: Path, language: str) -> list[str]:
    from .config import load_config

    conf = load_config(root)
    lang_cfg = conf.languages.get(language)
    cmd = lang_cfg.test_command if lang_cfg else None
    if not cmd:
        raise RunnerNotFoundError(f"no test_command configured for {language}")
    import shlex

    return shlex.split(cmd, posix=False)


PYTEST_SUMMARY = re.compile(r"(\d+) passed")


def pytest_passed_count(result: RunResult) -> int | None:
    m = PYTEST_SUMMARY.search(result.stdout)
    return int(m.group(1)) if m else None


def unittest_counts(result: RunResult) -> tuple[int, int]:
    """(ran, bad) from a unittest bootstrap JSON line."""
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
                return int(data.get("ran", 0)), int(data.get("bad", 1))
            except json.JSONDecodeError:
                continue
    return 0, 1
