"""Deterministic input synthesis and behaviour probing."""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..exec_env import run_command
from ..fsutil import temp_dir
from ..model import FunctionInfo, Parameter

_INT_NAMES = (
    "count", "num", "size", "length", "qty", "amount", "total", "index",
    "idx", "limit", "days", "hours", "people", "n", "i", "j", "k", "x",
    "y", "a", "b", "width", "height", "depth", "level", "age",
)
_FLOAT_NAMES = ("rate", "ratio", "percent", "factor", "price", "weight")
_STR_NAMES = (
    "name", "text", "message", "label", "title", "content", "description",
    "prefix", "suffix", "word", "key", "email",
)
_LIST_NAMES = (
    "items", "values", "entries", "xs", "arr", "numbers", "records",
    "results", "list", "rows", "elements",
)
_DICT_NAMES = ("mapping", "dict", "table", "lookup", "config", "options")
_BOOL_PREFIXES = ("is_", "has_", "use_", "should_")
_BOOL_NAMES = ("flag", "enabled", "verbose", "strict", "normalize", "reverse", "unique")
_CALLABLE_HINTS = ("func", "callback", "handler", "callable", "predicate")


@dataclass
class ProbeCase:
    args: list[str] = field(default_factory=list)  # literal source strings
    slug: str = ""


@dataclass
class ProbeResult:
    ok: bool = False
    repr_: str | None = None
    error_type: str | None = None
    timed_out: bool = False


def _annotation_base(annotation: str | None) -> str:
    if not annotation:
        return ""
    text = annotation.replace(" ", "")
    text = re.sub(r"^(Optional|Union)\[", "", text).rstrip("]")
    return text.split("|")[0].lower()


def value_for(param: Parameter) -> str | None:
    base = _annotation_base(param.type_annotation)
    if base.startswith("int"):
        return "3"
    if base.startswith("float"):
        return "1.5"
    if base.startswith("str"):
        return '"alpha"'
    if base.startswith("bool"):
        return "True"
    if base.startswith(("list", "sequence", "iterable", "tuple")):
        return "[1, 2, 3]"
    if base.startswith(("dict", "mapping")):
        return '{"key": 1}'
    name = param.name.lower()
    for hint in _CALLABLE_HINTS:
        if hint in name:
            return None
    if param.kind in ("vararg", "kwarg"):
        return None
    if any(w in name for w in _FLOAT_NAMES):
        return "1.5"
    if any(w in name for w in _LIST_NAMES):
        return "[1, 2, 3]"
    if any(w in name for w in _DICT_NAMES):
        return '{"key": 1}'
    if any(name.startswith(p) for p in _BOOL_PREFIXES) or name in _BOOL_NAMES:
        return "True"
    if any(w in name for w in _STR_NAMES) or name == "s":
        return '"alpha"'
    if any(w in name for w in _INT_NAMES):
        return "3"
    return "3"


def _slug_part(v: str) -> str:
    if v == "[1, 2, 3]":
        return "items"
    if v == "[]":
        return "empty"
    if v == '{"key": 1}':
        return "map"
    if v in ("True", "False"):
        return v.lower()
    if v.startswith('"'):
        word = re.sub(r"[^a-z0-9]+", "", v.strip('"').lower())
        return word or "str"
    try:
        fv = float(v)
        return str(int(fv)) if fv.is_integer() else str(fv).replace(".", "_")
    except ValueError:
        return "arg"


def _slug_for(values: list[str]) -> str:
    parts = [_slug_part(v) for v in values[:3]]
    return "_and_".join(parts) if parts else "no_args"


