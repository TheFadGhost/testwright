"""Deterministic JavaScript template generator (jest/vitest styles)."""

from __future__ import annotations

import json as jsonlib
import re

from . import CandidateTest, GenerationUnit, GeneratorBackend
from ..conventions import Conventions
from ..model import CodeModel, FunctionInfo
from .probe import ProbeCase, ProbeResult


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
    downs = [p for p in src_parts[:len(src_parts) - 1][depth:]] if False else []
    downs = [p for p in src_parts[:-1][depth:]]
    parts = ups + downs + [src_name]
    path = "/".join(parts)
    if not path.startswith("."):
        path = "./" + path
    return path


def _is_esm(source: str) -> bool:
    return bool(re.search(r"^\s*export\s+(const|function|class|default|\{)", source, re.MULTILINE))


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
        units: list[GenerationUnit] = []
        by_file: dict[str, GenerationUnit] = {}
        for func, cases in targets:
            mod = model.modules.get(func.file)
            if mod is None or mod.parse_error:
                continue
            esm = _is_esm(mod.source or "") or any(
                i.module and not i.module.startswith(".") and False for i in []
            )
            esm = esm or bool(re.search(r"\bexport\s+", mod.source or ""))
            if framework == "jest" and esm:
                continue  # jest without babel cannot execute ESM candidates
            usable = [(c, r) for c, r in cases if r.ok and r.repr_ is not None]
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
                names = sorted({t.name for t in []})
                symbols = sorted(
                    {f.qualname.split(".")[0] for f, _ in targets if f.file == func.file}
                )
                if esm:
                    imp = f"import {{ {', '.join(symbols)} }} from '{import_path}';"
                else:
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
        units = list(by_file.values())
        return units

    @staticmethod
    def _candidate(func: FunctionInfo, case: ProbeCase, result: ProbeResult) -> CandidateTest | None:
        if func.is_async:
            return None
        expected = result.repr_
        if expected is None:
            return None
        try:
            jsonlib.loads(expected)
        except (jsonlib.JSONDecodeError, TypeError):
            return None
        call_target = func.qualname
        args_src = ", ".join(_js_args(case.args))
        it_name = f"{func.qualname}({args_src})"
        code = (
            f"  it('{it_name}', () => {{\n"
            f"    const result = {call_target}({args_src});\n"
            f"\n"
            f"    expect(result).toEqual({expected});\n"
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
        elif a == "[1, 2, 3]":
            out.append("[1, 2, 3]")
        else:
            out.append(a)
    return out


def js_render(unit: GenerationUnit) -> str:
    lines: list[str] = []
    lines.extend(unit.header_lines)
    lines.append("")
    stem = unit.target_file.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    lines.append(f"describe('{stem}', () => {{")
    body = "\n\n".join(t.code for t in unit.tests)
    lines.append(body)
    lines.append("});")
    return "\n".join(lines) + "\n"
