import ast
import codeop
import sys

from ..engine import SericiteError, VMHandle
from ._diagnostics import _format_error
from ._hostio import _write_stdout
from ._sources import _CombinedSource, _ReplSourceMap


def _expression_delivery(source: str) -> tuple[str, int]:
    tree = ast.parse(source, filename="<stdin>")
    if len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr):
        # Bind the value once (avoiding a second evaluation), then echo its repr
        # only when it is not None — matching Python's REPL displayhook, which
        # suppresses None. `_` also serves as the last-expression result, as in
        # Python's REPL.
        return (
            f"_ = (\n{source}\n)\nif _ != None:\n    print(repr(_))",
            1,
        )
    return source, 0


def _repl(root: VMHandle, startup_source: _CombinedSource) -> int:
    source_map = _ReplSourceMap(startup_source)
    buffer: list[str] = []
    while True:
        _write_stdout("... " if buffer else ">>> ")
        line = sys.stdin.readline()
        if not line:
            return 0
        if not buffer and not line.strip():
            continue
        buffer.append(line.rstrip("\n"))
        source_text = "\n".join(buffer)
        try:
            complete = codeop.compile_command(source_text, filename="<stdin>")
        except SyntaxError as exc:
            error = SericiteError(
                exc.msg or "invalid syntax",
                kind="syntax_error",
                filename="<stdin>",
                line=exc.lineno,
                column=exc.offset,
            )
            print(error, file=sys.stderr)
            buffer.clear()
            continue
        if complete is None:
            continue

        buffer.clear()
        if not source_text.strip():
            continue
        delivery, line_offset = _expression_delivery(source_text)
        source = _CombinedSource([("<stdin>", source_text)])
        source_map.add(source, line_offset)
        try:
            root.exec(delivery)
        except SericiteError as exc:
            print(
                _format_error(
                    exc, source, line_offset=line_offset, source_map=source_map
                ),
                file=sys.stderr,
            )
            continue
