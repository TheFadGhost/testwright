"""JavaScript/TypeScript analyzer tests against fixture sources."""

import textwrap
from pathlib import Path

from testwright.analyze.javascript_analyzer import JavaScriptAnalyzer


def analyze(tmp_path: Path, source: str, name: str = "m.js"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(source), encoding="utf-8")
    return JavaScriptAnalyzer().analyze_file(p, tmp_path)


def by_name(mod, qualname):
    return {f.qualname: f for f in mod.functions}[qualname]


def test_functions_arrows_classes(tmp_path):
    mod = analyze(
        tmp_path,
        '''
        /** Adds. */
        export function add(a, b = 2) {
          if (a < 0) throw new Error("neg");
          return a + b;
        }

        const mul = (a, b) => a * b;

        const wrap = (prefix) => (text) => prefix + text;

        class Bag extends Base {
          get size() { return this._n; }
          static make(n) { return new Bag(); }
          async fill(items) { for (const i of items) {} }
        }
        ''',
    )
    add = by_name(mod, "add")
    assert add.exported and add.params[1].default == "2"
    assert add.raises == ["Error"] and add.complexity >= 2
    assert add.docstring == "Adds."
    assert by_name(mod, "mul").params[0].name == "a"
    assert not by_name(mod, "mul").exported  # no export keyword on this const
    bag = by_name(mod, "Bag.size")
    assert bag.is_method and bag.is_property
    assert by_name(mod, "Bag.make").is_static
    assert by_name(mod, "Bag.fill").is_async


def test_typescript_annotations(tmp_path):
    mod = analyze(
        tmp_path,
        '''
        export function clamp<T extends number>(value: T, lo: number, hi: number): T {
          return value < lo ? lo : (value > hi ? hi : value);
        }
        ''',
        name="m.ts",
    )
    fn = by_name(mod, "clamp")
    assert fn.return_type == "T"
    kinds = [p.type_annotation for p in fn.params]
    assert kinds[1:] == ["number", "number"]
    assert fn.complexity >= 3


def test_strings_and_regex_do_not_create_symbols(tmp_path):
    mod = analyze(
        tmp_path,
        '''
        const s = "function fake() { if (x) {} }";
        const r = /class Foo {}/;
        const t = `nested ${a ? "b" : "c"} done`;
        export function real() { return s.length + r.source.length; }
        ''',
    )
    names = {f.qualname for f in mod.functions}
    assert names == {"real"}


def test_unterminated_string_yields_parse_error(tmp_path):
    mod = analyze(tmp_path, 'const s = "oops;\nfunction gone() {}\n')
    assert mod.parse_error and "unterminated string" in mod.parse_error
    assert mod.functions == []


def test_commonjs_exports(tmp_path):
    mod = analyze(
        tmp_path,
        '''
        function sum(values) { return values.reduce((a, b) => a + b, 0); }
        module.exports = { sum };
        ''',
    )
    assert by_name(mod, "sum").exported
    imports = [(i.names, i.module) for i in mod.imports]
    assert ("sum", None) not in imports
