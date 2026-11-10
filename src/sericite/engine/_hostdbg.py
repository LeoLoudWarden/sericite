from __future__ import annotations

from ..accounting import AllocationPermit, Meter
from ..errors import SericiteError
from ..vfs import normalize_path
from ._model import (
    _UNBOUND,
    SericiteFunction,
    SericiteModule,
    SericiteRecord,
    SericiteSchema,
    VFSHandle,
    VMContext,
    VMHandle,
    _GrantedHostFunction,
    _GrantedSericiteFunction,
    _NativeFunction,
)
from ._values import _MAX_RENDER_NODES, _estimate_size, _schema_repr


class _EngineHostDebug:
    def _dispose_shape(self, handle: VMHandle) -> tuple[int, int]:
        target = handle._engine._contexts.get(handle._vm_id)
        if target is None:
            return 0, 0
        return target.live_descendant_count + 1, len(target.ancestor_ids)

    @staticmethod
    def _breakpoint_key(line: object, path: object) -> tuple[int, str | None]:
        if type(line) is not int or line <= 0:
            raise SericiteError(
                "breakpoint line must be a positive integer", kind="type_error"
            )
        if path is not None and not isinstance(path, str):
            raise SericiteError(
                "breakpoint path must be a string or None", kind="type_error"
            )
        return line, normalize_path(path) if path is not None else None

    def _breakpoint_call(
        self, args: tuple[object, ...], kwargs: dict[str, object]
    ) -> tuple[int, str | None]:
        count = len(args) + len(kwargs)
        if (
            not 1 <= count <= 2
            or len(args) > 2
            or set(kwargs) - {"line", "path"}
            or (args and "line" in kwargs)
            or (len(args) == 2 and "path" in kwargs)
        ):
            raise SericiteError("invalid breakpoint arguments", kind="type_error")
        line = args[0] if args else kwargs.get("line")
        path = args[1] if len(args) == 2 else kwargs.get("path")
        return self._breakpoint_key(line, path)

    @staticmethod
    def _add_breakpoint_key(context: VMContext, key: tuple[int, str | None]) -> None:
        if key in context.breakpoints:
            return
        if len(context.breakpoints) >= context.limits.max_breakpoints:
            raise SericiteError(
                "breakpoint limit exceeded", kind="breakpoint_limit_error"
            )
        context.breakpoints[key] = None

    def _add_breakpoint(
        self, context: VMContext, line: object, path: object = None
    ) -> None:
        self._add_breakpoint_key(context, self._breakpoint_key(line, path))

    def _remove_breakpoint(
        self, context: VMContext, line: object, path: object = None
    ) -> None:
        context.breakpoints.pop(self._breakpoint_key(line, path), None)

    @staticmethod
    def _breakpoints(context: VMContext) -> list[dict[str, object]]:
        return [{"line": line, "path": path} for line, path in context.breakpoints]

    @staticmethod
    def _breakpoint_at(context: VMContext) -> tuple[int, str | None] | None:
        if not context.breakpoints:
            return None
        frame = context.frames[-1]
        instr = frame.code.instrs[frame.pc]
        code = frame.code
        if not instr.stmt_start or code.origin_vm != context.vm_id:
            return None
        key = (instr.line, None)
        if (
            code.source_id == context.frames[0].code.source_id
            and key in context.breakpoints
        ):
            return key
        if code.filename.startswith("/"):
            key = (instr.line, code.filename)
            if key in context.breakpoints:
                return key
        return None

    def _vm_method_work(
        self,
        handle: VMHandle,
        attr: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> int:
        if attr == "dispose":
            size, ancestor_depth = self._dispose_shape(handle)
            return 2 * size + ancestor_depth
        if attr == "exec":
            source = args[0] if args else kwargs.get("source")
            return 1 + len(source) // 4 if isinstance(source, str) else 0
        if attr == "run":
            inputs = args[0] if args else kwargs.get("inputs", ())
            return len(inputs) if isinstance(inputs, (list, tuple)) else 0
        if attr in {"add_breakpoint", "remove_breakpoint"}:
            path = args[1] if len(args) == 2 else kwargs.get("path")
            if not isinstance(path, str):
                return 0
            return len(path) * (2 if attr == "add_breakpoint" else 1)
        if attr == "breakpoints":
            return len(self._context(handle).breakpoints)
        if attr in {
            "feed_input",
            "step",
            "step_instruction",
            "snapshot",
            "stdout",
            "terminate",
            "take_fs",
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
        if attr == "dispose":
            size, _ = self._dispose_shape(handle)
            return 32 * size
        if attr == "take_fs":
            return 8
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
        if attr == "add_breakpoint":
            public_kwargs = {
                name: value
                for name, value in kwargs.items()
                if name not in {"_caller_context", "_caller_meter"}
            }
            key = self._breakpoint_call(args, public_kwargs)
            if key in target.breakpoints:
                return 0
            return 64 + (len(key[1]) * 4 if key[1] is not None else 0)
        if attr in {
            "exec",
            "step",
            "step_instruction",
            "snapshot",
            "remove_breakpoint",
            "breakpoints",
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
        if attr == "feed_input" and feed_signature:
            value = args[0] if args else kwargs.get("value")
            if not isinstance(value, str):
                raise SericiteError("VM input must be a string")
            target = self._context(handle)
            target.io.feed_input(value, permit=permit)
            if target.state == "waiting_input":
                self._set_state(target, "ready", reason="input")
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
                    self._set_state(target, "ready", reason="input")
            result = self._run(handle)
        elif attr == "exec" and len(args) == 1 and not kwargs:
            result = self._exec_source(handle, args[0])
        elif attr in {"add_breakpoint", "remove_breakpoint"}:
            target = self._context(handle)
            key = self._breakpoint_call(args, kwargs)
            if attr == "add_breakpoint":
                self._add_breakpoint_key(target, key)
            else:
                target.breakpoints.pop(key, None)
            result = None
        elif not args and not kwargs and attr == "breakpoints":
            result = self._breakpoints(self._context(handle))
        elif not args and not kwargs and attr == "take_fs":
            result = self._take_fs(handle)
        elif not args and not kwargs and attr == "dispose":
            result = self._dispose(handle)
        elif not args and not kwargs and attr == "snapshot":
            result = self._snapshot(self._context(handle), meter=meter)
        elif not args and not kwargs and attr == "step":
            result = self._step(handle, meter=meter)
        elif not args and not kwargs and attr == "step_instruction":
            result = self._step_instruction(handle, meter=meter)
        elif not args and not kwargs and attr == "stdout":
            result = handle.stdout()
        elif not args and not kwargs and attr == "terminate":
            result = handle.terminate()
        else:
            raise SericiteError(f"invalid arguments for VM.{attr}", kind="type_error")
        if attr != "take_fs":
            _estimate_size(result, meter=result_meter)
        return result

    def _snapshot(
        self, context: VMContext, *, meter: Meter | None = None
    ) -> dict[str, object]:
        """Script-safe snapshot: never exposes engine-local diagnostic fields."""
        next_line = None
        if context.state in {"ready", "waiting_input", "paused"} and context.frames:
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
            frames = context.error._trace_for(context.vm_id)
            original_position = (
                context.error._trace_vm_id == context.vm_id
                and context.error.filename == context.filename
            )
            line = frames[-1].line if frames else None
            if not frames and original_position:
                line = context.error.line
            column = (
                context.error.column
                if original_position and line is not None and line == context.error.line
                else None
            )
            if meter is not None:
                meter.work(len(frames))
            error = {
                "kind": context.error.kind,
                "message": context.error.message,
                "line": line,
                "column": column,
                "frames": [
                    {"function": frame.function, "line": frame.line} for frame in frames
                ],
            }
        breakpoint = None
        if context.state == "paused" and context.paused_breakpoint is not None:
            line, path = context.paused_breakpoint
            breakpoint = {"line": line, "path": path}
        return {
            "state": context.state,
            "last_line": context.last_line,
            "next_line": next_line,
            "locals": locals_,
            "stdout": context.io.stdout(),
            "error": error,
            "breakpoint": breakpoint,
            "instruction_count": context.instruction_count,
        }

    def _host_snapshot(self, context: VMContext) -> dict[str, object]:
        """Host-only diagnostic snapshot: a strict superset of the script-safe view.

        Only callable from host-side driving code; scripts dispatch through
        `_charged_vm_method`, which uses `_snapshot` and can never reach this.
        """
        snapshot = self._snapshot(context)
        snapshot.update(
            {
                "vm_id": context.vm_id,
                "parent_id": context.parent_id,
                "depth": context.depth,
                "child_count": context.child_count,
            }
        )
        return snapshot

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
        if isinstance(value, (list, tuple, dict, SericiteRecord)):
            if _depth > 64:
                return "<max depth>"
            if type(value) is tuple and not value:
                return ()
            ident = id(value)
            if ident in _seen:
                if type(value) is list:
                    return "[...]"
                if type(value) is tuple:
                    return "(...)"
                if type(value) is dict:
                    return "{...}"
                return "record(...)"
            _seen.add(ident)
            if type(value) is list:
                return [
                    self._safe_value(item, _seen, _depth + 1, _budget, meter=meter)
                    for item in value
                ]
            if type(value) is tuple:
                return tuple(
                    self._safe_value(item, _seen, _depth + 1, _budget, meter=meter)
                    for item in value
                )
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
        if isinstance(
            value,
            (VMHandle, VFSHandle, SericiteFunction, SericiteModule, _NativeFunction),
        ):
            return repr(value)
        if isinstance(value, (_GrantedHostFunction, _GrantedSericiteFunction)):
            return repr(value)
        return f"<{type(value).__name__}>"
