from __future__ import annotations

import inspect
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .. import isa
from ..accounting import UNLIMITED, AllocationPermit, Meter
from ..compiler import VFS_METHODS, VM_METHODS
from ..errors import SericiteError
from ..io import VirtualIO
from ..vfs import VFSAttachment, VirtualFileSystem

if TYPE_CHECKING:
    from . import SericiteEngine

# Shared engine constants (single home; imported by the other engine parts).
_TERMINAL_STATES = {"done", "error", "resource_exhausted", "terminated"}
_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_VM_OPTIONS = {
    "max_instructions",
    "max_output_bytes",
    "max_frames",
    "max_list_size",
    "max_dict_size",
    "max_string_bytes",
    "max_int_bits",
    "max_total_bytes",
    "max_total_vms",
    "max_descendant_vms",
    "max_vm_depth",
    "max_breakpoints",
    "max_fs_files",
    "max_fs_file_bytes",
    "max_fs_storage_bytes",
}
_CUMULATIVE_VM_OPTIONS = {
    "max_instructions",
    "max_output_bytes",
    "max_total_bytes",
}


@dataclass(frozen=True)
class SericiteLimits:
    max_instructions: int = 1_000_000
    max_output_bytes: int = 1_048_576
    max_frames: int = 100
    max_list_size: int = 100_000
    max_dict_size: int = 100_000
    max_string_bytes: int = 1_048_576
    max_int_bits: int = 4096
    max_total_bytes: int = 67_108_864
    max_total_vms: int = 1000
    max_descendant_vms: int = 1000
    max_vm_depth: int = 8
    max_breakpoints: int = 100
    max_fs_files: int = 1000
    max_fs_file_bytes: int = 1_048_576
    max_fs_storage_bytes: int = 67_108_864

    def __post_init__(self) -> None:
        for key in _VM_OPTIONS:
            value = getattr(self, key)
            unlimited = key in _CUMULATIVE_VM_OPTIONS and value == UNLIMITED
            if type(value) is not int or (value < 0 and not unlimited):
                requirement = (
                    "a non-negative int or -1"
                    if key in _CUMULATIVE_VM_OPTIONS
                    else "a non-negative int"
                )
                raise SericiteError(
                    f"limit {key} must be {requirement}", kind="type_error"
                )


_UNBOUND = object()


class _Cell:
    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value = _UNBOUND


class SericiteModule:
    __slots__ = ("home", "is_package", "locals", "name", "package", "parent", "path")

    def __init__(
        self,
        name: str,
        path: str,
        locals: dict[str, object],
        home: object,
        *,
        package: str = "",
        is_package: bool = False,
        parent: object = None,
    ) -> None:
        self.name = name
        self.path = path
        self.locals = locals
        self.home = home
        self.package = package
        self.is_package = is_package
        self.parent = parent

    def __repr__(self) -> str:
        return "<module>"


@dataclass
class Frame:
    code: isa.CodeUnit
    pc: int = 0
    call_line: int | None = None
    stack: list[object] = field(default_factory=list)
    locals: dict[str, object] = field(default_factory=dict)
    cells: dict[str, _Cell] = field(default_factory=dict)
    closure: dict[str, _Cell] = field(default_factory=dict)
    module_locals: dict[str, object] | None = None
    granted: dict[str, object] | None = None
    active_errors: list[tuple[isa.Handler, SericiteError]] = field(default_factory=list)
    return_contract: object = None
    return_label: str | None = None
    display_name: str | None = None
    # The VM that defined this code; builtins (IO/filesystem/quotas and other world services) resolve back to it.
    home: object = None
    module: SericiteModule | None = None
    pending_import: tuple[SericiteModule, str] | None = None


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
    """Annotation-only contract-name singleton: any / bool / list / dict / tuple. Not callable."""

    __slots__ = ("tag",)

    def __init__(self, tag: str) -> None:
        self.tag = tag

    def __repr__(self) -> str:
        return self.tag


_ANY = _TagContract("any")
_TAG_CONTRACTS = {
    name: _TagContract(name) for name in ("bool", "list", "dict", "tuple")
}

