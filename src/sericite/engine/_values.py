from __future__ import annotations

import dataclasses

from .. import isa
from ..accounting import UNLIMITED, Meter
from ..compiler import RESERVED_NAMES
from ..errors import SericiteError
from ..io import OutputLimitExceeded
from ._model import (
    _CONTRACT_TAGS,
    _TAG_TYPES,
    _VM_OPTIONS,
    SericiteFunction,
    SericiteLimits,
    SericiteRecord,
    SericiteSchema,
    VMHandle,
    _GrantedHostFunction,
    _GrantedSericiteFunction,
    _NativeFunction,
    _TagContract,
)

_MAX_RENDER_NODES = 10_000
_MAX_RENDER_CHARS = 1_048_576


def _contract_text(
    contract: object,
    label: str | None = None,
    _depth: int = 0,
    _seen: set[int] | None = None,
    _budget: list[int] | None = None,
    *,
    meter: Meter | None = None,
) -> str:
    renderer = _StringRenderer(_MAX_RENDER_CHARS, truncate=True, meter=meter)
    if _seen is not None:
        renderer.seen = _seen
    if _budget is not None:
        renderer.remaining_nodes = _budget[0]
    if isinstance(contract, SericiteSchema):
        if label:
            renderer._add(label + " ")
        renderer.render_contract(contract, _depth)
    else:
        renderer._visit()
        renderer._add(label or str(contract))
    if _budget is not None:
        _budget[0] = renderer.remaining_nodes
    return renderer.text()


def _schema_repr(
    schema: SericiteSchema,
    seen: set[int] | None = None,
    budget: list[int] | None = None,
    *,
    meter: Meter | None = None,
) -> str:
    renderer = _StringRenderer(_MAX_RENDER_CHARS, truncate=True, meter=meter)
    if seen is not None:
        renderer.seen = seen
    if budget is not None:
        renderer.remaining_nodes = budget[0]
    renderer.render_schema(schema)
    if budget is not None:
        budget[0] = renderer.remaining_nodes
    return renderer.text()


def _normalize_contract(value: object) -> object:
    if isinstance(value, _TagContract):
        return value.tag
    if isinstance(value, SericiteSchema):
        return value
    if isinstance(value, _NativeFunction) and value.name in _CONTRACT_TAGS:
        return value.name
    raise SericiteError(f"not a contract: {_type_name(value)}", kind="contract_error")


def _contract_holds(value: object, contract: object) -> bool:
    if contract == "any":
        return True
    if isinstance(contract, SericiteSchema):
        return (
            isinstance(value, SericiteRecord) and _schema_fit(value.schema, contract)[0]
        )
    return type(value) is _TAG_TYPES[contract]


def _contract_compatible(actual: object, expected: object) -> bool:
    if expected == "any":
        return True
    if isinstance(expected, SericiteSchema):
        return isinstance(actual, SericiteSchema) and _schema_fit(actual, expected)[0]
    return actual == expected


def _schema_fit(
    actual: SericiteSchema, expected: SericiteSchema
) -> tuple[bool, list[str], list[str]]:
    """Whether actual satisfies expected: all fields present with compatible contracts. Returns (ok, missing fields, contract-mismatched fields)."""
    missing = [name for name, _ in expected.fields if name not in actual.field_map]
    mismatched = [
        name
        for name, contract in expected.fields
        if name in actual.field_map
        and not _contract_compatible(actual.field_map[name], contract)
    ]
    return (not missing and not mismatched, missing, mismatched)


def _actual_text(value: object, *, meter: Meter | None = None) -> str:
    if isinstance(value, SericiteRecord):
        return _contract_text(value.schema, meter=meter)
    return _type_name(value)


