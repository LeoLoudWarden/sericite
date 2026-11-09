from ..errors import SericiteError
from ._sources import _CombinedSource, _ReplSourceMap


def _format_error(
    error: SericiteError,
    source: _CombinedSource,
    *,
    line_offset: int = 0,
    source_map: dict[int, tuple[_CombinedSource, int]] | _ReplSourceMap | None = None,
) -> str:
    def current_location(line: int | None) -> tuple[str, int | None]:
        mapped_line = None if line is None else max(1, line - line_offset)
        return source.location(mapped_line)

    def location(
        line: int | None, source_id: int | None, logical: str | None = None
    ) -> tuple[str, int | None]:
        if logical is not None and not logical.startswith("<sericite:"):
            return logical, line
        if source_map is None:
            return current_location(line)
        entry = source_map.get(source_id)
        if entry is None:
            return "<sericite>", None
        mapped_source, offset = entry
        mapped_line = None if line is None else max(1, line - offset)
        return mapped_source.location(mapped_line)

    root_source = error.filename in (None, "<sericite>", "<sericite:vm_0>")
    frame_sources = error._frame_sources
    frame_filenames = error._frame_filenames
    if root_source:
        if not error.frames and error._trace_vm_id is None:
            filename, line = current_location(error.line)
        else:
            last = len(error.frames) - 1
            source_id = (
                frame_sources[-1]
                if error.frames and len(frame_sources) == len(error.frames)
                else None
            )
            logical = (
                frame_filenames[last]
                if last >= 0 and last < len(frame_filenames)
                else None
            )
            filename, line = location(error.line, source_id, logical)
        text = str(
            SericiteError(
                error.message,
                kind=error.kind,
                filename=filename,
                line=line,
                column=error.column,
            )
        )
    else:
        text = str(error)
    if not error.frames:
        return text
    lines = [text, "Traceback (most recent call last):"]
    for index, frame in enumerate(error.frames):
        logical = frame_filenames[index] if index < len(frame_filenames) else None
        if logical is not None and not logical.startswith("<sericite:"):
            filename, line = logical, frame.line
        elif root_source or logical == "<sericite:vm_0>":
            source_id = frame_sources[index] if index < len(frame_sources) else None
            filename, line = location(frame.line, source_id)
        elif logical is not None:
            filename, line = logical, frame.line
        else:
            filename, line = error.filename, frame.line
        shown_line = "?" if line is None else line
        lines.append(f'  File "{filename}", line {shown_line}, in {frame.function}')
    return "\n".join(lines)
