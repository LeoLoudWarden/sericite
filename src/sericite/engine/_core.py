from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager

from .. import isa
from ..accounting import UNLIMITED, AccountRoute, AllocationPermit, Meter
from ..compiler import compile_source
from ..errors import UNCATCHABLE_ERROR_KINDS as _UNCATCHABLE_KINDS
from ..errors import SericiteError, SericiteFrame
from ..io import InputRequired, OutputLimitExceeded, VirtualIO
from ..vfs import VirtualFileSystem
from ._model import (
    _MAX_SOURCE_BYTES,
    _TERMINAL_STATES,
    _UNBOUND,
    Frame,
    SericiteFunction,
    SericiteLimits,
    SericiteRecord,
    SericiteSchema,
    VMContext,
    VMHandle,
    _Cell,
    _GrantedHostFunction,
    _GrantedSericiteFunction,
    _NativeFunction,
)
from ._values import (
    _check_grant_name,
    _const_bytes,
    _contract_cost,
    _contract_holds,
    _contract_violation,
    _from_host,
    _make_iterator,
    _normalize_contract,
    _record_text,
    _stamp_origin,
    _to_host,
    _to_str,
    _truthy,
    _type_name,
)

_ERROR_FRAME_SCHEMA = SericiteSchema((("function", "str"), ("line", "any")))
_ERROR_SCHEMA = SericiteSchema(
    (("kind", "str"), ("message", "str"), ("frames", "list"))
)
_TERMINAL_VM_READ_METHODS = frozenset(
    {
        "VM.list_dir",
        "VM.path_exists",
        "VM.read_file",
        "VM.snapshot",
        "VM.step",
        "VM.step_instruction",
        "VM.stdout",
    }
)


