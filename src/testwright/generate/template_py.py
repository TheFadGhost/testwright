"""Deterministic Python template generator (pytest and unittest styles)."""

from __future__ import annotations

from ..conventions import Conventions
from ..model import CodeModel, FunctionInfo
from ..runners import TestRunner
from . import CandidateTest, GenerationUnit, GeneratorBackend
from .probe import ProbeCase, ProbeResult


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
        # widen import lines to every symbol exercised by the unit's tests
        for fname, unit in by_file.items():
            resolved = _module_import(model, next(
                f for f, _ in targets if f.file == fname
            ))
            if resolved is None:
                continue
            dotted, _ = resolved
            symbols = sorted({fid.split("::", 1)[1].split(".")[0]
                              for t in unit.tests
                              for fid in [t.function_id]})
            framework = unit.framework
            doc = f'"""Tests for {dotted}."""'
            if framework == "unittest":
                unit.header_lines = [
                    doc, "", "import unittest", "",
                    f"from {dotted} import {', '.join(symbols)}", "",
                ]
            else:
                unit.header_lines = [doc, "", f"from {dotted} import {', '.join(symbols)}", ""]
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
        usable = [(c, r) for c, r in cases if r.ok and r.repr_ is not None]
        if not usable:
            return out
        call_target, prefix_expr = self._call_shape(func)
        if call_target is None:
            return out
        multi = len(usable) > 1
        base = f"test_{func.qualname.replace('.', '_')}"
        if framework != "unittest":
            for case, result in usable:
                args_src = ", ".join(case.args)
                name = base if not multi else f"{base}_with_{case.slug}"
                code = (
                    f"def {name}():\n"
                    f"    result = {prefix_expr}{call_target}({args_src})\n"
                    f"\n"
                    f"    assert result == {result.repr_}\n"
                )
                out.append(CandidateTest(name=name, code=code, function_id=func.id))
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
                f"        self.assertEqual(result, {result.repr_})\n"
            )
            method_names.append(m_name)
        cls = _test_class(base)
        body = "\n".join(m.rstrip() for m in methods)
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