_CONTRACT_TAGS = ("int", "float", "str", "bool", "list", "dict", "tuple")
_TAG_TYPES = {
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "tuple": tuple,
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
        from ._values import _schema_repr

        return _schema_repr(self)


class SericiteRecord:
    """A fixed-shape object: payload dict + schema reference. Fields cannot be added or removed; values are contract-checked."""

    __slots__ = ("fields", "schema")

    def __init__(self, schema: SericiteSchema, fields: dict[str, object]) -> None:
        self.schema = schema
        self.fields = fields


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
    _signatures: tuple[inspect.Signature, ...] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_signatures",
            tuple(
                inspect.signature(callback)
                for callback in (self.work, self.allocation, self.execute)
            ),
        )

    def __repr__(self) -> str:
        return f"<function {self.name}>"


@dataclass(frozen=True)
class _GrantedHostFunction:
    """A host-injected Python function: deep-copied both ways across the boundary; uncontracted exceptions kill the VM with host_error."""

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


class VFSHandle:
    _METHODS = VFS_METHODS

    def __init__(self, engine: SericiteEngine, attachment: VFSAttachment) -> None:
        self._engine = engine
        self._attachment = attachment
        self._consumed = False

    def read_file(self, path: object) -> str:
        return self._engine._detached_vfs(self).read_file(path)

    def write_file(self, path: object, text: object) -> None:
        self._engine._detached_vfs(self).write_file_trusted(
            path, text, limits=self._engine._limits
        )

    def delete_file(self, path: object) -> None:
        self._engine._detached_vfs(self).delete_file(path)

    def rename_file(self, old_path: object, new_path: object) -> None:
        self._engine._detached_vfs(self).rename_file_trusted(
            old_path, new_path, limits=self._engine._limits
        )

    def copy_file(self, source_path: object, destination_path: object) -> None:
        self._engine._detached_vfs(self).copy_file_trusted(
            source_path, destination_path, limits=self._engine._limits
        )

    def delete_dir(self, path: object) -> None:
        self._engine._detached_vfs(self).delete_dir(path)

    def rename_dir(self, old_path: object, new_path: object) -> None:
        self._engine._detached_vfs(self).rename_dir_trusted(
            old_path, new_path, limits=self._engine._limits
        )

    def copy_dir(self, source_path: object, destination_path: object) -> None:
        self._engine._detached_vfs(self).copy_dir_trusted(
            source_path, destination_path, limits=self._engine._limits
        )

    def make_dir(self, path: object) -> None:
        self._engine._detached_vfs(self).make_dir_trusted(
            path, limits=self._engine._limits
        )

    def list_dir(self, path: object) -> list[str]:
        return self._engine._detached_vfs(self).list_dir(path)

    def path_exists(self, path: object) -> bool:
        return self._engine._detached_vfs(self).path_exists(path)

    def __repr__(self) -> str:
        return "<VFS>"


@dataclass
class VMContext:
    vm_id: int
    depth: int
    parent_id: int | None
    io: VirtualIO
    vfs: VFSAttachment | None
    limits: SericiteLimits
    module_root: str = "/"
    next_source_id: int = 1
    frames: list[Frame] = field(default_factory=list)
    granted: dict[str, object] = field(default_factory=dict)
    modules: dict[str, SericiteModule] = field(default_factory=dict)
    loading_modules: dict[str, SericiteModule] = field(default_factory=dict)
    output_writer: object = None
    state: str = "ready"
    last_line: int | None = None
    error: SericiteError | None = None
    breakpoints: dict[tuple[int, str | None], None] = field(default_factory=dict)
    paused_breakpoint: tuple[int, str | None] | None = None
    instruction_count: int = 0
    alloc_bytes: int = 0
    child_count: int = 0
    child_ids: set[int] = field(default_factory=set)
    live_descendant_count: int = 0
    ancestor_ids: tuple[int, ...] = ()
    running: bool = False
    meter_stack: list[Meter] = field(default_factory=list)
    meter: Meter | None = None
    finalizer: weakref.finalize | None = None
    finalizer_state: dict[str, object] = field(default_factory=dict)

    @property
    def fs(self) -> VirtualFileSystem | None:
        return self.vfs.fs if self.vfs is not None else None

    @property
    def filename(self) -> str:
        return f"<sericite:vm_{self.vm_id}>"


