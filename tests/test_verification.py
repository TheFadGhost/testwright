"""Verification loop and mutation validation behaviour."""

import shutil
from pathlib import Path

import testwright.safety as safety
from testwright.config import Config
from testwright.analyze import build_model
from testwright.conventions import detect
from testwright.prioritize import rank_targets
from testwright.pipeline import (
    run_pipeline,
    verify_candidate,
    validate_with_mutations,
)
from testwright.generate.template_py import PythonTemplateBackend
from testwright.generate.probe import probe_python, synthesize_cases

FIXTURES = Path(__file__).parent / "fixtures" / "repos"


def _prep(tmp_path: Path, name: str = "py_pytest_app") -> Path:
    root = tmp_path / "target"
    shutil.copytree(FIXTURES / name, root)
    return root


def _model(root: Path):
    return build_model(root, Config(root=root))


def _func(model, qual_suffix: str):
    for f in model.functions:
        if f.qualname == qual_suffix:
            return f
    raise AssertionError(f"{qual_suffix} not found")


def test_failing_candidate_is_reported_not_written(tmp_path: Path):
    root = _prep(tmp_path)
    before = safety.hash_tree(root)
    src = 'def test_bad():\n    assert 1 == 2\n'
    ok, detail = verify_candidate(src, "python", "pytest", root, 60.0, tmp_path)
    assert not ok
    after = safety.hash_tree(root)
    assert before == after


def test_passing_candidate_verifies_in_shadow(tmp_path: Path):
    root = _prep(tmp_path)
    src = (
        "from payroll.tax import bracket_rate\n\n\n"
        "def test_boundary():\n"
        "    result = bracket_rate(40000)\n\n"
        "    assert result == 0.15\n"
    )
    ok, detail = verify_candidate(src, "python", "pytest", root, 60.0, tmp_path)
    assert ok, detail


def test_pipeline_discards_weak_and_never_writes(tmp_path: Path):
    root = _prep(tmp_path)
    model = _model(root)
    conv = detect(root, model)
    ranked = rank_targets(model, {}, set())
    before = safety.hash_tree(root)
    result = run_pipeline(
        root, Config(root=root), conv, model, ranked,
        do_execute=True, do_write=False,
    )
    assert result.generated, "expected at least one generated unit on the corpus"
    for d in result.discards:
        assert d.reason
    after = safety.hash_tree(root)
    modified, added = safety.diff_trees(before, after)
    assert not modified and not added


def test_mutation_validation_rejects_insensitive_test(tmp_path: Path):
    root = _prep(tmp_path)
    model = _model(root)
    func = _func(model, "bracket_rate")
    weak = (
        "from payroll.tax import bracket_rate\n\n\n"
        "def test_only_low():\n"
        "    result = bracket_rate(5)\n\n"
        "    assert result == 0.0\n"
    )
    killed, detail = validate_with_mutations(root, func, weak, "pytest", 90.0, tmp_path)
    assert not killed
    strong = (
        "from payroll.tax import bracket_rate\n\n\n"
        "def test_boundaries():\n"
        "    assert bracket_rate(10000) == 0.0\n\n"
        "def test_mid():\n"
        "    assert bracket_rate(10001) == 0.15\n"
    )
    killed2, detail2 = validate_with_mutations(root, func, strong, "pytest", 90.0, tmp_path)
    assert killed2, detail2


def test_unittest_repo_generation_round_trip(tmp_path: Path):
    root = _prep(tmp_path, "py_unittest_app")
    model = _model(root)
    conv = detect(root, model)
    ranked = rank_targets(model, {}, set())
    result = run_pipeline(
        root, Config(root=root), conv, model, ranked,
        do_execute=True, do_write=True,
    )
    assert any(g["framework"] == "unittest" for g in result.generated), (
        result.warnings,
        [(d.name, d.reason) for d in result.discards],
    )
    written = [g["file"] for g in result.generated]
    for rel in written:
        assert (root / rel).exists()
    res = subprocess_run(root)
    assert res.returncode == 0, res.stdout + res.stderr


def subprocess_run(root: Path):
    import subprocess
    import os

    env = dict(os.environ)
    return subprocess.run(
        ["python", "-m", "unittest", "discover", "-q"],
        cwd=str(root), capture_output=True, text=True, env=env, timeout=120,
    )
