"""Language enable/disable configuration matrix."""

import shutil
from pathlib import Path

from testwright.analyze import build_model
from testwright.config import Config, LanguageConfig
from testwright.errors import UsageError

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "repos"


def _model(root: Path, config: Config):
    return build_model(root, config)


def test_disable_python_leaves_javascript(tmp_path: Path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURES / "js_jest_app", root)
    cfg = Config(root=root)
    cfg.languages["python"] = LanguageConfig(enabled=False)
    model = _model(root, cfg)
    assert model.modules
    assert all(m.language == "javascript" for m in model.modules.values())


def test_typescript_alias_controls_javascript(tmp_path: Path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURES / "js_jest_app", root)
    cfg = Config(root=root)
    cfg.languages["javascript"] = LanguageConfig(enabled=False)
    model = _model(root, cfg)
    assert all(m.language == "javascript" for m in model.modules.values())


def test_all_disabled_is_usage_error():
    root = FIXTURES / "py_pytest_app"
    cfg = Config(root=root)
    for lc in cfg.languages.values():
        lc.enabled = False
    with pytest.raises(UsageError):
        _model(root, cfg)
