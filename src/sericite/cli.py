import argparse
import ast
import codeop
import runpy
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .engine import SericiteEngine, SericiteError, SericiteLimits, VMHandle


class _CliError(Exception):
    pass


@dataclass(frozen=True)
class _SourcePart:
    name: str
    start_line: int
    line_count: int


class _CombinedSource:
    def __init__(self, parts: list[tuple[str, str]]) -> None:
        self._parts: list[_SourcePart] = []
        next_line = 1
        for name, text in parts:
            line_count = text.count("\n") + 1
            self._parts.append(_SourcePart(name, next_line, line_count))
            next_line += line_count
        self.text = "\n".join(text for _, text in parts)

    def location(self, line: int | None) -> tuple[str, int | None]:
        if line is None or not self._parts:
            return "<sericite>", None
        part = self._parts[-1]
        for candidate in self._parts:
            if (
                candidate.start_line
                <= line
                < candidate.start_line + candidate.line_count
            ):
                part = candidate
                break
        return part.name, line - part.start_line + 1


def _read_stdin() -> str | None:
    value = sys.stdin.readline()
    return value if value else None


def _write_stdout(value: str) -> None:
    sys.stdout.write(value)
    sys.stdout.flush()


def _read_file(path: str, role: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        detail = exc.strerror if isinstance(exc, OSError) else str(exc)
        raise _CliError(
            f"unable to read {role} '{path}': {detail or 'I/O error'}"
        ) from exc


def _load_source(
    args: argparse.Namespace, source_name: str | None, *, interactive: bool
) -> _CombinedSource:
    parts = [(path, _read_file(path, "include")) for path in args.include]
    if interactive:
        pass
    elif args.command is not None:
        parts.append(("<command>", args.command))
    elif source_name == "-":
        parts.append(("<stdin>", sys.stdin.read()))
    else:
        assert source_name is not None
        parts.append((source_name, _read_file(source_name, "source")))
    return _CombinedSource(parts)


def _load_capabilities(path: str) -> dict:
    try:
        namespace = runpy.run_path(path)
    except Exception as exc:
        raise _CliError(
            f"unable to load capabilities '{path}': {type(exc).__name__}: {exc}"
        ) from exc
    configure = namespace.get("configure")
    if not callable(configure):
        raise _CliError(f"capabilities '{path}' must define configure()")
    try:
        config = configure()
    except Exception as exc:
        raise _CliError(
            f"capabilities configure() failed: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(config, dict):
        raise _CliError("capabilities configure() must return a dict")
    unknown = set(config) - {"functions", "limits", "files"}
    if unknown:
        raise _CliError(f"unknown capabilities key(s): {sorted(map(repr, unknown))!r}")
    functions = config.get("functions")
    if functions is not None and (
        not isinstance(functions, dict)
        or not all(
            isinstance(name, str) and callable(callback)
            for name, callback in functions.items()
        )
    ):
        raise _CliError("capabilities functions must be a dict of callables")
    limits = config.get("limits")
    if limits is not None and not isinstance(limits, SericiteLimits):
        raise _CliError("capabilities limits must be a SericiteLimits")
    files = config.get("files")
    if files is not None and (
        not isinstance(files, dict)
        or not all(
            isinstance(vfs_path, str) and isinstance(text, str)
            for vfs_path, text in files.items()
        )
    ):
        raise _CliError("capabilities files must be a dict of string paths and text")
    return config


def _format_error(
    error: SericiteError, source: _CombinedSource, *, line_offset: int = 0
) -> str:
    if error.filename not in (None, "<sericite>", "<sericite:vm_0>"):
        return str(error)
    error_line = error.line
    if error_line is not None:
        error_line = max(1, error_line - line_offset)
    filename, line = source.location(error_line)
    return str(
        SericiteError(
            error.message,
            kind=error.kind,
            filename=filename,
            line=line,
            column=error.column,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sericite",
        description="Sericite language runtime (Sericite-PY reference implementation)",
        epilog=(
            "examples:\n"
            "  sericite\n"
            "  sericite app.sericite first second\n"
            "  sericite -c 'print(argv)' first second\n"
            "  sericite --capabilities caps.py app.sericite\n"
            "  sericite --include base.sericite app.sericite"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "-c", "--command", help="execute SOURCE as a Sericite command", metavar="SOURCE"
    )
    parser.add_argument(
        "--capabilities",
        metavar="FILE",
        help="trusted Python file defining configure() for the root VM",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="FILE",
        help="prepend source in the same root scope; repeat in desired order",
    )
    parser.add_argument(
        "items",
        nargs=argparse.REMAINDER,
        metavar="SOURCE_FILE [ARG ...]",
        help="source file and script arguments; omit SOURCE_FILE for the REPL",
    )
    return parser


def _report_input_required(
    root: VMHandle, source: _CombinedSource, *, line_offset: int = 0
) -> None:
    snapshot = root.snapshot()
    if snapshot["state"] != "waiting_input":
        return
    error = SericiteError(
        "input required",
        kind="input_error",
        filename="<sericite:vm_0>",
        line=snapshot["next_line"],
    )
    print(_format_error(error, source, line_offset=line_offset), file=sys.stderr)


def _run_root(root: VMHandle, source: _CombinedSource) -> bool:
    try:
        root.run()
    except SericiteError as exc:
        print(_format_error(exc, source), file=sys.stderr)
        return False
    if root.snapshot()["state"] == "waiting_input":
        _report_input_required(root, source)
        return False
    return True


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


def _repl(root: VMHandle) -> int:
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
        try:
            root.exec(delivery)
        except SericiteError as exc:
            print(_format_error(exc, source, line_offset=line_offset), file=sys.stderr)
            continue
        _report_input_required(root, source, line_offset=line_offset)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    values = list(sys.argv[1:] if argv is None else argv)
    cli_args: list[str] = []
    index = 0
    while index < len(values):
        value = values[index]
        if value == "--":
            items = values[index + 1 :]
            break
        if value in {"-c", "--command"}:
            cli_args.extend(values[index : index + 2])
            items = values[index + 2 :]
            break
        if value.startswith("--command=") or (
            value.startswith("-c") and not value.startswith("--") and len(value) > 2
        ):
            cli_args.append(value)
            items = values[index + 1 :]
            break
        if value in {"--include", "--capabilities"}:
            cli_args.extend(values[index : index + 2])
            index += 2
            continue
        if value == "-" or not value.startswith("-"):
            items = values[index:]
            break
        cli_args.append(value)
        index += 1
    else:
        items = []
    args = _parser().parse_args(cli_args)
    args.items = items
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    items = args.items[1:] if args.items[:1] == ["--"] else args.items
    interactive = args.command is None and not items
    if args.command is not None:
        source_name = None
        script_argv = ["-c", *items]
    elif interactive:
        source_name = None
        script_argv = []
    else:
        source_name = items[0]
        script_argv = items

    try:
        source = _load_source(args, source_name, interactive=interactive)
        config = _load_capabilities(args.capabilities) if args.capabilities else {}
    except _CliError as exc:
        print(f"sericite: {exc}", file=sys.stderr)
        return 1

    engine = SericiteEngine()
    try:
        root = engine.create_root(
            source.text,
            input_provider=_read_stdin,
            limits=config.get("limits"),
            functions=config.get("functions"),
            output_writer=_write_stdout,
            buffer_output=False,
            argv=script_argv,
        )
        for path, text in (config.get("files") or {}).items():
            root.write_file(path, text)
    except SericiteError as exc:
        print(_format_error(exc, source), file=sys.stderr)
        return 1

    if not _run_root(root, source):
        return 1
    if interactive:
        return _repl(root)
    return 0
