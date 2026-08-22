"""Summary report rendering (text, markdown) and the machine-readable schema."""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "testwright.report/1"


def coverage_delta(result) -> dict:
    """Executed-line counts on files that received generated tests.

    Raw counts before/after, never a percentage: without a full line map per
    file a percent figure would overstate precision. The method string always
    travels with the numbers.
    """
    before, after = result.coverage_before, result.coverage_after
    if before is None or after is None:
        return {"measured": False, "method": result.coverage_method}
    touched = set()
    for g in result.generated:
        for t in g["tests"]:
            touched.add(t["function"].split("::", 1)[0])
    touched &= set(after)
    if not touched:
        return {
            "measured": True,
            "method": result.coverage_method,
            "rows": [],
            "note": "no targeted file produced a kept test",
        }
    rows = []
    total_b = total_a = 0
    for rel in sorted(touched):
        b = len(before.get(rel, {}).get("lines", set()))
        a = len(after.get(rel, {}).get("lines", set()))
        total_b += b
        total_a += a
        rows.append({"file": rel, "before": b, "after": a})
    return {
        "measured": True,
        "method": result.coverage_method,
        "metric": "executed lines (coverage.py)",
        "rows": rows,
        "total_before": total_b,
        "total_after": total_a,
    }


def to_json_dict(result, target: str, ranked_count: int) -> dict:
    counts = result.counts()
    doc = {
        "schema": SCHEMA,
        "target": target,
        "ranked_targets": ranked_count,
        "counts": counts,
        "generated": [
            {
                "file": g["file"],
                "language": g["language"],
                "framework": g["framework"],
                "tests": g["tests"],
            }
            for g in result.generated
        ],
        "discarded": [
            {
                "function": d.function_id,
                "test": d.name,
                "reason": d.reason,
                **({"detail": d.detail} if d.detail else {}),
            }
            for d in result.discards
        ],
        "skipped": [
            {"function": fid, "reason": why} for fid, why in result.skipped_functions
        ],
        "coverage_delta": coverage_delta(result),
        "warnings": list(result.warnings),
    }
    return doc


def render_text(result, target: str, ranked_count: int) -> str:
    from . import color

    counts = result.counts()
    lines: list[str] = []
    lines.append(color.warning("Discarded") + f" ({counts['tests_discarded']})")
    by_reason: dict[str, list[str]] = {}
    for d in result.discards:
        key = d.reason.split(":")[0] if ":" in d.reason else d.reason
        label = f"{d.function_id}" + (f" [{d.name}]" if d.name else "")
        by_reason.setdefault(d.reason, []).append(label)
    for reason, items in sorted(by_reason.items()):
        lines.append(f"  {reason}:")
        for item in items[:8]:
            lines.append(f"    {item}")
        if len(items) > 8:
            lines.append(f"    ... and {len(items) - 8} more")
    if not result.discards:
        lines.append("  nothing was discarded")

    lines.append("")
    lines.append(color.success("Generated") + f" ({counts['tests_generated']})")
    if result.generated:
        for g in result.generated:
            names = ", ".join(t["name"] for t in g["tests"])
            suffix = " [mutation validated]" if any(t["mutation_validated"] for t in g["tests"]) else ""
            lines.append(f"  {g['file']}  {len(g['tests'])} test(s){suffix}")
            lines.append(f"    {names}")
    else:
        lines.append("  nothing was generated")

    if result.skipped_functions:
        lines.append("")
        lines.append(color.muted(f"Skipped ({len(result.skipped_functions)})"))
        shown = result.skipped_functions[:10]
        for fid, why in shown:
            lines.append(f"  {fid}: {why}")
        if len(result.skipped_functions) > 10:
            lines.append(f"  ... and {len(result.skipped_functions) - 10} more")

    lines.append("")
    cd = coverage_delta(result)
    if cd.get("measured") and cd.get("rows"):
        b, a = cd["total_before"], cd["total_after"]
        lines.append(
            f"Coverage delta ({cd['metric']}): {b} -> {a} "
            f"on {len(cd['rows'])} targeted file(s)"
        )
        lines.append(f"  method: {cd['method']}")
        for row in cd["rows"]:
            lines.append(f"  {row['file']}: {row['before']} -> {row['after']}")
    else:
        reason = cd.get("method") or "not measured"
        lines.append(f"Coverage delta: {reason}")

    if result.warnings:
        lines.append("")
        for w in result.warnings:
            lines.append(color.warning(f"warning: {w}"))
    return "\n".join(lines)
