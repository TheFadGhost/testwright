"""Masking and scanning primitives for the JavaScript analyzer."""

from __future__ import annotations

import re

_IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"

_REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%~^<>") | {"return", "typeof", "case", "in", "of", "new", "delete", "void", "do", "else", "yield", "await"}


def mask_source(src: str) -> tuple[str, str | None]:
    """Return a copy of *src* where comments and literal bodies are spaces.

    Newline positions are preserved so offsets map back to line numbers.
    Returns (masked, error) where error names the first unterminated construct.
    """
    out = list(src)
    i = 0
    n = len(src)
    line = 1
    prev_sig = ""  # last significant non-space char or word before current token

    def blank(idx: int) -> None:
        if out[idx] != "\n":
            out[idx] = " "

    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "\n":
            line += 1
            i += 1
            continue
        if c == "/" and nxt == "/":
            while i < n and src[i] != "\n":
                blank(i)
                i += 1
            continue
        if c == "/" and nxt == "*":
            start_line = line
            i += 2
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                blank(i)
                if src[i] == "\n":
                    line += 1
                i += 1
            if i >= n:
                return "".join(out), f"unterminated block comment starting near line {start_line}"
            blank(i)
            blank(i + 1)
            i += 2
            continue
        if c in "\"'`":
            quote = c
            template = quote == "`"
            start_line = line
            blank(i)
            i += 1
            closed = False
            while i < n:
                ch = src[i]
                if ch == "\\":
                    blank(i)
                    if i + 1 < n:
                        blank(i + 1)
                        if src[i + 1] == "\n":
                            line += 1
                    i += 2
                    continue
                if ch == "\n":
                    line += 1
                    if not template:
                        return "".join(out), f"unterminated string starting near line {start_line}"
                    i += 1
                    continue
                if ch == quote:
                    blank(i)
                    i += 1
                    closed = True
                    break
                if template and ch == "$" and i + 1 < n and src[i + 1] == "{":
                    # keep interpolation code visible; mask only the braces
                    depth = 0
                    while i < n:
                        ch2 = src[i]
                        if ch2 == "{":
                            depth += 1
                            blank(i)
                        elif ch2 == "}":
                            depth -= 1
                            blank(i)
                            if depth == 0:
                                break
                        elif ch2 == "\n":
                            line += 1
                        else:
                            blank(i)
                        i += 1
                    continue
                blank(i)
                i += 1
            if not closed:
                return "".join(out), f"unterminated string starting near line {start_line}"
            prev_sig = quote
            continue
        if c == "/":
            j = i - 1
            while j >= 0 and src[j] in " \t\n":
                j -= 1
            word_end = j
            while j >= 0 and (src[j].isalnum() or src[j] in "_$"):
                j -= 1
            prev_word = src[j + 1 : word_end + 1]
            prev_char = src[word_end] if word_end >= 0 else ""
            looks_regex = (
                prev_char == ""
                or prev_char in _REGEX_PRECEDERS - {"+" , "-", "*", "%", "~", "^", "<", ">"}
                or prev_word in _REGEX_PRECEDERS
            )
            if looks_regex:
                start_line = line
                i += 1
                in_class = False
                closed = False
                while i < n:
                    ch = src[i]
                    if ch == "\\":
                        blank(i)
                        if i + 1 < n:
                            blank(i + 1)
                        i += 2
                        continue
                    if ch == "\n":
                        break
                    if ch == "[":
                        in_class = True
                    elif ch == "]":
                        in_class = False
                    elif ch == "/" and not in_class:
                        blank(i)
                        i += 1
                        closed = True
                        break
                    blank(i)
                    i += 1
                if not closed:
                    return "".join(out), f"unterminated regex literal near line {start_line}"
                while i < n and src[i].isalpha():
                    blank(i)
                    i += 1
                continue
        if not c.isspace():
            prev_sig = c
        i += 1
    return "".join(out), None


