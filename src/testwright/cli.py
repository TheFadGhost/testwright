"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, color
from .analyze import build_model
from .config import load_config
from .conventions import detect
from .diffpreview import render_diff
from .errors import TestwrightError, UsageError
from .pipeline import run_pipeline
from .progress import Progress
from .report import render_text, to_json_dict
from .safety import WriteGuard, hash_tree


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="testwright",
        description=(
            "Find functions without test coverage and generate verified unit "
            "tests that match the project's own conventions."
        ),
    )
    parser.add_argument("--version", action="version", version=f"testwright {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("path", help="target repository root")
        p.add_argument("--config", help="path to testwright.toml")
        p.add_argument("--include", action="append", default=[], help="glob of files to include")
        p.add_argument("--exclude", action="append", default=[], help="path fragment or glob to exclude")
        p.add_argument("--top", type=int, default=None, help="limit to the N highest-ranked targets")
        p.add_argument("--coverage", default=None, help="coverage report: lcov, cobertura, or coverage.py JSON")
        p.add_argument("--changed", action="store_true", help="only consider files changed vs HEAD")
        p.add_argument("--json", action="store_true", help="machine-readable output (schema testwright.report/1)")
        p.add_argument("--no-color", action="store_true", help="disable colour output")
        p.add_argument("-v", "--verbose", action="store_true")
        p.add_argument("-q", "--quiet", action="store_true")

    scan = sub.add_parser(
        "scan",
        help="analyze the repository, rank untested functions, explain priorities",
    )
    _common(scan)
    scan.add_argument("--explain", default=None, metavar="FUNC",
                      help="print the full ranking rationale for FUNC")

    gen = sub.add_parser(
        "generate",
        help="generate candidate tests, verify each by running it, print a summary",
        epilog=(
            "Warning: --execute runs code from the target repository. "
            "Nothing is written unless --write is also given."
        ),
    )
    _common(gen)
    gen.add_argument("--execute", action="store_true",
                     help="grant permission to run target-project code (tests and probes)")
    gen.add_argument("--write", action="store_true",
                     help="create the new test files (verified tests only)")
    gen.add_argument("--mutate", action="store_true",
                     help="mutation-validate surviving tests (Python targets)")
    gen.add_argument("--backend", default=None,
                     help='"template" (default) or "command:<generator command>"')
    gen.add_argument("--timeout", type=float, default=120.0,
                     help="per-command timeout in seconds (default 120)")
    gen.add_argument("--report", default=None,
                     help="also write the JSON report to this file (outside the target)")

    clean = sub.add_parser(
        "clean",
        help="remove only test files previously written by testwright",
    )
    _common(clean)
    return parser


def _load(path_str: str, config_flag: str | None, include, exclude, top):
    root = Path(path_str).resolve()
    if not root.exists():
        raise UsageError(
            f"target path does not exist: {root}",
            next_step="pass the root of an existing repository",
        )
    config = load_config(root, Path(config_flag) if config_flag else None)
    if include:
        config.include = list(include)
    if exclude:
        config.exclude = list(exclude) + [e for e in config.exclude if e not in exclude]
    if top is not None:
        config.top = top
    return root, config


def cmd_scan(args) -> int:
    root, config = _load(args.path, args.config, args.include, args.exclude, args.top)
    progress = Progress(quiet=args.quiet or args.json, verbose=args.verbose)
    model = build_model(root, config, progress)
    conv = detect(root, model)
    covered: dict[str, float] = {}
    if args.coverage:
        from .coverage import function_coverage, parse_coverage

        report = parse_coverage(Path(args.coverage), root)
        covered = function_coverage(model, report)
    from .prioritize import explain, rank_targets

    existing = _existing_test_names(root, config)
    changed = _changed_files(root) if args.changed else None
    ranked = rank_targets(model, covered, existing, top=config.top, changed_files=changed)
    if args.json:
        doc = {
            "schema": "testwright.scan/1",
            "target": str(root),
            "conventions": {
                "language": conv.language,
                "framework": conv.framework,
                "layout": conv.layout,
                "assertion_style": conv.assertion_style,
                "fixture_style": conv.fixture_style,
                "evidence": conv.evidence,
            },
            "targets": [
                {"id": r.func.id, "score": r.score, "components": r.components, "raw": r.raw}
                for r in ranked
            ],
        }
        print(json.dumps(doc, indent=2))
        return 0
    progress.line("")
    progress.line(color.accent(f"Detected conventions"))
    for ev in conv.evidence[:6]:
        progress.line(f"  {ev}")
    progress.line("")
    progress.line(color.accent(f"Ranked untested functions ({len(ranked)})"))
    for r in ranked[:20]:
        progress.line(f"  {r.score:>6.2f}  {r.func.id}")
    if args.explain:
        from .prioritize import explain as explain_target

        match = next(
            (r for r in ranked if r.func.name == args.explain
             or r.func.qualname == args.explain or r.func.id.endswith("::" + args.explain)),
            None,
        )
        if match is None:
            raise UsageError(
                f"function not among ranked targets: {args.explain}",
                next_step="run without --explain to list ranked targets",
            )
        progress.line("")
        progress.line(explain_target(match))
    elif args.verbose and ranked:
        progress.line("")
        for r in ranked[:3]:
            progress.line(explain(r))
    return 0


def _existing_test_names(root, config):
    from .pipeline import _existing_test_names as f

    return f(root, config)


def _changed_files(root) -> set[str]:
    import subprocess

    try:
        res = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(root), capture_output=True, timeout=15,
        )
        out = res.stdout.decode("utf-8", errors="replace")
        return {line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()}
    except (OSError, subprocess.TimeoutExpired):
        return set()


