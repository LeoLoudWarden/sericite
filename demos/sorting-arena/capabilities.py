"""Trusted startup configuration for the sorting arena demo."""

import random
from pathlib import Path

from sericite import SericiteError, SericiteLimits

BASE_DIR = Path(__file__).resolve().parent


def random_int(below):
    if isinstance(below, bool) or not isinstance(below, int) or below <= 0:
        raise SericiteError("random_int expects a positive integer", kind="ffi_error")
    return random.randrange(below)


def configure():
    entries = {}
    for path in sorted((BASE_DIR / "entries").glob("*.sericite")):
        entries["/entries/" + path.name] = path.read_text(encoding="utf-8")
    return {
        "limits": SericiteLimits(max_instructions=20_000_000),
        "functions": {"random_int": random_int},
        "files": entries,
    }
