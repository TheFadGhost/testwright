"""Deterministic Python template generator (pytest and unittest styles)."""

from __future__ import annotations

import re

from ..conventions import Conventions
from ..model import CodeModel, FunctionInfo
from . import CandidateTest, GenerationUnit, GeneratorBackend
from .probe import ProbeCase, ProbeResult, repr_is_comparable

_FLOATY = re.compile(r"-?\d+\.\d{11,}")


def _assert_py(expected: str, framework: str) -> str:
    """Render the assertion line; long float reprs get tolerance matchers."""
    if framework == "unittest":
        if _FLOATY.fullmatch(expected):
            return f"        self.assertAlmostEqual(result, {expected}, places=10)\n"
        return f"        self.assertEqual(result, {expected})\n"
    if _FLOATY.fullmatch(expected):
        return f"    assert result == pytest.approx({expected})\n"
    return f"    assert result == {expected}\n"


def _module_import(model: CodeModel, func: FunctionInfo) -> tuple[str, str] | None:
    """Return (dotted_module, top_symbol) or None when not derivable."""
    mod = model.modules.get(func.file)
    if mod is None:
        return None
    dotted = mod.package
    if not dotted:
        stem = func.file[:-3] if func.file.endswith(".py") else func.file
        parts = stem.split("/")
        dotted = ".".join(parts)
        if "/" in func.file:
            return None  # unpackaged nested module: not importable reliably
    top = func.qualname.split(".")[0]
    return dotted, top


class PythonTemplateBackend(GeneratorBackend):
    name = "template"

    def generate(
        self,
        model: CodeModel,
        conventions: Conventions,
        targets: list[tuple[FunctionInfo, list[tuple[ProbeCase, ProbeResult]]]],
        probes: dict | None = None,
    ) -> list[GenerationUnit]:
        by_file: dict[str, GenerationUnit] = {}
        order: list[str] = []
        for func, cases in targets:
            unit = self._unit_for(by_file, order, model, conventions, func)
            if unit is None:
                continue
            tests = self._tests_for(func, cases, conventions.framework or "pytest")
            unit.tests.extend(tests)
            if func.file not in order:
                order.append(func.file)
        # widen import lines so every candidate can execute during verification
        for fname, unit in by_file.items():
            first = next((f for f, _ in targets if f.file == fname), None)
            if first is None:
                continue
            resolved = _module_import(model, first)
            if resolved is None:
                continue
            dotted, _ = resolved
            symbols = sorted({fid.split("::", 1)[1].split(".")[0]
                              for t in unit.tests
                              for fid in [t.function_id]})
            needs_pytest = any("pytest." in t.code for t in unit.tests)
            unit.header_lines = _header_lines(dotted, symbols, unit.framework, needs_pytest)
        return [by_file[f] for f in order]

    def _unit_for(
        self,
        by_file: dict,
        order: list,
        model: CodeModel,
        conventions: Conventions,
        func: FunctionInfo,
    ):
        if func.file in by_file:
            return by_file[func.file]
        resolved = _module_import(model, func)
        if resolved is None:
            return None
        dotted, symbol = resolved
        framework = conventions.framework or "pytest"
        doc = f'"""Tests for {dotted}."""'
        header: list[str]
        if framework == "unittest":
            header = [doc, "", "import unittest", "", f"from {dotted} import {symbol}", ""]
        else:
            header = [doc, "", f"from {dotted} import {symbol}", ""]
        mod = model.modules[func.file]
        test_rel = None
        if conventions.test_file_pattern:
            from ..conventions import test_file_path

            candidate = test_file_path(conventions, func.file)
            if not candidate.endswith(func.file.rsplit("/", 1)[-1]):
                # pattern rendered a path that does not sit beside its module
                pass
            test_rel = candidate
        if test_rel is None or test_rel == func.file:
            test_rel = self._default_test_file(func.file, mod.file.rsplit("/", 1)[-1][:-3])
        unit = GenerationUnit(
            target_file=func.file,
            test_file=test_rel,
            language="python",
            framework=framework,
            header_lines=header,
        )
        by_file[func.file] = unit
        return unit

    @staticmethod
    def _default_test_file(source_rel: str, stem: str) -> str:
        parent = "/".join(source_rel.split("/")[:-1])
        name = f"test_{stem}.py"
        return f"{parent}/{name}" if parent else name

    def _tests_for(
        self,
        func: FunctionInfo,
        cases: list[tuple[ProbeCase, ProbeResult]],
        framework: str,
    ) -> list[CandidateTest]:
        out: list[CandidateTest] = []
        usable = [
            (c, r)
            for c, r in cases
            if r.ok and repr_is_comparable(r.repr_)
        ]
        if not usable:
            return out
        call_target, prefix_expr = self._call_shape(func)
        if call_target is None:
            return out
        multi = len(usable) > 1
        base = f"test_{func.qualname.replace('.', '_')}"
        raised = [
            (c, r.error_type)
            for c, r in cases
            if not r.ok
            and r.error_type
            and r.error_type
            not in ("TimeoutError", "NoOutput", "BadProbeOutput", "ImportError")
        ]
        if framework != "unittest":
            for case, result in usable:
                args_src = ", ".join(case.args)
                name = base if not multi else f"{base}_with_{case.slug}"
                code = (
                    f"def {name}():\n"
                    f"    result = {prefix_expr}{call_target}({args_src})\n"
                    f"\n"
                    f"{_assert_py(result.repr_ or '', framework)}"
                )
                out.append(CandidateTest(name=name, code=code, function_id=func.id))
            seen_errors: set[str] = set()
            for _c, err in raised:
                if err in seen_errors:
                    continue
                seen_errors.add(err)
                args_src = ", ".join(_c.args)
                code = (
                    f"def {base}_raises_{err}():\n"
                    f"    with pytest.raises({err}):\n"
                    f"        {prefix_expr}{call_target}({args_src})\n"
                )
                out.append(
                    CandidateTest(name=f"{base}_raises_{err}", code=code, function_id=func.id)
                )
            return out
        methods: list[str] = []
        method_names: list[str] = []
        for case, result in usable:
            args_src = ", ".join(case.args)
            m_name = base if not multi else f"{base}_with_{case.slug}"
            methods.append(
                f"    def {m_name}(self):\n"
                f"        result = {prefix_expr}{call_target}({args_src})\n"
                f"\n"
                f"{_assert_py(result.repr_ or '', framework)}"
            )
            method_names.append(m_name)
        seen_errors_u: set[str] = set()
        for case_c, err in raised:
            if err in seen_errors_u:
                continue
            seen_errors_u.add(err)
            args_src = ", ".join(case_c.args)
            methods.append(
                f"    def {base}_raises_{err}(self):\n"
                f"        with self.assertRaises({err}):\n"
                f"            {prefix_expr}{call_target}({args_src})\n"
            )
            method_names.append(f"{base}_raises_{err}")
        cls = _test_class(base)
        body = "\n\n".join(m.rstrip("\n") for m in methods)
        code = f"class {cls}(unittest.TestCase):\n{body}\n"
        out.append(
            CandidateTest(name=f"{cls} ({', '.join(method_names)})", code=code, function_id=func.id)
        )
        return out

    @staticmethod
    def _call_shape(func: FunctionInfo) -> tuple[str | None, str]:
        """Return (callable expression, prefix expression) or (None, ...)."""
        if func.is_async or func.is_property:
            return None, ""
        if not func.is_method:
            return func.name, ""
        cls = func.class_name or ""
        if func.is_static or func.is_classmethod:
            return f"{cls}.{func.name}", ""
        return f"{cls}().{func.name}", ""


