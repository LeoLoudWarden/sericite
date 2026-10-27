from __future__ import annotations

from dataclasses import dataclass, field

LOAD_CONST = "LOAD_CONST"
LOAD_NAME = "LOAD_NAME"
STORE_NAME = "STORE_NAME"
LOAD_DEREF = "LOAD_DEREF"
STORE_DEREF = "STORE_DEREF"
DUP = "DUP"
POP = "POP"
BUILD_LIST = "BUILD_LIST"
BUILD_DICT = "BUILD_DICT"
LOAD_INDEX = "LOAD_INDEX"
LOAD_SLICE = "LOAD_SLICE"
STORE_INDEX = "STORE_INDEX"
BINARY_OP = "BINARY_OP"
UNARY_OP = "UNARY_OP"
COMPARE_OP = "COMPARE_OP"
JUMP = "JUMP"
JUMP_IF_FALSE = "JUMP_IF_FALSE"
JUMP_IF_TRUE_KEEP = "JUMP_IF_TRUE_KEEP"
JUMP_IF_FALSE_KEEP = "JUMP_IF_FALSE_KEEP"
LOAD_ATTR = "LOAD_ATTR"
STORE_ATTR = "STORE_ATTR"
MAKE_SCHEMA = "MAKE_SCHEMA"
CHECK_ANNOT = "CHECK_ANNOT"
MAKE_FUNCTION = "MAKE_FUNCTION"
GET_ITER = "GET_ITER"
FOR_ITER = "FOR_ITER"
RAISE = "RAISE"
CALL = "CALL"
CALL_KW = "CALL_KW"
RETURN = "RETURN"

JUMP_OPS = {JUMP, JUMP_IF_FALSE, JUMP_IF_TRUE_KEEP, JUMP_IF_FALSE_KEEP}


@dataclass
class Instr:
    op: str
    arg: object = None
    line: int = 0
    stmt_start: bool = False


@dataclass
class Handler:
    start: int
    end: int
    target: int
    kinds: tuple[str, ...] | None
    bind: str | None
    stack_depth: int = 0
    error_name: str | None = None


@dataclass
class CodeUnit:
    name: str
    params: list[str]
    local_names: tuple[str, ...] = ()
    cell_names: tuple[str, ...] = ()
    free_names: tuple[str, ...] = ()
    param_labels: tuple = ()
    return_label: str | None = None
    # ID of the VM that compiled this code unit; labels/definition-side names are visible only to that VM (invariant 16).
    origin_vm: int = -1
    instrs: list[Instr] = field(default_factory=list)
    handlers: list[Handler] = field(default_factory=list)
