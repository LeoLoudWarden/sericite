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

    def location(line: int | None, source_id: int | None) -> tuple[str, int | None]:
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
    if root_source:
        if not error.frames and error._trace_vm_id is None:
            filename, line = current_location(error.line)
        else:
            source_id = (
                frame_sources[-1]
                if error.frames and len(frame_sources) == len(error.frames)
                else None
            )
            filename, line = location(error.line, source_id)
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
        if root_source:
            source_id = frame_sources[index] if index < len(frame_sources) else None
            filename, line = location(frame.line, source_id)
        else:
            filename, line = error.filename, frame.line
        shown_line = "?" if line is None else line
        lines.append(f'  File "{filename}", line {shown_line}, in {frame.function}')
    return "\n".join(lines)
