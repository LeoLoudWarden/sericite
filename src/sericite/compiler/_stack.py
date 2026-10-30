from __future__ import annotations

from .. import isa
from ..errors import SericiteError

_STACK_DELTAS = {
    isa.LOAD_CONST: 1,
    isa.LOAD_NAME: 1,
    isa.LOAD_DEREF: 1,
    isa.DUP: 1,
    isa.STORE_NAME: -1,
    isa.STORE_DEREF: -1,
    isa.POP: -1,
    isa.GET_ITER: -1,
    isa.LOAD_INDEX: -1,
    isa.LOAD_SLICE: -3,
    isa.BINARY_OP: -1,
    isa.COMPARE_OP: -1,
    isa.STORE_INDEX: -3,
    isa.UNARY_OP: 0,
    isa.LOAD_ATTR: 0,
    isa.STORE_ATTR: -2,
    isa.CHECK_ANNOT: -1,
    isa.FORMAT_VALUE: 0,
}


def _analyze_stack(code: isa.CodeUnit, filename: str) -> None:
    instrs = code.instrs
    if not instrs:
        return
    depths: list[int | None] = [None] * len(instrs)
    depths[0] = 0
    worklist = [0]
    while worklist:
        i = worklist.pop()
        depth = depths[i]
        assert depth is not None
        instr = instrs[i]
        successors: list[tuple[int, int]] = []
        if instr.op == isa.JUMP:
            successors.append((instr.arg, depth))
        elif instr.op == isa.JUMP_IF_FALSE:
            successors.append((instr.arg, depth - 1))
            successors.append((i + 1, depth - 1))
        elif instr.op in (isa.JUMP_IF_TRUE_KEEP, isa.JUMP_IF_FALSE_KEEP):
            successors.append((instr.arg, depth))
            successors.append((i + 1, depth - 1))
        elif instr.op == isa.FOR_ITER:
            successors.append((instr.arg[1], depth))
            successors.append((i + 1, depth + 1))
        elif instr.op in (isa.RETURN, isa.RAISE):
            pass
        else:
            if instr.op in (isa.BUILD_LIST, isa.BUILD_STRING):
                delta = 1 - instr.arg
            elif instr.op == isa.BUILD_DICT:
                delta = 1 - 2 * instr.arg
            elif instr.op == isa.MAKE_SCHEMA:
                delta = 1 - len(instr.arg)
            elif instr.op == isa.MAKE_FUNCTION:
                delta = 1 - (instr.arg[1] + instr.arg[2])
            elif instr.op == isa.CALL:
                delta = -instr.arg
            elif instr.op == isa.CALL_KW:
                delta = -(instr.arg[0] + len(instr.arg[1]))
            else:
                delta = _STACK_DELTAS[instr.op]
            successors.append((i + 1, depth + delta))
        for target, target_depth in successors:
            if target >= len(instrs):
                raise SericiteError(
                    "compiler produced a jump out of range",
                    kind="internal_error",
                    filename=filename,
                )
            if depths[target] is None:
                depths[target] = target_depth
                worklist.append(target)
            elif depths[target] != target_depth:
                raise SericiteError(
                    "compiler produced inconsistent stack depths",
                    kind="internal_error",
                    filename=filename,
                )
    for handler in code.handlers:
        start_depth = depths[handler.start]
        if start_depth is not None:
            handler.stack_depth = start_depth
