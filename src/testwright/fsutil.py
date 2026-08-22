"""Filesystem utilities: path containment, atomic writes, temp dir lifecycle."""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .errors import SafetyViolation


def to_posix(rel: str | Path) -> str:
    return str(rel).replace("\\", "/")


def relpath_inside(root: Path, path: Path) -> str:
    """Relative posix path of *path* under *root*, refusing escapes."""
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise SafetyViolation(
            f"path escapes the target root: {path}",
            file=to_posix(path),
            next_step="pass a path inside the target repository",
        ) from exc
    return to_posix(rel)


def contained(root: Path, candidate: Path) -> Path:
    """Resolve *candidate* and assert it stays inside *root*."""
    resolved = (root / candidate).resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise SafetyViolation(
            f"refusing to operate outside the target root: {candidate}",
            file=to_posix(candidate),
        )
    return resolved


@contextmanager
def temp_dir(prefix: str = "testwright-"):
    """A temporary directory that is always removed, including on error."""
    d = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def write_new_file(path: Path, content: str) -> None:
    """Write a brand-new file atomically. Refuses to overwrite anything."""
    if path.exists():
        raise SafetyViolation(
            "refusing to overwrite an existing file",
            file=to_posix(path),
            next_step="remove the file first or choose a different target",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".testwright-tmp")
    try:
        tmp.write_text(content, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")
