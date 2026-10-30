import sys
from collections.abc import Sequence

from ..engine import SericiteEngine, SericiteError, VMHandle
from ._diagnostics import _format_error
from ._hostio import _read_stdin, _StdoutClosed, _write_stdout
from ._options import _parse_args
from ._repl import _repl
from ._sources import _CombinedSource
from ._sources import _ReplSourceMap as _ReplSourceMap
from ._startup import _CliError, _load_capabilities, _load_source


def _run_root(root: VMHandle, source: _CombinedSource) -> bool:
    try:
        root.run()
    except SericiteError as exc:
        print(_format_error(exc, source), file=sys.stderr)
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _main(argv)
    except _StdoutClosed:
        return 0


def _main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    items = args.items
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
        return _repl(root, source)
    return 0
