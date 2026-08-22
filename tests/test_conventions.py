"""Convention detection against fixture repositories."""

import shutil
from pathlib import Path

from testwright.analyze import build_model
from testwright.config import Config, load_config
from testwright.conventions import Conventions, detect
from testwright.conventions import test_file_path as render_test_path

FIXTURES = Path(__file__).parent / "fixtures" / "repos"


def model_for(root: Path):
    cfg = Config(root=root)
    return build_model(root, cfg)


def test_pytest_repo_conventions():
    root = FIXTURES / "py_pytest_app"
    conv = detect(root, model_for(root))
    assert conv.language == "python"
    assert conv.framework == "pytest"
    assert conv.layout == "mirrored" or conv.test_file_pattern.startswith("tests/")
    assert conv.assertion_style == "plain_assert"
    assert conv.fixture_style == "fixtures"
    assert any("pytest" in e for e in conv.evidence)
    target = render_test_path(conv, "payroll/tax.py")
    assert target == "tests/test_tax.py"


def test_unittest_repo_conventions(tmp_path: Path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURES / "py_unittest_app", root)
    conv = detect(root, model_for(root))
    assert conv.framework == "unittest"
    assert conv.assertion_style == "unittest_assert"
    assert conv.language == "python"


def test_jest_repo_conventions():
    root = FIXTURES / "js_jest_app"
    conv = detect(root, model_for(root))
    assert conv.language == "javascript"
    assert conv.framework == "jest"
    assert conv.layout == "__tests__"
    assert conv.assertion_style == "chai_expect"
    target = render_test_path(conv, "src/other.js")
    assert target.endswith("__tests__/other.test.js")
