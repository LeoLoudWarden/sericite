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
        if op == "*":
            if (type(left) is str and type(right) is int) or (
                type(left) is int and type(right) is str
            ):
                text = left if type(left) is str else right
                count = right if type(left) is str else left
                size = len(text) * count if count > 0 else 0
                if size > context.limits.max_string_bytes:
                    raise SericiteError(
                        "string size limit exceeded", kind="resource_exhausted"
                    )
                if size == 0:
                    return ""
                self._meter(context).allocate(size * 4)
                self._meter(context).work(size // 64)
                return text * count
            if _is_number(left) and _is_number(right):
                return self._check_int(context, left * right)
            raise _operand_error(op, left, right)
        if op == "-":
            if _is_number(left) and _is_number(right):
                return self._check_int(context, left - right)
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

    def _slice(
        self,
        context: VMContext,
        value: object,
        start: object,
        stop: object,
        step: object,
    ) -> object:
        if not isinstance(value, (str, list)):
            raise SericiteError(
                f"'{_type_name(value)}' is not sliceable", kind="type_error"
            )
        for index in (start, stop, step):
            if index is not None and type(index) is not int:
                raise SericiteError(
                    f"slice indices must be int or None, got {_type_name(index)}",
                    kind="type_error",
                )
        if step == 0:
            raise SericiteError("slice step cannot be zero", kind="type_error")
        indices = slice(start, stop, step).indices(len(value))
        size = len(range(*indices))
        if type(value) is str:
            if size > context.limits.max_string_bytes:
                raise SericiteError(
                    "string size limit exceeded", kind="resource_exhausted"
                )
            self._meter(context).allocate(size * 4)
            self._meter(context).work(size // 64)
        else:
            if size > context.limits.max_list_size:
                raise SericiteError(
                    "list size limit exceeded", kind="resource_exhausted"
                )
            self._meter(context).allocate(size * 8)
            self._meter(context).work(size)
        return value[start:stop:step]

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
                f"{_record_text(value, hint, meter=self._meter(context))} has no field '{attr}'",
                kind="attribute_error",
            )
        if isinstance(value, VMHandle) and attr in VMHandle._METHODS:
            home = None if attr == "dispose" else self._context(value)
            return _NativeFunction(
                f"VM.{attr}",
                lambda *a, **k: self._charged_vm_method(value, attr, a, k),
                home,
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
        if type(value) is str:
            if attr in (
                "strip",
                "lstrip",
                "rstrip",
                "split",
                "splitlines",
                "join",
                "find",
                "replace",
            ):
                return _NativeFunction(
                    f"str.{attr}",
                    lambda *args: self._string_method(context, value, attr, args),
                    context,
                    work=_no_work,
                    allocation=_no_allocation,
                )
            raise SericiteError(f"str has no method '{attr}'", kind="attribute_error")
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

    def _string_method(
        self,
        context: VMContext,
        target: str,
        attr: str,
        args: tuple[object, ...],
    ) -> object:
        if attr in ("strip", "lstrip", "rstrip"):
            return self._string_strip(context, target, attr, args)
        if attr == "split":
            return self._string_split(context, target, args)
        if attr == "splitlines":
            return self._string_splitlines(context, target, args)
        if attr == "join":
            return self._string_join(context, target, args)
        if attr == "find":
            return self._string_find(context, target, args)
        if attr == "replace":
            return self._string_replace(context, target, args)
        raise SericiteError(f"unknown string method: {attr}", kind="internal_error")

    @staticmethod
    def _string_arity(
        name: str, args: tuple[object, ...], minimum: int, maximum: int
    ) -> None:
        if minimum <= len(args) <= maximum:
            return
        expected = str(minimum) if minimum == maximum else f"{minimum} to {maximum}"
        raise SericiteError(
            f"str.{name}() expects {expected} argument(s), got {len(args)}",
            kind="arity_error",
        )

    def _string_copy(
        self, context: VMContext, target: str, start: int, stop: int
    ) -> str:
        size = stop - start
        if size > context.limits.max_string_bytes:
            raise SericiteError("string size limit exceeded", kind="resource_exhausted")
        self._meter(context).allocate(size * 4)
        self._meter(context).work(size // 64)
        return target[start:stop]

    def _string_append_piece(
        self,
        context: VMContext,
        result: list[str],
        target: str,
        start: int,
        stop: int,
    ) -> None:
        if len(result) >= context.limits.max_list_size:
            raise SericiteError("list size limit exceeded", kind="resource_exhausted")
        self._meter(context).allocate(8)
        result.append(self._string_copy(context, target, start, stop))

    def _string_find_from(
        self,
        context: VMContext,
        target: str,
        needle: str,
        start: int,
        stop: int,
    ) -> int:
        for position in range(start, stop - len(needle) + 1):
            self._meter(context).work(1 + len(needle))
            if target.startswith(needle, position):
                return position
        return -1

    def _string_strip(
        self,
        context: VMContext,
        target: str,
        attr: str,
        args: tuple[object, ...],
    ) -> str:
        self._string_arity(attr, args, 0, 1)
        chars = args[0] if args else None
        if chars is not None and type(chars) is not str:
            raise SericiteError(
                f"str.{attr}() chars must be str or None, got {_type_name(chars)}",
                kind="type_error",
            )
        start = 0
        stop = len(target)
        membership_cost = len(chars) if chars is not None else 0
        if attr != "rstrip":
            while start < stop:
                self._meter(context).work(1 + membership_cost)
                char = target[start]
                trimmed = char.isspace() if chars is None else char in chars
                if not trimmed:
                    break
                start += 1
        if attr != "lstrip":
            while stop > start:
                self._meter(context).work(1 + membership_cost)
                char = target[stop - 1]
                trimmed = char.isspace() if chars is None else char in chars
                if not trimmed:
                    break
                stop -= 1
        return self._string_copy(context, target, start, stop)

    def _string_skip_whitespace(
        self, context: VMContext, target: str, position: int
    ) -> int:
        while position < len(target):
            self._meter(context).work(1)
            if not target[position].isspace():
                break
            position += 1
        return position

    def _string_split(
        self,
        context: VMContext,
        target: str,
        args: tuple[object, ...],
    ) -> list[str]:
        self._string_arity("split", args, 0, 2)
        separator = args[0] if args else None
        maxsplit = args[1] if len(args) == 2 else -1
        if separator is not None and type(separator) is not str:
            raise SericiteError(
                f"str.split() separator must be str or None, got {_type_name(separator)}",
                kind="type_error",
            )
        if separator == "":
            raise SericiteError(
                "str.split() separator cannot be empty", kind="type_error"
            )
        if type(maxsplit) is not int:
            raise SericiteError(
                f"str.split() maxsplit must be int, got {_type_name(maxsplit)}",
                kind="type_error",
            )
        result: list[str] = []
        if separator is None:
            position = self._string_skip_whitespace(context, target, 0)
            while position < len(target) and (maxsplit < 0 or len(result) < maxsplit):
                start = position
                while position < len(target):
                    self._meter(context).work(1)
                    if target[position].isspace():
                        break
                    position += 1
                self._string_append_piece(context, result, target, start, position)
                position = self._string_skip_whitespace(context, target, position)
            if position < len(target):
                self._string_append_piece(
                    context, result, target, position, len(target)
                )
            return result
        position = 0
        piece_start = 0
        while maxsplit < 0 or len(result) < maxsplit:
            found = self._string_find_from(
                context, target, separator, position, len(target)
            )
            if found < 0:
                break
            self._string_append_piece(context, result, target, piece_start, found)
            position = found + len(separator)
            piece_start = position
        self._string_append_piece(context, result, target, piece_start, len(target))
        return result

    def _string_splitlines(
        self,
        context: VMContext,
        target: str,
        args: tuple[object, ...],
    ) -> list[str]:
        self._string_arity("splitlines", args, 0, 1)
        keepends = args[0] if args else False
        if type(keepends) is not bool:
            raise SericiteError(
                f"str.splitlines() keepends must be bool, got {_type_name(keepends)}",
                kind="type_error",
            )
        result: list[str] = []
        line_breaks = "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"
        position = 0
        line_start = 0
        while position < len(target):
            self._meter(context).work(1)
            char = target[position]
            if char not in line_breaks:
                position += 1
                continue
            line_end = position + 1
            if char == "\r" and line_end < len(target) and target[line_end] == "\n":
                line_end += 1
            self._string_append_piece(
                context,
                result,
                target,
                line_start,
                line_end if keepends else position,
            )
            position = line_end
            line_start = line_end
        if line_start < len(target):
            self._string_append_piece(context, result, target, line_start, len(target))
        return result

    def _string_join(
        self,
        context: VMContext,
        separator: str,
        args: tuple[object, ...],
    ) -> str:
        self._string_arity("join", args, 1, 1)
        values = args[0]
        if not isinstance(values, (str, list, dict)):
            raise SericiteError(
                f"str.join() expects str, list, or dict, got {_type_name(values)}",
                kind="type_error",
            )
        size = 0
        count = 0
        for value in values:
            self._meter(context).work(2)
            if type(value) is not str:
                raise SericiteError(
                    f"str.join() items must be str, got {_type_name(value)}",
                    kind="type_error",
                )
            size += len(value)
            count += 1
        if count > 1:
            size += len(separator) * (count - 1)
        if size > context.limits.max_string_bytes:
            raise SericiteError("string size limit exceeded", kind="resource_exhausted")
        self._meter(context).allocate(size * 4)
        self._meter(context).work(size // 64)
        return separator.join(values)

    def _string_find(
        self,
        context: VMContext,
        target: str,
        args: tuple[object, ...],
    ) -> int:
        self._string_arity("find", args, 1, 3)
        needle = args[0]
        start = args[1] if len(args) >= 2 else None
        stop = args[2] if len(args) == 3 else None
        if type(needle) is not str:
            raise SericiteError(
                f"str.find() substring must be str, got {_type_name(needle)}",
                kind="type_error",
            )
        for bound in (start, stop):
            if bound is not None and type(bound) is not int:
                raise SericiteError(
                    f"str.find() bounds must be int or None, got {_type_name(bound)}",
                    kind="type_error",
                )
        if needle == "":
            self._meter(context).work(1)
            return target.find(needle, start, stop)
        normalized_start, normalized_stop, _ = slice(start, stop).indices(len(target))
        return self._string_find_from(
            context, target, needle, normalized_start, normalized_stop
        )

    def _string_replace(
        self,
        context: VMContext,
        target: str,
        args: tuple[object, ...],
    ) -> str:
        self._string_arity("replace", args, 2, 3)
        old = args[0]
        new = args[1]
        count = args[2] if len(args) == 3 else -1
        if type(old) is not str or type(new) is not str:
            raise SericiteError(
                "str.replace() old and new must be str", kind="type_error"
            )
        if type(count) is not int:
            raise SericiteError(
                f"str.replace() count must be int, got {_type_name(count)}",
                kind="type_error",
            )
        if count < 0 or count > len(target):
            count = -1
        replacements = 0
        if count != 0:
            if old == "":
                replacements = (
                    len(target) + 1 if count < 0 else min(count, len(target) + 1)
                )
            else:
                position = 0
                while count < 0 or replacements < count:
                    found = self._string_find_from(
                        context, target, old, position, len(target)
                    )
                    if found < 0:
                        break
                    replacements += 1
                    position = found + len(old)
        size = len(target) + replacements * (len(new) - len(old))
        if size > context.limits.max_string_bytes:
            raise SericiteError("string size limit exceeded", kind="resource_exhausted")
        self._meter(context).allocate(size * 4)
        construction_work = size // 64
        if count != 0:
            construction_work += len(target)
        self._meter(context).work(construction_work)
        return target.replace(old, new, count)

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
        return (
            len(data)
            + sum(len(key) for key in data if type(key) is str)
            + sum(_contract_cost(contract) for _, contract in schema.fields)
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
                raise _contract_violation(
                    f"field {name}", None, contract, value, meter=self._meter(context)
                )
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
