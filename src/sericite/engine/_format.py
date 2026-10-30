from __future__ import annotations

import math
from dataclasses import dataclass

from ..accounting import Meter
from ..errors import SericiteError
from ._values import _MAX_RENDER_CHARS, _StringRenderer, _to_str, _type_name

_INTEGER_TYPES = frozenset({"", "b", "c", "d", "o", "x", "X"})
_FLOAT_TYPES = frozenset({"e", "E", "f", "F", "g", "G", "%"})
_NUMERIC_TYPES = _INTEGER_TYPES | _FLOAT_TYPES


@dataclass(frozen=True)
class _FormatSpec:
    align: str | None
    sign: str | None
    negative_zero: bool
    alternate: bool
    zero: bool
    width: int
    grouping: str | None
    precision: int | None
    presentation: str


def _invalid_spec() -> SericiteError:
    return SericiteError("invalid format spec", kind="conversion_error")


def _unsupported_spec(value: object) -> SericiteError:
    return SericiteError(
        f"format spec is not supported for {_type_name(value)}", kind="type_error"
    )


def _parse_number(spec: str, position: int, max_chars: int) -> tuple[int, int]:
    value = 0
    while position < len(spec) and "0" <= spec[position] <= "9":
        digit = ord(spec[position]) - ord("0")
        if value > (max_chars - digit) // 10:
            raise SericiteError(
                "formatted string size limit exceeded", kind="resource_exhausted"
            )
        value = value * 10 + digit
        position += 1
    return value, position


def _parse_spec(spec: str, max_chars: int) -> _FormatSpec:
    position = 0
    align = None
    if len(spec) >= 2 and spec[1] in "<>=^":
        align = spec[1]
        position = 2
    elif spec and spec[0] in "<>=^":
        align = spec[0]
        position = 1

    sign = None
    if position < len(spec) and spec[position] in "+- ":
        sign = spec[position]
        position += 1

    negative_zero = False
    if position < len(spec) and spec[position] == "z":
        negative_zero = True
        position += 1

    alternate = False
    if position < len(spec) and spec[position] == "#":
        alternate = True
        position += 1

    zero = False
    if position < len(spec) and spec[position] == "0":
        zero = True
        position += 1

    width, position = _parse_number(spec, position, max_chars)

    grouping = None
    if position < len(spec) and spec[position] in ",_":
        grouping = spec[position]
        position += 1

    precision = None
    if position < len(spec) and spec[position] == ".":
        position += 1
        if position >= len(spec) or not "0" <= spec[position] <= "9":
            raise _invalid_spec()
        precision, position = _parse_number(spec, position, max_chars)

    presentation = ""
    if position < len(spec):
        presentation = spec[position]
        position += 1
    if position != len(spec):
        raise _invalid_spec()
    return _FormatSpec(
        align,
        sign,
        negative_zero,
        alternate,
        zero,
        width,
        grouping,
        precision,
        presentation,
    )


