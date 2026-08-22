"""Configuration loading for Testwright.

Reads an optional ``testwright.toml`` from the target root (or ``--config FILE``).
Every value is overridable on the command line. Unknown keys are reported as
usage errors rather than silently ignored.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .errors import UsageError

DEFAULT_EXCLUDES = [
    "node_modules/",
    "vendor/",
    "venv/",
    ".venv/",
    "dist/",
    "build/",
    "__pycache__/",
    "migrations/",
    "*_pb2.py",
    "*_pb2_grpc.py",
    "*.min.js",
    ".git/",
]

VALID_KEYS = {
    "include",
    "exclude",
    "top",
    "backend",
    "languages",
}


@dataclass
class LanguageConfig:
    enabled: bool = True
    test_command: str | None = None  # explicit override, run from target root


@dataclass
class Config:
    root: Path
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    top: int | None = None  # generation budget; None = all targets
    backend: str = "template"
    languages: dict[str, LanguageConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.exclude = list(dict.fromkeys(DEFAULT_EXCLUDES + self.exclude))
        for lang in ("python", "javascript", "typescript"):
            self.languages.setdefault(lang, LanguageConfig())


def load_config(root: Path, config_file: Path | None = None) -> Config:
    """Load configuration for a target root, applying defaults."""
    path = config_file or root / "testwright.toml"
    data: dict = {}
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise UsageError(
                f"configuration file is not valid TOML: {exc}",
                file=str(path),
                next_step="fix the syntax error or pass a different --config",
            ) from exc
        unknown = set(data) - VALID_KEYS
        if unknown:
            raise UsageError(
                "unknown configuration keys: " + ", ".join(sorted(unknown)),
                file=str(path),
                next_step=f"allowed keys are: {', '.join(sorted(VALID_KEYS))}",
            )
    languages_raw = data.get("languages", {})
    if not isinstance(languages_raw, dict):
        raise UsageError(
            "[languages] must be a table",
            file=str(path),
            next_step='use e.g. [languages.python] test_command = "python -m pytest"',
        )
    langs = {}
    for name, val in languages_raw.items():
        if not isinstance(val, dict):
            raise UsageError(
                f"[languages.{name}] must be a table",
                file=str(path),
            )
        unknown_lang_keys = set(val) - {"enabled", "test_command"}
        if unknown_lang_keys:
            raise UsageError(
                f"unknown keys in [languages.{name}]: "
                + ", ".join(sorted(unknown_lang_keys)),
                file=str(path),
            )
        langs[name] = LanguageConfig(
            enabled=bool(val.get("enabled", True)),
            test_command=val.get("test_command"),
        )

    def _strlist(key: str) -> list[str]:
        val = data.get(key, [])
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            raise UsageError(f"'{key}' must be a list of strings", file=str(path))
        return list(val)

    top = data.get("top")
    if top is not None and (not isinstance(top, int) or isinstance(top, bool)):
        raise UsageError("'top' must be an integer", file=str(path))

    return Config(
        root=root,
        include=_strlist("include"),
        exclude=_strlist("exclude"),
        top=top,
        backend=data.get("backend", "template"),
        languages=langs,
    )