class _EngineCore:
    def __init__(self, limits: SericiteLimits | None = None) -> None:
        self._validate_limits(limits)
        self._limits = limits if limits is not None else SericiteLimits()
        self._contexts: dict[int, VMContext] = {}
        self._account_routes: dict[int, AccountRoute] = {}
        self._meters: dict[int, Meter] = {}
        self._next_vm_id = 0

    @staticmethod
    def _validate_limits(limits: SericiteLimits | None) -> None:
        if limits is not None and not isinstance(limits, SericiteLimits):
            raise SericiteError(
                "limits must be a SericiteLimits or None", kind="type_error"
            )

    @staticmethod
    def _copy_string_iterable(values: object, name: str) -> list[str]:
        try:
            copied = list(values)
        except TypeError:
            raise SericiteError(
                f"{name} must be an iterable of strings", kind="type_error"
            ) from None
        if any(not isinstance(value, str) for value in copied):
            raise SericiteError(f"{name} must contain strings", kind="type_error")
        return copied

    def create_root(
        self,
        source: str,
        inputs: Iterable[str] | None = None,
        input_provider: Callable[[], str | None] | None = None,
        limits: SericiteLimits | None = None,
        functions: dict[str, Callable[..., object]] | None = None,
        output_writer: Callable[[str], object] | None = None,
        buffer_output: bool = True,
        argv: Iterable[str] | None = None,
    ) -> VMHandle:
        if not isinstance(source, str):
            raise SericiteError("source must be a string", kind="type_error")
        self._validate_limits(limits)
        if type(buffer_output) is not bool:
            raise SericiteError("buffer_output must be a bool", kind="type_error")
        if functions is not None and not isinstance(functions, dict):
            raise SericiteError(
                "functions must be a dict of callables", kind="type_error"
            )
        if input_provider is not None and not callable(input_provider):
            raise SericiteError(
                "input_provider must be callable or None", kind="type_error"
            )
        if output_writer is not None and not callable(output_writer):
            raise SericiteError(
                "output_writer must be callable or None", kind="type_error"
            )
        if argv is None:
            root_argv = []
        else:
            if isinstance(argv, str):
                raise SericiteError("root argv must contain strings", kind="type_error")
            root_argv = self._copy_string_iterable(argv, "root argv")
        root_inputs = (
            None
            if inputs is None
            else self._copy_string_iterable(inputs, "root inputs")
        )
        effective = self._limits if limits is None else limits
        if functions is not None and "argv" in functions:
            raise SericiteError(
                "granted function name 'argv' conflicts with a root initial value",
                kind="type_error",
            )
        granted = self._validate_host_functions(functions)
        io = VirtualIO(
            inputs=root_inputs,
            input_provider=input_provider,
            max_output_bytes=(
                None
                if effective.max_output_bytes == UNLIMITED
                else effective.max_output_bytes
            ),
            output_writer=output_writer,
            buffer_output=buffer_output,
        )
        return self._create_vm(
            source=source,
            parent_id=None,
            depth=0,
            io=io,
            limits=effective,
            granted=granted,
            initial_locals={"argv": root_argv},
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
        output_writer: object = None,
        initial_locals: dict[str, object] | None = None,
    ) -> VMHandle:
        filename = f"<sericite:vm_{self._next_vm_id}>"
        if len(source.encode("utf-8")) > _MAX_SOURCE_BYTES:
            raise SericiteError(
                "source too large", kind="syntax_error", filename=filename
            )
        if (
            limits.max_total_vms != UNLIMITED
            and self._next_vm_id >= limits.max_total_vms
        ):
            raise SericiteError(
                "total VM limit exceeded",
                kind="resource_exhausted",
                filename=filename,
            )
        code = compile_source(source, filename)
        vm_id = self._next_vm_id
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
            frames=[Frame(code=code, locals=dict(initial_locals or {}))],
            granted=dict(granted) if granted else {},
            output_writer=output_writer,
        )
        if not any(instr.stmt_start for instr in code.instrs):
            context.state = "done"
        route = AccountRoute(context, resolve=self._contexts.__getitem__)
        meter = Meter(route)
        meter.allocate(_const_bytes(code))
        self._next_vm_id += 1
        self._contexts[vm_id] = context
        self._account_routes[vm_id] = route
        self._meters[vm_id] = meter
        if parent_id is not None:
            self._contexts[parent_id].child_ids.add(vm_id)
        return VMHandle(self, vm_id)

    def _context(self, handle: VMHandle) -> VMContext:
        if handle._engine is not self:
            raise SericiteError(
                "VM handle belongs to another engine", kind="internal_error"
            )
        context = self._contexts.get(handle._vm_id)
        if context is None:
            raise SericiteError("VM has been disposed", kind="runtime_error")
        return context

    def _dispose(self, handle: VMHandle) -> None:
        if handle._engine is not self:
            raise SericiteError(
                "VM handle belongs to another engine", kind="internal_error"
            )
        context = self._contexts.get(handle._vm_id)
        if context is None:
            return
        if context.state not in {"done", "error", "resource_exhausted", "terminated"}:
            raise SericiteError(
                "cannot dispose a VM that has not reached a terminal state",
                kind="runtime_error",
            )
        if context.child_ids:
            raise SericiteError(
                "cannot dispose a VM with live child VMs", kind="runtime_error"
            )
        if context.parent_id is not None:
            self._contexts[context.parent_id].child_ids.remove(context.vm_id)
        del self._meters[context.vm_id]
        del self._account_routes[context.vm_id]
        del self._contexts[context.vm_id]

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

    def _exec_source(self, handle: VMHandle, source: object) -> str:
        # Deliver new source to an existing VM: the fresh module frame reuses the
        # previous module locals, so module-level names (and the world: VFS, IO,
        # granted functions, quotas) persist across deliveries. Any program still
        # pending (ready/waiting_input) and the old debugging frames are discarded.
        context = self._context(handle)
        if not isinstance(source, str):
            raise SericiteError("VM.exec source must be a string", kind="type_error")
        if context.running:
            raise SericiteError("VM is already running")
        if context.state == "terminated":
            raise SericiteError(
                "cannot exec into a terminated VM", kind="runtime_error"
            )
        source_id = context.next_source_id
        context.next_source_id += 1
        if len(source.encode("utf-8")) > _MAX_SOURCE_BYTES:
            raise SericiteError(
                "source too large", kind="syntax_error", filename=context.filename
            )
        code = compile_source(source, context.filename)
        _stamp_origin(code, context.vm_id, source_id)
        self._meter(context).allocate(_const_bytes(code))
        module_locals = context.frames[0].locals if context.frames else {}
        context.frames = [Frame(code=code, locals=module_locals)]
        context.error = None
        context.last_line = None
        context.state = (
            "ready" if any(instr.stmt_start for instr in code.instrs) else "done"
        )
        before = len(context.io.stdout())
        self._run(handle)
        return context.io.stdout()[before:]

    def _step(
        self, handle: VMHandle, *, meter: Meter | None = None, host: bool = False
    ) -> dict[str, object]:
        context = self._context(handle)
        if context.running:
            raise SericiteError("VM is already running")
        if context.state != "ready":
            return self._view(context, meter=meter, host=host)
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
        return self._view(context, meter=meter, host=host)

    def _step_instruction(
        self, handle: VMHandle, *, meter: Meter | None = None, host: bool = False
    ) -> dict[str, object]:
        context = self._context(handle)
        if context.running:
            raise SericiteError("VM is already running")
        if context.state != "ready":
            return self._view(context, meter=meter, host=host)
        context.running = True
        try:
            line = self._current_instr(context).line
            if self._execute_one(context):
                context.last_line = line
        finally:
            context.running = False
        return self._view(context, meter=meter, host=host)

    def _view(
        self, context: VMContext, *, meter: Meter | None = None, host: bool = False
    ) -> dict[str, object]:
        if host:
            return self._host_snapshot(context)
        return self._snapshot(context, meter=meter)

    def _current_instr(self, context: VMContext) -> isa.Instr:
        frame = context.frames[-1]
        return frame.code.instrs[frame.pc]

    def _invoke_output_writer(
        self, context: VMContext, function: object, value: str
    ) -> None:
        frame = context.frames[-1]
        frame_pc = frame.pc
        stack_depth = len(frame.stack)
        frame_depth = len(context.frames)
        try:
            frame.stack.extend((function, value))
            self._call(context, frame, 1, ())
            while context.state == "ready" and len(context.frames) > frame_depth:
                self._execute_one(context, exception_floor=frame_depth)
            if context.state == "waiting_input":
                raise SericiteError(
                    "output writer cannot wait for input", kind="runtime_error"
                )
        finally:
            if context.state == "waiting_input":
                context.state = "ready"
            del context.frames[frame_depth:]
            frame.pc = frame_pc
            del frame.stack[stack_depth:]

    def _execute_one(
        self, context: VMContext, *, exception_floor: int | None = None
    ) -> bool:
        if context.state != "ready":
            return False
        frame = context.frames[-1]
        self._sync_active_errors(frame)
        instr = frame.code.instrs[frame.pc]
        try:
            self._meter(context).work(1)
            self._dispatch(context, frame, instr)
        except InputRequired:
            context.state = "waiting_input"
            return False
        except OutputLimitExceeded:
            error = SericiteError("output limit exceeded", kind="resource_exhausted")
            return self._handle_error(context, error, instr.line, exception_floor)
        except SericiteError as exc:
            return self._handle_error(context, exc, instr.line, exception_floor)
        except RecursionError:
            error = SericiteError("recursion limit exceeded", kind="resource_exhausted")
            return self._handle_error(context, error, instr.line, exception_floor)
        except OverflowError:
            error = SericiteError("numeric overflow", kind="conversion_error")
            return self._handle_error(context, error, instr.line, exception_floor)
        except Exception:  # noqa: BLE001 — any host-internal failure becomes internal_error
            error = SericiteError("internal runtime error", kind="internal_error")
            return self._handle_error(context, error, instr.line, exception_floor)
        return True

    def _handle_error(
        self,
        context: VMContext,
        error: SericiteError,
        line: int,
        exception_floor: int | None,
    ) -> bool:
        try:
            self._capture_error(context, error, line)
            if self._handle_exception(context, error, floor=exception_floor or 0):
                return True
        except SericiteError as handling_error:
            error = handling_error
            self._capture_error(context, error, line)
        if exception_floor is not None:
            raise error
        self._fail(context, error, line)
        return False

    def _capture_error(
        self, context: VMContext, error: SericiteError, line: int | None
    ) -> None:
        if context.vm_id in error._traces:
            return
        frames = context.frames
        try:
            self._meter(context).work(len(frames))
            self._meter(context).allocate(16 + len(frames) * 48)
        except SericiteError:
            if (
                error.kind != "resource_exhausted"
                and error.kind not in _UNCATCHABLE_KINDS
            ):
                raise
            error._set_trace(context.vm_id, ())
            return
        trace = []
        sources = []
        last = len(frames) - 1
        for index, frame in enumerate(frames):
            visible = frame.code.origin_vm == context.vm_id
            if not visible:
                frame_line = None
            elif index == last:
                frame_line = line
            else:
                frame_line = frame.call_line
            trace.append(
                SericiteFrame(frame.display_name or frame.code.name, frame_line)
            )
            sources.append(frame.code.source_id if visible else None)
        error._set_trace(context.vm_id, tuple(trace), tuple(sources))

    def _fail(self, context: VMContext, error: SericiteError, line: int | None) -> None:
        try:
            self._capture_error(context, error, line)
        except SericiteError as capture_error:
            error = capture_error
            self._capture_error(context, error, line)
        trace = error._trace_for(context.vm_id)
        if trace:
            line = trace[-1].line
        elif context.frames and context.frames[-1].code.origin_vm != context.vm_id:
            line = None
        if error.kind == "resource_exhausted" and error._resource_vm_id is None:
            error._resource_vm_id = context.vm_id
        context.error = error.bind(context.filename, line)
        context.state = (
            "resource_exhausted" if error.kind == "resource_exhausted" else "error"
        )

    @staticmethod
    def _sync_active_errors(frame: Frame) -> None:
        while frame.active_errors:
            handler, _ = frame.active_errors[-1]
            if handler.target <= frame.pc < handler.body_end:
                break
            frame.active_errors.pop()

    def _handle_exception(
        self, context: VMContext, error: SericiteError, *, floor: int = 0
    ) -> bool:
        if error.kind in _UNCATCHABLE_KINDS:
            return False
        if error.kind == "resource_exhausted":
            source_id = error._resource_vm_id
            if source_id is None:
                return False
            ancestor: VMContext | None = context
            while ancestor is not None:
                if source_id == ancestor.vm_id:
                    return False
                ancestor = (
                    self._contexts.get(ancestor.parent_id)
                    if ancestor.parent_id is not None
                    else None
                )
            source = self._contexts.get(source_id)
            if source is None or source.state not in _TERMINAL_STATES:
                return False
        while len(context.frames) > floor:
            frame = context.frames[-1]
            handler = self._find_handler(frame, error.kind)
            if handler is None:
                if len(context.frames) == floor + 1:
                    return False
                context.frames.pop()
                continue
            del frame.stack[handler.stack_depth :]
            frame.pc = handler.target
            self._sync_active_errors(frame)
            frame.active_errors.append((handler, error))
            if handler.error_name is not None:
                self._store_local(frame, handler.error_name, error)
            if handler.bind is not None:
                self._store_local(
                    frame, handler.bind, self._error_record(context, error)
                )
            return True
        return False

    def _error_record(self, context: VMContext, error: SericiteError) -> SericiteRecord:
        trace = error._trace_for(context.vm_id)
        self._meter(context).work(len(trace))
        self._meter(context).allocate(len(trace) * 8)
        frames = [
            self._construct_record(
                context,
                _ERROR_FRAME_SCHEMA,
                (frame.function, frame.line),
                {},
            )
            for frame in trace
        ]
        return self._construct_record(
            context,
            _ERROR_SCHEMA,
            (error.kind, error.message, frames),
            {},
        )

    def _find_handler(self, frame: Frame, kind: str) -> isa.Handler | None:
        best: isa.Handler | None = None
        pc = frame.pc
        for handler in frame.code.handlers:
            if not (handler.start <= pc < handler.end):
                continue
            if any(start <= pc < end for start, end in handler.exit_ranges):
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
            stack.append(self._load_deref(context, frame, arg))
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
        elif op == isa.FORMAT_VALUE:
            stack[-1] = _to_str(
                stack[-1], context.limits.max_string_bytes, meter=self._meter(context)
            )
        elif op == isa.BUILD_STRING:
            parts = stack[len(stack) - arg :] if arg else []
            if arg:
                del stack[len(stack) - arg :]
            size = sum(len(part) for part in parts)
            if size > context.limits.max_string_bytes:
                raise SericiteError(
                    "string size limit exceeded", kind="resource_exhausted"
                )
            meter = self._meter(context)
            meter.allocate(size * 4)
            meter.work(size // 64)
            stack.append("".join(parts))
        elif op == isa.LOAD_INDEX:
            index = stack.pop()
            value = stack.pop()
            stack.append(self._index(context, value, index))
        elif op == isa.LOAD_SLICE:
            step = stack.pop()
            stop = stack.pop()
            start = stack.pop()
            value = stack.pop()
            stack.append(self._slice(context, value, start, stop, step))
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
            attr, hint, _ = arg
            if frame.code.origin_vm != context.vm_id:
                hint = None
            stack.append(self._load_attr(context, stack.pop(), attr, hint))
        elif op == isa.STORE_ATTR:
            attr, hint, contract_label = arg
            if frame.code.origin_vm != context.vm_id:
                hint = None
                contract_label = None
            target = stack.pop()
            value = stack.pop()
            self._store_attr(context, target, attr, value, hint, contract_label)
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
                    "annotated assignment",
                    label,
                    contract,
                    value,
                    meter=self._meter(context),
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
                if not frame.active_errors:
                    raise SericiteError(
                        "raise without an active error", kind="raise_error"
                    )
                raise frame.active_errors[-1][1]
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
                        meter=self._meter(context),
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
        frame.call_line = frame.code.instrs[frame.pc].line
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
                meter=self._meter(context),
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
            label = (
                frame.code.instrs[frame.pc].label
                if frame.code.origin_vm == context.vm_id
                else None
            )
            record = self._construct_record(
                context, function, args, kwargs, label=label
            )
            del stack[base - 1 :]
            frame.pc += 1
            stack.append(record)
            return
        if isinstance(function, _NativeFunction):
            home = function.home
            if (
                isinstance(home, VMContext)
                and home.state in _TERMINAL_STATES
                and function.name in _TERMINAL_VM_READ_METHODS
            ):
                home = None
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
            except SericiteError as error:
                if (
                    isinstance(home, VMContext)
                    and home is not context
                    and function.name.startswith("VM.")
                    and error.kind == "resource_exhausted"
                    and error._resource_vm_id == home.vm_id
                    and home.state not in _TERMINAL_STATES
                ):
                    line = (
                        self._current_instr(home).line
                        if home.frames
                        and home.frames[-1].pc < len(home.frames[-1].code.instrs)
                        else None
                    )
                    self._fail(home, error, line)
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
            except Exception as exc:  # noqa: BLE001 — uncontracted host failure kills the VM with uncatchable host_error; BaseExceptions (SystemExit, KeyboardInterrupt) propagate to the host
                raise SericiteError(
                    f"host function '{function.name}' failed with {type(exc).__name__}",
                    kind="host_error",
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
                meter=self._meter(context),
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
                raise _contract_violation(
                    where, label, contract, value, meter=self._meter(context)
                )

    def _construct_record(
        self,
        context: VMContext,
        schema: SericiteSchema,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        label: isa._DiagnosticLabel | None = None,
    ) -> SericiteRecord:
        fields = schema.fields
        constructor = f"{label.text if label is not None else 'schema'}()"
        field_labels = dict(label.fields) if label is not None else {}
        if len(args) > len(fields):
            raise SericiteError(
                f"{constructor} takes {len(fields)} positional argument(s), got {len(args)}",
                kind="contract_error",
            )
        values: dict[str, object] = {}
        for (name, _), value in zip(fields, args):
            values[name] = value
        for key, value in kwargs.items():
            if key in values:
                raise SericiteError(
                    f"{constructor} got multiple values for field '{key}'",
                    kind="contract_error",
                )
            if key not in schema.field_map:
                raise SericiteError(
                    f"{constructor} got unexpected field '{key}'",
                    kind="contract_error",
                )
            values[key] = value
        missing = [name for name, _ in fields if name not in values]
        if missing:
            self._meter(context).work(sum(len(name) for name in missing))
            raise SericiteError(
                f"{constructor} missing field(s): {', '.join(missing)}",
                kind="contract_error",
            )
        for name, contract in fields:
            value = values[name]
            self._meter(context).work(_contract_cost(contract))
            if not _contract_holds(value, contract):
                raise _contract_violation(
                    f"field {name}",
                    field_labels.get(name),
                    contract,
                    value,
                    meter=self._meter(context),
                )
        self._meter(context).allocate(64 + len(fields) * 16)
        return SericiteRecord(schema, {name: values[name] for name, _ in fields})

    def _store_attr(
        self,
        context: VMContext,
        target: object,
        attr: str,
        value: object,
        hint: str | None,
        contract_label: str | None,
    ) -> None:
        if not isinstance(target, SericiteRecord):
            raise SericiteError(
                f"'{_type_name(target)}' does not support attribute assignment",
                kind="type_error",
            )
        schema = target.schema
        if attr not in schema.field_map:
            raise SericiteError(
                f"{_record_text(target, hint, meter=self._meter(context))} has no field '{attr}' "
                "(fields are fixed at construction)",
                kind="attribute_error",
            )
        contract = schema.field_map[attr]
        self._meter(context).work(_contract_cost(contract))
        if not _contract_holds(value, contract):
            raise _contract_violation(
                f"field {attr}",
                contract_label,
                contract,
                value,
                meter=self._meter(context),
            )
        target.fields[attr] = value

    def _bind_arguments(
        self,
        code: isa.CodeUnit,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        defaults: tuple[object, ...] = (),
        display_name: str | None = None,
        hide_params: bool = False,
        meter: Meter | None = None,
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
            if meter is not None:
                meter.work(sum(len(name) for name in missing))
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

    @staticmethod
    def _undefined_name(context: VMContext, frame: Frame, name: str) -> SericiteError:
        if frame.code.origin_vm == context.vm_id:
            return SericiteError(f"name '{name}' is not defined", kind="name_error")
        return SericiteError("name is not defined", kind="name_error")

    def _load_deref(self, context: VMContext, frame: Frame, name: str) -> object:
        value = self._cell(frame, name).value
        if value is _UNBOUND:
            raise self._undefined_name(context, frame, name)
        return value

    def _load_name(self, context: VMContext, frame: Frame, name: str) -> object:
        if name in frame.locals:
            return frame.locals[name]
        if frame.code.name != "<module>" and name in frame.code.local_names:
            raise self._undefined_name(context, frame, name)
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
        raise self._undefined_name(context, frame, name)