def _test_class(test_name: str) -> str:
    raw = test_name.replace("test_", "", 1)
    parts = raw.split("_")
    return "Test" + "".join(p.capitalize() for p in parts)


def _header_lines(dotted: str, symbols: list[str], framework: str, needs_pytest: bool) -> list[str]:
    doc = f'"""Tests for {dotted}."""'
    imports = []
    if framework == "unittest":
        imports.append("import unittest")
    elif needs_pytest:
        imports.append("import pytest")
    imports.append(f"from {dotted} import {', '.join(symbols)}")
    return [doc, "", *imports, ""]


def finalize_unit(unit, kept, main_guard: bool) -> str:
    """Render the final file with imports narrowed to kept tests only."""
    dotted = unit.target_file
    stem = dotted[:-3] if dotted.endswith(".py") else dotted
    dotted_mod = stem.replace("/", ".")
    symbols = sorted({fid.split("::", 1)[1].split(".")[0] for fid in {t.function_id for t in kept}})
    body_codes = [t.code.rstrip("\n") for t in kept]
    joined = "\n".join(body_codes)
    needs_pytest = "pytest." in joined
    lines = _header_lines(dotted_mod, symbols, unit.framework, needs_pytest)
    head = "\n".join(lines).rstrip("\n")
    if unit.framework == "unittest":
        blocks = "\n\n\n".join(body_codes)
        out = head + "\n\n\n" + blocks + "\n"
        if main_guard:
            out += '\n\nif __name__ == "__main__":\n    unittest.main()\n'
        return out
    return head + "\n\n\n" + "\n\n\n".join(body_codes) + "\n"
