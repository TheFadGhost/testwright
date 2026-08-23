"""Deterministic JavaScript template generator (jest/vitest styles)."""

from __future__ import annotations

import json as jsonlib
import re

from ..conventions import Conventions
from ..model import CodeModel, FunctionInfo
from . import CandidateTest, GenerationUnit, GeneratorBackend
from .probe import ProbeCase, ProbeResult, repr_is_comparable

_FLOATY = re.compile(r"-?\d+\.\d{11,}")
_SAFE_PATH = re.compile(r"[A-Za-z0-9_\-./]+")


def _rel_import(test_rel: str, source_rel: str) -> str:
    test_parts = test_rel.split("/")[:-1]
    src_parts = source_rel.split("/")
    src_name = src_parts[-1]
    depth = 0
    while depth < len(src_parts) - 1 and depth < len(test_parts):
        if test_parts[depth] == src_parts[depth]:
            depth += 1
        else:
            break
    ups = [".."] * (len(test_parts) - depth)
    downs = [p for p in src_parts[:-1][depth:]]
    parts = ups + downs + [src_name]
    path = "/".join(parts)
    if not path.startswith("."):
        path = "./" + path
    return path


def _expect_line(expected: str) -> str:
    if _FLOATY.fullmatch(expected):
        return f"    expect(result).toBeCloseTo({expected}, 10);"
    return f"    expect(result).toEqual({expected});"


def _js_str(text: str) -> str:
    """A safely escaped double-quoted JS string literal."""
    return jsonlib.dumps(text)


class JavaScriptTemplateBackend(GeneratorBackend):
    name = "template"

    def generate(
        self,
        model: CodeModel,
        conventions: Conventions,
        targets: list[tuple[FunctionInfo, list[tuple[ProbeCase, ProbeResult]]]],
        probes: dict | None = None,
    ) -> list[GenerationUnit]:
        framework = conventions.framework or "jest"
        by_file: dict[str, GenerationUnit] = {}
        for func, cases in targets:
            mod = model.modules.get(func.file)
            if mod is None or mod.parse_error:
                continue
            esm = bool(
                re.search(r"\bexport\s+", "\n".join(f.source for f in mod.functions if f.source))
            )
            if framework == "jest" and esm:
                continue  # jest without a babel setup cannot execute ESM candidates
            usable = [(c, r) for c, r in cases if r.ok and repr_is_comparable(r.repr_)]
            raised = [
                (c, r.error_type)
                for c, r in cases
                if not r.ok
                and r.error_type
                and r.error_type
                not in ("TimeoutError", "NoOutput", "BadProbeOutput", "ImportError", "NotFound")
            ]
            if not usable:
                continue
            unit = by_file.get(func.file)
            if unit is None:
                stem = func.file.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                parent = "/".join(func.file.split("/")[:-1])
                suffix = ".test.js"
                test_rel = (
                    f"{parent}/__tests__/{stem}{suffix}"
                    if conventions.layout == "__tests__" and parent
                    else f"{parent}/{stem}{suffix}" if parent else f"{stem}{suffix}"
                )
                import_path = _rel_import(test_rel, func.file)
                if not _SAFE_PATH.fullmatch(import_path) or not _SAFE_PATH.fullmatch(test_rel):
                    continue  # unsafe names are skipped rather than escaped into code
                symbols = sorted(
                    {f.qualname.split(".")[0] for f, _ in targets if f.file == func.file}
                )
                imp = f"const {{ {', '.join(symbols)} }} = require('{import_path}');"
                unit = GenerationUnit(
                    target_file=func.file,
                    test_file=test_rel,
                    language="javascript",
                    framework=framework,
                    header_lines=[imp],
                )
                by_file[func.file] = unit
            for case, result in usable:
                cand = self._candidate(func, case, result)
                if cand:
                    unit.tests.append(cand)
            seen_errors: set[str] = set()
            for case_c, err in raised:
                if err in seen_errors:
                    continue
                seen_errors.add(err)
                cand = self._raises_candidate(func, case_c, err)
                if cand:
                    unit.tests.append(cand)
        return list(by_file.values())

    @staticmethod
    def _candidate(func: FunctionInfo, case: ProbeCase, result: ProbeResult) -> CandidateTest | None:
        if func.is_async:
            return None
        expected = result.repr_
        if expected is None or not repr_is_comparable(expected):
            return None
        try:
            jsonlib.loads(expected)
        except (jsonlib.JSONDecodeError, TypeError):
            return None
        call_target = func.qualname
        args_src = ", ".join(_js_args(case.args))
        it_name = _js_str(f"{func.qualname}({args_src})")
        code = (
            f"  it({it_name}, () => {{\n"
            f"    const result = {call_target}({args_src});\n"
            f"\n"
            f"{_expect_line(expected)}\n"
            f"  }});"
        )
        return CandidateTest(name=it_name, code=code, function_id=func.id)

    @staticmethod
    def _raises_candidate(func: FunctionInfo, case: ProbeCase, err: str) -> CandidateTest | None:
        if func.is_async or not re.fullmatch(r"[A-Za-z_$][\w$]*", err):
            return None
        args_src = ", ".join(_js_args(case.args))
        it_name = _js_str(f"{func.qualname}({args_src}) throws {err}")
        code = (
            f"  it({it_name}, () => {{\n"
            f"    expect(() => {func.qualname}({args_src})).toThrow({err});\n"
            f"  }});"
        )
        return CandidateTest(name=it_name, code=code, function_id=func.id)


def _js_args(args: list[str]) -> list[str]:
    out = []
    for a in args:
        if a == "True":
            out.append("true")
        elif a == "False":
            out.append("false")
        elif a == "None":
            out.append("null")
        else:
            out.append(a)
    return out


def js_render(unit: GenerationUnit, kept_names: set[str]) -> str:
    lines: list[str] = []
    lines.extend(unit.header_lines)
    lines.append("")
    stem = unit.target_file.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    lines.append(f"describe({_js_str(stem)}, () => {{")
    body = "\n\n".join(t.code for t in unit.tests if t.name in kept_names)
    lines.append(body)
    lines.append("});")
    return "\n".join(lines) + "\n"