def _fit_detail(value: object, expected: object, *, meter: Meter | None = None) -> str:
    if not (isinstance(value, SericiteRecord) and isinstance(expected, SericiteSchema)):
        return ""
    if meter is not None:
        meter.work(_contract_cost(expected))
    _, missing, mismatched = _schema_fit(value.schema, expected)
    parts = []
    if missing:
        parts.append("missing: " + ", ".join(missing))
    if mismatched:
        parts.append("contract mismatch: " + ", ".join(mismatched))
    if meter is not None:
        meter.work(
            len(missing)
            + len(mismatched)
            + sum(len(name) for name in missing + mismatched) // 64
        )
    return f" ({'; '.join(parts)})" if parts else ""


def _contract_violation(
    where: str,
    label: str | None,
    contract: object,
    value: object,
    *,
    meter: Meter | None = None,
) -> SericiteError:
    expected = _contract_text(contract, label, meter=meter)
    return SericiteError(
        f"{where}: expected {expected}, got "
        f"{_actual_text(value, meter=meter)}{_fit_detail(value, contract, meter=meter)}",
        kind="contract_error",
    )


def _contract_cost(contract: object) -> int:
    if isinstance(contract, SericiteSchema):
        return 1 + contract.size
    return 1


def _record_text(
    record: SericiteRecord, hint: str | None = None, *, meter: Meter | None = None
) -> str:
    return f"record {_contract_text(record.schema, hint, meter=meter)}"


class _Iterator:
    __slots__ = ("items", "pos")

    def __init__(self, items: list[object]) -> None:
        self.items = items
        self.pos = 0


def _make_iterator(value: object) -> _Iterator:
    if type(value) is list:
        return _Iterator(value)
    if type(value) is str:
        return _Iterator(list(value))
    if type(value) is dict:
        return _Iterator(list(value.keys()))
    raise SericiteError(f"'{_type_name(value)}' is not iterable", kind="type_error")


def _is_number(value: object) -> bool:
    return type(value) in (int, float)


def _tighten_limit(ceiling: int, requested: int) -> int:
    if ceiling == UNLIMITED:
        return requested
    if requested == UNLIMITED:
        return ceiling
    return min(ceiling, requested)


def _min_limits(a: SericiteLimits, b: SericiteLimits) -> SericiteLimits:
    return dataclasses.replace(
        a,
        **{
            key: _tighten_limit(getattr(a, key), getattr(b, key)) for key in _VM_OPTIONS
        },
    )


def _stamp_origin(code: isa.CodeUnit, vm_id: int, source_id: int = 0) -> None:
    """Stamp a CodeUnit tree with its defining VM and source delivery."""
    seen: set[int] = set()
    units = [code]
    while units:
        unit = units.pop()
        if id(unit) in seen:
            continue
        seen.add(id(unit))
        unit.origin_vm = vm_id
        unit.source_id = source_id
        for instr in unit.instrs:
            if instr.op == isa.MAKE_FUNCTION:
                units.append(instr.arg[0])


def _check_grant_name(name: object) -> None:
    if not isinstance(name, str) or not name.isidentifier() or name.startswith("__"):
        raise SericiteError(
            f"invalid granted function name: {name!r}", kind="type_error"
        )
    if name in RESERVED_NAMES:
        raise SericiteError(
            f"granted function name '{name}' conflicts with a builtin",
            kind="type_error",
        )


def _to_host(
    value: object,
    budget: list[int],
    depth: int = 0,
    *,
    meter: Meter,
) -> object:
    """Deep-copy one bounded node at a time, charging before each node is processed."""
    budget[0] -= 1
    if budget[0] < 0:
        raise SericiteError("FFI argument structure too large", kind="ffi_error")
    if depth > 64:
        raise SericiteError("FFI argument nested too deeply", kind="ffi_error")
    meter.work(1)
    if value is None or type(value) in (str, int, float, bool):
        return value
    if type(value) is list:
        return [_to_host(item, budget, depth + 1, meter=meter) for item in value]
    if type(value) is dict:
        return {
            _to_host(key, budget, depth + 1, meter=meter): _to_host(
                item, budget, depth + 1, meter=meter
            )
            for key, item in value.items()
        }
    if isinstance(value, (SericiteRecord, SericiteSchema)):
        raise SericiteError(
            f"'{_type_name(value)}' cannot cross the host boundary; "
            "unwrap it to a dict first",
            kind="ffi_error",
        )
    raise SericiteError(
        f"value of type '{_type_name(value)}' cannot cross the host boundary",
        kind="ffi_error",
    )


