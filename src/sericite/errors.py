from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SericiteFrame:
    function: str
    line: int | None


UNCATCHABLE_ERROR_KINDS = frozenset({"host_error", "internal_error"})
# Kinds a script can catch at runtime with an `except <kind>` filter. `syntax_error`
# is included because nested-VM compilation raises it at runtime when a child VM's
# source is rejected. `resource_exhausted` is catchable only when it arrives from
# another VM; the runtime still rejects it in the VM whose quota was exhausted.
CATCHABLE_ERROR_KINDS = frozenset(
    {
        "arity_error",
        "attribute_error",
        "contract_error",
        "conversion_error",
        "ffi_error",
        "file_not_found",
        "index_error",
        "input_error",
        "is_directory",
        "key_error",
        "name_error",
        "not_directory",
        "raise_error",
        "resource_exhausted",
        "runtime_error",
        "syntax_error",
        "type_error",
        "zero_division",
    }
)
# Complete registry of every error kind (catchable + uncatchable): the single
# source of truth for documentation and external consumers. The engine and
# compiler consume the finer-grained subsets above.
ERROR_KINDS = CATCHABLE_ERROR_KINDS | UNCATCHABLE_ERROR_KINDS


class SericiteError(Exception):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "runtime_error",
        filename: str | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.filename = filename
        self.line = line
        self.column = column
        self._line_bound = line is not None
        self._resource_vm_id: int | None = None
        self._traces: dict[int, tuple[SericiteFrame, ...]] = {}
        self._trace_sources: dict[int, tuple[int | None, ...]] = {}
        self._trace_vm_id: int | None = None

    @property
    def frames(self) -> tuple[SericiteFrame, ...]:
        if self._trace_vm_id is None:
            return ()
        return self._traces[self._trace_vm_id]

    @property
    def _frame_sources(self) -> tuple[int | None, ...]:
        if self._trace_vm_id is None:
            return ()
        return self._trace_sources.get(self._trace_vm_id, ())

    def _trace_for(self, vm_id: int) -> tuple[SericiteFrame, ...]:
        return self._traces.get(vm_id, ())

    def _set_trace(
        self,
        vm_id: int,
        frames: tuple[SericiteFrame, ...],
        sources: tuple[int | None, ...] = (),
    ) -> None:
        self._traces[vm_id] = frames
        self._trace_sources[vm_id] = sources
        if self._trace_vm_id is None:
            self._trace_vm_id = vm_id

    def bind(self, filename: str, line: int | None) -> SericiteError:
        if self.filename is None:
            self.filename = filename
        if not self._line_bound:
            self.line = line
            self._line_bound = True
        return self

    def __str__(self) -> str:
        location = self.filename or "<sericite>"
        if self.line is not None:
            location += f":{self.line}"
            if self.column is not None:
                location += f":{self.column}"
        return f"{location}: {self.kind}: {self.message}"
