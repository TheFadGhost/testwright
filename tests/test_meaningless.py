"""Meaninglessness detector: reject trivially-passing tests, accept real ones."""

import textwrap

from testwright.meaningless import check_python_test, check_js_test


def py(body: str) -> str:
    return textwrap.dedent(body)


MUST_REJECT = [
    "def test_a():\n    assert True\n",
    "def test_b():\n    x = 1\n    assert x == x\n",
    "def test_c():\n    assert 1 == 1\n",
    "def test_d():\n    # TODO real case\n    assert f() is not None\n",
    "def test_e():\n    result = f(2)\n    pass\n",
]

MUST_ACCEPT = [
    "def test_ok():\n    result = add(1, 2)\n    assert result == 3\n",
    "def test_empty():\n    result = split(9, 0)\n    assert result == []\n",
]


def test_rejects_trivial_set():
    for src in MUST_REJECT:
        verdict = check_python_test(py(src))
        assert not verdict.meaningful, src


def test_accepts_legitimate_simple_tests():
    for src in MUST_ACCEPT:
        verdict = check_python_test(py(src))
        assert verdict.meaningful, (src, verdict.reason)


def test_unittest_style_assertions_accepted():
    src = py(
        """
        class TestG(unittest.TestCase):
            def test_two(self):
                result = g(2)

                self.assertEqual(result, 4)
        """
    )
    assert check_python_test(src).meaningful


def test_reasons_are_actionable():
    v = check_python_test("def test_x():\n    assert True\n")
    assert "assertion" in v.reason


def test_js_detector():
    good = (
        "it('adds', () => {\n"
        "  const result = add(1, 2);\n"
        "\n"
        "  expect(result).toEqual(3);\n"
        "});\n"
    )
    trivial = "it('ok', () => {\n  expect(true).toBe(true);\n});\n"
    empty = "it('calls', () => {\n  add(1, 2);\n});\n"
    assert check_js_test(good).meaningful
    assert not check_js_test(trivial).meaningful
    assert not check_js_test(empty).meaningful