def _from_host(
    value: object,
    budget: list[int],
    limits: SericiteLimits,
    depth: int = 0,
    *,
    meter: Meter,
) -> object:
    """Validate and copy one bounded node at a time, charging work and space upfront."""
    budget[0] -= 1
    if budget[0] < 0:
        raise SericiteError("FFI result structure too large", kind="ffi_error")
    if depth > 64:
        raise SericiteError("FFI result nested too deeply", kind="ffi_error")
    meter.work(1)
    if type(value) is int and value.bit_length() > limits.max_int_bits:
        raise SericiteError("FFI result integer too large", kind="ffi_error")
    if value is None or type(value) in (int, float, bool):
        meter.allocate(8)
        return value
    if type(value) is str:
        if len(value) > limits.max_string_bytes:
            raise SericiteError("FFI result string too large", kind="ffi_error")
        meter.allocate(len(value) * 4)
        return value
    if type(value) in (list, tuple):
        if len(value) > limits.max_list_size:
            raise SericiteError("FFI result list too large", kind="ffi_error")
        meter.allocate(len(value) * 8)
        return [
            _from_host(item, budget, limits, depth + 1, meter=meter) for item in value
        ]
    if type(value) is dict:
        if len(value) > limits.max_dict_size:
            raise SericiteError("FFI result dict too large", kind="ffi_error")
        meter.allocate(len(value) * 16)
        result: dict[object, object] = {}
        for key, item in value.items():
            if type(key) not in (str, int, float, bool) and key is not None:
                raise SericiteError(
                    f"FFI result has unhashable key of type '{type(key).__name__}'",
                    kind="ffi_error",
                )
            copied_key = _from_host(key, budget, limits, depth + 1, meter=meter)
            result[copied_key] = _from_host(
                item, budget, limits, depth + 1, meter=meter
            )
        return result
    raise SericiteError(
        f"host function returned unsupported type '{type(value).__name__}'",
        kind="ffi_error",
    )


def _const_bytes(code: isa.CodeUnit) -> int:
    total = 0
    for instr in code.instrs:
        if instr.op == isa.LOAD_CONST and type(instr.arg) is str:
            total += len(instr.arg) * 4
        elif instr.op == isa.MAKE_FUNCTION:
            total += _const_bytes(instr.arg[0])
    return total


