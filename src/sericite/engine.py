from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from . import isa
from .accounting import AccountRoute, AllocationPermit, Meter
from .compiler import RESERVED_NAMES, VM_METHODS, compile_source
from .errors import UNCATCHABLE_ERROR_KINDS as _UNCATCHABLE_KINDS
from .errors import SericiteError
from .io import InputRequired, OutputLimitExceeded, VirtualIO
from .vfs import VirtualFileSystem

_TERMINAL_STATES = {"done", "error", "resource_exhausted", "terminated"}
_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_MAX_RENDER_NODES = 10_000
_MAX_RENDER_CHARS = 1_048_576
_VM_OPTIONS = {
    "max_instructions",
    "max_output_bytes",
    "max_frames",
    "max_child_vms",
    "max_list_size",
    "max_dict_size",
    "max_string_bytes",
    "max_int_bits",
    "max_total_bytes",
    "max_total_vms",
    "max_vm_depth",
    "max_fs_files",
    "max_fs_file_bytes",
}


@dataclass(frozen=True)
class SericiteLimits:
    max_instructions: int = 1_000_000
    max_output_bytes: int = 1_048_576
    max_frames: int = 100
    max_child_vms: int = 100
    max_list_size: int = 100_000
    max_dict_size: int = 100_000
    max_string_bytes: int = 1_048_576
    max_int_bits: int = 4096
    max_total_bytes: int = 67_108_864
    max_total_vms: int = 1000
    max_vm_depth: int = 8
    max_fs_files: int = 1000
    max_fs_file_bytes: int = 1_048_576


_UNBOUND = object()


class _Cell:
    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value = _UNBOUND


@dataclass
class Frame:
    code: isa.CodeUnit
    pc: int = 0
    stack: list[object] = field(default_factory=list)
    locals: dict[str, object] = field(default_factory=dict)
    cells: dict[str, _Cell] = field(default_factory=dict)
    closure: dict[str, _Cell] = field(default_factory=dict)
    module_locals: dict[str, object] | None = None
    granted: dict[str, object] | None = None
    active_error: SericiteError | None = None
    return_contract: object = None
    return_label: str | None = None
    display_name: str | None = None
    # The VM that defined this code; builtins (IO/filesystem/quotas and other world services) resolve back to it.
    home: object = None


class SericiteFunction:
    def __init__(
        self,
        code: isa.CodeUnit,
        defaults: tuple[object, ...],
        closure: dict[str, _Cell],
        module_locals: dict[str, object],
        granted: dict[str, object],
        param_contracts: tuple[object, ...] = (),
        return_contract: object = None,
        home: object = None,
    ) -> None:
        self.code = code
        self.defaults = defaults
        self.closure = closure
        self.module_locals = module_locals
        self.granted = granted
        self.param_contracts = param_contracts
        self.return_contract = return_contract
        self.home = home

    def __repr__(self) -> str:
        return f"<function {self.code.name}>"


class _TagContract:
    """Annotation-only contract-name singleton: any / bool / list / dict. Not callable."""

    __slots__ = ("tag",)

    def __init__(self, tag: str) -> None:
        self.tag = tag

    def __repr__(self) -> str:
        return self.tag


_ANY = _TagContract("any")
_TAG_CONTRACTS = {name: _TagContract(name) for name in ("bool", "list", "dict")}

_CONTRACT_TAGS = ("int", "float", "str", "bool", "list", "dict")
_TAG_TYPES = {
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
}


class SericiteSchema:
    """A record's structural contract: field names + per-field contracts. Structural equality, no runtime name."""

    __slots__ = ("field_map", "fields", "key", "size")

    def __init__(self, fields: tuple[tuple[str, object], ...]) -> None:
        self.fields = fields
        self.field_map = dict(fields)
        self.key = frozenset(
            (name, _contract_key(contract)) for name, contract in fields
        )
        # Total field slots across nesting (nested schemas are already built, so
        # their size is precomputed): the scale of a full _schema_fit traversal,
        # used for depth-proportional contract charging.
        self.size = len(fields) + sum(
            contract.size
            for _, contract in fields
            if isinstance(contract, SericiteSchema)
        )

    def __repr__(self) -> str:
        return _schema_repr(self)


class SericiteRecord:
    """A fixed-shape object: payload dict + schema reference. Fields cannot be added or removed; values are contract-checked."""

    __slots__ = ("fields", "schema")

    def __init__(self, schema: SericiteSchema, fields: dict[str, object]) -> None:
        self.schema = schema
        self.fields = fields


def _contract_key(contract: object) -> object:
    if isinstance(contract, SericiteSchema):
        return ("schema", contract.key)
    return ("tag", contract)


def _contract_text(
    contract: object,
    label: str | None = None,
    _depth: int = 0,
    _seen: set[int] | None = None,
    _budget: list[int] | None = None,
) -> str:
    renderer = _StringRenderer(_MAX_RENDER_CHARS, truncate=True)
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


def _actual_text(value: object) -> str:
    if isinstance(value, SericiteRecord):
        return _contract_text(value.schema)
    return _type_name(value)


def _fit_detail(value: object, expected: object) -> str:
    if not (isinstance(value, SericiteRecord) and isinstance(expected, SericiteSchema)):
        return ""
    _, missing, mismatched = _schema_fit(value.schema, expected)
    parts = []
    if missing:
        parts.append("missing: " + ", ".join(missing))
    if mismatched:
        parts.append("contract mismatch: " + ", ".join(mismatched))
    return f" ({'; '.join(parts)})" if parts else ""


def _contract_violation(
    where: str, label: str | None, contract: object, value: object
) -> SericiteError:
    expected = _contract_text(contract, label)
    return SericiteError(
        f"{where}: expected {expected}, got "
        f"{_actual_text(value)}{_fit_detail(value, contract)}",
        kind="contract_error",
    )


