from __future__ import annotations

from ..accounting import AllocationPermit, Meter
from ..errors import SericiteError
from ._model import (
    _UNBOUND,
    SericiteFunction,
    SericiteRecord,
    SericiteSchema,
    VMContext,
    VMHandle,
    _GrantedHostFunction,
    _GrantedSericiteFunction,
    _NativeFunction,
)
from ._values import _MAX_RENDER_NODES, _estimate_size, _schema_repr


class _EngineHostDebug:
    def _vm_method_work(
        self,
        handle: VMHandle,
        attr: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> int:
        if attr == "dispose":
            return 0
        fs = self._context(handle).fs
        if attr == "exec":
            source = args[0] if args else kwargs.get("source")
            return 1 + len(source) // 4 if isinstance(source, str) else 0
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
            "dispose",
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
            return 0
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
            "exec",
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
            target = self._context(handle)
            try:
                target.fs.write_file(path, text, permit=permit)
            except SericiteError as error:
                if error.kind == "resource_exhausted" and error._resource_vm_id is None:
                    error._resource_vm_id = target.vm_id
                raise
            result = None
        elif attr == "exec" and len(args) == 1 and not kwargs:
            result = self._exec_source(handle, args[0])
        elif not args and not kwargs and attr == "dispose":
            result = self._dispose(handle)
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
        """Script-safe snapshot: never exposes engine-local diagnostic fields."""
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
        return {
            "state": context.state,
            "last_line": context.last_line,
            "next_line": next_line,
            "locals": locals_,
            "stdout": context.io.stdout(),
            "error": error,
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