def _estimate_size(value: object, *, meter: Meter) -> None:
    """Charge ownership transfer and estimation work for every node of a result.

    Every node is charged; if the caller's quotas cannot cover the full result,
    the meter raises and the result is not delivered.
    """
    meter.work(1)
    if type(value) is str:
        meter.work(len(value) // 64)
        size = len(value) * 4
    elif type(value) is list:
        size = len(value) * 8
    elif type(value) is dict:
        size = len(value) * 16
    else:
        size = 8
    meter.allocate(size)
    if type(value) is list:
        for item in value:
            _estimate_size(item, meter=meter)
    elif type(value) is dict:
        for key, item in value.items():
            _estimate_size(key, meter=meter)
            _estimate_size(item, meter=meter)


def _truthy(value: object) -> bool:
    if value is None:
        return False
    if type(value) is bool:
        return value
    if type(value) in (int, float):
        return value != 0
    if isinstance(value, (str, list, dict)):
        return len(value) > 0
    return True


def _equals(
    left: object,
    right: object,
    _active: set | None = None,
    _cache: dict | None = None,
    *,
    meter: Meter,
) -> bool:
    """Compare structurally, charging each visited node before processing it."""
    meter.work(1)
    if _is_number(left) and _is_number(right):
        return left == right
    if left is right:
        return True
    if type(left) is not type(right):
        return False
    if type(left) is str:
        meter.work(len(left))
        return left == right
    if isinstance(left, bool) or left is None:
        return left == right
    if isinstance(left, (list, dict, SericiteRecord)):
        pair = (id(left), id(right))
        if _active is not None:
            if pair in _active:
                return True
            cached = _cache.get(pair)
            if cached is not None:
                return cached
            _active.add(pair)
            result = _equals_container(left, right, _active, _cache, meter)
            _active.discard(pair)
            _cache[pair] = result
            return result
        return _equals_container(left, right, _active, _cache, meter)
    if isinstance(left, SericiteSchema):
        meter.work(len(left.key))
        return left.key == right.key
    return left is right


def _equals_container(
    left: object,
    right: object,
    active: set | None,
    cache: dict | None,
    meter: Meter,
) -> bool:
    if type(left) is list:
        return len(left) == len(right) and all(
            _equals(a, b, active, cache, meter=meter) for a, b in zip(left, right)
        )
    if type(left) is dict:
        meter.work(len(left))
        return left.keys() == right.keys() and all(
            _equals(left[key], right[key], active, cache, meter=meter) for key in left
        )
    meter.work(len(left.schema.key))
    return left.schema.key == right.schema.key and _equals(
        left.fields, right.fields, active, cache, meter=meter
    )


def _contains(
    container: object,
    item: object,
    _active: set | None = None,
    _cache: dict | None = None,
    *,
    meter: Meter,
) -> bool:
    if type(container) is dict:
        if type(item) not in (str, int, float, bool) and item is not None:
            raise SericiteError(
                f"unhashable key type: {_type_name(item)}",
                kind="type_error",
            )
        if type(item) is str:
            meter.work(len(item))
        return item in container
    if type(container) is list:
        return any(
            _equals(element, item, _active, _cache, meter=meter)
            for element in container
        )
    if type(container) is str and type(item) is str:
        meter.work(len(container))
        return item in container
    raise SericiteError(
        f"'in' not supported between {_type_name(item)} and {_type_name(container)}",
        kind="type_error",
    )


def _type_name(value: object) -> str:
    if value is None:
        return "None"
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is float:
        return "float"
    if type(value) is str:
        return "str"
    if type(value) is list:
        return "list"
    if type(value) is dict:
        return "dict"
    if isinstance(value, SericiteFunction):
        return "function"
    if isinstance(value, _NativeFunction):
        return "function"
    if isinstance(value, (_GrantedHostFunction, _GrantedSericiteFunction)):
        return "function"
    if isinstance(value, VMHandle):
        return "VM"
    if isinstance(value, SericiteRecord):
        return "record"
    if isinstance(value, SericiteSchema):
        return "schema"
    if isinstance(value, _TagContract):
        return value.tag
    return type(value).__name__


def _operand_error(op: str, left: object, right: object) -> SericiteError:
    return SericiteError(
        f"unsupported operand types for '{op}': "
        f"{_type_name(left)} and {_type_name(right)}",
        kind="type_error",
    )


class _StringRenderer:
    def __init__(
        self,
        max_chars: int,
        *,
        output: bool = False,
        truncate: bool = False,
        meter: Meter | None = None,
    ) -> None:
        self.parts: list[str] = []
        self.size = 0
        self.seen: set[int] = set()
        self.remaining_nodes = _MAX_RENDER_NODES
        self.remaining_chars = max(0, max_chars)
        self.output = output
        self.truncate = truncate
        self.meter = meter
        self.exhausted = False

    def _work(self, amount: int) -> None:
        if self.meter is not None:
            self.meter.work(amount)

    def _add(self, text: str) -> None:
        if self.exhausted:
            return
        if len(text) > self.remaining_chars:
            if self.truncate:
                if self.remaining_chars >= 3:
                    self.parts.append("...")
                    self.size += 3
                    self.remaining_chars -= 3
                self.exhausted = True
                return
            if self.output:
                raise OutputLimitExceeded
            raise SericiteError("string size limit exceeded", kind="resource_exhausted")
        self.parts.append(text)
        self.size += len(text)
        self.remaining_chars -= len(text)

    def _visit(self) -> None:
        if self.exhausted:
            return
        if self.remaining_nodes <= 0:
            if self.truncate:
                self._add("...")
                self.exhausted = True
                return
            raise SericiteError(
                "rendering node limit exceeded", kind="resource_exhausted"
            )
        self.remaining_nodes -= 1
        self._work(1)

    def render(self, value: object, repr_strings: bool = False, depth: int = 0) -> None:
        self._visit()
        if self.exhausted:
            return
        if value is None:
            self._add("None")
            return
        if type(value) is bool:
            self._add("True" if value else "False")
            return
        if type(value) is str:
            if repr_strings:
                self._work(len(value) // 64)
                self._add(repr(value))
            else:
                self._add(value)
            return
        if type(value) in (int, float):
            if type(value) is int:
                self._work(value.bit_length() // 64)
            self._add(str(value))
            return
        if type(value) in (list, dict) or isinstance(value, SericiteRecord):
            ident = id(value)
            if ident in self.seen:
                if type(value) is list:
                    self._add("[...]")
                elif type(value) is dict:
                    self._add("{...}")
                else:
                    self._add("record(...)")
                return
            if depth > 64:
                self._add("<max depth>")
                return
            self.seen.add(ident)
            if type(value) is list:
                self._add("[")
                for index, item in enumerate(value):
                    if index:
                        self._add(", ")
                    self.render(item, True, depth + 1)
                    if self.exhausted:
                        return
                self._add("]")
                return
            if isinstance(value, SericiteRecord):
                self._add("record(")
                items = value.fields.items()
                separator = "="
            else:
                self._add("{")
                items = value.items()
                separator = ": "
            for index, (key, item) in enumerate(items):
                if index:
                    self._add(", ")
                if isinstance(value, SericiteRecord):
                    self._add(str(key))
                else:
                    self.render(key, True, depth + 1)
                self._add(separator)
                self.render(item, True, depth + 1)
                if self.exhausted:
                    return
            self._add(")" if isinstance(value, SericiteRecord) else "}")
            return
        if isinstance(value, SericiteSchema):
            self.render_schema(value)
            return
        self._add(repr(value))

    def render_schema(self, schema: SericiteSchema) -> None:
        if self.exhausted:
            return
        if id(schema) in self.seen:
            self._add("schema(...)")
            return
        self.seen.add(id(schema))
        self._add("schema(")
        for index, (name, contract) in enumerate(schema.fields):
            if index:
                self._add(", ")
            self._add(name)
            self._add(": ")
            self.render_contract(contract)
            if self.exhausted:
                return
        self._add(")")

    def render_contract(self, contract: object, depth: int = 0) -> None:
        self._visit()
        if self.exhausted:
            return
        if not isinstance(contract, SericiteSchema):
            self._add(str(contract))
            return
        if depth >= 64 or id(contract) in self.seen:
            self._add("...")
            return
        self.seen.add(id(contract))
        self._add("{")
        for index, (name, inner) in enumerate(contract.fields):
            if index:
                self._add(", ")
            self._add(name)
            self._add(": ")
            self.render_contract(inner, depth + 1)
            if self.exhausted:
                return
        self._add("}")

    def text(self, *, allocate: bool = False) -> str:
        self._work(self.size // 64)
        if allocate and self.meter is not None:
            self.meter.allocate(self.size * 4)
        return "".join(self.parts)


def _to_str(
    value: object,
    max_chars: int = _MAX_RENDER_CHARS,
    *,
    meter: Meter | None = None,
) -> str:
    renderer = _StringRenderer(max_chars, meter=meter)
    renderer.render(value)
    return renderer.text(allocate=meter is not None)
