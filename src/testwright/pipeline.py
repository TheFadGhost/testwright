"""The generation-to-verification pipeline.

Nothing reaches disk inside the target repository until every candidate has
been executed and passed. Candidates live in a temporary shadow directory;
the target repository is never touched during verification.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .conventions import Conventions
from .meaningless import check_python_test
from .model import CodeModel, FunctionInfo
from .runners import target_python
from .safety import WriteGuard

BOOTSTRAP = """
import importlib.util, json, os, sys, unittest
cfg = json.loads(open(sys.argv[1], encoding='utf-8').read())
for p in reversed(cfg['path_prepend']):
    sys.path.insert(0, p)
if cfg['mode'] == 'pytest':
    import pytest
    raise SystemExit(int(pytest.main(cfg['pytest_args'])))
spec = importlib.util.spec_from_file_location('tw_candidate', cfg['candidate'])
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except Exception:
    print(json.dumps({'ran': 0, 'bad': 1}))
    raise SystemExit(1)
stream = open(os.devnull, 'w')
res = unittest.TextTestRunner(verbosity=0, stream=stream).run(
    unittest.TestLoader().loadTestsFromModule(mod)
)
bad = len(res.failures) + len(res.errors)
print(json.dumps({'ran': res.testsRun, 'bad': bad}))
raise SystemExit(0 if bad == 0 else 1)
"""


from .generate import CandidateTest as _CandidateTest  # noqa: F401 (re-exported type)


@dataclass
class DiscardRecord:
    function_id: str
    name: str | None
    reason: str
    detail: str = ""


@dataclass
class UnitOutcome:
    """Result of processing one GenerationUnit."""

    unit: object
    kept: list[_CandidateTest] = field(default_factory=list)
    discards: list[DiscardRecord] = field(default_factory=list)


def _run_bootstrap(
    mode: str,
    candidate: Path,
    root: Path,
    path_prepend: list[Path],
    timeout: float,
    workdir: Path,
) -> tuple[int, str, str]:
    """Run the verification bootstrap. Returns (exit_code, stdout, stderr)."""
    cfg_path = workdir / "bootstrap-cfg.json"
    script_path = workdir / "bootstrap.py"
    if not script_path.exists():
        script_path.write_text(BOOTSTRAP, encoding="utf-8")
    cfg = {
        "mode": mode,
        "candidate": str(candidate),
        "path_prepend": [str(p) for p in path_prepend],
    }
    if mode == "pytest":
        cfg["pytest_args"] = [
            "-q",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(root),
            str(candidate),
        ]
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    from .exec_env import run_command

    res = run_command(
        [target_python(), str(script_path), str(cfg_path)], root, timeout=timeout
    )
    return (
        res.exit_code if res.exit_code is not None else 1,
        res.stdout,
        res.stderr + ("\n[timed out]" if res.timed_out else ""),
    )


def verify_candidate(
    candidate_src: str,
    language: str,
    framework: str,
    root: Path,
    timeout: float,
    workdir: Path,
    rel_import_dir: str | None = None,
) -> tuple[bool, str]:
    """Execute one candidate test module in the shadow dir.

    Returns (passed, failure_detail). Never writes inside root.
    """
    if language == "python":
        try:
            ast.parse(candidate_src)
        except SyntaxError as exc:
            return False, f"candidate does not parse (line {exc.lineno})"
    cand_dir = workdir / "candidate"
    cand_dir.mkdir(parents=True, exist_ok=True)
    ext = ".py" if language == "python" else ".js"
    cand_path = cand_dir / f"tw_candidate{ext}"
    cand_path.write_text(candidate_src, encoding="utf-8")
    if language == "javascript":
        from .exec_env import run_command
        import re as _re

        # candidates are verified outside the repo: pin relative requires to
        # the target root so module resolution works from the shadow directory
        def _abs_require(m: "_re.Match") -> str:
            spec = m.group(2)
            if not spec.startswith("."):
                return m.group(0)
            base_dir = root / rel_import_dir if rel_import_dir else root
            base = (base_dir / spec).resolve()
            target = None
            for candidate in (
                base,
                base.with_suffix(".js") if base.suffix == "" else None,
                base.with_suffix(".ts") if base.suffix == "" else None,
                base / "index.js",
            ):
                if candidate is not None and candidate.is_file():
                    target = candidate
                    break
            abs_spec = (target or base).as_posix()
            return f"require({m.group(1)}{abs_spec}{m.group(1)})"

        # pattern consumes the closing paren; _abs_require re-emits it
        pinned = _re.sub(
            r"""require\((['"])([^'"]+)\1\)""",
            _abs_require,
            candidate_src,
        )
        cand_path.write_text(pinned, encoding="utf-8")
        npx = "npx.cmd" if sys.platform == "win32" else "npx"
        runner = "jest" if framework == "jest" else framework or "jest"
        inline_cfg = json.dumps(
            {
                "rootDir": str(root),
                "roots": [str(cand_dir)],
                "testEnvironment": "node",
                "modulePaths": [str(root)],
                "testMatch": [str(cand_path).replace("\\", "/")],
            }
        )
        res = run_command(
            [npx, runner, "--ci", "--config", inline_cfg], root, timeout=timeout
        )
        ok = res.ok
        detail = "" if ok else (res.stdout + "\n" + res.stderr)[:3500]
        return ok, detail
    if framework == "unittest":
        code, out, err = _run_bootstrap(
            "unittest", cand_path, root, [root], timeout, workdir
        )
        return code == 0, (err or out).strip()[-1500:]
    code, out, err = _run_bootstrap(
        "pytest", cand_path, root, [root], timeout, workdir
    )
    return code == 0, (out + "\n" + err).strip()[-1500:]

def _existing_test_names(root: Path, config: Config) -> set[str]:
    from .analyze import discover_files

    names: set[str] = set()
    for p in discover_files(root, config):
        n = p.name
        is_py_test = n.startswith("test_") and n.endswith(".py") or n.endswith("_test.py")
        is_js_test = re.fullmatch(r".+\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs)", n)
        if not (is_py_test or is_js_test):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        names.update(re.findall(r"def\s+(test_\w+)\s*\(", text))
        names.update(re.findall(r"\bit\s*\(\s*['\"]([^'\"]+)", text))
    return names


def _check_js(source: str):
    from .meaningless import check_js_test

    return check_js_test(source)


def _module_for(model: CodeModel, func: FunctionInfo) -> str | None:
    mod = model.modules.get(func.file)
    if mod is None:
        return None
    if mod.package:
        return mod.package
    if "/" in func.file:
        return None
    stem = func.file[:-3] if func.file.endswith(".py") else func.file.rsplit(".", 1)[0]
    return stem


def _find_func(model: CodeModel, fid: str) -> FunctionInfo | None:
    for f in model.functions:
        if f.id == fid:
            return f
    return None


def _generation_blocker(model: CodeModel, func: FunctionInfo) -> str | None:
    if func.language == "python":
        if func.is_async:
            return "async function requires an event loop"
        if func.is_property:
            return "properties are read as attributes; generator skips them"
        if func.is_method and not func.is_static and not func.is_classmethod:
            init_id = f"{func.file}::{func.class_name}.__init__"
            init = next((f for f in model.functions if f.id == init_id), None)
            if init and any(p.required for p in init.params):
                return "constructor requires arguments"
    else:
        if func.is_async:
            return "async function requires promise-aware test bodies"
        if func.is_method and not func.is_static:
            return "instance methods need object construction"
    return None


def run_pipeline(
    root: Path,
    config: Config,
    conventions: Conventions,
    model: CodeModel,
    ranked: list,
    *,
    do_execute: bool = False,
    do_write: bool = False,
    mutate: bool = False,
    timeout: float = 120.0,
    progress=None,
    backend_spec: str | None = None,
) -> PipelineResult:
    """Generate, verify, and (optionally) write new tests."""
    from .fsutil import temp_dir
    from .generate.probe import (
        ProbeCase,
        ProbeResult,
        probe_javascript,
        probe_python,
        synthesize_cases,
    )
    from .generate.template_js import JavaScriptTemplateBackend
    from .generate.template_py import PythonTemplateBackend

    result = PipelineResult(root=root)
    conv_main_guard = bool(getattr(conventions, "main_guard", False))
    if not ranked:
        result.warnings.append("no untested functions matched the ranking rules")
        return result
    if not do_execute:
        result.warnings.append(
            "preview only: pass --execute to run the target project's code "
            "(its tests and the functions under test)"
        )
        result.skipped_functions = [
            (r.func.id, "not executed: --execute not granted") for r in ranked
        ]
        return result

    with temp_dir(prefix="tw-run-") as workdir:
        probes: dict[str, list[tuple[ProbeCase, ProbeResult]]] = {}
        for idx, rt in enumerate(ranked, 1):
            func = rt.func
            if progress:
                progress.item(idx, len(ranked), f"probing {func.id}")
            blocker = _generation_blocker(model, func)
            if blocker:
                result.skipped_functions.append((func.id, blocker))
                continue
            if func.language == "python":
                module_dotted = _module_for(model, func)
                if module_dotted is None:
                    result.skipped_functions.append(
                        (func.id, "cannot derive an importable module path")
                    )
                    continue
            else:
                module_dotted = None
            cases, why = synthesize_cases(func)
            if why:
                result.skipped_functions.append((func.id, why))
                continue
            got: list[tuple[ProbeCase, ProbeResult]] = []
            for case in cases:
                if func.language == "python":
                    res = probe_python(root, module_dotted, func.qualname, case, timeout=30)
                else:
                    res = probe_javascript(root, func.file, func.qualname, case, timeout=30)
                got.append((case, res))
            if not any(r.ok and r.repr_ is not None for _, r in got):
                err = next(
                    (r.error_type or "no comparable result" for _, r in got if not r.ok),
                    "no comparable result",
                )
                result.skipped_functions.append((func.id, f"probe failed: {err}"))
                continue
            probes[func.id] = got

        py_targets = [
            (rt.func, probes[rt.func.id])
            for rt in ranked
            if rt.func.id in probes and rt.func.language == "python"
        ]
        js_targets = [
            (rt.func, probes[rt.func.id])
            for rt in ranked
            if rt.func.id in probes and rt.func.language == "javascript"
        ]
        units = []
        external = None
        if backend_spec:
            from .generate.command_backend import parse_backend_spec

            external = parse_backend_spec(backend_spec)
        if external is not None:
            if not do_execute:
                result.warnings.append(
                    "command backend output cannot be trusted without --execute; "
                    "candidates will be discarded"
                )
            else:
                units = external.generate(model, conventions, [rt.func for rt in ranked])
        else:
            if py_targets and conventions.framework != "jest":
                units += PythonTemplateBackend().generate(model, conventions, py_targets)
            if js_targets:
                units += JavaScriptTemplateBackend().generate(model, conventions, js_targets)

        for u_idx, unit in enumerate(units, 1):
            outcome = UnitOutcome(unit=unit)
            for t_idx, cand in enumerate(unit.tests):
                if progress:
                    progress.item(t_idx + 1, len(unit.tests), f"checking {cand.name}")
                checker = check_python_test if unit.language == "python" else _check_js
                verdict = checker(cand.code)
                if not verdict.meaningful:
                    outcome.discards.append(
                        DiscardRecord(cand.function_id, cand.name, f"meaningless: {verdict.reason}")
                    )
            kept_names = {t.name for t in unit.tests} - {d.name for d in outcome.discards}
            rel_dir = "/".join(unit.test_file.split("/")[:-1]) or None
            src_subset = _render_unit(unit, kept_names)
            ok, detail = verify_candidate(
                src_subset, unit.language, unit.framework, root, timeout, workdir,
                rel_import_dir=rel_dir,
            )
            if not ok and len(kept_names) > 1:
                survivors: set[str] = set()
                for cand in unit.tests:
                    if cand.name not in kept_names:
                        continue
                    solo = _render_unit(unit, {cand.name})
                    sok, sdetail = verify_candidate(
                        solo, unit.language, unit.framework, root, timeout, workdir,
                        rel_import_dir=rel_dir,
                    )
                    if sok:
                        survivors.add(cand.name)
                    else:
                        outcome.discards.append(
                            DiscardRecord(
                                cand.function_id,
                                cand.name,
                                "failed verification",
                                _last_line(sdetail),
                            )
                        )
                kept_names = survivors & kept_names
            elif not ok:
                first = next((t for t in unit.tests if t.name in kept_names), None)
                if first is not None:
                    outcome.discards.append(
                        DiscardRecord(
                            first.function_id,
                            first.name,
                            "failed verification",
                            _last_line(detail),
                        )
                    )
                kept_names = set()
            if mutate and unit.language == "python" and kept_names:
                func_ids = {t.function_id for t in unit.tests if t.name in kept_names}
                strong = True
                weak_details: list[str] = []
                for fid in sorted(func_ids):
                    func = _find_func(model, fid)
                    if func is None:
                        continue
                    killed, mdetail = validate_with_mutations(
                        root, func, src_subset, unit.framework, timeout, workdir
                    )
                    if killed:
                        for t in unit.tests:
                            if t.name in kept_names and t.function_id == fid:
                                t.mutation_validated = True
                    else:
                        strong = False
                        weak_details.append(f"{fid}: {mdetail}")
                if not strong:
                    weak_names = {
                        t.name
                        for t in unit.tests
                        if t.function_id in func_ids and t.name in kept_names and not t.mutation_validated
                    }
                    for name in weak_names:
                        cand = next(t for t in unit.tests if t.name == name)
                        outcome.discards.append(
                            DiscardRecord(cand.function_id, name, "weak: survived mutations")
                        )
                    kept_names -= weak_names
            for t in unit.tests:
                if t.name in kept_names:
                    outcome.kept.append(t)
            result.units.append(outcome)
            result.discards.extend(outcome.discards)

        # assemble final files
        from .generate.template_py import finalize_unit

        for unit, outcome in zip(units, result.units):
            if not outcome.kept:
                continue
            kept_names = {t.name for t in outcome.kept}
            if unit.language == "javascript":
                content = _render_unit(unit, kept_names)
            else:
                content = finalize_unit(unit, outcome.kept, conv_main_guard)
            target_abs = root / unit.test_file.replace("/", '/')
            if target_abs.exists():
                for t in outcome.kept:
                    result.discards.append(
                        DiscardRecord(t.function_id, t.name,
                                      "refusing to overwrite existing test file",
                                      str(unit.test_file))
                    )
                outcome.kept = []
                continue
            result.generated.append(
                {
                    "file": unit.test_file,
                    "language": unit.language,
                    "framework": unit.framework,
                    "content": content,
                    "tests": [
                        {"name": t.name, "function": t.function_id,
                         "mutation_validated": t.mutation_validated}
                        for t in outcome.kept
                    ],
                }
            )

        # coverage delta (Python only; requires the coverage package)
        if py_targets:
            before = _measure_coverage_py(root, timeout, [], workdir)
            extra = []
            for gen in result.generated:
                if gen["language"] == "python":
                    cand_path = workdir / "assembled" / Path(gen["file"]).name
                    cand_path.parent.mkdir(parents=True, exist_ok=True)
                    cand_path.write_text(gen["content"], encoding="utf-8")
                    extra.append(str(cand_path))
            after = _measure_coverage_py(root, timeout, extra, workdir)
            if before is not None and after is not None:
                result.coverage_before = before
                result.coverage_after = after
                result.coverage_method = (
                    "coverage.py line coverage over repository sources; "
                    "existing suite vs existing suite plus generated tests"
                )
            else:
                result.coverage_method = (
                    "not measured: the coverage package is not installed "
                    "(pip install coverage)"
                )

        # write phase
        if do_write:
            guard = WriteGuard(root)
            from .fsutil import write_new_file, contained

            for gen in result.generated:
                dest = contained(root, Path(*gen["file"].split("/")))
                write_new_file(dest, gen["content"])
                guard.record(gen["file"])
    return result


def _measure_coverage_py(root: Path, timeout: float, extra_files: list[str], workdir: Path):
    import importlib.util

    if importlib.util.find_spec("coverage") is None:
        return None
    from .exec_env import run_command
    from .runners import detect_python_runner, target_python

    runner = detect_python_runner(root, load_config_safe(root))
    if runner is None:
        return None
    dataf = workdir / "covdata"
    jsonf = workdir / "cov.json"
    if runner.name == "pytest":
        inner = ["-m", "pytest", "-q", "-p", "no:cacheprovider"] + extra_files
    elif runner.name == "unittest":
        inner = ["-m", "unittest", "discover", "-q"]
    else:
        return None
    argv = [target_python(), "-m", "coverage", "run", "--data-file", str(dataf), "--source", "."] + inner
    res = run_command(argv, root, timeout=timeout)
    if res.exit_code not in (0, 1, 5):
        return None
    res2 = run_command(
        [target_python(), "-m", "coverage", "json", "-o", str(jsonf), "--data-file", str(dataf)],
        root,
        timeout=60,
    )
    if not res2.ok or not jsonf.exists():
        return None
    try:
        data = json.loads(jsonf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    out: dict[str, dict] = {}
    for raw_path, info in (data.get("files") or {}).items():
        rel = raw_path.replace("\\", "/")
        rel_norm = rel[len(str(root).replace("\\", "/")) + 1 :] if rel.startswith(str(root).replace("\\", "/")) else rel
        out[rel_norm] = {"lines": set(info.get("executed_lines", []))}
    return out


def load_config_safe(root: Path) -> Config:
    try:
        return load_config(root)
    except Exception:
        return Config(root=root)


def _last_line(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    lines = [l for l in stripped.splitlines() if l.strip()]
    return lines[-1][:300] if lines else ""


_MUTATIONS = (
    ("inverted comparison", lambda s: s.replace("==", "!=", 1)),
    ("tightened ordering", lambda s: _swap_once(s, "<=", "<")),
    ("addition to subtraction", lambda s: s.replace(" + ", " - ", 1)),
    ("flipped boolean return", lambda s: _flip_bool(s)),
    ("bumped integer literal", lambda s: _bump_int(s)),
)


def _swap_once(text: str, a: str, b: str) -> str:
    if a in text:
        return text.replace(a, b, 1)
    return text.replace(b, a + "=", 1) if b in text else text


def _flip_bool(text: str) -> str:
    if "return True" in text:
        return text.replace("return True", "return False", 1)
    if "return False" in text:
        return text.replace("return False", "return True", 1)
    return text


def _bump_int(text: str) -> str:
    m = re.search(r"(?<![\w.])(\d+)(?![\w.])", text)
    if not m:
        return text
    return text[: m.start()] + str(int(m.group(1)) + 1) + text[m.end() :]


def validate_with_mutations(
    root: Path,
    func: FunctionInfo,
    candidate_src: str,
    framework: str,
    timeout: float,
    workdir: Path,
    max_mutants: int = 4,
) -> tuple[bool, str]:
    """Shadow-copy mutation validation (Python targets only).

    Copies the whole repository (minus VCS/dependency dirs) into temp, applies
    one text-level mutation to the function's own source segment, and reruns
    the candidate against the copy. A candidate that survives every applied
    mutant is discarded as weak: it executes lines but pins no behaviour.
    """
    target_abs = root / func.file.replace("/", '/')
    try:
        original = target_abs.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"unreadable target file: {type(exc).__name__}"
    if original.count(func.source) != 1:
        return False, "function source segment not uniquely located for mutation"

    ignore = shutil.ignore_patterns(
        ".git", "__pycache__", "node_modules", ".venv", "venv",
        ".testwright*", ".pytest_cache", "*.egg-info",
    )
    shadow = Path(workdir) / "mutant-shadow"
    if shadow.exists():
        shutil.rmtree(shadow)
    try:
        shutil.copytree(root, shadow, ignore=ignore, dirs_exist_ok=True)
    except shutil.Error as exc:
        return False, f"could not create the mutation shadow copy: {exc}"
    shadow_file = shadow / func.file.replace("/", '/')
    cand_dir = workdir / "candidate"
    cand_dir.mkdir(parents=True, exist_ok=True)
    ext = ".py"
    cand_path = cand_dir / f"tw_mutant_candidate{ext}"

    applied = 0
    killed = False
    detail = ""
    for label, mutator in _MUTATIONS:
        if applied >= max_mutants or killed:
            break
        mutated_segment = mutator(func.source)
        if mutated_segment == func.source:
            continue
        mutated_file = original.replace(func.source, mutated_segment, 1)
        shadow_file.write_text(mutated_file, encoding="utf-8")
        mode = "pytest" if framework != "unittest" else "unittest"
        cand_path.write_text(candidate_src, encoding="utf-8")
        code, out, err = _run_bootstrap(
            mode, cand_path, shadow, [shadow], timeout, workdir
        )
        applied += 1
        if code == 1:
            killed = True
            detail = f"mutation '{label}' was detected by the test"
        elif code == 0:
            detail = f"survived mutation '{label}'"
        else:
            detail = f"inconclusive under mutation '{label}' ({code})"
    return killed, detail

@dataclass
class PipelineResult:
    root: Path
    units: list[UnitOutcome] = field(default_factory=list)
    generated: list[dict] = field(default_factory=list)  # rendered file records
    discards: list[DiscardRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    coverage_before: dict | None = None
    coverage_after: dict | None = None
    coverage_method: str = "not measured"
    skipped_functions: list[tuple[str, str]] = field(default_factory=list)

    def counts(self) -> dict:
        kept = sum(len(u.kept) for u in self.units)
        return {
            "functions_targeted": len({t.function_id for u in self.units for t in u.kept}
                                     | {d.function_id for d in self.discards}),
            "tests_generated": kept,
            "tests_discarded": len(self.discards),
            "mutation_validated": sum(1 for u in self.units for t in u.kept if t.mutation_validated),
        }


def _render_unit(unit, kept_names: set[str]) -> str:
    """Render a unit keeping only tests whose names survived verification."""
    from .generate.template_js import js_render

    if getattr(unit, "language", "") == "javascript":
        return js_render(unit, kept_names)
    tests = [t for t in unit.tests if t.name in kept_names]
    header = "\n".join(unit.header_lines).rstrip("\n")
    body = "\n\n\n".join(t.code.rstrip() for t in tests)
    return header + "\n\n\n" + body + "\n"

# __PIPELINE_PART5__