def _contract_cost(contract: object) -> int:
    if isinstance(contract, SericiteSchema):
        return 1 + contract.size
    return 1


def _record_text(record: SericiteRecord, hint: str | None = None) -> str:
    return f"record {_contract_text(record.schema, hint)}"


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


def _no_work(*args: object, **kwargs: object) -> int:
    return 0


def _no_allocation(*args: object, **kwargs: object) -> int:
    return 0


@dataclass(frozen=True, repr=False)
class _NativeFunction:
    """A trusted native operation with mandatory home, work, and allocation contracts."""

    name: str
    execute: Callable[..., object]
    home: object
    work: Callable[..., int]
    allocation: Callable[..., int | AllocationPermit]
    needs_caller: bool = False

    def __repr__(self) -> str:
        return f"<function {self.name}>"


@dataclass(frozen=True)
class _GrantedHostFunction:
    """A host-injected Python function: deep-copied both ways across the boundary, exceptions sanitized into ffi_error."""

    name: str
    callback: Callable[..., object]

    def __repr__(self) -> str:
        return f"<function {self.name}>"


@dataclass(frozen=True)
class _GrantedSericiteFunction:
    """A function granted by the parent VM: executes on the caller's frame stack, retaining its full definition-side environment."""

    name: str
    code: isa.CodeUnit
    module_locals: dict[str, object]
    closure: dict[str, _Cell]
    granted: dict[str, object]
    defaults: tuple[object, ...] = ()
    param_contracts: tuple[object, ...] = ()
    return_contract: object = None
    home: object = None

    def __repr__(self) -> str:
        return f"<function {self.name}>"


@dataclass
class VMContext:
    vm_id: int
    depth: int
    parent_id: int | None
    io: VirtualIO
    fs: VirtualFileSystem
    limits: SericiteLimits
    frames: list[Frame] = field(default_factory=list)
    granted: dict[str, object] = field(default_factory=dict)
    state: str = "ready"
    last_line: int | None = None
    error: SericiteError | None = None
    instruction_count: int = 0
    alloc_bytes: int = 0
    child_count: int = 0
    running: bool = False
    meter_stack: list[Meter] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return f"<sericite:vm_{self.vm_id}>"


class VMHandle:
    _METHODS = VM_METHODS

    def __init__(self, engine: SericiteEngine, vm_id: int) -> None:
        self._engine = engine
        self._vm_id = vm_id

    def run(self, inputs: object = None) -> str:
        if inputs is not None:
            if not isinstance(inputs, (list, tuple)) or any(
                not isinstance(value, str) for value in inputs
            ):
                raise SericiteError("VM.run inputs must be a list of strings")
            context = self._engine._context(self)
            context.io.feed_batch_trusted(inputs)
            if context.state == "waiting_input":
                context.state = "ready"
        return self._engine._run(self)

    def feed_input(self, value: object) -> None:
        if not isinstance(value, str):
            raise SericiteError("VM input must be a string")
        context = self._engine._context(self)
        context.io.feed_input_trusted(value)
        if context.state == "waiting_input":
            context.state = "ready"

    def step(self) -> dict[str, object]:
        return self._engine._step(self)

    def step_instruction(self) -> dict[str, object]:
        return self._engine._step_instruction(self)

    def snapshot(self) -> dict[str, object]:
        return self._engine._snapshot(self._engine._context(self))

    def stdout(self) -> str:
        return self._engine._context(self).io.stdout()

    def terminate(self) -> None:
        context = self._engine._context(self)
        if context.state in {"ready", "waiting_input"}:
            context.state = "terminated"

    def read_file(self, path: object) -> str:
        return self._engine._context(self).fs.read_file(path)

    def write_file(self, path: object, text: object) -> None:
        self._engine._context(self).fs.write_file_trusted(path, text)

    def list_dir(self, path: object) -> list[str]:
        return self._engine._context(self).fs.list_dir(path)

    def path_exists(self, path: object) -> bool:
        return self._engine._context(self).fs.path_exists(path)

    def __repr__(self) -> str:
        context = self._engine._context(self)
        return f"<VM id={context.vm_id} state={context.state}>"


