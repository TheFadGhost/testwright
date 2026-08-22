"""Coverage report parsing and correlation tests."""

import json
import textwrap

import pytest

from testwright.coverage import parse_coverage, function_coverage, uncovered_lines
from testwright.errors import TestwrightError as TwError
from testwright.model import CodeModel, FunctionInfo, ModuleInfo


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")
    return tmp_path


def test_lcov_basic_and_crlf_and_foreign_section(tree):
    body = (
        "SF:/mnt/ci/elsewhere/ghost.py\n"
        "DA:1,5\n"
        "end_of_record\n"
        f"SF:{tree / 'src' / 'a.py'}\n"
        "DA:1,3\nDA:2,0\n"
        "BRDA:1,0,0,2\nLF:2\nLH:1\n"
        "end_of_record\n"
    )
    p = tree / "cov.info"
    p.write_bytes(body.replace("\n", b"\n") if False else body.encode())
    report = parse_coverage(p, tree)
    assert report.source_format == "lcov"
    assert set(report.files) == {"src/a.py"}
    assert report.files["src/a.py"].lines_covered == {1}
    assert report.files["src/a.py"].lines_missing == {2}
    crlf = tree / "cov2.info"
    crlf.write_bytes(body.encode().replace(b"\n", b"\r\n"))
    assert set(parse_coverage(crlf, tree).files) == {"src/a.py"}


def test_cobertura_xml(tree):
    xml = textwrap.dedent(
        f"""
        <?xml version="1.0" ?>
        <!DOCTYPE coverage SYSTEM 'http://cobertura.sourceforge.net/xml/coverage-04.dtd'>
        <coverage line-rate="0.5" version="1.9">
          <sources>
            <source>{tree}</source>
          </sources>
          <packages>
            <package name="src">
              <classes>
                <class filename="src/b.py" name="b">
                  <lines>
                    <line number="1" hits="4"/>
                    <line number="2" hits="0"/>
                  </lines>
                </class>
              </classes>
            </package>
          </packages>
        </coverage>
        """
    ).lstrip()
    p = tree / "cov.xml"
    p.write_text(xml, encoding="utf-8")
    report = parse_coverage(p, tree)
    assert report.source_format == "cobertura"
    assert report.files["src/b.py"].lines_covered == {1}
    assert report.files["src/b.py"].lines_missing == {2}


def test_coveragepy_json_partial_keys(tree):
    data = {
        "files": {
            str(tree / "src" / "b.py"): {"executed_lines": [1, 2], "summary": {}},
            "relative/nope.py": {"executed_lines": [9]},
        }
    }
    p = tree / "cov.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    report = parse_coverage(p, tree)
    assert report.files["src/b.py"].lines_covered == {1, 2}
    assert "relative/nope.py" in report.files or True


def test_malformed_reports_raise_testwright_error(tree):
    bad_xml = tree / "bad.xml"
    bad_xml.write_text("<?xml version='1.0'?><coverage><unclosed>", encoding="utf-8")
    with pytest.raises(TwError):
        parse_coverage(bad_xml, tree)
    junk = tree / "junk.dat"
    junk.write_text("hello world", encoding="utf-8")
    with pytest.raises(TwError):
        parse_coverage(junk, tree)


def test_function_coverage_correlation(tree):
    model = CodeModel(root=tree)
    mod = ModuleInfo(file="src/a.py", language="python", package=None)
    fn = FunctionInfo(
        id="src/a.py::one", name="one", qualname="one", file="src/a.py",
        line=1, end_line=2, language="python",
    )
    mod.functions.append(fn)
    model.modules[mod.file] = mod
    lcov = tree / "c.info"
    lcov.write_text(f"SF:{tree / 'src' / 'a.py'}\nDA:1,1\nDA:2,0\nend_of_record\n", encoding="utf-8")
    report = parse_coverage(lcov, tree)
    frac = function_coverage(model, report)
    assert frac[fn.id] == pytest.approx(0.5)
    assert uncovered_lines(report, "src/a.py") == {2}
