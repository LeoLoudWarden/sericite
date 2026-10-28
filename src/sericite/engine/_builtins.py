from __future__ import annotations

import dataclasses

from ..accounting import UNLIMITED, AllocationPermit
from ..errors import SericiteError
from ..io import VirtualIO
from ._model import (
    _ANY,
    _CUMULATIVE_VM_OPTIONS,
    _TAG_CONTRACTS,
    _VM_OPTIONS,
    SericiteFunction,
    VMContext,
    VMHandle,
    _GrantedHostFunction,
    _GrantedSericiteFunction,
    _NativeFunction,
    _no_allocation,
    _no_work,
)
from ._values import (
    _MAX_RENDER_CHARS,
    _check_grant_name,
    _min_limits,
    _StringRenderer,
    _tighten_limit,
    _to_str,
    _type_name,
)


class _EngineBuiltins:
    def _builtin(
        self,
        home: VMContext,
        name: str,
        caller: VMContext | None = None,
    ) -> _NativeFunction | None:
        if name == "input":
            return _NativeFunction(
                "input",
                lambda: self._read_input(home),
                home,
                work=_no_work,
                allocation=_no_allocation,
            )
        if name == "print":
            return _NativeFunction(
                "print",
                lambda *values, end="\n": self._print(home, values, end),
                home,
                work=_no_work,
                allocation=_no_allocation,
            )
        if name == "len":
            return _NativeFunction(
                "len",
                self._len,
                None,
                work=_no_work,
                allocation=_no_allocation,
            )
        if name == "int":
            return _NativeFunction(
                "int",
                lambda value: self._convert_int(home, value),
                home,
                work=self._string_work,
                allocation=_no_allocation,
            )
        if name == "float":
            return _NativeFunction(
                "float",
                lambda value: self._convert_float(home, value),
                home,
                work=self._string_work,
                allocation=_no_allocation,
            )
        if name == "str":
            return _NativeFunction(
                "str",
                lambda value: self._str_builtin(home, value),
                home,
                work=_no_work,
                allocation=_no_allocation,
            )
        if name == "range":
            return _NativeFunction(
                "range",
                lambda *args: self._range(home, args),
                home,
                work=self._range_work,
                allocation=_no_allocation,
            )
        if name == "any":
            return _ANY
        if name in _TAG_CONTRACTS:
            return _TAG_CONTRACTS[name]
        if name == "wrap":
            return _NativeFunction(
                "wrap",
                lambda schema, data: self._wrap(home, schema, data),
                home,
                work=self._wrap_work,
                allocation=self._wrap_allocation,
            )
        if name == "unwrap":
            return _NativeFunction(
                "unwrap",
                lambda record: self._unwrap(home, record),
                home,
                work=self._unwrap_work,
                allocation=self._unwrap_allocation,
            )
        if name == "read_file":
            return _NativeFunction(
                "read_file",
                lambda path: self._read_file(home, path),
                home,
                work=home.fs.path_work,
                allocation=_no_allocation,
            )
        if name == "write_file":
            return _NativeFunction(
                "write_file",
                lambda path, text, *, _allocation_permit=None: self._write_file(
                    home, path, text, _allocation_permit
                ),
                home,
                work=home.fs.write_work,
                allocation=lambda path, text: self._vfs_allocation(home, path, text),
            )
        if name == "list_dir":
            return _NativeFunction(
                "list_dir",
                lambda path: self._list_dir(home, path),
                home,
                work=home.fs.list_dir_work,
                allocation=_no_allocation,
            )
        if name == "path_exists":
            return _NativeFunction(
                "path_exists",
                home.fs.path_exists,
                home,
                work=home.fs.path_work,
                allocation=_no_allocation,
            )
        if name == "VM":
            return _NativeFunction(
                "VM",
                lambda source, **kwargs: self._create_child(
                    home, source, kwargs, cap=caller
                ),
                home,
                work=self._source_work,
                allocation=_no_allocation,
            )
        return None

    @staticmethod
    def _source_work(source: object, **kwargs: object) -> int:
        return 1 + len(source) // 4 if isinstance(source, str) else 0

    def _create_child(
        self,
        parent: VMContext,
        source: object,
        config: dict[str, object],
        cap: VMContext | None = None,
    ) -> VMHandle:
        # The world belongs to parent (home: source of grant validation and quota
        # ceilings); the causal owner is the caller `cap`: the new VM is an empty
        # world whose tree position only affects accounting/depth/child count —
        # it hangs under the triggering caller, with consumption pushed up the
        # caller's ancestor chain (invariant 14). Quotas are the elementwise
        # minimum of parent's and the caller's.
        causal = cap if cap is not None else parent
        if not isinstance(source, str):
            raise SericiteError("VM source must be a string", kind="type_error")
        granted = self._validate_child_functions(parent, config.pop("functions", None))
        limits = parent.limits
        if causal is not parent:
            limits = _min_limits(limits, causal.limits)
        if config:
            overrides: dict[str, int] = {}
            for key, value in config.items():
                if key not in _VM_OPTIONS:
                    raise SericiteError(f"unknown VM option: {key}", kind="type_error")
                unlimited = key in _CUMULATIVE_VM_OPTIONS and value == UNLIMITED
                if type(value) is not int or (value < 0 and not unlimited):
                    requirement = (
                        "a non-negative int or -1"
                        if key in _CUMULATIVE_VM_OPTIONS
                        else "a non-negative int"
                    )
                    raise SericiteError(
                        f"VM option {key} must be {requirement}",
                        kind="type_error",
                    )
                overrides[key] = _tighten_limit(getattr(limits, key), value)
            limits = dataclasses.replace(limits, **overrides)
        depth = causal.depth + 1
        if depth > limits.max_vm_depth:
            raise SericiteError("VM depth limit exceeded", kind="resource_exhausted")
        if (
            causal.limits.max_child_vms != UNLIMITED
            and causal.child_count >= causal.limits.max_child_vms
        ):
            raise SericiteError("child VM limit exceeded", kind="resource_exhausted")
        handle = self._create_vm(
            source=source,
            parent_id=causal.vm_id,
            depth=depth,
            io=VirtualIO(
                max_output_bytes=(
                    None
                    if limits.max_output_bytes == UNLIMITED
                    else limits.max_output_bytes
                )
            ),
            limits=limits,
            granted=granted,
        )
        causal.child_count += 1
        return handle

    def _validate_child_functions(
        self, parent: VMContext, functions: object
    ) -> dict[str, object]:
        if functions is None:
            return {}
        if not isinstance(functions, dict):
            raise SericiteError("VM option functions must be a dict", kind="type_error")
        granted: dict[str, object] = {}
        for name, value in functions.items():
            _check_grant_name(name)
            if isinstance(value, SericiteFunction):
                granted[name] = _GrantedSericiteFunction(
                    name,
                    value.code,
                    value.module_locals,
                    value.closure,
                    value.granted,
                    value.defaults,
                    value.param_contracts,
                    value.return_contract,
                    value.home,
                )
            elif isinstance(value, _GrantedHostFunction):
                granted[name] = _GrantedHostFunction(name, value.callback)
            elif isinstance(value, _GrantedSericiteFunction):
                granted[name] = _GrantedSericiteFunction(
                    name,
                    value.code,
                    value.module_locals,
                    value.closure,
                    value.granted,
                    value.defaults,
                    value.param_contracts,
                    value.return_contract,
                    value.home,
                )
            else:
                raise SericiteError(
                    f"granted value '{name}' is not a function",
                    kind="type_error",
                )
        return granted

    def _print(
        self, context: VMContext, values: tuple[object, ...], end: object = "\n"
    ) -> None:
        if type(end) is not str:
            raise SericiteError(
                f"print() end must be str, got {_type_name(end)}", kind="type_error"
            )
        remaining = context.io.remaining_output_bytes
        meter = self._meter(context)
        renderer = _StringRenderer(
            _MAX_RENDER_CHARS if remaining is None else remaining,
            output=True,
            meter=meter,
        )
        for index, value in enumerate(values):
            if index:
                renderer._add(" ")
            renderer.render(value)
        renderer._add(end)
        line = renderer.text()
        meter.work(len(line) // 64)
        context.io.write_output(line)

    def _read_input(self, context: VMContext) -> str:
        value = context.io.read_input()
        if len(value) > context.limits.max_string_bytes:
            raise SericiteError("string size limit exceeded", kind="resource_exhausted")
        self._meter(context).allocate(len(value) * 4)
        return value

    def _read_file(self, context: VMContext, path: object) -> str:
        text = context.fs.read_file(path)
        self._meter(context).allocate(len(text) * 4)
        return text

    def _vfs_allocation(
        self, context: VMContext, path: object, text: object
    ) -> AllocationPermit:
        amount = context.fs.write_allocation(path, text)
        return self._meter(context).reserve(context.fs, "write", amount)

    def _write_file(
        self,
        context: VMContext,
        path: object,
        text: object,
        permit: AllocationPermit,
    ) -> None:
        context.fs.write_file(path, text, permit=permit)

    def _list_dir(self, context: VMContext, path: object) -> list[str]:
        result = context.fs.list_dir(path)
        if len(result) > context.limits.max_list_size:
            raise SericiteError("list size limit exceeded", kind="resource_exhausted")
        self._meter(context).allocate(len(result) * 8)
        return result

    def _len(self, value: object) -> int:
        if isinstance(value, (str, list, dict)):
            return len(value)
        raise SericiteError(
            f"object of type '{_type_name(value)}' has no len()",
            kind="type_error",
        )

    def _convert_int(self, context: VMContext, value: object) -> int:
        if type(value) is bool:
            return int(value)
        if type(value) is int:
            return self._check_int(context, value)
        if type(value) is float:
            try:
                return self._check_int(context, int(value))
            except ValueError:
                raise SericiteError(
                    "cannot convert nan to int", kind="conversion_error"
                ) from None
        if type(value) is str:
            text = value.strip()
            if len(text) > context.limits.max_int_bits // 3:
                raise SericiteError(
                    "integer size limit exceeded", kind="resource_exhausted"
                )
            try:
                return self._check_int(context, int(text, 10))
            except ValueError:
                raise SericiteError(
                    f"cannot convert to int: {value!r}", kind="conversion_error"
                ) from None
        raise SericiteError(
            f"cannot convert {_type_name(value)} to int", kind="type_error"
        )

    def _str_builtin(self, context: VMContext, value: object) -> str:
        meter = self._meter(context)
        return _to_str(value, context.limits.max_string_bytes, meter=meter)

    @staticmethod
    def _string_work(value: object) -> int:
        return len(value) if isinstance(value, str) else 0

    def _convert_float(self, context: VMContext, value: object) -> float:
        if type(value) is bool:
            return float(value)
        if type(value) in (int, float):
            return float(value)
        if type(value) is str:
            try:
                return float(value.strip())
            except ValueError:
                shown = value if len(value) <= 64 else value[:61] + "..."
                raise SericiteError(
                    f"cannot convert to float: {shown!r}",
                    kind="conversion_error",
                ) from None
        raise SericiteError(
            f"cannot convert {_type_name(value)} to float", kind="type_error"
        )

    @staticmethod
    def _range_work(*args: object) -> int:
        try:
            return len(range(*args))
        except (TypeError, ValueError, OverflowError):
            return 0

    def _range(self, context: VMContext, args: tuple[object, ...]) -> list[int]:
        if not 1 <= len(args) <= 3:
            raise SericiteError(
                f"range() expects 1 to 3 argument(s), got {len(args)}",
                kind="arity_error",
            )
        for value in args:
            if type(value) is not int:
                raise SericiteError(
                    f"range() arguments must be int, got {_type_name(value)}",
                    kind="type_error",
                )
        if len(args) == 3 and args[2] == 0:
            raise SericiteError("range() step cannot be zero", kind="type_error")
        result = range(*args)
        if len(result) > context.limits.max_list_size:
            raise SericiteError("list size limit exceeded", kind="resource_exhausted")
        self._meter(context).allocate(len(result) * 8)
        return list(result)