class SericiteEngine:
    def __init__(self, limits: SericiteLimits | None = None) -> None:
        self._limits = limits or SericiteLimits()
        self._contexts: dict[int, VMContext] = {}
        self._account_routes: dict[int, AccountRoute] = {}
        self._meters: dict[int, Meter] = {}
        self._next_vm_id = 0

    def create_root(
        self,
        source: str,
        inputs: Iterable[str] | None = None,
        input_provider: Callable[[], str | None] | None = None,
        limits: SericiteLimits | None = None,
        functions: dict[str, Callable[..., object]] | None = None,
    ) -> VMHandle:
        effective = limits or self._limits
        io = VirtualIO(
            inputs=inputs,
            input_provider=input_provider,
            max_output_bytes=effective.max_output_bytes,
        )
        granted = self._validate_host_functions(functions)
        return self._create_vm(
            source=source,
            parent_id=None,
            depth=0,
            io=io,
            limits=effective,
            granted=granted,
        )

    def _validate_host_functions(
        self, functions: dict[str, Callable[..., object]] | None
    ) -> dict[str, object]:
        granted: dict[str, object] = {}
        if not functions:
            return granted
        for name, callback in functions.items():
            _check_grant_name(name)
            if not callable(callback):
                raise SericiteError(
                    f"granted function '{name}' is not callable",
                    kind="type_error",
                )
            granted[name] = _GrantedHostFunction(name, callback)
        return granted

    def _create_vm(
        self,
        *,
        source: str,
        parent_id: int | None,
        depth: int,
        io: VirtualIO,
        limits: SericiteLimits,
        granted: dict[str, object] | None = None,
    ) -> VMHandle:
        filename = f"<sericite:vm_{self._next_vm_id}>"
        if len(source.encode("utf-8")) > _MAX_SOURCE_BYTES:
            raise SericiteError(
                "source too large", kind="validation_error", filename=filename
            )
        if len(self._contexts) >= limits.max_total_vms:
            raise SericiteError(
                "total VM limit exceeded",
                kind="resource_exhausted",
                filename=filename,
            )
        code = compile_source(source, filename)
        vm_id = self._next_vm_id
        self._next_vm_id += 1
        _stamp_origin(code, vm_id)
        context = VMContext(
            vm_id=vm_id,
            depth=depth,
            parent_id=parent_id,
            io=io,
            fs=VirtualFileSystem(
                max_files=limits.max_fs_files,
                max_file_bytes=limits.max_fs_file_bytes,
            ),
            limits=limits,
            frames=[Frame(code=code)],
            granted=dict(granted) if granted else {},
        )
        if not any(instr.stmt_start for instr in code.instrs):
            context.state = "done"
        self._contexts[vm_id] = context
        route = AccountRoute(context, resolve=self._contexts.__getitem__)
        self._account_routes[vm_id] = route
        self._meters[vm_id] = Meter(route)
        self._meter(context).allocate(_const_bytes(code))
        return VMHandle(self, vm_id)

    def _context(self, handle: VMHandle) -> VMContext:
        if handle._engine is not self:
            raise SericiteError(
                "VM handle belongs to another engine", kind="internal_error"
            )
        return self._contexts[handle._vm_id]

    def _meter(self, context: VMContext) -> Meter:
        if context.meter_stack:
            return context.meter_stack[-1]
        return self._meters[context.vm_id]

    @contextmanager
    def _causal_meter(self, *contexts: VMContext) -> Iterator[Meter]:
        unique = list({id(context): context for context in contexts}.values())
        meter = Meter(AccountRoute(*unique, resolve=self._contexts.__getitem__))
        for context in unique:
            context.meter_stack.append(meter)
        try:
            yield meter
        finally:
            for context in reversed(unique):
                if context.meter_stack.pop() is not meter:
                    raise SericiteError("meter stack corrupted", kind="internal_error")

    def _run(self, handle: VMHandle) -> str:
        context = self._context(handle)
        if context.running:
            raise SericiteError("VM is already running")
        context.running = True
        try:
            while context.state == "ready":
                if not self._execute_one(context):
                    break
        finally:
            context.running = False
        if context.error is not None:
            raise context.error
        return context.io.stdout()

    def _step(
        self, handle: VMHandle, *, meter: Meter | None = None
    ) -> dict[str, object]:
        context = self._context(handle)
        if context.running:
            raise SericiteError("VM is already running")
        if context.state != "ready":
            return self._snapshot(context, meter=meter)
        context.running = True
        try:
            start_depth = len(context.frames)
            start_line = self._current_instr(context).line
            executed = False
            while context.state == "ready":
                instr = self._current_instr(context)
                if executed and len(context.frames) <= start_depth and instr.stmt_start:
                    break
                if not self._execute_one(context):
                    break
                executed = True
            if executed and context.state in {"ready", "done"}:
                context.last_line = start_line
        finally:
            context.running = False
        return self._snapshot(context, meter=meter)

    def _step_instruction(
        self, handle: VMHandle, *, meter: Meter | None = None
    ) -> dict[str, object]:
        context = self._context(handle)
        if context.running:
            raise SericiteError("VM is already running")
        if context.state != "ready":
            return self._snapshot(context, meter=meter)
        context.running = True
        try:
            line = self._current_instr(context).line
            if self._execute_one(context):
                context.last_line = line
        finally:
            context.running = False
        return self._snapshot(context, meter=meter)

    def _current_instr(self, context: VMContext) -> isa.Instr:
        frame = context.frames[-1]
        return frame.code.instrs[frame.pc]

    def _execute_one(self, context: VMContext) -> bool:
        if context.state != "ready":
            return False
        frame = context.frames[-1]
        instr = frame.code.instrs[frame.pc]
        try:
            self._meter(context).work(1)
            self._dispatch(context, frame, instr)
        except InputRequired:
            context.state = "waiting_input"
            return False
        except OutputLimitExceeded:
            self._fail(
                context,
                SericiteError("output limit exceeded", kind="resource_exhausted"),
                instr.line,
            )
            return False
        except SericiteError as exc:
            if self._handle_exception(context, exc):
                return True
            self._fail(context, exc, instr.line)
            return False
        except RecursionError:
            self._fail(
                context,
                SericiteError("recursion limit exceeded", kind="resource_exhausted"),
                instr.line,
            )
            return False
        except OverflowError:
            error = SericiteError("numeric overflow", kind="conversion_error")
            if self._handle_exception(context, error):
                return True
            self._fail(context, error, instr.line)
            return False
        except Exception:  # noqa: BLE001 — any host-internal failure becomes internal_error
            self._fail(
                context,
                SericiteError("internal runtime error", kind="internal_error"),
                instr.line,
            )
            return False
        return True

    def _fail(self, context: VMContext, error: SericiteError, line: int) -> None:
        context.error = error.bind(context.filename, line)
        context.state = (
            "resource_exhausted" if error.kind == "resource_exhausted" else "error"
        )

    def _handle_exception(self, context: VMContext, error: SericiteError) -> bool:
        if error.kind in _UNCATCHABLE_KINDS:
            return False
        while context.frames:
            frame = context.frames[-1]
            handler = self._find_handler(frame, error.kind)
            if handler is None:
                if len(context.frames) == 1:
                    return False
                context.frames.pop()
                continue
            del frame.stack[handler.stack_depth :]
            frame.active_error = error
            if handler.error_name is not None:
                self._store_local(frame, handler.error_name, error)
            if handler.bind is not None:
                self._store_local(frame, handler.bind, error.message)
            frame.pc = handler.target
            return True
        return False

    def _find_handler(self, frame: Frame, kind: str) -> isa.Handler | None:
        best: isa.Handler | None = None
        pc = frame.pc
        for handler in frame.code.handlers:
            if not (handler.start <= pc < handler.end):
                continue
            if handler.kinds is not None and kind not in handler.kinds:
                continue
            if best is None or handler.start > best.start:
                best = handler
        return best

    def _dispatch(self, context: VMContext, frame: Frame, instr: isa.Instr) -> None:
        op = instr.op
        arg = instr.arg
        stack = frame.stack
        advance = True
        if op == isa.LOAD_CONST:
            if type(arg) is int:
                if arg.bit_length() > context.limits.max_int_bits:
                    raise SericiteError(
                        "integer size limit exceeded", kind="resource_exhausted"
                    )
            elif type(arg) is str and len(arg) > context.limits.max_string_bytes:
                raise SericiteError(
                    "string size limit exceeded", kind="resource_exhausted"
                )
            stack.append(arg)
        elif op == isa.LOAD_NAME:
            stack.append(self._load_name(context, frame, arg))
        elif op == isa.STORE_NAME:
            frame.locals[arg] = stack.pop()
        elif op == isa.LOAD_DEREF:
            stack.append(self._load_deref(frame, arg))
        elif op == isa.STORE_DEREF:
            self._cell(frame, arg).value = stack.pop()
        elif op == isa.DUP:
            stack.append(stack[-1])
        elif op == isa.POP:
            stack.pop()
        elif op == isa.BUILD_LIST:
            if arg > context.limits.max_list_size:
                raise SericiteError(
                    "list size limit exceeded", kind="resource_exhausted"
                )
            items = stack[len(stack) - arg :] if arg else []
            if arg:
                del stack[len(stack) - arg :]
            self._meter(context).allocate(arg * 8)
            stack.append(list(items))
        elif op == isa.BUILD_DICT:
            if arg > context.limits.max_dict_size:
                raise SericiteError(
                    "dict size limit exceeded", kind="resource_exhausted"
                )
            pairs = stack[len(stack) - 2 * arg :] if arg else []
            if arg:
                del stack[len(stack) - 2 * arg :]
            mapping: dict[object, object] = {}
            for position in range(0, len(pairs), 2):
                key = pairs[position]
                if type(key) not in (str, int, float, bool) and key is not None:
                    raise SericiteError(
                        f"unhashable key type: {_type_name(key)}",
                        kind="type_error",
                    )
                if type(key) is str:
                    self._meter(context).work(len(key))
                mapping[key] = pairs[position + 1]
            self._meter(context).allocate(arg * 16)
            stack.append(mapping)
        elif op == isa.LOAD_INDEX:
            index = stack.pop()
            value = stack.pop()
            stack.append(self._index(context, value, index))
        elif op == isa.STORE_INDEX:
            index = stack.pop()
            target = stack.pop()
            value = stack.pop()
            self._store_index(context, target, index, value)
        elif op == isa.BINARY_OP:
            right = stack.pop()
            left = stack.pop()
            stack.append(self._binary_op(context, arg, left, right))
        elif op == isa.UNARY_OP:
            stack.append(self._unary_op(context, arg, stack.pop()))
        elif op == isa.COMPARE_OP:
            right = stack.pop()
            left = stack.pop()
            stack.append(self._compare_op(context, arg, left, right))
        elif op == isa.JUMP:
            frame.pc = arg
            advance = False
        elif op == isa.JUMP_IF_FALSE:
            if not _truthy(stack.pop()):
                frame.pc = arg
                advance = False
        elif op == isa.JUMP_IF_TRUE_KEEP:
            if _truthy(stack[-1]):
                frame.pc = arg
                advance = False
            else:
                stack.pop()
        elif op == isa.JUMP_IF_FALSE_KEEP:
            if not _truthy(stack[-1]):
                frame.pc = arg
                advance = False
            else:
                stack.pop()
        elif op == isa.LOAD_ATTR:
            attr, hint = arg
            if frame.code.origin_vm != context.vm_id:
                hint = None
            stack.append(self._load_attr(context, stack.pop(), attr, hint))
        elif op == isa.STORE_ATTR:
            attr, hint = arg
            if frame.code.origin_vm != context.vm_id:
                hint = None
            target = stack.pop()
            value = stack.pop()
            self._store_attr(context, target, attr, value, hint)
        elif op == isa.MAKE_SCHEMA:
            names = arg
            count = len(names)
            raw = stack[len(stack) - count :] if count else []
            if count:
                del stack[len(stack) - count :]
            if len(set(names)) != count:
                raise SericiteError(
                    "duplicate field name in schema", kind="contract_error"
                )
            contracts = tuple(_normalize_contract(contract) for contract in raw)
            self._meter(context).allocate(64 + count * 16)
            stack.append(SericiteSchema(tuple(zip(names, contracts))))
        elif op == isa.CHECK_ANNOT:
            contract_value = stack.pop()
            value = stack[-1]
            contract = _normalize_contract(contract_value)
            self._meter(context).work(_contract_cost(contract))
            if not _contract_holds(value, contract):
                label = arg if frame.code.origin_vm == context.vm_id else None
                raise _contract_violation(
                    "annotated assignment", label, contract, value
                )
        elif op == isa.MAKE_FUNCTION:
            code, defaults_count, annot_count = arg
            defaults = (
                tuple(
                    stack[
                        len(stack) - defaults_count - annot_count : len(stack)
                        - annot_count
                    ]
                )
                if defaults_count
                else ()
            )
            annots = tuple(stack[len(stack) - annot_count :])
            del stack[len(stack) - defaults_count - annot_count :]
            param_contracts = tuple(
                _normalize_contract(v) if v is not None else None for v in annots[:-1]
            )
            return_contract = (
                _normalize_contract(annots[-1]) if annots[-1] is not None else None
            )
            closure = {name: self._cell(frame, name) for name in code.free_names}
            module_locals = (
                frame.module_locals
                if frame.module_locals is not None
                else context.frames[0].locals
            )
            granted = frame.granted if frame.granted is not None else context.granted
            if closure:
                self._meter(context).allocate(64 + len(closure) * 8)
            stack.append(
                SericiteFunction(
                    code,
                    defaults,
                    closure,
                    module_locals,
                    granted,
                    param_contracts,
                    return_contract,
                    frame.home or context,
                )
            )
        elif op == isa.GET_ITER:
            value = stack.pop()
            if isinstance(value, (str, dict)):
                self._meter(context).work(len(value))
            iterator = _make_iterator(value)
            self._meter(context).allocate(len(iterator.items) * 8)
            frame.locals[arg] = iterator
        elif op == isa.FOR_ITER:
            name, target = arg
            iterator = frame.locals[name]
            if iterator.pos >= len(iterator.items):
                frame.pc = target
                advance = False
            else:
                stack.append(iterator.items[iterator.pos])
                iterator.pos += 1
        elif op == isa.RAISE:
            if isinstance(arg, tuple):
                raise frame.locals[arg[1]]
            if arg is None:
                if frame.active_error is None:
                    raise SericiteError(
                        "raise without an active error", kind="raise_error"
                    )
                raise frame.active_error
            message = stack.pop()
            if type(message) is not str:
                raise SericiteError("raise expects a string message", kind="type_error")
            raise SericiteError(message, kind="raise_error")
        elif op == isa.CALL:
            argc, kw_names = arg, ()
            self._call(context, frame, argc, kw_names)
            advance = False
        elif op == isa.CALL_KW:
            argc, kw_names = arg
            self._call(context, frame, argc, kw_names)
            advance = False
        elif op == isa.RETURN:
            value = stack.pop() if stack else None
            if frame.return_contract is not None:
                self._meter(context).work(_contract_cost(frame.return_contract))
                if not _contract_holds(value, frame.return_contract):
                    raise _contract_violation(
                        f"return value of {frame.display_name or frame.code.name}",
                        frame.return_label,
                        frame.return_contract,
                        value,
                    )
            if len(context.frames) == 1:
                context.state = "done"
            else:
                context.frames.pop()
                context.frames[-1].stack.append(value)
            advance = False
        else:
            raise SericiteError(f"unknown opcode: {op}", kind="internal_error")
        if advance and context.state == "ready":
            frame.pc += 1

    def _call(
        self,
        context: VMContext,
        frame: Frame,
        argc: int,
        kw_names: tuple[str, ...],
    ) -> None:
        stack = frame.stack
        base = len(stack) - argc - len(kw_names)
        function = stack[base - 1]
        args = tuple(stack[base : base + argc])
        kwargs = dict(zip(kw_names, stack[base + argc :]))
        if isinstance(function, SericiteFunction):
            code = function.code
            visible = code.origin_vm == context.vm_id
            locals_ = self._bind_arguments(
                code,
                args,
                kwargs,
                function.defaults,
                display_name=None if visible else "function",
                hide_params=not visible,
            )
            self._check_param_contracts(context, function, locals_)
            if len(context.frames) + 1 > context.limits.max_frames:
                raise SericiteError(
                    "call depth limit exceeded", kind="resource_exhausted"
                )
            del stack[base - 1 :]
            frame.pc += 1
            context.frames.append(
                self._new_frame(
                    context,
                    code,
                    locals_,
                    function.module_locals,
                    function.closure,
                    function.granted,
                    function.return_contract,
                    code.return_label if visible else None,
                    None if visible else "function",
                    function.home,
                )
            )
            return
        if isinstance(function, SericiteSchema):
            record = self._construct_record(context, function, args, kwargs)
            del stack[base - 1 :]
            frame.pc += 1
            stack.append(record)
            return
        if isinstance(function, _NativeFunction):
            home = function.home
            contexts = (context,) if home is None else (context, home)
            if function.needs_caller:
                kwargs["_caller_context"] = context
                kwargs["_caller_meter"] = self._meter(context)
            try:
                with self._causal_meter(*contexts) as meter:
                    meter.work(function.work(*args, **kwargs))
                    allocation = function.allocation(*args, **kwargs)
                    if isinstance(allocation, AllocationPermit):
                        kwargs["_allocation_permit"] = allocation
                    else:
                        meter.allocate(allocation)
                    result = function.execute(*args, **kwargs)
            except InputRequired:
                raise
            except SericiteError:
                raise
            except TypeError:
                raise SericiteError(
                    f"invalid arguments for {function.name}", kind="type_error"
                ) from None
            del stack[base - 1 :]
            frame.pc += 1
            stack.append(result)
            return
        if isinstance(function, _GrantedHostFunction):
            meter = self._meter(context)
            budget = [context.limits.max_list_size + context.limits.max_dict_size]
            host_args = [_to_host(value, budget, meter=meter) for value in args]
            host_kwargs = {
                key: _to_host(value, budget, meter=meter)
                for key, value in kwargs.items()
            }
            try:
                raw = function.callback(*host_args, **host_kwargs)
            except SericiteError:
                raise
            except Exception as exc:  # noqa: BLE001 — host exceptions are sanitized into ffi_error
                raise SericiteError(
                    f"host function '{function.name}' failed with {type(exc).__name__}",
                    kind="ffi_error",
                ) from None
            result_budget = [
                context.limits.max_list_size + context.limits.max_dict_size
            ]
            result = _from_host(
                raw,
                result_budget,
                context.limits,
                meter=meter,
            )
            del stack[base - 1 :]
            frame.pc += 1
            stack.append(result)
            return
        if isinstance(function, _GrantedSericiteFunction):
            code = function.code
            locals_ = self._bind_arguments(
                code,
                args,
                kwargs,
                function.defaults,
                display_name=function.name,
                hide_params=True,
            )
            self._check_param_contracts(context, function, locals_)
            if len(context.frames) + 1 > context.limits.max_frames:
                raise SericiteError(
                    "call depth limit exceeded", kind="resource_exhausted"
                )
            del stack[base - 1 :]
            frame.pc += 1
            context.frames.append(
                self._new_frame(
                    context,
                    code,
                    locals_,
                    function.module_locals,
                    function.closure,
                    function.granted,
                    function.return_contract,
                    None,
                    function.name,
                    function.home,
                )
            )
            return
        raise SericiteError("value is not callable", kind="type_error")

    def _new_frame(
        self,
        context: VMContext,
        code: isa.CodeUnit,
        locals_: dict[str, object],
        module_locals: dict[str, object],
        closure: dict[str, _Cell],
        granted: dict[str, object],
        return_contract: object = None,
        return_label: str | None = None,
        display_name: str | None = None,
        home: object = None,
    ) -> Frame:
        cells = {name: _Cell() for name in code.cell_names}
        for name, cell in cells.items():
            if name in locals_:
                cell.value = locals_.pop(name)
        self._meter(context).allocate(len(cells) * 64)
        return Frame(
            code=code,
            locals=locals_,
            cells=cells,
            closure=closure,
            module_locals=module_locals,
            granted=granted,
            return_contract=return_contract,
            return_label=return_label,
            display_name=display_name,
            home=home,
        )

    def _check_param_contracts(
        self,
        context: VMContext,
        function: SericiteFunction | _GrantedSericiteFunction,
        locals_: dict[str, object],
    ) -> None:
        contracts = function.param_contracts
        if not contracts:
            return
        code = function.code
        # Labels and definition-side function names are visible only inside the
        # code's defining VM; granted functions use the granted name (the name on
        # the door), foreign nested functions omit the name.
        visible = code.origin_vm == context.vm_id
        if isinstance(function, _GrantedSericiteFunction):
            func_name: str | None = function.name
        elif visible:
            func_name = code.name
        else:
            func_name = None
        labels: tuple = code.param_labels
        if not visible or len(labels) != len(code.params):
            labels = (None,) * len(code.params)
        for index, (name, contract, label) in enumerate(
            zip(code.params, contracts, labels)
        ):
            if contract is None:
                continue
            self._meter(context).work(_contract_cost(contract))
            value = locals_[name]
            if not _contract_holds(value, contract):
                shown = name if visible else str(index + 1)
                where = f"argument {shown}"
                if func_name is not None:
                    where += f" of {func_name}"
                raise _contract_violation(where, label, contract, value)

    def _construct_record(
        self,
        context: VMContext,
        schema: SericiteSchema,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> SericiteRecord:
        fields = schema.fields
        if len(args) > len(fields):
            raise SericiteError(
                f"schema() takes {len(fields)} positional argument(s), got {len(args)}",
                kind="contract_error",
            )
        values: dict[str, object] = {}
        for (name, _), value in zip(fields, args):
            values[name] = value
        for key, value in kwargs.items():
            if key in values:
                raise SericiteError(
                    f"schema() got multiple values for field '{key}'",
                    kind="contract_error",
                )
            if key not in schema.field_map:
                raise SericiteError(
                    f"schema() got unexpected field '{key}'",
                    kind="contract_error",
                )
            values[key] = value
        missing = [name for name, _ in fields if name not in values]
        if missing:
            raise SericiteError(
                f"schema() missing field(s): {', '.join(missing)}",
                kind="contract_error",
            )
        for name, contract in fields:
            value = values[name]
            self._meter(context).work(_contract_cost(contract))
            if not _contract_holds(value, contract):
                raise _contract_violation(f"field {name}", None, contract, value)
        self._meter(context).allocate(64 + len(fields) * 16)
        return SericiteRecord(schema, {name: values[name] for name, _ in fields})

    def _store_attr(
        self,
        context: VMContext,
        target: object,
        attr: str,
        value: object,
        hint: str | None,
    ) -> None:
        if not isinstance(target, SericiteRecord):
            raise SericiteError(
                f"'{_type_name(target)}' does not support attribute assignment",
                kind="type_error",
            )
        schema = target.schema
        if attr not in schema.field_map:
            raise SericiteError(
                f"{_record_text(target, hint)} has no field '{attr}' "
                "(fields are fixed at construction)",
                kind="attribute_error",
            )
        contract = schema.field_map[attr]
        self._meter(context).work(_contract_cost(contract))
        if not _contract_holds(value, contract):
            raise _contract_violation(f"field {attr}", None, contract, value)
        target.fields[attr] = value

    def _bind_arguments(
        self,
        code: isa.CodeUnit,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        defaults: tuple[object, ...] = (),
        display_name: str | None = None,
        hide_params: bool = False,
    ) -> dict[str, object]:
        # hide_params: when the code does not belong to the current VM, parameter
        # names are definition-side internals — errors use positional indices instead (invariant 16).
        params = code.params
        fname = display_name or code.name

        def shown(name: str) -> str:
            if not hide_params:
                return name
            return str(params.index(name) + 1)

        if len(args) > len(params):
            raise SericiteError(
                f"{fname}() expects {len(params)} argument(s), got {len(args)}",
                kind="arity_error",
            )
        locals_ = dict(zip(params, args))
        for key, value in kwargs.items():
            if key in locals_:
                raise SericiteError(
                    f"{fname}() got multiple values for '{shown(key)}'",
                    kind="arity_error",
                )
            if key not in params:
                raise SericiteError(
                    f"{fname}() got unexpected argument '{key}'",
                    kind="arity_error",
                )
            locals_[key] = value
        if defaults:
            default_start = len(params) - len(defaults)
            for offset, name in enumerate(params[default_start:]):
                if name not in locals_:
                    locals_[name] = defaults[offset]
        if len(locals_) != len(params):
            missing = [shown(name) for name in params if name not in locals_]
            raise SericiteError(
                f"{fname}() missing argument(s): {', '.join(missing)}",
                kind="arity_error",
            )
        return locals_

    def _store_local(self, frame: Frame, name: str, value: object) -> None:
        if name in frame.cells:
            frame.cells[name].value = value
        else:
            frame.locals[name] = value

    def _cell(self, frame: Frame, name: str) -> _Cell:
        if name in frame.cells:
            return frame.cells[name]
        if name in frame.closure:
            return frame.closure[name]
        raise SericiteError("missing closure cell", kind="internal_error")

    def _load_deref(self, frame: Frame, name: str) -> object:
        value = self._cell(frame, name).value
        if value is _UNBOUND:
            raise SericiteError(f"name '{name}' is not defined", kind="name_error")
        return value

    def _load_name(self, context: VMContext, frame: Frame, name: str) -> object:
        if name in frame.locals:
            return frame.locals[name]
        if frame.code.name != "<module>" and name in frame.code.local_names:
            raise SericiteError(f"name '{name}' is not defined", kind="name_error")
        module_locals = (
            frame.module_locals
            if frame.module_locals is not None
            else context.frames[0].locals
        )
        if name in module_locals:
            return module_locals[name]
        granted = frame.granted if frame.granted is not None else context.granted
        if name in granted:
            return granted[name]
        # Builtins resolve back to the code's defining VM (home), not the currently executing VM
        builtin = self._builtin(frame.home or context, name, caller=context)
        if builtin is not None:
            return builtin
        raise SericiteError(f"name '{name}' is not defined", kind="name_error")

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
                if type(value) is not int or value < 0:
                    raise SericiteError(
                        f"VM option {key} must be a non-negative int",
                        kind="type_error",
                    )
                overrides[key] = min(getattr(limits, key), value)
            limits = dataclasses.replace(limits, **overrides)
        depth = causal.depth + 1
        if depth > limits.max_vm_depth:
            raise SericiteError("VM depth limit exceeded", kind="resource_exhausted")
        if causal.child_count >= causal.limits.max_child_vms:
            raise SericiteError("child VM limit exceeded", kind="resource_exhausted")
        causal.child_count += 1
        return self._create_vm(
            source=source,
            parent_id=causal.vm_id,
            depth=depth,
            io=VirtualIO(max_output_bytes=limits.max_output_bytes),
            limits=limits,
            granted=granted,
        )

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

    def _vm_method_work(
        self,
        handle: VMHandle,
        attr: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> int:
        fs = self._context(handle).fs
        if attr == "run":
            inputs = args[0] if args else kwargs.get("inputs", ())
            return len(inputs) if isinstance(inputs, (list, tuple)) else 0
        if attr == "write_file":
            path = args[0] if args else kwargs.get("path")
            text = args[1] if len(args) > 1 else kwargs.get("text")
            return fs.write_work(path, text)
        if attr == "list_dir":
            path = args[0] if args else kwargs.get("path")
            return fs.list_dir_work(path)
        if attr in ("read_file", "path_exists"):
            path = args[0] if args else kwargs.get("path")
            return fs.path_work(path)
        if attr in {
            "feed_input",
            "step",
            "step_instruction",
            "snapshot",
            "stdout",
            "terminate",
        }:
            return 0
        raise SericiteError(
            f"no work contract for VM method '{attr}'", kind="internal_error"
        )

    def _vm_method_allocation(
        self,
        handle: VMHandle,
        attr: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> int | AllocationPermit:
        context = kwargs["_caller_context"]
        target = self._context(handle)
        if attr == "run":
            inputs = args[0] if args else kwargs.get("inputs")
            if inputs is None:
                return 0
            if not isinstance(inputs, (list, tuple)):
                return 0
            amount = target.io.batch_cost(inputs)
            return self._meter(context).reserve(target.io, "input", amount)
        if attr == "feed_input":
            value = args[0] if args else kwargs.get("value")
            amount = target.io.input_cost(value)
            return self._meter(context).reserve(target.io, "input", amount)
        if attr == "write_file":
            path = args[0] if args else kwargs.get("path")
            text = args[1] if len(args) > 1 else kwargs.get("text")
            amount = target.fs.write_allocation(path, text)
            return self._meter(context).reserve(target.fs, "write", amount)
        if attr in {
            "read_file",
            "list_dir",
            "path_exists",
            "step",
            "step_instruction",
            "snapshot",
            "stdout",
            "terminate",
        }:
            return 0
        raise SericiteError(
            f"no allocation contract for VM method '{attr}'", kind="internal_error"
        )

    def _charged_vm_method(
        self,
        handle: VMHandle,
        attr: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> object:
        context = kwargs.pop("_caller_context")
        result_meter = kwargs.pop("_caller_meter")
        meter = self._meter(context)
        permit = kwargs.pop("_allocation_permit", None)
        feed_signature = (
            len(args) + len(kwargs) == 1 and len(args) <= 1 and set(kwargs) <= {"value"}
        )
        run_signature = (
            len(args) <= 1
            and set(kwargs) <= {"inputs"}
            and not (args and "inputs" in kwargs)
        )
        write_signature = (
            len(args) + len(kwargs) == 2
            and len(args) <= 2
            and set(kwargs) <= {"path", "text"}
            and (bool(args) or "path" in kwargs)
            and (len(args) > 1 or "text" in kwargs)
        )
        if attr == "feed_input" and feed_signature:
            value = args[0] if args else kwargs.get("value")
            if not isinstance(value, str):
                raise SericiteError("VM input must be a string")
            target = self._context(handle)
            target.io.feed_input(value, permit=permit)
            if target.state == "waiting_input":
                target.state = "ready"
            result = None
        elif attr == "run" and run_signature:
            inputs = args[0] if args else kwargs.get("inputs")
            if inputs is not None:
                if not isinstance(inputs, (list, tuple)) or any(
                    not isinstance(value, str) for value in inputs
                ):
                    raise SericiteError("VM.run inputs must be a list of strings")
                target = self._context(handle)
                target.io.feed_batch(inputs, permit=permit)
                if target.state == "waiting_input":
                    target.state = "ready"
            result = self._run(handle)
        elif attr == "write_file" and write_signature:
            path = args[0] if args else kwargs["path"]
            text = args[1] if len(args) > 1 else kwargs["text"]
            self._context(handle).fs.write_file(path, text, permit=permit)
            result = None
        elif not args and not kwargs and attr == "snapshot":
            result = self._snapshot(self._context(handle), meter=meter)
        elif not args and not kwargs and attr == "step":
            result = self._step(handle, meter=meter)
        elif not args and not kwargs and attr == "step_instruction":
            result = self._step_instruction(handle, meter=meter)
        else:
            result = getattr(handle, attr)(*args, **kwargs)
        _estimate_size(result, meter=result_meter)
        return result

    def _snapshot(
        self, context: VMContext, *, meter: Meter | None = None
    ) -> dict[str, object]:
        next_line = None
        if context.state in {"ready", "waiting_input"} and context.frames:
            frame = context.frames[-1]
            if frame.pc < len(frame.code.instrs):
                next_line = frame.code.instrs[frame.pc].line
        locals_: dict[str, object] = {}
        if context.frames:
            frame = context.frames[-1]
            if meter is not None:
                meter.work(len(frame.locals) + len(frame.cells))
            visible = dict(frame.locals)
            for name, cell in frame.cells.items():
                if cell.value is not _UNBOUND:
                    visible[name] = cell.value
            seen: set[int] = set()
            budget = [_MAX_RENDER_NODES]
            locals_ = {
                name: self._safe_value(value, seen, _budget=budget, meter=meter)
                for name, value in visible.items()
                if not name.startswith("$")
            }
        error = None
        if context.error is not None:
            error = {
                "kind": context.error.kind,
                "message": context.error.message,
                "line": context.error.line,
                "column": context.error.column,
            }
        return {
            "vm_id": context.vm_id,
            "state": context.state,
            "last_line": context.last_line,
            "next_line": next_line,
            "locals": locals_,
            "stdout": context.io.stdout(),
            "error": error,
            "instruction_count": context.instruction_count,
        }

    def _safe_value(
        self,
        value: object,
        _seen: set[int] | None = None,
        _depth: int = 0,
        _budget: list[int] | None = None,
        *,
        meter: Meter | None = None,
    ) -> object:
        if _seen is None:
            _seen = set()
        if _budget is None:
            _budget = [_MAX_RENDER_NODES]
        if _budget[0] <= 0:
            return "<max nodes>"
        _budget[0] -= 1
        if meter is not None:
            meter.work(1)
        if value is None or type(value) in {str, int, float, bool}:
            return value
        if isinstance(value, (list, dict, SericiteRecord)):
            if _depth > 64:
                return "<max depth>"
            ident = id(value)
            if ident in _seen:
                if type(value) is list:
                    return "[...]"
                if type(value) is dict:
                    return "{...}"
                return "record(...)"
            _seen.add(ident)
            if type(value) is list:
                return [
                    self._safe_value(item, _seen, _depth + 1, _budget, meter=meter)
                    for item in value
                ]
            fields = value.fields if isinstance(value, SericiteRecord) else value
            result = {
                str(key): self._safe_value(
                    item, _seen, _depth + 1, _budget, meter=meter
                )
                for key, item in fields.items()
            }
            return {"<record>": result} if isinstance(value, SericiteRecord) else result
        if isinstance(value, SericiteSchema):
            return _schema_repr(value, _seen, _budget, meter=meter)
        if isinstance(value, (VMHandle, SericiteFunction, _NativeFunction)):
            return repr(value)
        if isinstance(value, (_GrantedHostFunction, _GrantedSericiteFunction)):
            return repr(value)
        return f"<{type(value).__name__}>"


def _is_number(value: object) -> bool:
    return type(value) in (int, float)


def _min_limits(a: SericiteLimits, b: SericiteLimits) -> SericiteLimits:
    return dataclasses.replace(
        a, **{key: min(getattr(a, key), getattr(b, key)) for key in _VM_OPTIONS}
    )


def _stamp_origin(code: isa.CodeUnit, vm_id: int) -> None:
    """Stamp a CodeUnit tree with the id of the VM that compiled it: the basis for label and definition-name visibility."""
    seen: set[int] = set()
    units = [code]
    while units:
        unit = units.pop()
        if id(unit) in seen:
            continue
        seen.add(id(unit))
        unit.origin_vm = vm_id
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
    if left is right:
        return True
    if _is_number(left) and _is_number(right):
        return left == right
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