def _literal_harvest(func: FunctionInfo, limit: int = 2) -> list[str]:
    """Numeric literals used inside the function, as clean strings.

    Boundary-oriented inputs built from the function's own constants give the
    deterministic backend a fighting chance of pinning comparison behaviour.
    """
    found: list[str] = []
    for raw in re.findall(r"(?<![\w.])(\d[\d_]*(?:\.\d+)?)(?![\w.])", func.source):
        clean = raw.replace("_", "")
        try:
            value = float(clean)
        except ValueError:
            continue
        if value <= 0 or not float(value).is_integer():
            continue
        if clean in found:
            continue
        found.append(clean)
        if len(found) >= limit:
            break
    return found


def synthesize_cases(
    func: FunctionInfo, max_edges: int = 2
) -> tuple[list[ProbeCase], str | None]:
    """Build deterministic probe cases; returns (cases, skip_reason)."""
    values: list[str] = []
    for p in func.params:
        if p.kind in ("vararg", "kwarg"):
            continue
        v = value_for(p)
        if v is None:
            if p.required:
                return [], f"cannot construct a value for parameter '{p.name}'"
            continue
        values.append(v)
    cases = [ProbeCase(args=list(values), slug=_slug_for(values))]

    def variant(idx: int, new_val: str) -> ProbeCase:
        vals = list(values)
        vals[idx] = new_val
        return ProbeCase(args=vals, slug=_slug_for(vals))

    made = 0
    list_idx = next((i for i, v in enumerate(values) if v == "[1, 2, 3]"), -1)
    int_idx = next((i for i, v in enumerate(values) if re.fullmatch(r"-?\d+", v)), -1)
    num_idx = int_idx if int_idx != -1 else next(
        (i for i, v in enumerate(values) if re.fullmatch(r"-?\d+\.\d+", v)), -1
    )
    if list_idx != -1 and made < max_edges:
        cases.append(variant(list_idx, "[]"))
        made += 1
    if int_idx != -1 and int_idx != list_idx and made < max_edges:
        cases.append(variant(int_idx, "0" if values[int_idx] != "0" else "7"))
        made += 1
    if num_idx != -1 and made < max_edges - 1:
        for lit in _literal_harvest(func):
            if made >= max_edges:
                break
            for candidate_val in (lit, str(int(lit) + 1)):
                if made >= max_edges:
                    break
                case = variant(num_idx, candidate_val)
                if all(c.args != case.args for c in cases):
                    cases.append(case)
                    made += 1
    seen: set[tuple[str, ...]] = set()
    unique = [c for c in cases if not (tuple(c.args) in seen or seen.add(tuple(c.args)))]
    return unique, None


def _literal_to_json(literal: str) -> str:
    try:
        value = ast.literal_eval(literal)
    except (ValueError, SyntaxError):
        return "null"
    return json.dumps(value)


_PROBE_SCRIPT = (
    "import importlib, json, sys\n"
    "spec = json.loads(sys.argv[1])\n"
    "sys.path.insert(0, spec['root'])\n"
    "try:\n"
    "    mod = importlib.import_module(spec['module'])\n"
    "except Exception as exc:\n"
    "    print(json.dumps({'ok': False, 'error_type': type(exc).__name__, 'stage': 'import'}))\n"
    "    raise SystemExit(0)\n"
    "obj = mod\n"
    "try:\n"
    "    for part in spec['qualname'].split('.'):\n"
    "        obj = getattr(obj, part)\n"
    "    result = obj(*[json.loads(a) for a in spec['args']])\n"
    "    print(json.dumps({'ok': True, 'repr': repr(result)}))\n"
    "except Exception as exc:\n"
    "    print(json.dumps({'ok': False, 'error_type': type(exc).__name__, 'stage': 'call'}))\n"
)


