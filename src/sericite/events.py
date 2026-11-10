from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from .errors import SericiteError

if TYPE_CHECKING:
    from .engine import SericiteEngine


@dataclass(frozen=True)
class SericiteEvent:
    sequence: int
    kind: str
    vm_id: int
    parent_id: int | None
    depth: int
    data: dict[str, object]


class SericiteObservation:
    def __init__(
        self,
        engine: SericiteEngine,
        sink: Callable[[SericiteEvent], object],
        start_sequence: int,
    ) -> None:
        if not callable(sink):
            raise SericiteError("observation sink must be callable", kind="type_error")
        self._engine = engine
        self._sink = sink
        self._start_sequence = start_sequence
        self._closed = False
        self._failure: str | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def failed(self) -> bool:
        return self._failure is not None

    @property
    def failure(self) -> str | None:
        return self._failure

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._engine._remove_observation(self)

    def poll(self) -> None:
        self._engine._flush_observation_events()

    def _fail(self, error: Exception) -> None:
        self._failure = f"{type(error).__name__}: {error}"
        self.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
