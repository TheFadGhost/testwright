"""Python analyzer built on the stdlib ``ast`` module."""

from __future__ import annotations

import ast
from pathlib import Path

from ..fsutil import relpath_inside
from ..model import ClassInfo, FunctionInfo, ImportInfo, ModuleInfo, Parameter
from . import Analyzer


def _unparse(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _set_parents(tree: ast.AST) -> None:
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            setattr(child, "tw_parent", parent)


def _qualname(node: ast.AST) -> str:
    parts: list[str] = []
    cur = getattr(node, "tw_parent", None)
    while cur is not None and isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        parts.insert(0, cur.name)
        cur = getattr(cur, "tw_parent", None)
    parts.append(node.name)  # type: ignore[attr-defined]
    return ".".join(parts)


def _is_methodish(node: ast.AST) -> bool:
    """True when the nearest enclosing scope is a ClassDef."""
    cur = getattr(node, "tw_parent", None)
    while cur is not None and isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
        cur = getattr(cur, "tw_parent", None)
    return isinstance(cur, ast.ClassDef)


def _cyclomatic(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.ExceptHandler)):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            score += 1 + len(child.ifs)
        elif isinstance(child, (ast.IfExp, ast.Assert)):
            score += 1
    return score


def _raised_exceptions(node: ast.AST) -> list[str]:
    names: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Raise) and child.exc is not None:
            target = child.exc.func if isinstance(child.exc, ast.Call) else child.exc
            name = _unparse(target)
            if name:
                names.append(name.split("(")[0].split(".")[0])
    seen: set[str] = set()
    return [n for n in names if not (n in seen or seen.add(n))]


def _params(args: ast.arguments) -> list[Parameter]:
    out: list[Parameter] = []
    defaults = list(args.defaults)
    pos_args = list(args.posonlyargs) + list(args.args)
    pos_defaults = [None] * (len(pos_args) - len(defaults)) + defaults
    posonly_ids = {a.arg for a in args.posonlyargs}
    for arg, default in zip(pos_args, pos_defaults):
        out.append(
            Parameter(
                name=arg.arg,
                type_annotation=_unparse(arg.annotation),
                default=_unparse(default),
                kind="positional_only" if arg.arg in posonly_ids else "positional",
            )
        )
    if args.vararg:
        out.append(Parameter(name=args.vararg.arg, kind="vararg"))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        out.append(
            Parameter(
                name=arg.arg,
                type_annotation=_unparse(arg.annotation),
                default=_unparse(default),
                kind="keyword_only",
            )
        )
    if args.kwarg:
        out.append(Parameter(name=args.kwarg.arg, kind="kwarg"))
    return out


class PythonAnalyzer(Analyzer):
    language = "python"
    extensions = (".py",)

    def analyze_file(self, path: Path, root: Path) -> ModuleInfo:
        rel = relpath_inside(root, path)
        mod = ModuleInfo(file=rel, language="python", package=self._package(root, path))
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            mod.parse_error = f"syntax error at line {exc.lineno}"
            return mod
        except (OSError, UnicodeDecodeError) as exc:
            mod.parse_error = f"unreadable: {type(exc).__name__}"
            return mod

        mod.docstring = ast.get_docstring(tree)
        exports = self._all_exports(tree)
        lines = source.splitlines()

        for stmt in tree.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                if isinstance(stmt, ast.Import):
                    mod.imports.append(
                        ImportInfo(names=[a.name for a in stmt.names], module=None, line=stmt.lineno)
                    )
                else:
                    mod.imports.append(
                        ImportInfo(names=[a.name for a in stmt.names], module=stmt.module, line=stmt.lineno)
                    )

        _set_parents(tree)

        func_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef] = [
            n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for fn_node in func_nodes:
            qual = _qualname(fn_node)
            decs = [_unparse(d) or "" for d in fn_node.decorator_list]
            methodish = _is_methodish(fn_node)
            top_level = qual.count(".") == 0
            mod.functions.append(
                FunctionInfo(
                    id=f"{rel}::{qual}",
                    name=fn_node.name,
                    qualname=qual,
                    file=rel,
                    line=fn_node.lineno,
                    end_line=fn_node.end_lineno or fn_node.lineno,
                    params=_params(fn_node.args),
                    return_type=_unparse(fn_node.returns),
                    raises=_raised_exceptions(fn_node),
                    is_method=methodish,
                    class_name=(qual.rsplit(".", 1)[0] if methodish else None),
                    is_async=isinstance(fn_node, ast.AsyncFunctionDef),
                    is_static=any("staticmethod" == d or d.startswith("staticmethod") for d in decs),
                    is_classmethod=any("classmethod" == d or d.startswith("classmethod") for d in decs),
                    is_property=any(d.split(".")[0] == "property" for d in decs),
                    decorators=decs,
                    complexity=_cyclomatic(fn_node),
                    docstring=ast.get_docstring(fn_node),
                    exported=(qual in exports or qual.split(".")[0] in exports)
                    if exports
                    else not fn_node.name.startswith("_"),
                    source=self._segment(lines, fn_node),
                    language="python",
                )
            )

        for cls_node in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            qual = _qualname(cls_node)
            mod.classes.append(
                ClassInfo(
                    id=f"{rel}::{qual}",
                    name=cls_node.name,
                    qualname=qual,
                    file=rel,
                    line=cls_node.lineno,
                    end_line=cls_node.end_lineno or cls_node.lineno,
                    bases=[_unparse(b) or "" for b in cls_node.bases],
                    docstring=ast.get_docstring(cls_node),
                    methods=[f"{rel}::{qual}.{n.name}" for n in cls_node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))],
                    exported=(cls_node.name in exports) if exports else True,
                    language="python",
                )
            )
        return mod

    @staticmethod
    def _segment(lines: list[str], node: ast.AST) -> str:
        start = node.lineno  # type: ignore[attr-defined]
        deco = getattr(node, "decorator_list", None)
        if deco:
            start = deco[0].lineno
        begin = max(start - 1, 0)
        end = min(getattr(node, "end_lineno", len(lines)) or len(lines), len(lines))
        return "\n".join(lines[begin:end])

    @staticmethod
    def _all_exports(tree: ast.Module) -> set[str]:
        for node in tree.body:
            targets: list[ast.expr] = []
            value = None
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            for t in targets:
                if isinstance(t, ast.Name) and t.id == "__all__" and isinstance(value, (ast.List, ast.Tuple)):
                    try:
                        return {ast.literal_eval(e) for e in value.elts}
                    except Exception:
                        return set()
        return set()

    @staticmethod
    def _package(root: Path, path: Path) -> str | None:
        rel = path.relative_to(root.resolve())
        parts = list(rel.parts[:-1])
        stem = path.stem
        if stem == "__init__":
            dotted_parts = parts
        else:
            dotted_parts = parts + [stem]
        # verify each directory is a package (has __init__.py); otherwise no package
        check = root
        for part in parts:
            check = check / part
            if not (check / "__init__.py").exists():
                return None
        if not dotted_parts:
            return None
        return ".".join(dotted_parts)