def _decimal_digits(value: int) -> int:
    bits = value.bit_length()
    return max(1, (bits * 30103) // 100000 + 1)


def _sign_size(value: float, spec: _FormatSpec) -> int:
    negative = value < 0 if type(value) is int else math.copysign(1, value) < 0
    return 1 if negative or spec.sign in ("+", " ") else 0


def _float_exponent(value: float) -> int:
    text = str(abs(value))
    if "e" in text:
        return int(text.rsplit("e", 1)[1])
    whole, fraction = text.split(".")
    if whole != "0":
        return len(whole) - 1
    for index, char in enumerate(fraction):
        if char != "0":
            return -(index + 1)
    return 0


def _exponent_notation(exponent: int) -> int:
    return 2 + max(2, len(str(abs(exponent))))


def _float_bound(value: float, spec: _FormatSpec) -> int:
    integer = type(value) is int
    precision = 6 if spec.precision is None else spec.precision
    presentation = spec.presentation
    sign = _sign_size(value, spec)
    if not integer and not math.isfinite(value):
        size = 3 + sign + (1 if presentation == "%" else 0)
        return max(spec.width, size)

    exponent = _decimal_digits(value) - 1 if integer else _float_exponent(value)
    integer_digits = max(1, exponent + 1)
    if presentation == "" and spec.precision is None and not integer:
        grouping = (integer_digits - 1) // 3 if spec.grouping else 0
        return max(spec.width, len(str(abs(value))) + sign + grouping)

    point = 1 if precision > 0 or spec.alternate else 0
    if presentation in ("f", "F", "%"):
        digits = integer_digits + (2 if presentation == "%" else 0)
        grouping = (digits - 1) // 3 if spec.grouping else 0
        size = digits + precision + point + sign + grouping
        if presentation == "%":
            size += 1
        return max(spec.width, size)
    if presentation in ("e", "E"):
        size = 1 + precision + point + _exponent_notation(exponent) + sign
        return max(spec.width, size)

    significant = max(1, precision)
    scientific = significant + 1 + _exponent_notation(exponent) + sign
    grouping = (integer_digits - 1) // 3 if spec.grouping else 0
    fixed = significant + max(0, -exponent) + 1 + sign + grouping
    if not integer and -4 <= exponent < significant:
        return max(spec.width, fixed)
    if not integer:
        return max(spec.width, scientific)
    return max(spec.width, fixed, scientific)


def _integer_bound(value: int, spec: _FormatSpec) -> int:
    presentation = spec.presentation
    if presentation in _FLOAT_TYPES:
        return _float_bound(value, spec)
    if presentation == "c":
        return max(spec.width, 1)

    bits = value.bit_length()
    if presentation == "b":
        digits = max(1, bits)
    elif presentation == "o":
        digits = max(1, (bits + 2) // 3)
    elif presentation in ("x", "X"):
        digits = max(1, (bits + 3) // 4)
    else:
        digits = _decimal_digits(value)

    prefix = 2 if spec.alternate and presentation in ("b", "o", "x", "X") else 0
    if spec.grouping and presentation in ("", "d"):
        grouping = (digits - 1) // 3
    elif spec.grouping == "_":
        grouping = (digits - 1) // 4
    else:
        grouping = 0
    return max(spec.width, digits + prefix + grouping + _sign_size(value, spec))


def _result_bound(value: str | float, spec: _FormatSpec) -> int:
    if type(value) is str:
        size = len(value)
        if spec.precision is not None:
            size = min(size, spec.precision)
        return max(spec.width, size)
    if type(value) is int:
        return _integer_bound(value, spec)
    return _float_bound(value, spec)


def _validate_value_spec(value: str | float, spec: _FormatSpec) -> None:
    if type(value) is str:
        if (
            spec.presentation not in ("", "s")
            or spec.align == "="
            or spec.sign is not None
            or spec.negative_zero
            or spec.alternate
            or spec.zero
            or spec.grouping is not None
        ):
            raise _invalid_spec()
        return
    if type(value) is int:
        if spec.presentation not in _NUMERIC_TYPES:
            raise _unsupported_spec(value)
        if spec.precision is not None and spec.presentation in _INTEGER_TYPES:
            raise _invalid_spec()
        return
    if spec.presentation not in _FLOAT_TYPES | {""}:
        raise _unsupported_spec(value)


def _format_with_spec(
    value: str | float,
    raw_spec: str,
    max_chars: int,
    meter: Meter | None,
) -> str:
    spec = _parse_spec(raw_spec, max_chars)
    _validate_value_spec(value, spec)
    bound = _result_bound(value, spec)
    if bound > max_chars:
        raise SericiteError(
            "formatted string size limit exceeded", kind="resource_exhausted"
        )
    if meter is not None:
        meter.work(bound // 64)
        meter.allocate(bound * 4)
    try:
        result = format(value, raw_spec)
    except (ValueError, OverflowError):
        raise _invalid_spec() from None
    if len(result) > bound:
        raise SericiteError(
            "formatted string exceeds size bound", kind="internal_error"
        )
    return result


def _format_value(
    value: object,
    conversion: int,
    max_chars: int = _MAX_RENDER_CHARS,
    *,
    spec: str | None = None,
    meter: Meter | None = None,
) -> str:
    if conversion not in (-1, 97, 114, 115):
        raise SericiteError("unknown f-string conversion", kind="internal_error")
    if spec is not None and meter is not None:
        meter.work(len(spec))

    if conversion == -1:
        if spec:
            if type(value) not in (str, int, float):
                raise _unsupported_spec(value)
            return _format_with_spec(value, spec, max_chars, meter)
        return _to_str(value, max_chars, meter=meter)

    if conversion == 115:
        converted = _to_str(value, max_chars, meter=meter)
    else:
        renderer = _StringRenderer(max_chars, meter=meter, ascii_only=conversion == 97)
        renderer.render(value, repr_strings=True)
        converted = renderer.text(allocate=meter is not None)
    if spec:
        return _format_with_spec(converted, spec, max_chars, meter)
    return converted
