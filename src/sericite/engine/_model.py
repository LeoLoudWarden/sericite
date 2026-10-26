from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .. import isa
from ..accounting import AllocationPermit, Meter
from ..compiler import VM_METHODS
from ..errors import SericiteError
from ..io import VirtualIO
from ..vfs import VirtualFileSystem

if TYPE_CHECKING:
    from . import SericiteEngine

# Shared engine constants (single home; imported by the other engine parts).
_TERMINAL_STATES = {"done", "error", "resource_exhausted", "terminated"}
_MAX_SOURCE_BYTES = 4 * 1024 * 1024
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


def _contract_key(contract: object) -> object:
    if isinstance(contract, SericiteSchema):
        return ("schema", contract.key)
    return ("tag", contract)
