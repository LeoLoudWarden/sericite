import argparse
import sys
from collections.abc import Sequence

from .. import __version__
from ._hostio import _write_stdout


class _ArgumentParser(argparse.ArgumentParser):
    def _print_message(self, message, file=None):
        if message and file is sys.stdout:
            _write_stdout(message)
        else:
            super()._print_message(message, file)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
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
