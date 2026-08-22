"""JavaScript/TypeScript analyzer built on the js_scan primitives."""

from __future__ import annotations

import re
from pathlib import Path

from ..fsutil import relpath_inside
from ..model import ClassInfo, FunctionInfo, ImportInfo, ModuleInfo
from . import Analyzer
from .js_scan import (
    count_complexity,
    line_of,
    mask_source,
    match_brace,
    match_paren,
    offset_of_line,
    parse_param,
    split_params,
    thrown_names,
)

_IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"

_FUNC_DECL = re.compile(rf"\b(?:(async)\s+)?function\s*\*?\s*({_IDENT})\s*\(")
_ARROW_ASSIGN = re.compile(
    rf"\b(?:const|let|var)\s+({_IDENT})\s*(?::[^=;\n]+)?=\s*(async\s+)?(?:\(([^()]*)\)|({_IDENT}))\s*=>"
)
_CLASS_DECL = re.compile(rf"\bclass\s+({_IDENT})(?:\s+extends\s+({_IDENT}))?")
_METHOD_SIG = re.compile(
    rf"\s*(?:(static)\s+)?(?:(async)\s+)?(?:get\s+|set\s+)?(\*?{_IDENT})\s*(?:<[^>]*>)?\(([^)]*)\)"
)
_IMPORT_FROM = re.compile(
    rf"""\bimport\s+(?:\{{([^}}]*)\}}|\*\s+as\s+({_IDENT})(?:\s*,\s*)?|({_IDENT})(?:\s*,\s*\{{([^}}]*)\}})?)\s*from\s*["']([^"']+)["']"""
)
_REQUIRE = re.compile(
    rf"""(?:const|let|var)\s+(?:\{{([^}}]*)\}}|({_IDENT}))\s*=\s*require\s*\(\s*["']([^"']+)["']\s*\)"""
)
_DYNAMIC_IMPORT = re.compile(r"""\bimport\s*\(\s*["']([^"']+)["']""")
_JSDOC = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)
_MODULE_EXPORTS_OBJ = re.compile(r"module\.exports\s*=\s*\{([^}]*)\}", re.DOTALL)


