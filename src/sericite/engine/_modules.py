from __future__ import annotations

from ..compiler import compile_source
from ..errors import SericiteError
from ._model import _MAX_SOURCE_BYTES, Frame, SericiteModule, VMContext
from ._values import _const_bytes, _stamp_origin


class _EngineModules:
    def _import_error(
        self, home: VMContext, context: VMContext, message: str
    ) -> SericiteError:
        if home is not context:
            message = "module import failed"
        return SericiteError(message, kind="import_error")

    def _import_module(
        self, context: VMContext, frame: Frame, name: object
    ) -> SericiteModule | None:
        if not isinstance(name, str):
            raise SericiteError("invalid module name", kind="internal_error")
        home = frame.home or context
        self._require_live_home(home)
        path = f"/{name}.sericite"
        meter = self._meter(context)
        meter.work(len(path))
        cached = home.modules.get(path)
        if cached is not None:
            return cached
        if path in home.loading_modules:
            chain = [
                item.module.name for item in context.frames if item.module is not None
            ]
            chain.append(name)
            raise self._import_error(
                home, context, "circular import: " + " -> ".join(chain)
            )
        if len(context.frames) + 1 > context.limits.max_frames:
            raise SericiteError("call depth limit exceeded", kind="resource_exhausted")
        try:
            source = home.fs.read_file(path)
        except SericiteError as error:
            if error.kind not in {"file_not_found", "is_directory", "not_directory"}:
                raise
            raise self._import_error(
                home, context, f"module '{name}' not found at {path}"
            ) from None
        meter.work(1 + len(source) // 4)
        meter.allocate(len(source) * 4)
        if len(source.encode("utf-8")) > _MAX_SOURCE_BYTES:
            raise SericiteError("source too large", kind="syntax_error", filename=path)
        code = compile_source(source, path)
        source_id = home.next_source_id
        home.next_source_id += 1
        _stamp_origin(code, home.vm_id, source_id)
        meter.allocate(_const_bytes(code))
        meter.allocate(128 + len(path) * 4)
        module = SericiteModule(name, path, {}, home)
        home.loading_modules[path] = module
        frame.call_line = frame.code.instrs[frame.pc].line
        frame.pc += 1
        module_frame = self._new_frame(
            context,
            code,
            module.locals,
            module.locals,
            {},
            home.granted,
            home=home,
        )
        module_frame.module = module
        context.frames.append(module_frame)
        return None

    def _import_from(self, context: VMContext, module: object, name: object) -> object:
        if not isinstance(module, SericiteModule) or not isinstance(name, str):
            raise SericiteError("invalid import state", kind="internal_error")
        self._require_live_home(module.home)
        self._meter(context).work(len(name))
        if name not in module.locals:
            raise SericiteError(f"cannot import name '{name}'", kind="import_error")
        return module.locals[name]

    @staticmethod
    def _discard_module_frame(frame: Frame) -> None:
        module = frame.module
        if module is None:
            return
        home = module.home
        if home.loading_modules.get(module.path) is module:
            del home.loading_modules[module.path]

    @staticmethod
    def _finish_module_frame(frame: Frame) -> SericiteModule | None:
        module = frame.module
        if module is None:
            return None
        home = module.home
        if home.loading_modules.get(module.path) is module:
            del home.loading_modules[module.path]
        home.modules[module.path] = module
        return module