def match_brace(masked: str, open_idx: int) -> int:
    """Index of the brace matching the '{' at *open_idx*, or -1."""
    depth = 0
    for i in range(open_idx, len(masked)):
        c = masked[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def match_paren(masked: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(masked)):
        c = masked[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        elif c == "{":
            skip_to = match_brace(masked, i)
            if skip_to == -1:
                return -1
            i = skip_to
    return -1


def line_of(src: str, idx: int) -> int:
    return src.count("\n", 0, idx) + 1


def offset_of_line(src: str, line_no: int) -> int:
    pos = 0
    for _ in range(line_no - 1):
        nl = src.find("\n", pos)
        if nl == -1:
            return len(src)
        pos = nl + 1
    return pos


def split_params(text: str) -> list[str]:
    """Split a parameter list source into individual parameter strings."""
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    angle = 0
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "<":
            angle += 1
        elif ch == ">":
            angle = max(0, angle - 1)
        if ch == "," and depth == 0 and angle == 0:
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def parse_param(raw: str) -> Parameter:
    """Parse one parameter string into a model Parameter."""
    from ..model import Parameter

    raw = raw.strip()
    kind = "positional"
    if raw.startswith("..."):
        kind = "vararg"
        raw = raw[3:]
    annotation = None
    default = None
    depth = 0
    angle = 0
    eq_idx = -1
    colon_idx = -1
    for idx, ch in enumerate(raw):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "<":
            angle += 1
        elif ch == ">":
            angle = max(0, angle - 1)
        elif ch in "=" and depth == 0 and angle == 0 and eq_idx == -1 and raw[idx : idx + 2] not in ("=>", "==", "<="):
            if idx > 0 and raw[idx - 1] in "=<>!+-*/%&|^?":
                continue
            eq_idx = idx
        elif ch == ":" and depth == 0 and angle == 0 and colon_idx == -1:
            if idx > 0 and raw[idx - 1] == "?":
                colon_idx = idx
            else:
                colon_idx = idx
    name_part = raw
    if colon_idx != -1:
        name_part = raw[:colon_idx].rstrip()
        annotation = raw[colon_idx + 1 :].strip()
        if eq_idx != -1 and eq_idx > colon_idx:
            default = raw[eq_idx + 1 :].strip()
            annotation = raw[colon_idx + 1 : eq_idx].strip()
    elif eq_idx != -1:
        name_part = raw[:eq_idx].rstrip()
        default = raw[eq_idx + 1 :].strip()
    name = name_part.strip()
    optional = name.endswith("?")
    if optional:
        name = name[:-1].rstrip()
    if name.startswith("{") or name.startswith("["):
        kind = "destructured"
    return Parameter(
        name=name,
        type_annotation=annotation,
        default=default,
        kind=kind,
    )


def count_complexity(body_masked: str) -> int:
    score = 1
    score += len(re.findall(r"\bif\b", body_masked))
    score += len(re.findall(r"\bfor\b", body_masked))
    score += len(re.findall(r"\bwhile\b", body_masked))
    score += len(re.findall(r"\bcase\b", body_masked))
    score += len(re.findall(r"\bcatch\b", body_masked))
    score += len(re.findall(r"&&|\|\||\?\?", body_masked))
    score += len(re.findall(r"\?", body_masked)) - len(re.findall(r"\?\.", body_masked)) - len(re.findall(r"\?\?", body_masked))
    return max(score, 1)


_THROW_NEW = re.compile(rf"\bthrow\s+new\s+({_IDENT}(?:\.{_IDENT})*)")
_THROW_BARE = re.compile(rf"\bthrow\s+({_IDENT})")


def thrown_names(body_masked: str) -> list[str]:
    names: list[str] = []
    for m in _THROW_NEW.finditer(body_masked):
        parts = m.group(1).split(".")
        names.append(parts[-1])
    for m in _THROW_BARE.finditer(body_masked):
        if m.group(1) not in ("Error",):
            pass
    seen: set[str] = set()
    return [x for x in names if not (x in seen or seen.add(x))]