def probe_python(
    root: Path,
    module: str,
    qualname: str,
    case: ProbeCase,
    timeout: float = 30.0,
) -> ProbeResult:
    payload = {
        "root": str(root),
        "module": module,
        "qualname": qualname,
        "args": [_literal_to_json(a) for a in case.args],
    }
    with temp_dir(prefix="tw-probe-") as tmp:
        script = tmp / "probe.py"
        script.write_text(_PROBE_SCRIPT, encoding="utf-8")
        from ..runners import target_python

        res = run_command(
            [target_python(), str(script), json.dumps(payload)], root, timeout=timeout
        )
    if res.timed_out:
        return ProbeResult(ok=False, timed_out=True)
    match = None
    for line in reversed(res.stdout.splitlines()):
        if line.startswith("{"):
            match = line
            break
    if match is None:
        return ProbeResult(ok=False, error_type="NoOutput")
    try:
        data = json.loads(match)
    except json.JSONDecodeError:
        return ProbeResult(ok=False, error_type="BadProbeOutput")
    return ProbeResult(
        ok=bool(data.get("ok")),
        repr_=data.get("repr"),
        error_type=data.get("error_type"),
    )


def repr_is_comparable(repr_text: str | None) -> bool:
    """True when the repr round-trips to an equal value (safe to assert on).

    This gate doubles as an injection guard: only literals that evaluate back
    to themselves ever reach a generated assertion, so a target object cannot
    smuggle arbitrary source into a written test through its __repr__.
    """
    if repr_text is None:
        return False
    if re.search(r"0x[0-9a-fA-F]+", repr_text):
        return False
    if repr_text.startswith("<"):
        return False
    try:
        value = ast.literal_eval(repr_text)
    except (ValueError, SyntaxError, MemoryError):
        return False
    try:
        return repr(value) == repr_text
    except Exception:
        return False


def probe_javascript(
    root: Path,
    file_rel: str,
    qualname: str,
    case: ProbeCase,
    timeout: float = 30.0,
) -> ProbeResult:
    """Probe a JS function via node; only JSON-safe results are comparable."""
    args_json = ",".join(_literal_to_json(a) for a in case.args)
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    script = (
        "const path = require('path');\n"
        "const modPath = path.resolve(process.argv[2]);\n"
        "let mod;\n"
        "try { mod = require(modPath); } catch (e) {\n"
        "  console.log(JSON.stringify({ok:false,error_type:'ImportError'}));\n"
        "  process.exit(0);\n"
        "}\n"
        f"let obj = mod; for (const part of {json.dumps(qualname)}.split('.')) "
        "obj = obj[part];\n"
        "if (typeof obj !== 'function') {\n"
        "  console.log(JSON.stringify({ok:false,error_type:'NotFound'})); process.exit(0);\n"
        "}\n"
        f"Promise.resolve().then(() => obj({args_json})).then((result) => {{\n"
        "  const s = JSON.stringify(result === undefined ? null : result);\n"
        "  const rt = JSON.parse(s);\n"
        "  const stable = require('util').isDeepStrictEqual(result, rt);\n"
        "  console.log(JSON.stringify({ok:true,json:s,stable}));\n"
        "}).catch((e) => console.log(JSON.stringify({ok:false,error_type:e.constructor.name})));\n"
    )
    with temp_dir(prefix="tw-probe-js-") as tmp:
        script_path = tmp / "probe.js"
        script_path.write_text(script, encoding="utf-8")
        target_abs = root / file_rel
        res = run_command(
            [npx, "node", str(target_abs)] if False else ["node", str(script_path), str(target_abs)],
            root,
            timeout=timeout,
        )
    if res.timed_out:
        return ProbeResult(ok=False, timed_out=True)
    match = None
    for line in reversed(res.stdout.splitlines()):
        if line.startswith("{"):
            match = line
            break
    if match is None:
        return ProbeResult(ok=False, error_type="NoOutput")
    try:
        data = json.loads(match)
    except json.JSONDecodeError:
        return ProbeResult(ok=False, error_type="BadProbeOutput")
    if data.get("ok") and not data.get("stable", False):
        return ProbeResult(ok=True, repr_=None, error_type="NotComparable")
    return ProbeResult(
        ok=bool(data.get("ok")),
        repr_=data.get("json"),
        error_type=data.get("error_type"),
    )
