"""JavaScript corpus end-to-end (skipped when jest is not installed)."""

import json
import shutil
import subprocess
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "repos"
SRC = Path(__file__).resolve().parents[1] / "src"


def _env():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    return env


def jest_available() -> bool:
    pkg = FIXTURES / "js_jest_app" / "node_modules" / "jest"
    return pkg.exists()


@pytest.mark.skipif(not jest_available(), reason="jest not installed for corpus")
def test_js_jest_app_write_then_suite_passes(tmp_path: Path):
    root = tmp_path / "app"
    shutil.copytree(FIXTURES / "js_jest_app", root)
    res = subprocess.run(
        ["python", "-m", "testwright", "generate", str(root),
         "--execute", "--write", "--json"],
        capture_output=True, text=True, env=_env(), timeout=600,
    )
    assert res.returncode == 0, res.stderr
    doc = json.loads(res.stdout)
    js_units = [g for g in doc["generated"] if g["language"] == "javascript"]
    assert js_units, json.dumps(doc["discarded"], indent=2)
    after = subprocess.run(
        ["npx.cmd" if os.name == "nt" else "npx", "jest", "--silent"],
        cwd=str(root), capture_output=True, text=True, timeout=300,
    )
    assert after.returncode == 0, after.stdout + after.stderr
