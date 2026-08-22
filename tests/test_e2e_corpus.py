"""End-to-end runs over the committed corpus, including write + rerun."""

import json
import shutil
import subprocess
import os
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "repos"
SRC = Path(__file__).resolve().parents[1] / "src"


def _env():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    return env


def _tw(*args: str, timeout: int = 420):
    return subprocess.run(
        ["python", "-m", "testwright", *args],
        capture_output=True, text=True, env=_env(), timeout=timeout,
    )


def test_py_pytest_app_write_then_suite_passes(tmp_path: Path):
    root = tmp_path / "app"
    shutil.copytree(FIXTURES / "py_pytest_app", root)
    before = subprocess.run(
        ["python", "-m", "pytest", "-q"], cwd=str(root),
        capture_output=True, text=True, timeout=180,
    )
    assert before.returncode == 0
    res = _tw("generate", str(root), "--execute", "--write", "--json")
    assert res.returncode == 0, res.stderr
    doc = json.loads(res.stdout)
    assert doc["schema"] == "testwright.report/1"
    assert doc["counts"]["tests_generated"] >= 3
    assert doc["counts"]["tests_discarded"] >= 0
    for g in doc["generated"]:
        assert (root / g["file"]).exists()
    after = subprocess.run(
        ["python", "-m", "pytest", "-q", "--tb=short"], cwd=str(root),
        capture_output=True, text=True, timeout=180,
    )
    assert after.returncode == 0, after.stdout
    # every generated test ran: count grew by the number generated
    def passed(out: str) -> int:
        for line in out.splitlines():
            if " passed" in line:
                return int(line.strip().split()[0])
        return -1

    assert passed(after.stdout) == passed(before.stdout) + doc["counts"]["tests_generated"]
    manifest = root / ".testwright-manifest.json"
    assert manifest.exists()
    listed = json.loads(manifest.read_text(encoding="utf-8"))["written"]
    assert sorted(listed) == sorted(g["file"] for g in doc["generated"])
    clean = _tw("clean", str(root), "--json")
    assert clean.returncode == 0
    assert not any((root / f).exists() for f in listed)


def test_scan_json_schema_stable(tmp_path: Path):
    root = tmp_path / "app"
    shutil.copytree(FIXTURES / "py_unittest_app", root)
    res = _tw("scan", str(root), "--json")
    assert res.returncode == 0, res.stderr
    doc = json.loads(res.stdout)
    assert doc["schema"] == "testwright.scan/1"
    assert {"framework", "layout"} <= set(doc["conventions"])
    for t in doc["targets"]:
        assert {"id", "score", "components"} <= set(t)
