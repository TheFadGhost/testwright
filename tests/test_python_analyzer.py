"""Analyzer tests against fixture source files (Python)."""

import textwrap
from pathlib import Path

from testwright.analyze.python_analyzer import PythonAnalyzer


def analyze(tmp_path: Path, source: str):
    pkg = tmp_path / "mod.py"
    pkg.write_text(textwrap.dedent(source), encoding="utf-8")
    return PythonAnalyzer().analyze_file(pkg, tmp_path)


def by_name(mod, qualname):
    return {f.qualname: f for f in mod.functions}[qualname]


def test_functions_params_types_raises_complexity(tmp_path):
    mod = analyze(
        tmp_path,
        '''
        def grade(score: int, extra: float = 0.0) -> str:
            if score < 0:
                raise ValueError("bad")
            return "ok" if score > 5 else "meh"
        ''',
    )
    fn = by_name(mod, "grade")
    assert fn.line >= 1 and fn.end_line >= fn.line
    assert [p.name for p in fn.params] == ["score", "extra"]
    assert fn.params[0].type_annotation == "int"
    assert fn.params[1].default == "0.0"
    assert fn.return_type == "str"
    assert fn.raises == ["ValueError"]
    assert fn.complexity == 3  # base + if + ifexp
    assert fn.exported


def test_nested_and_async_and_decorators(tmp_path):
    mod = analyze(
        tmp_path,
        '''
        import functools

        def outer(n):
            def helper(k):
                return k * 2
            return helper(n)

        @functools.cache
        async def fetch(url: str):
            return url

        class Widget:
            @staticmethod
            def make():
                return Widget()

            @property
            def size(self):
                return self._s
        ''',
    )
    assert by_name(mod, "outer.helper").name == "helper"
    fetch = by_name(mod, "fetch")
    assert fetch.is_async and fetch.decorators == ["functools.cache"]
    make = by_name(mod, "Widget.make")
    assert make.is_method and make.is_static and make.class_name == "Widget"
    size = by_name(mod, "Widget.size")
    assert size.is_property
    cls = mod.classes[0]
    assert cls.name == "Widget" and len(cls.methods) == 2


def test_exports_all_and_private(tmp_path):
    mod = analyze(
        tmp_path,
        '''
        __all__ = ["Public"]

        def Public(): ...
        def _hidden(): ...
        ''',
    )
    assert by_name(mod, "Public").exported
    assert not by_name(mod, "_hidden").exported


def test_positional_only_and_vararg(tmp_path):
    mod = analyze(
        tmp_path,
        '''
        def f(a, /, b, *args, c=1, **kw):
            return a + b
        ''',
    )
    kinds = {p.name: p.kind for p in by_name(mod, "f").params}
    assert kinds == {
        "a": "positional_only",
        "b": "positional",
        "args": "vararg",
        "c": "keyword_only",
        "kw": "kwarg",
    }


def test_unusual_but_valid_code(tmp_path):
    mod = analyze(
        tmp_path,
        '''
        lambda_result = (lambda x: x)(1)

        def tricky():
            s = "def fake(): pass"
            return {"def": s}

        async def gen():
            yield 1
        ''',
    )
    assert by_name(mod, "tricky").complexity >= 1
    names = {f.qualname for f in mod.functions}
    assert "outer" not in names  # different fixture
    assert "tricky" in names and "gen" in names