def _clean_jsdoc(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("*"):
            line = line[1:].strip()
        lines.append(line)
    return "\n".join(lines).strip()


def _find_jsdoc(src: str, decl_start: int) -> tuple[str | None, int]:
    j = decl_start - 1
    while j >= 0 and src[j] in " \t\r\n":
        j -= 1
    end = j + 1
    if j >= 1 and src[j] == "/" and src[j - 1] == "*":
        k = src.rfind("/**", 0, j)
        if k != -1:
            m = _JSDOC.match(src[k:end], 0)
            if m and m.end() == end - k:
                return _clean_jsdoc(m.group(1)), k
    return None, -1


def _has_export_before(masked: str, idx: int) -> bool:
    j = idx - 1
    while j >= 0 and masked[j].isspace():
        j -= 1
    word_end = j + 1
    while j >= 0 and (masked[j].isalnum() or masked[j] in "_$"):
        j -= 1
    return masked[j + 1 : word_end] == "export"


def _line_span(src: str, start_idx: int, end_idx: int) -> tuple[int, int]:
    begin_off = offset_of_line(src, line_of(src, start_idx))
    end_line_no = min(line_of(src, end_idx) + 1, src.count("\n") + 2)
    return begin_off, offset_of_line(src, end_line_no)


class JavaScriptAnalyzer(Analyzer):
    language = "javascript"
    extensions = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")

    def analyze_file(self, path: Path, root: Path) -> ModuleInfo:
        rel = relpath_inside(root, path)
        mod = ModuleInfo(file=rel, language="javascript", package=None)
        try:
            src = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            mod.parse_error = f"unreadable: {type(exc).__name__}"
            return mod
        masked, error = mask_source(src)
        if error:
            mod.parse_error = error
            return mod
        first_doc = _JSDOC.search(masked)
        if first_doc and not masked[: first_doc.start()].strip():
            mod.docstring = _clean_jsdoc(first_doc.group(1))

        self._collect_imports(mod, masked)
        exported_names = self._module_exports_names(masked)

        class_spans: list[tuple[int, int]] = []
        for cls in _CLASS_DECL.finditer(masked):
            open_brace = masked.find("{", cls.end())
            if open_brace == -1:
                continue
            close = match_brace(masked, open_brace)
            if close == -1:
                mod.parse_error = f"unbalanced braces in class {cls.group(1)}"
                return mod
            class_spans.append((cls.start(), close))
            self._scan_class(
                mod, src, masked, cls.start(), open_brace, close, cls.group(1), cls.group(2), exported_names
            )

        self._scan_functions(mod, src, masked, 0, len(masked), "", class_spans, exported_names)
        return mod

    def _scan_class(self, mod, src, masked, decl_start, body_open, body_close, cname, base, exported_names) -> None:
        rel = mod.file
        method_ids: list[str] = []
        i = body_open + 1
        depth = 0
        while i < body_close:
            ch = masked[i]
            if ch == "{":
                depth += 1
                i += 1
                continue
            if ch == "}":
                depth -= 1
                i += 1
                continue
            if depth == 0 and (i == 0 or masked[i - 1] in " \t\n\r;"):
                line_begin = masked.rfind("\n", body_open, i) + 1
                if masked[line_begin:i].strip():
                    i += 1
                    continue
                m2 = _METHOD_SIG.match(masked, line_begin)
                if m2 and self._method_at(masked, line_begin, m2):
                    info_end = self._emit_function(
                        mod, src, masked,
                        sig_start=line_begin,
                        name=m2.group(3),
                        param_text=m2.group(4),
                        is_async=bool(m2.group(2)),
                        prefix=cname + ".",
                        is_method=True,
                        is_static=bool(m2.group(1)),
                        is_accessor=m2.group(0).strip().startswith(("get ", "set ")),
                        skip_spans=[],
                        force_export=False,
                        end_limit=body_close,
                    )
                    if info_end is not None:
                        method_ids.append(f"{rel}::{cname}.{m2.group(3)}")
                        i = info_end
            i += 1
        doc, _ = _find_jsdoc(src, decl_start)
        mod.classes.append(
            ClassInfo(
                id=f"{rel}::{cname}",
                name=cname,
                qualname=cname,
                file=rel,
                line=line_of(src, decl_start),
                end_line=line_of(src, body_close),
                bases=[base] if base else [],
                docstring=doc,
                methods=sorted(set(method_ids)),
                exported=_has_export_before(masked, decl_start) or cname in exported_names,
                language="javascript",
            )
        )

    @staticmethod
    def _method_at(masked: str, sig_start: int, m: re.Match) -> bool:
        after_name = sig_start + m.end(3)
        between = masked[after_name : sig_start + m.start(4)]
        return "(" in between or between.strip() == ""

    def _scan_functions(
        self,
        mod: ModuleInfo,
        src: str,
        masked: str,
        begin: int,
        end: int,
        prefix: str,
        skip_spans: list[tuple[int, int]],
        exported_names: set[str],
    ) -> None:
        i = begin
        while i < end:
            candidates: list[tuple[int, str, object]] = []
            mf = _FUNC_DECL.search(masked, i, end)
            if mf:
                candidates.append((mf.start(), "func", mf))
            ma = _ARROW_ASSIGN.search(masked, i, end)
            if ma:
                candidates.append((ma.start(), "arrow", ma))
            md = _DEFAULT_DECL.search(masked, i, end)
            if md:
                candidates.append((md.start(), "default", md))
            if not candidates:
                return
            pos, kind, m = min(candidates, key=lambda t: t[0])

            def inside_skip(p: int) -> bool:
                return any(s <= p < e for s, e in skip_spans)

            if kind == "func":
                params_open = m.end() - 1
                name = m.group(2)
                is_async = bool(m.group(1))
                stop = self._handle_callable(
                    mod, src, masked, pos, name, None, params_open, is_async, prefix,
                    skip_spans, exported_names, end,
                )
                i = stop if stop is not None else m.end()
                del inside_skip
                continue
            if kind == "arrow":
                name = m.group(1)
                is_async = bool(m.group(2))
                if m.group(3) is not None:
                    stop = self._handle_callable(
                        mod, src, masked, m.start(), name, m.group(3),
                        masked.find("(", m.start()), is_async, prefix,
                        skip_spans, exported_names, end,
                    )
                else:
                    stop = self._emit_function(
                        mod, src, masked, sig_start=m.start(), name=name,
                        param_text=None, is_async=is_async, prefix=prefix,
                        single_param=m.group(4), skip_spans=skip_spans,
                        force_export=_has_export_before(masked, m.start())
                        or name in exported_names,
                        end_limit=end,
                    )
                i = stop if stop is not None else m.end()
                continue
            # export default anonymous function/arrow
            name = "default"
            is_async = bool(m.group(1))
            paren_idx = masked.find("(", m.start())
            stop = self._handle_callable(
                mod, src, masked, m.start(), name, m.group(2), paren_idx,
                is_async, prefix, skip_spans, exported_names, end, force=True,
            )
            i = stop if stop is not None else m.end()

    def _handle_callable(
        self,
        mod: ModuleInfo,
        src: str,
        masked: str,
        decl_pos: int,
        name: str,
        param_text: str | None,
        params_open: int,
        is_async: bool,
        prefix: str,
        skip_spans: list[tuple[int, int]],
        exported_names: set[str],
        limit: int,
        force: bool = False,
    ) -> int | None:
        if any(s <= decl_pos < e for s, e in skip_spans):
            close_guess = masked.find("\n", decl_pos)
            return close_guess + 1 if close_guess != -1 else decl_pos + 1
        return self._emit_function(
            mod, src, masked, sig_start=decl_pos, name=name, param_text=param_text,
            is_async=is_async, prefix=prefix, skip_spans=skip_spans,
            force_export=force or _has_export_before(masked, decl_pos)
            or name in exported_names,
            end_limit=limit, params_open=params_open,
        )

    def _emit_function(
        self,
        mod: ModuleInfo,
        src: str,
        masked: str,
        sig_start: int,
        name: str,
        param_text: str | None,
        is_async: bool,
        prefix: str,
        skip_spans: list[tuple[int, int]],
        force_export: bool,
        end_limit: int,
        params_open: int | None = None,
        single_param: str | None = None,
        is_method: bool = False,
        is_static: bool = False,
        is_accessor: bool = False,
    ) -> int | None:
        rel = mod.file
        if params_open is None:
            paren = masked.find("(", sig_start)
            if paren == -1 or paren > sig_start + 300:
                return None
            params_open = paren
        params_close = match_paren(masked, params_open)
        if params_close == -1:
            mod.parse_error = f"unbalanced parameter list near line {line_of(src, params_open)}"
            return None
        if single_param is not None:
            params = [parse_param(single_param)]
        elif param_text is not None:
            params = [parse_param(p) for p in split_params(param_text)]
        else:
            params = [
                parse_param(p) for p in split_params(masked[params_open + 1 : params_close])
            ]
        arrow_body = masked.find("=>", params_close, min(params_close + 6, len(masked)))
        body_open = masked.find("{", params_close + 1, min(end_limit, params_close + 400))
        semi = masked.find(";", params_close + 1, min(end_limit, params_close + 400))
        if arrow_body != -1 and (semi > arrow_body or semi == -1):
            nxt = masked[arrow_body + 2 :].lstrip()[:1]
            if nxt == "{":
                body_open = masked.find("{", arrow_body)
            else:
                body_open = -1  # expression-bodied arrow handled below
        if body_open != -1 and semi != -1 and semi < body_open:
            return semi + 1  # overload/ambient declaration without a body
        if body_open == -1:
            body_close = self._expression_end(masked, arrow_body if arrow_body != -1 else params_close)
            body_src = masked[
                (arrow_body + 2 if arrow_body != -1 else params_close) : body_close
            ]
            src_end_off = offset_of_line(src, min(line_of(src, body_close) + 1, src.count("\n") + 2))
        else:
            body_close = match_brace(masked, body_open)
            if body_close == -1:
                mod.parse_error = f"unbalanced braces near line {line_of(src, body_open)}"
                return None
            body_src = masked[body_open : body_close + 1]
            src_end_off = offset_of_line(src, min(line_of(src, body_close) + 1, src.count("\n") + 2))
        qual = prefix + name
        doc, doc_start = _find_jsdoc(src, sig_start)
        seg_from = doc_start if doc_start != -1 else sig_start
        seg_begin = offset_of_line(src, line_of(src, seg_from))
        ret_type = self._return_type(masked, params_close, body_open, arrow_body)
        info = FunctionInfo(
            id=f"{rel}::{qual}",
            name=name,
            qualname=qual,
            file=rel,
            line=line_of(src, sig_start),
            end_line=line_of(src, body_close),
            params=params,
            return_type=ret_type,
            raises=thrown_names(body_src),
            is_method=is_method,
            class_name=(prefix.rstrip(".") or None) if is_method else None,
            is_async=is_async,
            is_static=is_static,
            is_property=is_accessor,
            complexity=count_complexity(body_src) if body_src.strip() else 1,
            docstring=doc,
            exported=force_export,
            source=src[seg_begin:src_end_off].rstrip(),
            language="javascript",
        )
        if info.class_name == "":
            info.class_name = None
        mod.functions.append(info)
        if body_open != -1:
            inner = self._child_scopes(masked, body_open, body_close)
            for cs, ce in inner:
                self._scan_functions(mod, src, masked, cs, ce, qual + ".", [], set())
            return body_close + 1
        return body_close + 1

    @staticmethod
    def _child_scopes(masked: str, body_open: int, body_close: int) -> list[tuple[int, int]]:
        """Nested function bodies inside a region, as (open, close) spans."""
        spans: list[tuple[int, int]] = []
        for m in list(_FUNC_DECL.finditer(masked, body_open, body_close)) + list(
            _ARROW_ASSIGN.finditer(masked, body_open, body_close)
        ):
            paren = masked.find("(", m.start(), min(m.end() + 1, body_close))
            pclose = match_paren(masked, paren) if paren != -1 else -1
            if pclose == -1 or pclose >= body_close:
                continue
            bopen = masked.find("{", pclose, body_close)
            if bopen == -1:
                continue
            bclose = match_brace(masked, bopen)
            if bclose != -1 and bclose <= body_close:
                spans.append((bopen + 1, bclose))
        return spans

    @staticmethod
    def _expression_end(masked: str, start: int) -> int:
        depth = 0
        i = start
        n = len(masked)
        while i < n:
            c = masked[i]
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    return i
                depth -= 1
            elif c in ";," and depth == 0:
                return i
            elif c == "\n" and depth == 0:
                j = i + 1
                while j < n and masked[j] in " \t":
                    j += 1
                if j < n and masked[j] not in ".+-)]}&|?":
                    return i
            i += 1
        return n

    @staticmethod
    def _return_type(masked: str, params_close: int, body_open: int, arrow_body: int = -1) -> str | None:
        stop_candidates = [x for x in (body_open, arrow_body) if x != -1]
        stop = min(stop_candidates) if stop_candidates else params_close + 200
        seg = masked[params_close + 1 : max(stop, params_close + 1)]
        colon = seg.find(":")
        if colon == -1:
            return None
        text = seg[colon + 1 :].strip()
        text = text.split("\n")[0].strip()
        return text or None

    def _collect_imports(self, mod: ModuleInfo, masked: str) -> None:
        for m in _IMPORT_FROM.finditer(masked):
            names: list[str] = []
            braces = m.group(1) or m.group(4)
            if braces:
                for part in braces.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    base = part.split(" as ")[0].strip()
                    if base:
                        names.append(base)
            if m.group(2):
                names.append(m.group(2))
            if m.group(3):
                names.append(m.group(3))
            mod.imports.append(ImportInfo(names=names, module=m.group(5), line=line_of(masked, m.start())))
        for m in _REQUIRE.finditer(masked):
            names = []
            if m.group(1):
                names += [p.strip().split(" as ")[0].strip() for p in m.group(1).split(",") if p.strip()]
            if m.group(2):
                names.append(m.group(2))
            mod.imports.append(ImportInfo(names=names, module=m.group(3), line=line_of(masked, m.start())))
        for m in _DYNAMIC_IMPORT.finditer(masked):
            mod.imports.append(
                ImportInfo(names=[f'import({m.group(1)})'], module=m.group(1), line=line_of(masked, m.start()))
            )

    @staticmethod
    def _module_exports_names(masked: str) -> set[str]:
        names: set[str] = set()
        for m in _MODULE_EXPORTS_OBJ.finditer(masked):
            for part in m.group(1).split(","):
                part = part.strip()
                if not part:
                    continue
                key = part.split(":")[0].strip()
                if re.fullmatch(_IDENT, key):
                    names.add(key)
        for m in re.finditer(rf"module\.exports\.({_IDENT})\s*=", masked):
            names.add(m.group(1))
        return names


_DEFAULT_FUNC = re.compile(r"\bexport\s+default\s+(async\s+)?function\s*\(")
_DEFAULT_ARROW = re.compile(rf"\bexport\s+default\s+(async\s+)?\(([^()]*)\)\s*=>")
_DEFAULT_DECL = re.compile(r"\bexport\s+default\s+(async\s+)?(?:function\s*\(|\()")
