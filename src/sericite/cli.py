import argparse
import runpy
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .engine import SericiteEngine, SericiteError, SericiteLimits


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
        if line is None:
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


def _load_source(args: argparse.Namespace) -> _CombinedSource:
    parts = [(path, _read_file(path, "include")) for path in args.include]
    if args.command is not None:
        parts.append(("<command>", args.command))
    elif args.source == "-":
        parts.append(("<stdin>", sys.stdin.read()))
    else:
        parts.append((args.source, _read_file(args.source, "source")))
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


def _format_error(error: SericiteError, source: _CombinedSource) -> str:
    if error.filename not in (None, "<sericite>", "<sericite:vm_0>"):
        return str(error)
    filename, line = source.location(error.line)
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
            "  sericite app.sericite\n"
            "  sericite -c 'print(\"hello\")'\n"
            "  sericite --capabilities caps.py app.sericite\n"
            "  sericite --include base.sericite app.sericite"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    entry = parser.add_mutually_exclusive_group(required=True)
    entry.add_argument("source", nargs="?", help="Sericite source file, or - for stdin")
    entry.add_argument(
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source = _load_source(args)
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
        )
        for path, text in (config.get("files") or {}).items():
            root.write_file(path, text)
    except SericiteError as exc:
        print(_format_error(exc, source), file=sys.stderr)
        return 1

    try:
        root.run()
    except SericiteError as exc:
        print(_format_error(exc, source), file=sys.stderr)
        return 1

    snapshot = root.snapshot()
    if snapshot["state"] == "waiting_input":
        error = SericiteError(
            "input required",
            kind="input_error",
            filename="<sericite:vm_0>",
            line=snapshot["next_line"],
        )
        print(_format_error(error, source), file=sys.stderr)
        return 1
    return 0
