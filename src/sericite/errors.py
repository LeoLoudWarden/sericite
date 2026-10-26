from __future__ import annotations

UNCATCHABLE_ERROR_KINDS = frozenset(
    {"host_error", "internal_error", "resource_exhausted"}
)
# Kinds a script can catch at runtime with an `except <kind>` filter. `syntax_error`
# and `validation_error` are included because nested-VM compilation raises them at
# runtime (e.g. a child VM whose source fails to parse or validate).
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
        "runtime_error",
        "syntax_error",
        "type_error",
        "validation_error",
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

    def bind(self, filename: str, line: int | None) -> SericiteError:
        if self.filename is None:
            self.filename = filename
        if self.line is None:
            self.line = line
        return self

    def __str__(self) -> str:
        location = self.filename or "<sericite>"
        if self.line is not None:
            location += f":{self.line}"
            if self.column is not None:
                location += f":{self.column}"
        return f"{location}: {self.kind}: {self.message}"
