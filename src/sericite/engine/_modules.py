from __future__ import annotations

from ..accounting import Meter
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

    @staticmethod
    def _module_named(home: VMContext, name: str) -> SericiteModule | None:
        return home.modules.get(name) or home.loading_modules.get(name)

    def _resolve_module_name(
        self,
        home: VMContext,
        context: VMContext,
        frame: Frame,
        name: str,
        level: int,
    ) -> str:
        if level == 0:
            return name
        base = frame.code.package
        if not base:
            raise self._import_error(home, context, "relative import outside a package")
        for _ in range(level - 1):
            base = base.rpartition(".")[0]
            if not base:
                raise self._import_error(
                    home, context, "relative import escapes the package root"
                )
        return f"{base}.{name}" if name else base

    def _import_module(
        self,
        context: VMContext,
        frame: Frame,
        spec: object,
        *,
        advance: bool = True,
    ) -> SericiteModule | None:
        if (
            not isinstance(spec, tuple)
            or len(spec) != 2
            or not isinstance(spec[0], str)
            or type(spec[1]) is not int
        ):
            raise SericiteError("invalid module name", kind="internal_error")
        name, level = spec
        home = frame.home or context
        self._require_live_home(home)
        with self._causal_meter(context, home) as meter:
            return self._load_module(
                context, frame, name, level, home, meter, advance=advance
            )

    def _load_module(
        self,
        context: VMContext,
        frame: Frame,
        name: str,
        level: int,
        home: VMContext,
        meter: Meter,
        *,
        advance: bool,
    ) -> SericiteModule | None:
        full_name = self._resolve_module_name(home, context, frame, name, level)
        meter.work(len(full_name))
        cached = home.modules.get(full_name)
        if cached is not None:
            return cached
        loading = home.loading_modules.get(full_name)
        if loading is not None:
            if level and not name:
                return loading
            chain = [
                item.module.name for item in context.frames if item.module is not None
            ]
            chain.append(full_name)
            raise self._import_error(
                home, context, "circular import: " + " -> ".join(chain)
            )

        parent_name = full_name.rpartition(".")[0]
        parent = self._module_named(home, parent_name) if parent_name else None
        if parent_name and parent is None:
            raise SericiteError("parent package is not loaded", kind="internal_error")
        if parent is not None and not parent.is_package:
            raise self._import_error(
                home, context, f"module '{parent_name}' is not a package"
            )

        stem = full_name.replace(".", "/")
        file_path = f"/{stem}.sericite"
        package_path = f"/{stem}/__init__.sericite"
        meter.work(len(file_path) + len(package_path))
        fs = self._attached_vfs(home)
        file_exists = fs.path_exists(file_path)
        package_exists = fs.path_exists(package_path)
        if file_exists and package_exists:
            raise self._import_error(
                home,
                context,
                f"module '{full_name}' is both a file and a package",
            )
        if not file_exists and not package_exists:
            raise self._import_error(home, context, f"module '{full_name}' not found")
        is_package = package_exists
        path = package_path if is_package else file_path
        package = full_name if is_package else parent_name

        if len(context.frames) + 1 > context.limits.max_frames:
            raise SericiteError("call depth limit exceeded", kind="resource_exhausted")
        try:
            source = fs.read_file(path)
        except SericiteError as error:
            if error.kind not in {"file_not_found", "is_directory", "not_directory"}:
                raise
            raise self._import_error(
                home, context, f"module '{full_name}' cannot be read"
            ) from None
        meter.work(1 + len(source) // 4)
        meter.allocate(len(source) * 4)
        if len(source.encode("utf-8")) > _MAX_SOURCE_BYTES:
            raise SericiteError("source too large", kind="syntax_error", filename=path)
        code = compile_source(source, path)
        code.package = package
        _stamp_origin(code, home.vm_id, None)
        meter.allocate(_const_bytes(code))
        meter.allocate(192 + (len(path) + len(full_name) + len(package)) * 4)
        module = SericiteModule(
            full_name,
            path,
            {},
            home,
            package=package,
            is_package=is_package,
            parent=parent,
        )
        home.loading_modules[full_name] = module
        frame.call_line = frame.code.instrs[frame.pc].line
        if advance:
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

    def _import_from(
        self, context: VMContext, frame: Frame, module: object, name: object
    ) -> tuple[object, bool]:
        if not isinstance(module, SericiteModule) or not isinstance(name, str):
            raise SericiteError("invalid import state", kind="internal_error")
        self._require_live_home(module.home)
        with self._causal_meter(context, module.home) as meter:
            return self._import_from_with_meter(context, frame, module, name, meter)

    def _import_from_with_meter(
        self,
        context: VMContext,
        frame: Frame,
        module: SericiteModule,
        name: str,
        meter: Meter,
    ) -> tuple[object, bool]:
        meter.work(len(name))
        if name in module.locals:
            return module.locals[name], False
        if not module.is_package:
            raise SericiteError(f"cannot import name '{name}'", kind="import_error")
        child_name = f"{module.name}.{name}"
        child = self._import_module(context, frame, (child_name, 0), advance=False)
        if child is None:
            frame.pending_import = (module, name)
            return None, True
        module.locals[name] = child
        return child, False

    def _resume_import_from(self, frame: Frame, stack: list[object]) -> None:
        pending = frame.pending_import
        if pending is None:
            raise SericiteError("missing pending import", kind="internal_error")
        parent, _ = pending
        child = stack.pop()
        receiver = stack.pop()
        if receiver is not parent:
            raise SericiteError("corrupted import stack", kind="internal_error")
        frame.pending_import = None
        stack.append(child)

    @staticmethod
    def _import_root(module: SericiteModule) -> SericiteModule:
        while module.parent is not None:
            module = module.parent
        return module

    @staticmethod
    def _discard_module_frame(frame: Frame) -> None:
        module = frame.module
        if module is None:
            return
        home = module.home
        if home.loading_modules.get(module.name) is module:
            del home.loading_modules[module.name]

    @staticmethod
    def _finish_module_frame(frame: Frame) -> SericiteModule | None:
        module = frame.module
        if module is None:
            return None
        home = module.home
        if home.loading_modules.get(module.name) is module:
            del home.loading_modules[module.name]
        home.modules[module.name] = module
        if module.parent is not None:
            module.parent.locals[module.name.rpartition(".")[2]] = module
        return module
