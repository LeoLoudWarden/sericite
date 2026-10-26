"""Sericite execution engine, split into cohesive parts.

- `_model`: limits, frames, functions, schemas/records, native wrappers, VMContext/VMHandle
- `_values`: value semantics, rendering, contract helpers, FFI deep-copy
- `_core`: engine lifecycle, dispatch loop, exception unwinding, call machinery
- `_builtins`: built-in functions and child-VM creation
- `_operators`: operator/index/attribute semantics and container/record natives
- `_hostdbg`: VM-handle method charging and debug snapshots
"""

from ..errors import SericiteError
from ._builtins import _EngineBuiltins
from ._core import _EngineCore
from ._hostdbg import _EngineHostDebug
from ._model import (
    Frame,
    SericiteFunction,
    SericiteLimits,
    SericiteRecord,
    SericiteSchema,
    VMContext,
    VMHandle,
    _NativeFunction,
)
from ._operators import _EngineOperators
from ._values import _estimate_size, _StringRenderer

__all__ = [
    "Frame",
    "SericiteEngine",
    "SericiteError",
    "SericiteFunction",
    "SericiteLimits",
    "SericiteRecord",
    "SericiteSchema",
    "VMContext",
    "VMHandle",
    "_NativeFunction",
    "_StringRenderer",
    "_estimate_size",
]


class SericiteEngine(_EngineBuiltins, _EngineOperators, _EngineHostDebug, _EngineCore):
    """Unified dispatch engine: all VMs at every nesting level execute here."""