class VMHandle:
    _METHODS = VM_METHODS

    def __init__(self, engine: SericiteEngine, vm_id: int) -> None:
        self._engine = engine
        self._vm_id = vm_id
        self._context = engine._contexts.get(vm_id)

    def run(self, inputs: object = None) -> str:
        if inputs is not None:
            if not isinstance(inputs, (list, tuple)) or any(
                not isinstance(value, str) for value in inputs
            ):
                raise SericiteError("VM.run inputs must be a list of strings")
            context = self._engine._context(self)
            context.io.feed_batch_trusted(inputs)
            if context.state == "waiting_input":
                self._engine._set_state(context, "ready", reason="input")
        return self._engine._run(self)

    def exec(self, source: object) -> str:
        return self._engine._exec_source(self, source)

    def feed_input(self, value: object) -> None:
        if not isinstance(value, str):
            raise SericiteError("VM input must be a string")
        context = self._engine._context(self)
        context.io.feed_input_trusted(value)
        if context.state == "waiting_input":
            self._engine._set_state(context, "ready", reason="input")

    def step(self) -> dict[str, object]:
        return self._engine._step(self, host=True)

    def step_instruction(self) -> dict[str, object]:
        return self._engine._step_instruction(self, host=True)

    def snapshot(self) -> dict[str, object]:
        return self._engine._host_snapshot(self._engine._context(self))

    def add_breakpoint(self, line: object, path: object = None) -> None:
        self._engine._add_breakpoint(self._engine._context(self), line, path)

    def remove_breakpoint(self, line: object, path: object = None) -> None:
        self._engine._remove_breakpoint(self._engine._context(self), line, path)

    def breakpoints(self) -> list[dict[str, object]]:
        return self._engine._breakpoints(self._engine._context(self))

    def stdout(self) -> str:
        return self._engine._context(self).io.stdout()

    def terminate(self) -> None:
        context = self._engine._context(self)
        if context.state in {"ready", "waiting_input", "paused"}:
            self._engine._set_state(context, "terminated", reason="terminate")
            context.paused_breakpoint = None

    def dispose(self) -> None:
        self._engine._dispose(self)

    def take_fs(self) -> VFSHandle:
        return self._engine._take_fs(self)

    def read_file(self, path: object) -> str:
        return self._engine._attached_vfs(self._engine._context(self)).read_file(path)

    def write_file(self, path: object, text: object) -> None:
        context = self._engine._context(self)
        self._engine._attached_vfs(context).write_file_trusted(
            path, text, limits=context.limits
        )

    def delete_file(self, path: object) -> None:
        self._engine._attached_vfs(self._engine._context(self)).delete_file(path)

    def rename_file(self, old_path: object, new_path: object) -> None:
        context = self._engine._context(self)
        self._engine._attached_vfs(context).rename_file_trusted(
            old_path, new_path, limits=context.limits
        )

    def copy_file(self, source_path: object, destination_path: object) -> None:
        context = self._engine._context(self)
        self._engine._attached_vfs(context).copy_file_trusted(
            source_path, destination_path, limits=context.limits
        )

    def delete_dir(self, path: object) -> None:
        self._engine._attached_vfs(self._engine._context(self)).delete_dir(path)

    def rename_dir(self, old_path: object, new_path: object) -> None:
        context = self._engine._context(self)
        self._engine._attached_vfs(context).rename_dir_trusted(
            old_path, new_path, limits=context.limits
        )

    def copy_dir(self, source_path: object, destination_path: object) -> None:
        context = self._engine._context(self)
        self._engine._attached_vfs(context).copy_dir_trusted(
            source_path, destination_path, limits=context.limits
        )

    def make_dir(self, path: object) -> None:
        context = self._engine._context(self)
        self._engine._attached_vfs(context).make_dir_trusted(
            path, limits=context.limits
        )

    def list_dir(self, path: object) -> list[str]:
        return self._engine._attached_vfs(self._engine._context(self)).list_dir(path)

    def path_exists(self, path: object) -> bool:
        return self._engine._attached_vfs(self._engine._context(self)).path_exists(path)

    def __repr__(self) -> str:
        context = self._engine._contexts.get(self._vm_id)
        if context is None:
            return "<VM state=disposed>"
        return f"<VM state={context.state}>"


def _contract_key(contract: object) -> object:
    if isinstance(contract, SericiteSchema):
        return ("schema", contract.key)
    return ("tag", contract)
