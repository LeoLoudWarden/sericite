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
                lambda *values, sep=" ", end="\n", _caller_context=None, _caller_meter=None: (
                    self._print(home, values, sep, end, _caller_context)
                ),
                home,
                work=_no_work,
                allocation=_no_allocation,
                needs_caller=True,
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
        if name == "repr":
            return _NativeFunction(
                "repr",
                lambda value: self._repr_builtin(home, value),
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
                work=lambda path: self._attached_vfs(home).path_work(path),
                allocation=_no_allocation,
            )
        if name == "write_file":
            return _NativeFunction(
                "write_file",
                lambda path, text, *, _allocation_permit=None: self._write_file(
                    home, path, text, _allocation_permit
                ),
                home,
                work=lambda path, text: self._attached_vfs(home).write_work(path, text),
                allocation=lambda path, text: self._vfs_allocation(home, path, text),
            )
        if name == "delete_file":
            return _NativeFunction(
                "delete_file",
                lambda path: self._attached_vfs(home).delete_file(path),
                home,
                work=lambda path: self._attached_vfs(home).path_work(path),
                allocation=_no_allocation,
            )
        if name == "rename_file":
            return _NativeFunction(
                "rename_file",
                lambda old_path, new_path, *, _allocation_permit=None: (
                    self._attached_vfs(home).rename_file(
                        old_path,
                        new_path,
                        permit=_allocation_permit,
                        limits=self._file_operation_limits(home),
                    )
                ),
                home,
                work=lambda old_path, new_path: self._attached_vfs(home).rename_work(
                    old_path, new_path
                ),
                allocation=lambda old_path, new_path: self._vfs_mutation_allocation(
                    home, "rename_allocation", old_path, new_path
                ),
            )
        if name == "copy_file":
            return _NativeFunction(
                "copy_file",
                lambda source_path, destination_path, *, _allocation_permit=None: (
                    self._attached_vfs(home).copy_file(
                        source_path,
                        destination_path,
                        permit=_allocation_permit,
                        limits=self._file_operation_limits(home),
                    )
                ),
                home,
                work=lambda source_path, destination_path: self._attached_vfs(
                    home
                ).copy_work(source_path, destination_path),
                allocation=lambda source_path, destination_path: (
                    self._vfs_mutation_allocation(
                        home, "copy_allocation", source_path, destination_path
                    )
                ),
            )
        if name == "delete_dir":
            return _NativeFunction(
                "delete_dir",
                lambda path: self._attached_vfs(home).delete_dir(path),
                home,
                work=lambda path: self._attached_vfs(home).delete_dir_work(path),
                allocation=_no_allocation,
            )
        if name == "rename_dir":
            return _NativeFunction(
                "rename_dir",
                lambda old_path, new_path, *, _allocation_permit=None: (
                    self._attached_vfs(home).rename_dir(
                        old_path,
                        new_path,
                        permit=_allocation_permit,
                        limits=self._file_operation_limits(home),
                    )
                ),
                home,
                work=lambda old_path, new_path: self._attached_vfs(
                    home
                ).rename_dir_work(old_path, new_path),
                allocation=lambda old_path, new_path: self._vfs_mutation_allocation(
                    home, "rename_dir_allocation", old_path, new_path
                ),
            )
        if name == "copy_dir":
            return _NativeFunction(
                "copy_dir",
                lambda source_path, destination_path, *, _allocation_permit=None: (
                    self._attached_vfs(home).copy_dir(
                        source_path,
                        destination_path,
                        permit=_allocation_permit,
                        limits=self._file_operation_limits(home),
                    )
                ),
                home,
                work=lambda source_path, destination_path: self._attached_vfs(
                    home
                ).copy_dir_work(source_path, destination_path),
                allocation=lambda source_path, destination_path: (
                    self._vfs_mutation_allocation(
                        home, "copy_dir_allocation", source_path, destination_path
                    )
                ),
            )
        if name == "make_dir":
            return _NativeFunction(
                "make_dir",
                lambda path, *, _allocation_permit=None: self._attached_vfs(
                    home
                ).make_dir(
                    path,
                    permit=_allocation_permit,
                    limits=self._file_operation_limits(home),
                ),
                home,
                work=lambda path: self._attached_vfs(home).path_work(path),
                allocation=lambda path: self._vfs_mutation_allocation(
                    home, "make_dir_allocation", path
                ),
            )
        if name == "list_dir":
            return _NativeFunction(
                "list_dir",
                lambda path: self._list_dir(home, path),
                home,
                work=lambda path: self._attached_vfs(home).list_dir_work(path),
                allocation=_no_allocation,
            )
        if name == "path_exists":
            return _NativeFunction(
                "path_exists",
                lambda path: self._attached_vfs(home).path_exists(path),
                home,
                work=lambda path: self._attached_vfs(home).path_work(path),
                allocation=_no_allocation,
            )
        if name == "VFS":
            return _NativeFunction(
                "VFS",
                self.create_vfs,
                home,
                work=_no_work,
                allocation=lambda: 8,
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
        # Grant validation and quota ceilings come from parent (home); the causal
        # owner is caller `cap`. A supplied VFS moves into the new VM, while the
        # default remains a fresh empty world.
        causal = cap if cap is not None else parent
        if not isinstance(source, str):
            raise SericiteError("VM source must be a string", kind="type_error")
        fs = config.pop("fs", None)
        granted = self._validate_child_functions(parent, config.pop("functions", None))
        output_writer = config.pop("output_writer", None)
        if output_writer is not None:
            output_writer = self._validate_child_functions(
                parent, {"output_writer": output_writer}
            )["output_writer"]
        buffer_output = config.pop("buffer_output", True)
        if type(buffer_output) is not bool:
            raise SericiteError(
                "VM option buffer_output must be a bool", kind="type_error"
            )
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
        handle = self._create_vm(
            source=source,
            parent_id=causal.vm_id,
            depth=depth,
            io=VirtualIO(
                max_output_bytes=(
                    None
                    if limits.max_output_bytes == UNLIMITED
                    else limits.max_output_bytes
                ),
                buffer_output=buffer_output,
            ),
            limits=limits,
            granted=granted,
            output_writer=output_writer,
            fs=fs,
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
        self,
        context: VMContext,
        values: tuple[object, ...],
        sep: object = " ",
        end: object = "\n",
        caller: VMContext | None = None,
    ) -> None:
        if type(sep) is not str:
            raise SericiteError(
                f"print() sep must be str, got {_type_name(sep)}", kind="type_error"
            )
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
                renderer._add(sep)
            renderer.render(value)
        renderer._add(end)
        line = renderer.text()
        meter.work(len(line) // 64)
        context.io.write_output(line)
        if context.output_writer is not None:
            self._invoke_output_writer(caller or context, context.output_writer, line)

    def _read_input(self, context: VMContext) -> str:
        value = context.io.read_input()
        if len(value) > context.limits.max_string_bytes:
            raise SericiteError("string size limit exceeded", kind="resource_exhausted")
        self._meter(context).allocate(len(value) * 4)
        return value

    def _read_file(self, context: VMContext, path: object) -> str:
        text = self._attached_vfs(context).read_file(path)
        self._meter(context).allocate(len(text) * 4)
        return text

    def _vfs_mutation_allocation(
        self, context: VMContext, estimate: str, *args: object
    ) -> AllocationPermit:
        fs = self._attached_vfs(context)
        amount = getattr(fs, estimate)(*args)
        return self._meter(context).reserve(fs, "write", amount)

    def _vfs_allocation(
        self, context: VMContext, path: object, text: object
    ) -> AllocationPermit:
        return self._vfs_mutation_allocation(context, "write_allocation", path, text)

    def _write_file(
        self,
        context: VMContext,
        path: object,
        text: object,
        permit: AllocationPermit,
    ) -> None:
        self._attached_vfs(context).write_file(
            path,
            text,
            permit=permit,
            limits=self._file_operation_limits(context),
        )

    def _list_dir(self, context: VMContext, path: object) -> list[str]:
        result = self._attached_vfs(context).list_dir(path)
        if len(result) > context.limits.max_list_size:
            raise SericiteError("list size limit exceeded", kind="resource_exhausted")
        self._meter(context).allocate(len(result) * 8)
        return result

    def _len(self, value: object) -> int:
        if isinstance(value, (str, list, dict, tuple)):
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

    def _repr_builtin(self, context: VMContext, value: object) -> str:
        renderer = _StringRenderer(
            context.limits.max_string_bytes, meter=self._meter(context)
        )
        renderer.render(value, repr_strings=True)
        return renderer.text(allocate=True)

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
