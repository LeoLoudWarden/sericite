from collections import deque
from collections.abc import Callable, Iterable
from io import StringIO


class InputRequired(Exception):
    pass


class OutputLimitExceeded(Exception):
    pass


class VirtualIO:
    def __init__(
        self,
        inputs: Iterable[str] | None = None,
        input_provider: Callable[[], str | None] | None = None,
        max_output_bytes: int | None = None,
    ) -> None:
        self._inputs: deque[str] = deque()
        self._output = StringIO()
        self._output_size = 0
        self._max_output_bytes = max_output_bytes
        self._input_provider = input_provider
        if inputs is not None:
            for value in inputs:
                self.feed_input(value)

    @property
    def buffered_input_count(self) -> int:
        return len(self._inputs)

    @property
    def has_input_provider(self) -> bool:
        return self._input_provider is not None

    def feed_input(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("input must be a string")
        self._inputs.append(value)

    def read_input(self) -> str:
        if self._inputs:
            value = self._inputs.popleft()
        elif self._input_provider is not None:
            try:
                value = self._input_provider()
            except (EOFError, StopIteration):
                raise InputRequired from None
            if value is None:
                raise InputRequired
        else:
            raise InputRequired
        if not isinstance(value, str):
            raise TypeError("input provider must return a string or None")
        if value.endswith("\n"):
            value = value[:-1]
            value = value.removesuffix("\r")
        return value

    @property
    def remaining_output_bytes(self) -> int | None:
        if self._max_output_bytes is None:
            return None
        return max(0, self._max_output_bytes - self._output_size)

    def write_output(self, value: str) -> None:
        if self._max_output_bytes is not None:
            size = len(value.encode("utf-8"))
            if self._output_size + size > self._max_output_bytes:
                raise OutputLimitExceeded
            self._output_size += size
        self._output.write(value)

    def stdout(self) -> str:
        return self._output.getvalue()
