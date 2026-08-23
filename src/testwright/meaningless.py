"""Meaninglessness detection: reject tests that pass while asserting nothing.

A generated test is meaningless when it contains no assertion, an assertion
that cannot fail, or no assertion that touches a value derived from exercising
the function under test. Detection is static (AST for Python, structural
scanning for JavaScript) so it runs before any process is spawned.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass


@dataclass
class MeaningVerdict:
    meaningful: bool
    reason: str | None = None


class _PythonTestVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.assert_count = 0
        self.trivial_asserts = 0
        self.bound_names: set[str] = set()
        self.assert_referenced_bound = False

    def visit_Assign(self, node: ast.Assign) -> None:
        for t in node.targets:
            if isinstance(t, ast.Name):
                self.bound_names.add(t.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self.bound_names.add(node.target.id)
        self.generic_visit(node)

    def _check_compare(self, node: ast.Assert) -> bool:
        test = node.test
        if isinstance(test, ast.Constant):
            return True  # assert True / assert "x"
        if isinstance(test, ast.Compare) and len(test.ops) == 1 and len(test.comparators) == 1:
            left, right = test.left, test.comparators[0]
            if isinstance(left, ast.Name) and isinstance(right, ast.Name):
                if left.id == right.id:
                    return True
            try:
                if ast.dump(left) == ast.dump(right):
                    return True
            except Exception:
                pass
        return False

    def visit_Assert(self, node: ast.Assert) -> None:
        self.assert_count += 1
        names_in_assert = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if names_in_assert & self.bound_names:
            self.assert_referenced_bound = True
        if self._check_compare(node):
            self.trivial_asserts += 1

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = getattr(func, "attr", None) or (
            func.id if isinstance(func, ast.Name) else ""
        )
        if isinstance(name, str) and name.startswith("assert") and len(name) > 6:
            self.assert_count += 1
            arg_names = {
                n.id
                for a in node.args
                for n in ast.walk(a)
                if isinstance(n, ast.Name)
            }
            if arg_names & self.bound_names:
                self.assert_referenced_bound = True
            if len(node.args) == 2 and all(
                isinstance(a, ast.Name) for a in node.args
            ):
                if node.args[0].id == node.args[1].id:
                    self.trivial_asserts += 1
            if any(isinstance(a, ast.Constant) and a.value is True for a in node.args) and name in (
                "assertTrue",
                "assert",
            ):
                self.trivial_asserts += 1
        self.generic_visit(node)


def check_python_test(source: str) -> MeaningVerdict:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return MeaningVerdict(False, f"generated test does not parse ({exc.lineno})")
    visitor = _PythonTestVisitor()
    visitor.visit(tree)
    if "TODO" in source or "FIXME" in source:
        return MeaningVerdict(False, "contains TODO/FIXME marker")
    if visitor.assert_count == 0:
        return MeaningVerdict(False, "no assertion in test body")
    if visitor.trivial_asserts == visitor.assert_count:
        return MeaningVerdict(False, "every assertion can trivially pass")
    if not visitor.assert_referenced_bound:
        return MeaningVerdict(
            False, "assertions never reference a value derived from the call under test"
        )
    return MeaningVerdict(True)


def check_js_test(source: str) -> MeaningVerdict:
    stripped = re.sub(r"//[^\n]*", "", source)
    stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.DOTALL)
    if "TODO" in source or "FIXME" in source:
        return MeaningVerdict(False, "contains TODO/FIXME marker")
    # expect(...) with a single nesting level of parens inside
    expect_calls = re.findall(r"expect\s*\(((?:[^()]|\([^()]*\))*)\)\s*\.\s*(\w+)\s*\(", source)
    throws = re.findall(r"\.\s*(?:toThrow|toThrowError)\s*\(", source)
    if not expect_calls and not throws and not re.search(r"\bassert\b", source):
        return MeaningVerdict(False, "no assertion in test body")
    nontrivial = len(throws)
    for target, matcher in expect_calls:
        t = target.strip()
        if matcher in (
            "toBeCloseTo",
            "toBeGreaterThan",
            "toBeGreaterThanOrEqual",
            "toBeLessThan",
            "toBeLessThanOrEqual",
            "toContain",
            "toMatch",
            "toHaveLength",
            "toThrow",
            "toThrowError",
        ):
            nontrivial += 1
            continue
        trivial = t in ("true", "false", "null", "undefined")
        if matcher in ("toBe", "toEqual", "toStrictEqual", "toBeNull", "toBeTruthy") and not trivial:
            nontrivial += 1
    plain_asserts = re.findall(r"assert\.(\w+)\s*\(([^()]*)\)", source)
    for _name, args in plain_asserts:
        parts = [a.strip() for a in args.split(",")]
        if len(parts) >= 2 and parts[0] != parts[1]:
            nontrivial += 1
    if nontrivial == 0:
        return MeaningVerdict(False, "every assertion can trivially pass")
    return MeaningVerdict(True)
