"""Safety layer: tree hashing and the write guard.

The invariant under test everywhere in this project: a Testwright run never
modifies or deletes an existing file in the target repository, and writes only
new files it records in its manifest. Tree hashing before/after every run is the
mechanism the automated tests use to prove it, including on error paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

MANIFEST_NAME = ".testwright-manifest.json"


def hash_tree(root: Path) -> dict[str, str]:
    """Content hashes of every regular file under root (gitignored dirs skipped)."""
    out: dict[str, str] = {}
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in sorted(filenames):
            p = Path(dirpath) / name
            try:
                st = p.lstat()
                if stat.S_ISLNK(st.st_mode):
                    continue
                h = hashlib.sha256()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                rel = p.relative_to(root).as_posix()
                out[rel] = h.hexdigest()
            except OSError:
                continue
    return out


def diff_trees(before: dict[str, str], after: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return (modified_or_deleted_existing, added) relative paths."""
    modified = []
    for path, digest in before.items():
        if after.get(path) != digest:
            modified.append(path)
    added = sorted(set(after) - set(before))
    return modified, added


class WriteGuard:
    """Tracks new files written by Testwright in a manifest at target root.

    The manifest is itself a new file Testwright owns; it is created only when
    something is actually written.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest_path = root / MANIFEST_NAME

    def load(self) -> dict[str, list[str]]:
        if not self.manifest_path.exists():
            return {"written": []}
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return {"written": list(data.get("written", []))}
        except (json.JSONDecodeError, OSError):
            return {"written": []}

    def record(self, rel_path: str) -> None:
        data = self.load()
        if rel_path not in data["written"]:
            data["written"].append(rel_path)
            tmp = self.manifest_path.with_name(
                self.manifest_path.name + ".tmp"
            )
            tmp.write_text(
                json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            os.replace(tmp, self.manifest_path)

    def written_files(self) -> list[str]:
        return self.load()["written"]
