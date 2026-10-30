import os
import sys

from ..errors import SericiteError


class _StdoutClosed(BaseException):
    pass


def _read_stdin() -> str:
    value = sys.stdin.readline()
    if value:
        return value
    raise SericiteError("input required", kind="input_error")


def _write_stdout(value: str) -> None:
    try:
        sys.stdout.write(value)
        sys.stdout.flush()
    except BrokenPipeError:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull_fd, sys.stdout.fileno())
        finally:
            os.close(devnull_fd)
        raise _StdoutClosed() from None
