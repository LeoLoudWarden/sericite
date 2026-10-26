from collections import deque
from collections.abc import Callable, Iterable
from io import StringIO

from .accounting import AllocationPermit


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
            self.feed_batch_trusted(inputs)

    @property
    def buffered_input_count(self) -> int:
        return len(self._inputs)

    @property
    def has_input_provider(self) -> bool:
        return self._input_provider is not None

    @staticmethod
    def input_cost(value: object) -> int:
        return 8 + (len(value) * 4 if isinstance(value, str) else 0)

    @classmethod
    def batch_cost(cls, values: Iterable[object]) -> int:
        return sum(cls.input_cost(value) for value in values)

    def feed_input(self, value: str, *, permit: AllocationPermit) -> None:
        self.feed_batch([value], permit=permit)

    def feed_batch(
        self, values: list[str] | tuple[str, ...], *, permit: AllocationPermit
    ) -> None:
        if any(not isinstance(value, str) for value in values):
            raise TypeError("input must be a string")
        amount = self.batch_cost(values)
        permit.consume(self, "input", amount)
        self._inputs.extend(values)

    def feed_input_trusted(self, value: str) -> None:
        """Preconfigure input on behalf of the trusted host, outside script accounting."""
        self.feed_batch_trusted([value])

    def feed_batch_trusted(self, values: Iterable[str]) -> None:
        """Preconfigure a batch atomically on behalf of the trusted host."""
        batch = list(values)
        if any(not isinstance(value, str) for value in batch):
            raise TypeError("input must be a string")
        self._inputs.extend(batch)

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
