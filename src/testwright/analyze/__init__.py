"""Analyzer interface and model builder.

One analyzer per language; all produce the shared CodeModel schema. The
``build_model`` orchestrator is language-agnostic: it discovers files, applies
include/exclude rules, and dispatches to the right analyzer.
"""

from __future__ import annotations

import fnmatch
import os
from abc import ABC, abstractmethod
from pathlib import Path

from ..config import Config
from ..errors import UsageError
from ..model import CodeModel, ModuleInfo
from ..progress import Progress


class Analyzer(ABC):
    """Parses one source file into a ModuleInfo."""

    language: str = ""
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def analyze_file(self, path: Path, root: Path) -> ModuleInfo: ...

    def matches(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions


ANALYZERS: dict[str, type[Analyzer]] = {}


def _register(cls: type[Analyzer]) -> None:
    ANALYZERS[cls.language] = cls


from . import javascript_analyzer as _js  # noqa: E402
from . import python_analyzer as _py  # noqa: E402

_register(_py.PythonAnalyzer)
_register(_js.JavaScriptAnalyzer)


def enabled_languages(config: Config) -> list[str]:
    langs = []
    for name, lang_cfg in config.languages.items():
        if lang_cfg.enabled:
            langs.append(name)
    if not langs:
        raise UsageError(
            "all languages are disabled in configuration",
            next_step="enable at least one [languages.<name>] section",
        )
    return langs


def excluded(rel_posix: str, patterns: list[str]) -> bool:
    for pat in patterns:
        pat_norm = pat.rstrip("/")
        if fnmatch.fnmatch(rel_posix, pat):
            return True
        parts = rel_posix.split("/")
        for i in range(len(parts)):
            if fnmatch.fnmatch("/".join(parts[: i + 1]), pat_norm + "/*") or (
                fnmatch.fnmatch(parts[i], pat_norm)
            ):
                return True
    return False


def discover_files(root: Path, config: Config) -> list[Path]:
    files: list[Path] = []
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tmp"}
    for dirpath, dirnames, filenames in sorted(os.walk(root)):
        dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
        for fname in sorted(filenames):
            p = Path(dirpath) / fname
            rel = p.relative_to(root).as_posix()
            if excluded(rel, config.exclude):
                continue
            if config.include and not any(
                fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(fname, pat)
                for pat in config.include
            ):
                continue
            files.append(p)
    return files


def build_model(root: Path, config: Config, progress: Progress | None = None) -> CodeModel:
    enabled_languages(config)  # validates that something is enabled
    analyzers: dict[str, Analyzer] = {}
    for key in ("python", "javascript"):
        cfg = config.languages.get(key) or config.languages.get("typescript")
        if cfg and not cfg.enabled and key == "python":
            continue
        cls = ANALYZERS.get(key)
        if cls and (cfg is None or cfg.enabled or key != "python"):
            if key not in analyzers:
                analyzers[key] = cls()

    model = CodeModel(root=root)
    files = [
        f
        for f in discover_files(root, config)
        if any(a.matches(f) for a in analyzers.values())
    ]
    total = len(files)
    if progress:
        progress.phase(f"analyzing {total} source file(s)")
    for i, path in enumerate(files, 1):
        for key, analyzer in analyzers.items():
            if not analyzer.matches(path):
                continue
            if progress:
                progress.item(i, total, f"{key}: {path.relative_to(root).as_posix()}")
            mod = analyzer.analyze_file(path, root)
            if mod.parse_error and progress:
                progress.detail(f"unparseable, skipped: {mod.file} ({mod.parse_error})")
            model.modules[mod.file] = mod
            break
    return model
