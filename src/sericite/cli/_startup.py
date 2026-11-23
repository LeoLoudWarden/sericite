import argparse
import runpy
import sys
from pathlib import Path

from ..engine import SericiteLimits
from ._sources import _CombinedSource


class _CliError(Exception):
    pass


def _read_file(path: str, role: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        detail = exc.strerror if isinstance(exc, OSError) else str(exc)
        raise _CliError(
            f"unable to read {role} '{path}': {detail or 'I/O error'}"
        ) from exc


def _load_source(
    args: argparse.Namespace, source_name: str | None, *, interactive: bool
) -> _CombinedSource:
    parts = []
    if interactive:
        pass
    elif args.command is not None:
        parts.append(("<command>", args.command))
    elif source_name == "-":
        parts.append(("<stdin>", sys.stdin.read().removeprefix("\ufeff")))
    else:
        assert source_name is not None
        parts.append((source_name, _read_file(source_name, "source")))
    return _CombinedSource(parts)


def _load_addons(path: str) -> dict:
    try:
        namespace = runpy.run_path(path)
    except Exception as exc:
        raise _CliError(
            f"unable to load addons '{path}': {type(exc).__name__}: {exc}"
        ) from exc
    configure = namespace.get("configure")
    if not callable(configure):
        raise _CliError(f"addons '{path}' must define configure()")
    try:
        config = configure()
    except Exception as exc:
        raise _CliError(
            f"addons configure() failed: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(config, dict):
        raise _CliError("addons configure() must return a dict")
    unknown = set(config) - {"addons", "limits", "files"}
    if unknown:
        raise _CliError(f"unknown addons key(s): {sorted(map(repr, unknown))!r}")
    addons = config.get("addons")
    if addons is not None and (
        not isinstance(addons, dict)
        or not all(
            isinstance(name, str) and callable(callback)
            for name, callback in addons.items()
        )
    ):
        raise _CliError("addons must be a dict of callables")
    limits = config.get("limits")
    if limits is not None and not isinstance(limits, SericiteLimits):
        raise _CliError("addons limits must be a SericiteLimits")
    files = config.get("files")
    if files is not None and (
        not isinstance(files, dict)
        or not all(
            isinstance(vfs_path, str) and isinstance(text, str)
            for vfs_path, text in files.items()
        )
    ):
        raise _CliError("addons files must be a dict of string paths and text")
    return config
