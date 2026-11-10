"""Sericite execution engine, split into cohesive parts.

- `_model`: limits, frames, functions, schemas/records, native wrappers, VMContext and VM/VFS handles
- `_values`: value semantics, rendering, contract helpers, FFI deep-copy
- `_core`: engine lifecycle, dispatch loop, exception unwinding, call machinery, VFS attachment
- `_builtins`: built-in functions and child-VM/VFS creation
- `_operators`: operator/index/attribute semantics and container/record/handle natives
- `_hostdbg`: VM-handle method charging and debug snapshots
- `_vfs`: detached-VFS validation, caller charging, and file-operation dispatch
"""

from ..errors import SericiteError, SericiteFrame
from ._builtins import _EngineBuiltins
from ._core import _EngineCore
from ._hostdbg import _EngineHostDebug
from ._model import (
    Frame,
    SericiteFunction,
    SericiteLimits,
    SericiteModule,
    SericiteRecord,
    SericiteSchema,
    VFSHandle,
    VMContext,
    VMHandle,
    _NativeFunction,
)
from ._modules import _EngineModules
from ._operators import _EngineOperators
from ._values import _estimate_size, _StringRenderer
from ._vfs import _EngineVFS

__all__ = [
    "Frame",
    "SericiteEngine",
    "SericiteError",
    "SericiteFrame",
    "SericiteFunction",
    "SericiteLimits",
    "SericiteModule",
    "SericiteRecord",
    "SericiteSchema",
    "VFSHandle",
    "VMContext",
    "VMHandle",
    "_NativeFunction",
    "_StringRenderer",
    "_estimate_size",
]


class SericiteEngine(
    _EngineBuiltins,
    _EngineOperators,
    _EngineHostDebug,
    _EngineModules,
    _EngineVFS,
    _EngineCore,
):
    """Unified dispatch engine: all VMs at every nesting level execute here."""
