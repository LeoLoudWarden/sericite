"""Sericite compiler: the only entry point for source code.

Source is parsed with ``ast``, validated against the node whitelist and
except-kind rules, compiled to the internal instruction stream, and passed
through static stack-depth analysis. Split into cohesive parts:

- `_rules`: whitelist tables, operator maps, reserved and VM-method names
- `_validate`: AST whitelist and except-kind validation
- `_scopes`: lexical scope/cell analysis
- `_stack`: static stack-depth analysis (safe truncation on exception catch)
- `_compiler`: the `_Compiler` emitting the instruction stream
"""

from __future__ import annotations

import ast

from .. import isa
from ..errors import SericiteError
from ._compiler import _Compiler
from ._rules import RESERVED_NAMES, VM_METHODS
from ._scopes import _analyze_scopes
from ._stack import _analyze_stack
from ._validate import _validate

__all__ = ["RESERVED_NAMES", "VM_METHODS", "compile_source"]


def compile_source(source: object, filename: str) -> isa.CodeUnit:
    if not isinstance(source, str):
        raise SericiteError("VM source must be a string", filename=filename)
    try:
        tree = ast.parse(source, filename=filename, mode="exec")
    except SyntaxError as exc:
        raise SericiteError(
            exc.msg or "invalid syntax",
            kind="syntax_error",
            filename=filename,
            line=exc.lineno,
            column=exc.offset,
        ) from None
    except RecursionError:
        raise SericiteError(
            "source nesting too deep",
            kind="syntax_error",
            filename=filename,
        ) from None
    except MemoryError:
        raise SericiteError(
            "source too large to compile",
            kind="syntax_error",
            filename=filename,
        ) from None
    try:
        _validate(tree, filename)
        code = isa.CodeUnit(name="<module>", params=[])
        scopes = _analyze_scopes(tree, code)
        compiler = _Compiler(filename, scopes)
        compiler.compile_body(tree.body, code)
        compiler.emit(code, isa.LOAD_CONST, None, 0)
        compiler.emit(code, isa.RETURN, None, 0)
        _analyze_stack(code, filename)
    except RecursionError:
        raise SericiteError(
            "source nesting too deep",
            kind="syntax_error",
            filename=filename,
        ) from None
    except MemoryError:
        raise SericiteError(
            "source too large to compile",
            kind="syntax_error",
            filename=filename,
        ) from None
    return code
