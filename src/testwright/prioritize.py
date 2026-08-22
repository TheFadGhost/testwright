"""Ranking of untested functions and the --explain rationale."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .model import CodeModel, FunctionInfo


@dataclass
class RankedTarget:
    func: FunctionInfo
    score: float
    components: dict[str, float] = field(default_factory=dict)
    raw: dict[str, object] = field(default_factory=dict)
    skip_reason: str | None = None


def _git_last_commit_ts(root: Path, rel_file: str) -> int | None:
    try:
        res = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", rel_file],
            cwd=str(root),
            capture_output=True,
            timeout=15,
        )
        out = res.stdout.decode().strip()
        return int(out) if out else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _recency_component(ts: int | None) -> float:
    if ts is None:
        return 0.0
    import time

    age_days = max((time.time() - ts) / 86400.0, 0.0)
    # newer is more important; 30 days or newer scores 1, a year old ~0
    import math

    return max(0.0, 1.0 - math.log1p(age_days) / math.log1p(365))


def rank_targets(
    model: CodeModel,
    covered_fraction: dict[str, float],
    existing_test_names: set[str],
    top: int | None = None,
    changed_files: set[str] | None = None,
) -> list[RankedTarget]:
    """Score untested functions.

    Components (documented weights): complexity 40, fan-in 25,
    public API surface 20, git recency 15.
    """
    functions = model.functions
    max_cx = max((f.complexity for f in functions), default=1) or 1
    fanins = {f.id: model.fan_in(f) for f in functions}
    max_fan = max(fanins.values(), default=1) or 1

    ranked: list[RankedTarget] = []
    for f in functions:
        if f.qualname.split(".")[-1].startswith("_") and not f.exported:
            continue
        if f.name.startswith("test_"):
            continue
        cov = covered_fraction.get(f.id)
        referenced_by_tests = any(f.name in n for n in existing_test_names)
        if cov is None:
            # without coverage data, a function already named in tests is
            # presumed covered; we do not guess further
            if referenced_by_tests:
                continue
            uncovered = True
        else:
            uncovered = cov < 0.999
        if not uncovered:
            continue
        if changed_files is not None and f.file not in changed_files:
            continue
        already = f"{f.name}" in existing_test_names
        cx_norm = min(f.complexity / max_cx, 1.0)
        fan_norm = fanins.get(f.id, 0) / max_fan
        public = 1.0 if (f.exported and not f.name.startswith("_")) else 0.4
        ts = _git_last_commit_ts(model.root, f.file)
        rec = _recency_component(ts)
        score = 40 * cx_norm + 25 * fan_norm + 20 * public + 15 * rec
        rt = RankedTarget(func=f, score=round(score, 2))
        rt.components = {
            "complexity": round(40 * cx_norm, 2),
            "fan_in": round(25 * fan_norm, 2),
            "public_api": round(20 * public, 2),
            "recency": round(15 * rec, 2),
        }
        rt.raw = {
            "complexity": f.complexity,
            "fan_in": fanins.get(f.id, 0),
            "exported": f.exported,
            "covered_fraction": cov if cov is not None else "no coverage data",
            "last_commit_days_ago": (
                None if ts is None else round((__import__("time").time() - ts) / 86400, 1)
            ),
        }
        ranked.append(rt)
    ranked.sort(key=lambda r: (-r.score, r.func.file, r.func.line))
    if top is not None:
        ranked = ranked[:top]
    return ranked


def explain(target: RankedTarget) -> str:
    f = target.func
    lines = [
        f"{f.id}  score {target.score}",
        f"  file {f.file}:{f.line}  language {f.language}",
        f"  complexity {f.complexity} -> {target.components.get('complexity')}/40",
        f"  fan-in {target.raw.get('fan_in')} -> {target.components.get('fan_in')}/25",
        f"  public API surface {'yes' if f.exported else 'internal'} "
        f"-> {target.components.get('public_api')}/20",
        f"  last commit {target.raw.get('last_commit_days_ago')} days ago "
        f"-> {target.components.get('recency')}/15",
        f"  coverage of body lines: {target.raw.get('covered_fraction')}",
    ]
    return "\n".join(lines)
