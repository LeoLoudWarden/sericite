from dataclasses import dataclass


@dataclass(frozen=True)
class _SourcePart:
    name: str
    start_line: int
    line_count: int


class _CombinedSource:
    def __init__(self, parts: list[tuple[str, str]]) -> None:
        self._parts: list[_SourcePart] = []
        next_line = 1
        for name, text in parts:
            line_count = text.count("\n") + 1
            self._parts.append(_SourcePart(name, next_line, line_count))
            next_line += line_count
        self.text = "\n".join(text for _, text in parts)

    def location(self, line: int | None) -> tuple[str, int | None]:
        if line is None or not self._parts:
            return "<sericite>", None
        part = self._parts[-1]
        for candidate in self._parts:
            if (
                candidate.start_line
                <= line
                < candidate.start_line + candidate.line_count
            ):
                part = candidate
                break
        return part.name, line - part.start_line + 1


class _ReplSourceMap:
    """Keep only startup and current sources; retained functions come from unshifted statement deliveries."""

    def __init__(self, startup: _CombinedSource) -> None:
        self._startup = (startup, 0)
        self._current = self._startup
        self._current_id = 0
        self._next_id = 1
        self._stdin = _CombinedSource([("<stdin>", "")])

    def add(self, source: _CombinedSource, line_offset: int) -> int:
        source_id = self._next_id
        self._next_id += 1
        self._current_id = source_id
        self._current = (source, line_offset)
        return source_id

    def get(self, source_id: int | None) -> tuple[_CombinedSource, int] | None:
        if source_id == 0:
            return self._startup
        if source_id == self._current_id:
            return self._current
        if type(source_id) is int and 0 < source_id < self._next_id:
            return self._stdin, 0
        return None