def cmd_generate(args) -> int:
    root, config = _load(args.path, args.config, args.include, args.exclude, args.top)
    progress = Progress(quiet=args.quiet or args.json, verbose=args.verbose)
    model = build_model(root, config, progress)
    conv = detect(root, model)
    covered: dict[str, float] = {}
    if args.coverage:
        from .coverage import function_coverage, parse_coverage

        report = parse_coverage(Path(args.coverage), root)
        covered = function_coverage(model, report)
    from .prioritize import rank_targets

    existing = _existing_test_names(root, config)
    changed = _changed_files(root) if args.changed else None
    ranked = rank_targets(model, covered, existing, top=config.top, changed_files=changed)

    if not args.json:
        progress.line("")
        progress.line(color.warning(
            "Running with --execute will execute code from the target repository."
        ))
    result = run_pipeline(
        root, config, conv, model, ranked,
        do_execute=args.execute,
        do_write=args.write,
        mutate=args.mutate,
        timeout=args.timeout,
        progress=progress,
        backend_spec=args.backend or config.backend,
    )

    if args.json:
        print(json.dumps(to_json_dict(result, str(root), len(ranked)), indent=2))
    else:
        if args.execute:
            for g in result.generated:
                progress.line("")
                progress.line(color.accent(f"+ {g['file']}"))
                progress.line(render_diff(g["file"], g["content"]))
        progress.line("")
        progress.line(render_text(result, str(root), len(ranked)))
        if result.generated and not args.write:
            progress.line("")
            progress.line(
                color.warning(
                    "Dry run: nothing was written. Pass --write to create these files."
                )
            )
        if not result.generated and args.execute:
            progress.line("")
            progress.line("No tests were generated.")
    if args.report:
        Path(args.report).write_text(
            json.dumps(to_json_dict(result, str(root), len(ranked)), indent=2),
            encoding="utf-8",
        )
    return 0


def cmd_clean(args) -> int:
    root, _config = _load(args.path, args.config, [], [], None)
def cmd_clean(args) -> int:
    root, _config = _load(args.path, args.config, [], [], None)
    guard = WriteGuard(root)
    written = guard.written_files()
    removed = 0
    warnings: list[str] = []
    from .fsutil import contained

    for rel in sorted(written, reverse=True):
        try:
            p = contained(root, Path(*rel.split("/")))
        except TestwrightError:
            warnings.append(f"manifest entry escapes the target root, skipped: {rel}")
            continue
        if p.is_file():
            p.unlink()
            removed += 1
            parent = p.parent
            if parent != root and not any(parent.iterdir()):
                parent.rmdir()
    manifest = root / ".testwright-manifest.json"
    if manifest.exists():
        remaining = json.loads(manifest.read_text(encoding="utf-8")).get("written", [])
        if not remaining:
            manifest.unlink()
    if args.json:
        print(json.dumps({"schema": "testwright.clean/1", "removed": removed,
                          **({"warnings": warnings} if warnings else {})}))
    else:
        print(f"removed {removed} generated file(s); no other files were touched")
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    color.configure(no_color_flag=getattr(args, "no_color", False))
    handlers = {"scan": cmd_scan, "generate": cmd_generate, "clean": cmd_clean}
    try:
        return handlers[args.command](args)
    except TestwrightError as exc:
        stream = sys.stderr
        if getattr(args, "json", False):
            payload = {
                "schema": "testwright.error/1",
                "error": exc.message,
                **({"file": exc.file} if exc.file else {}),
                **({"next_step": exc.next_step} if exc.next_step else {}),
            }
            print(json.dumps(payload, indent=2), file=stream)
        else:
            print(color.error(exc.render()), file=stream)
        from .errors import TargetError

        return 2 if isinstance(exc, TargetError) else 1


if __name__ == "__main__":
    sys.exit(main())
