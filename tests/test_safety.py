"""Safety guarantees: no modification of existing files, dry-run, sandbox."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from testwright.config import Config
from testwright.safety import hash_tree, diff_trees, WriteGuard
from testwright.fsutil import write_new_file
from testwright.errors import SafetyViolation
from testwright.exec_env import run_command

REPO = Path(__file__).parent / "fixtures" / "repos" / "py_pytest_app"
TOOL = ["python", "-m", "testwright"]


def _env():
    env_path = Path(__file__).resolve().parents[1] / "src"
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(env_path)
    return env


def tree_snapshot(root: Path):
    return hash_tree(root)


def test_write_new_file_refuses_overwrite(tmp_path: Path):
    f = tmp_path / "x.txt"
    write_new_file(f, "one")
    try:
        write_new_file(f, "two")
    except SafetyViolation:
        pass
    else:
        raise AssertionError("overwrite was allowed")
    assert f.read_text(encoding="utf-8") == "one"


def test_diff_trees_reports_changes(tmp_path: Path):
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    before = hash_tree(tmp_path)
    (tmp_path / "a.txt").write_text("2", encoding="utf-8")
    (tmp_path / "b.txt").write_text("new", encoding="utf-8")
    after = hash_tree(tmp_path)
    modified, added = diff_trees(before, after)
    assert modified == ["a.txt"] and added == ["b.txt"]


def test_generate_without_execute_writes_nothing_and_changes_nothing():
    before = tree_snapshot(REPO)
    res = subprocess.run(
        TOOL + ["generate", str(REPO)],
        capture_output=True, text=True, env=_env(), timeout=180,
    )
    assert res.returncode == 0, res.stderr
    after = tree_snapshot(REPO)
    modified, added = diff_trees(before, after)
    assert not modified and not added
    assert "preview only" in res.stdout


def test_dry_run_with_execute_writes_nothing_but_verifies():
    before = tree_snapshot(REPO)
    res = subprocess.run(
        TOOL + ["generate", str(REPO), "--execute", "--top", "3"],
        capture_output=True, text=True, env=_env(), timeout=300,
    )
    assert res.returncode == 0, res.stderr
    after = tree_snapshot(REPO)
    modified, added = diff_trees(before, after)
    assert not modified and not added
    assert "nothing was written" in res.stdout
    assert "Generated" in res.stdout


def test_error_paths_leave_target_untouched(tmp_path: Path):
    broken = tmp_path / "broken_repo"
    (broken / "pkg").mkdir(parents=True)
    (broken / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (broken / "pkg" / "mod.py").write_text("def oops(:\n", encoding="utf-8")  # syntax error
    before = tree_snapshot(broken)
    res = subprocess.run(
        TOOL + ["scan", str(broken), "-v"],
        capture_output=True, text=True, env=_env(), timeout=120,
    )
    after = tree_snapshot(broken)
    modified, added = diff_trees(before, after)
    assert not modified and not added
    assert res.returncode in (0, 1)


def test_sandbox_timeout_kills_runaway_process(tmp_path: Path):
    script = tmp_path / "forever.py"
    script.write_text("import time\nwhile True:\n    time.sleep(0.1)\n", encoding="utf-8")
    res = run_command(["python", str(script)], tmp_path, timeout=2.0)
    assert res.timed_out and not res.ok
