"""The code model: the contract between language analyzers and test generators.

Every analyzer produces a CodeModel from a target repository; every generator
consumes FunctionInfo objects from that model. This module is the single shared
schema. Additive changes only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Parameter:
    """One parameter of a function or method."""

    name: str
    type_annotation: str | None = None
    default: str | None = None  # source text of the default, None when required
    kind: str = "positional"  # positional_only|positional|keyword_only|vararg|kwarg

    @property
    def required(self) -> bool:
        return self.default is None and self.kind not in ("vararg", "kwarg")


@dataclass
class FunctionInfo:
    """A function, method, or other callable with a definition site."""

    id: str  # "<posix relative file>::<qualname>"
    name: str
    qualname: str  # e.g. "Invoice.total" inside its module
    file: str  # path relative to target root, posix separators
    line: int
    end_line: int
    params: list[Parameter] = field(default_factory=list)
    return_type: str | None = None
    raises: list[str] = field(default_factory=list)  # exception names raised
    is_method: bool = False
    class_name: str | None = None
    is_async: bool = False
    is_static: bool = False
    is_classmethod: bool = False
    is_property: bool = False
    decorators: list[str] = field(default_factory=list)
    complexity: int = 1
    docstring: str | None = None
    exported: bool = False  # part of the module's public API surface
    source: str = ""
    language: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"{self.file}::{self.qualname}"


@dataclass
class ClassInfo:
    """A class with its bases and methods."""

    id: str
    name: str
    qualname: str
    file: str
    line: int
    end_line: int
    bases: list[str] = field(default_factory=list)
    docstring: str | None = None
    methods: list[str] = field(default_factory=list)  # FunctionInfo ids
    exported: bool = False
    language: str = ""


@dataclass
class ImportInfo:
    """An import statement in a module."""

    names: list[str]  # imported names as written ("os.path", "pytest")
    module: str | None  # the dotted module, when it is a from-import
    line: int


@dataclass
class ModuleInfo:
    """One analyzed source file."""

    file: str  # relative posix path
    language: str  # "python" | "javascript"
    package: str | None  # dotted import path, when derivable
    docstring: str | None = None
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    imports: list[ImportInfo] = field(default_factory=list)
    parse_error: str | None = None  # set when the source could not be parsed

    @property
    def all_functions(self) -> list[FunctionInfo]:
        return list(self.functions)


@dataclass
class CodeModel:
    """The analyzed surface of a target repository."""

    root: Path
    modules: dict[str, ModuleInfo] = field(default_factory=dict)  # by file

    @property
    def functions(self) -> list[FunctionInfo]:
        out: list[FunctionInfo] = []
        for mod in self.modules.values():
            out.extend(mod.functions)
        return out

    def fan_in(self, func: FunctionInfo) -> int:
        """Number of distinct other modules referencing this function's name."""
        count = 0
        for mod in self.modules.values():
            if mod.file == func.file:
                continue
            referenced = False
            for imp in mod.imports:
                if func.name in imp.names or (
                    imp.module and func.qualname.split(".")[0] in imp.names
                ):
                    referenced = True
                    break
            if not referenced:
                # crude textual call reference within the module body
                pass
            if referenced:
                count += 1
        return count
