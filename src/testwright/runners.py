"""Test runner discovery for target repositories."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .errors import RunnerNotFoundError, TestwrightError
from .exec_env import run_command


@dataclass
class TestRunner:
    language: str
    name: str  # pytest|unittest|jest|vitest|mocha


def _python_has_module(module: str) -> bool:
    res = run_command([sys.executable, "-c", f"import {module}"], Path.cwd(), timeout=30)
    return res.ok


def detect_python_runner(root: Path, config: Config) -> TestRunner | None:
    override = config.languages.get("python")
    if override and override.test_command:
        return TestRunner("python", "custom")
    if _python_has_module("pytest"):
        return TestRunner("python", "pytest")
    return TestRunner("python", "unittest")


def require_python_runner(root: Path, config: Config) -> TestRunner:
    runner = detect_python_runner(root, config)
    if runner is None:
        raise RunnerNotFoundError(
            "could not find a way to run Python tests",
            next_step="install pytest (pip install pytest) or set "
            "[languages.python] test_command in testwright.toml",
        )
    return runner


def config_override_command(root: Path, language: str) -> list[str]:
    from .config import load_config

    conf = load_config(root)
    lang_cfg = conf.languages.get(language)
    cmd = lang_cfg.test_command if lang_cfg else None
    if not cmd:
        raise RunnerNotFoundError(
            f"no test_command configured for {language}",
            next_step="set [languages." + language + "] test_command in testwright.toml",
        )
    import shlex

    return shlex.split(cmd, posix=False)


def target_python() -> str:
    """Interpreter used to execute target-project code (probes, bootstrap)."""
    return sys.executable
