from __future__ import annotations

from ..errors import SericiteError
from ._model import (
    SericiteRecord,
    SericiteSchema,
    VMContext,
    VMHandle,
    _NativeFunction,
    _no_allocation,
    _no_work,
)
from ._values import (
    _contains,
    _contract_cost,
    _contract_holds,
    _contract_violation,
    _equals,
    _is_number,
    _operand_error,
    _record_text,
    _to_str,
    _truthy,
    _type_name,
)


class _EngineOperators:
    def _binary_op(
        self, context: VMContext, op: str, left: object, right: object
    ) -> object:
        if op == "+":
            if type(left) is str and type(right) is str:
                if len(left) + len(right) > context.limits.max_string_bytes:
                    raise SericiteError(
                        "string size limit exceeded", kind="resource_exhausted"
                    )
                self._meter(context).allocate((len(left) + len(right)) * 4)
                self._meter(context).work((len(left) + len(right)) // 64)
                return left + right
            if type(left) is list and type(right) is list:
                result = left + right
                if len(result) > context.limits.max_list_size:
                    raise SericiteError(
                        "list size limit exceeded", kind="resource_exhausted"
                    )
                self._meter(context).allocate(len(result) * 8)
                self._meter(context).work(len(result))
                return result
            if _is_number(left) and _is_number(right):
                return self._check_int(context, left + right)
            raise _operand_error(op, left, right)
        if op in ("-", "*"):
            if _is_number(left) and _is_number(right):
                return self._check_int(
                    context, left - right if op == "-" else left * right
                )
            raise _operand_error(op, left, right)
        if op in ("/", "//", "%"):
            if _is_number(left) and _is_number(right):
                if right == 0:
                    raise SericiteError(
                        "division by zero" if op != "%" else "modulo by zero",
                        kind="zero_division",
                    )
                if op == "/":
                    return left / right
                if op == "//":
                    return self._check_int(context, left // right)
                return self._check_int(context, left % right)
            raise _operand_error(op, left, right)
        raise SericiteError(f"unknown operator: {op}", kind="internal_error")

    def _check_int(self, context: VMContext, value: object) -> object:
        if type(value) is int and value.bit_length() > context.limits.max_int_bits:
            raise SericiteError(
                "integer size limit exceeded", kind="resource_exhausted"
            )
        return value

    def _unary_op(self, context: VMContext, op: str, value: object) -> object:
        if op == "-":
            if _is_number(value):
                return self._check_int(context, -value)
            raise SericiteError(
                f"bad operand type for unary '-': {_type_name(value)}",
                kind="type_error",
            )
        if op == "not":
            return not _truthy(value)
        raise SericiteError(f"unknown operator: {op}", kind="internal_error")

    def _compare_op(
        self, context: VMContext, op: str, left: object, right: object
    ) -> bool:
        if op in ("==", "!="):
            meter = self._meter(context)
            meter.work(1)
            result = _equals(left, right, set(), {}, meter=meter)
            return result if op == "==" else not result
        if op in ("in", "not in"):
            meter = self._meter(context)
            meter.work(1)
            result = _contains(right, left, set(), {}, meter=meter)
            return result if op == "in" else not result
        if (_is_number(left) and _is_number(right)) or (
            type(left) is str and type(right) is str
        ):
            if type(left) is str:
                self._meter(context).work(min(len(left), len(right)))
            if op == "<":
                return left < right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            return left >= right
        raise SericiteError(
            f"'{op}' not supported between {_type_name(left)} and {_type_name(right)}",
            kind="type_error",
        )

    def _index(self, context: VMContext, value: object, index: object) -> object:
        if type(value) is dict:
            if type(index) not in (str, int, float, bool) and index is not None:
                raise SericiteError(
                    f"unhashable key type: {_type_name(index)}",
                    kind="type_error",
                )
            if type(index) is str:
                self._meter(context).work(len(index))
            if index not in value:
                raise SericiteError(
                    f"missing key: {_to_str(index)!s}", kind="key_error"
                )
            return value[index]
        if isinstance(value, (str, list)):
            if type(index) is not int:
                raise SericiteError(
                    f"indices must be int, got {_type_name(index)}",
                    kind="type_error",
                )
            if not -len(value) <= index < len(value):
                raise SericiteError("index out of range", kind="index_error")
            return value[index]
        raise SericiteError(
            f"'{_type_name(value)}' is not indexable", kind="type_error"
        )

    def _store_index(
        self, context: VMContext, target: object, index: object, value: object
    ) -> None:
        if type(target) is dict:
            if type(index) not in (str, int, float, bool) and index is not None:
                raise SericiteError(
                    f"unhashable key type: {_type_name(index)}",
                    kind="type_error",
                )
            if type(index) is str:
                self._meter(context).work(len(index))
            if index not in target and len(target) >= context.limits.max_dict_size:
                raise SericiteError(
                    "dict size limit exceeded", kind="resource_exhausted"
                )
            if index not in target:
                self._meter(context).allocate(16)
            target[index] = value
            return
        if type(target) is not list:
            raise SericiteError(
                f"'{_type_name(target)}' does not support item assignment",
                kind="type_error",
            )
        if type(index) is not int:
            raise SericiteError(
                f"indices must be int, got {_type_name(index)}",
                kind="type_error",
            )
        if not -len(target) <= index < len(target):
            raise SericiteError("index out of range", kind="index_error")
        target[index] = value

    def _load_attr(
        self, context: VMContext, value: object, attr: str, hint: str | None
    ) -> object:
        if isinstance(value, SericiteRecord):
            if attr in value.fields:
                return value.fields[attr]
            raise SericiteError(
                f"{_record_text(value, hint)} has no field '{attr}'",
                kind="attribute_error",
            )
        if isinstance(value, VMHandle) and attr in VMHandle._METHODS:
            return _NativeFunction(
                f"VM.{attr}",
                lambda *a, **k: self._charged_vm_method(value, attr, a, k),
                self._context(value),
                work=lambda *a, **k: self._vm_method_work(value, attr, a, k),
                allocation=lambda *a, **k: self._vm_method_allocation(
                    value, attr, a, k
                ),
                needs_caller=True,
            )
        if isinstance(value, VMHandle):
            raise SericiteError(f"VM has no method '{attr}'", kind="attribute_error")
        if type(value) is list:
            if attr == "append":
                return _NativeFunction(
                    "list.append",
                    lambda *args: self._list_append(context, value, args),
                    context,
                    work=_no_work,
                    allocation=lambda *args: 8 if len(args) == 1 else 0,
                )
            if attr == "pop":
                return _NativeFunction(
                    "list.pop",
                    lambda *args: self._list_pop(context, value, args),
                    context,
                    work=lambda *args: self._list_pop_work(value, args),
                    allocation=_no_allocation,
                )
        if type(value) is dict:
            if attr in ("keys", "values"):
                return _NativeFunction(
                    f"dict.{attr}",
                    lambda *args: self._dict_snapshot(context, value, attr, args),
                    context,
                    work=lambda *args: 0 if args else len(value),
                    allocation=lambda *args: 0 if args else len(value) * 8,
                )
            if attr == "get":
                return _NativeFunction(
                    "dict.get",
                    lambda *args: self._dict_get(context, value, args),
                    context,
                    work=lambda *args: self._dict_method_work(args),
                    allocation=_no_allocation,
                )
            if attr == "pop":
                return _NativeFunction(
                    "dict.pop",
                    lambda *args: self._dict_pop(context, value, args),
                    context,
                    work=lambda *args: self._dict_method_work(args),
                    allocation=_no_allocation,
                )
        if type(value) in (list, dict):
            raise SericiteError(
                f"{_type_name(value)} has no method '{attr}'", kind="attribute_error"
            )
        raise SericiteError(
            f"'{_type_name(value)}' does not support attribute access",
            kind="type_error",
        )

    def _list_append(
        self, context: VMContext, target: list[object], args: tuple[object, ...]
    ) -> None:
        if len(args) != 1:
            raise SericiteError(
                f"list.append() expects 1 argument(s), got {len(args)}",
                kind="arity_error",
            )
        if len(target) >= context.limits.max_list_size:
            raise SericiteError("list size limit exceeded", kind="resource_exhausted")
        target.append(args[0])

    @staticmethod
    def _list_pop_work(target: list[object], args: tuple[object, ...]) -> int:
        if len(args) > 1:
            return 0
        index = args[0] if args else -1
        if type(index) is not int or not -len(target) <= index < len(target):
            return 0
        if index < 0:
            index += len(target)
        return len(target) - index - 1

    def _list_pop(
        self, context: VMContext, target: list[object], args: tuple[object, ...]
    ) -> object:
        if len(args) > 1:
            raise SericiteError(
                f"list.pop() expects 0 to 1 argument(s), got {len(args)}",
                kind="arity_error",
            )
        index = args[0] if args else -1
        if type(index) is not int:
            raise SericiteError(
                f"indices must be int, got {_type_name(index)}", kind="type_error"
            )
        if not -len(target) <= index < len(target):
            raise SericiteError("pop index out of range", kind="index_error")
        if index < 0:
            index += len(target)
        return target.pop(index)

    def _dict_snapshot(
        self,
        context: VMContext,
        target: dict[object, object],
        attr: str,
        args: tuple[object, ...],
    ) -> list[object]:
        if args:
            raise SericiteError(
                f"dict.{attr}() expects 0 argument(s), got {len(args)}",
                kind="arity_error",
            )
        if len(target) > context.limits.max_list_size:
            raise SericiteError("list size limit exceeded", kind="resource_exhausted")
        return list(target.keys()) if attr == "keys" else list(target.values())

    @staticmethod
    def _dict_method_work(args: tuple[object, ...]) -> int:
        return len(args[0]) if args and isinstance(args[0], str) else 0

    @staticmethod
    def _check_dict_method_key(key: object) -> None:
        if type(key) not in (str, int, float, bool) and key is not None:
            raise SericiteError(
                f"unhashable key type: {_type_name(key)}", kind="type_error"
            )

    def _dict_get(
        self,
        context: VMContext,
        target: dict[object, object],
        args: tuple[object, ...],
    ) -> object:
        if not 1 <= len(args) <= 2:
            raise SericiteError(
                f"dict.get() expects 1 to 2 argument(s), got {len(args)}",
                kind="arity_error",
            )
        self._check_dict_method_key(args[0])
        default = args[1] if len(args) == 2 else None
        return target.get(args[0], default)

    def _dict_pop(
        self,
        context: VMContext,
        target: dict[object, object],
        args: tuple[object, ...],
    ) -> object:
        if not 1 <= len(args) <= 2:
            raise SericiteError(
                f"dict.pop() expects 1 to 2 argument(s), got {len(args)}",
                kind="arity_error",
            )
        self._check_dict_method_key(args[0])
        if args[0] not in target:
            if len(args) == 2:
                return args[1]
            raise SericiteError(f"missing key: {_to_str(args[0])!s}", kind="key_error")
        return target.pop(args[0])

    @staticmethod
    def _wrap_work(schema: object, data: object) -> int:
        if not isinstance(schema, SericiteSchema) or type(data) is not dict:
            return 0
        return len(data) + sum(
            _contract_cost(contract) for _, contract in schema.fields
        )

    @staticmethod
    def _wrap_allocation(schema: object, data: object) -> int:
        if not isinstance(schema, SericiteSchema) or type(data) is not dict:
            return 0
        return 64 + len(schema.fields) * 16

    def _wrap(self, context: VMContext, schema: object, data: object) -> SericiteRecord:
        if not isinstance(schema, SericiteSchema):
            raise SericiteError(
                f"wrap() expects a schema, got {_type_name(schema)}",
                kind="type_error",
            )
        if type(data) is not dict:
            raise SericiteError(
                f"wrap() expects a dict, got {_type_name(data)}",
                kind="type_error",
            )
        field_names = {name for name, _ in schema.fields}
        extra = [key for key in data if key not in field_names]
        missing = [name for name in field_names if name not in data]
        if missing or extra:
            parts = []
            if missing:
                parts.append("missing: " + ", ".join(sorted(missing)))
            if extra:
                parts.append("unexpected: " + ", ".join(str(key) for key in extra))
            raise SericiteError(
                f"wrap() key mismatch ({'; '.join(parts)})",
                kind="contract_error",
            )
        for name, contract in schema.fields:
            value = data[name]
            if not _contract_holds(value, contract):
                raise _contract_violation(f"field {name}", None, contract, value)
        return SericiteRecord(schema, {name: data[name] for name, _ in schema.fields})

    @staticmethod
    def _unwrap_work(record: object) -> int:
        return len(record.fields) if isinstance(record, SericiteRecord) else 0

    @staticmethod
    def _unwrap_allocation(record: object) -> int:
        return len(record.fields) * 16 if isinstance(record, SericiteRecord) else 0

    def _unwrap(self, context: VMContext, record: object) -> dict:
        if not isinstance(record, SericiteRecord):
            raise SericiteError(
                f"unwrap() expects a record, got {_type_name(record)}",
                kind="type_error",
            )
        return dict(record.fields)
