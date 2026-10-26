from __future__ import annotations

from .accounting import AllocationPermit
from .errors import SericiteError


def normalize_path(path: object) -> str:
    if not isinstance(path, str):
        raise SericiteError("path must be a string", kind="type_error")
    parts: list[str] = []
    for segment in path.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    return "/" + "/".join(parts)


class _Directory:
    __slots__ = ("directories", "files", "name_chars")

    def __init__(self) -> None:
        self.directories: dict[str, _Directory] = {}
        self.files: set[str] = set()
        self.name_chars = 0


class VirtualFileSystem:
    """A private text-only VFS whose directory tree stores each direct-child name once."""

    def __init__(self, max_files: int = 1000, max_file_bytes: int = 1_048_576) -> None:
        self._files: dict[str, str] = {}
        self._root = _Directory()
        self._max_files = max_files
        self._max_file_bytes = max_file_bytes

    @staticmethod
    def path_work(path: object) -> int:
        return len(path) if isinstance(path, str) else 0

    @staticmethod
    def _segments(path: str) -> list[str]:
        return [] if path == "/" else path[1:].split("/")

    def _find_directory(self, path: str) -> _Directory | None:
        directory = self._root
        for segment in self._segments(path):
            directory = directory.directories.get(segment)
            if directory is None:
                return None
        return directory

    def list_dir_work(self, path: object) -> int:
        if not isinstance(path, str):
            return 0
        directory = self._find_directory(normalize_path(path))
        if directory is None:
            return len(path)
        count = len(directory.directories) + len(directory.files)
        scale = max(1, count.bit_length())
        return len(path) + (count + directory.name_chars) * scale

    def write_work(self, path: object, text: object) -> int:
        return self.path_work(path) + (len(text) if isinstance(text, str) else 0)

    def _missing_directory_allocation(self, path: str) -> int:
        segments = self._segments(path)[:-1]
        directory = self._root
        for index, segment in enumerate(segments):
            child = directory.directories.get(segment)
            if child is None:
                return sum(64 + len(name) * 4 for name in segments[index:])
            directory = child
        return 0

    def _write_allocation(self, normalized: str, text: str) -> int:
        if normalized in self._files:
            return len(text) * 4
        return (
            len(text) * 4
            + 64
            + len(normalized) * 4
            + self._missing_directory_allocation(normalized)
        )

    def write_allocation(self, path: object, text: object) -> int:
        if not isinstance(text, str):
            return 0
        if not isinstance(path, str):
            return len(text) * 4
        return self._write_allocation(normalize_path(path), text)

    def _validate_write(self, path: object, text: object) -> str:
        normalized = normalize_path(path)
        if not isinstance(text, str):
            raise SericiteError("file content must be a string", kind="type_error")
        if normalized == "/" or self._find_directory(normalized) is not None:
            raise SericiteError(f"is a directory: {path}", kind="is_directory")
        size = len(text.encode("utf-8"))
        if size > self._max_file_bytes:
            raise SericiteError("file size limit exceeded", kind="resource_exhausted")
        if normalized not in self._files and len(self._files) >= self._max_files:
            raise SericiteError("file count limit exceeded", kind="resource_exhausted")
        return normalized

    def _commit_write(self, normalized: str, text: str) -> None:
        is_new = normalized not in self._files
        self._files[normalized] = text
        if not is_new:
            return
        segments = self._segments(normalized)
        directory = self._root
        for segment in segments[:-1]:
            child = directory.directories.get(segment)
            if child is None:
                child = _Directory()
                directory.directories[segment] = child
                directory.name_chars += len(segment)
            directory = child
        directory.files.add(segments[-1])
        directory.name_chars += len(segments[-1])

    def write_file(
        self, path: object, text: object, *, permit: AllocationPermit
    ) -> None:
        normalized = self._validate_write(path, text)
        permit.consume(self, "write", self._write_allocation(normalized, text))
        self._commit_write(normalized, text)

    def write_file_trusted(self, path: object, text: object) -> None:
        """Preconfigure a file on behalf of the trusted host, outside script accounting."""
        normalized = self._validate_write(path, text)
        self._commit_write(normalized, text)

    def read_file(self, path: object) -> str:
        normalized = normalize_path(path)
        if normalized in self._files:
            return self._files[normalized]
        if self._find_directory(normalized) is not None:
            raise SericiteError(f"is a directory: {path}", kind="is_directory")
        raise SericiteError(f"no such file: {path}", kind="file_not_found")

    def list_dir(self, path: object) -> list[str]:
        normalized = normalize_path(path)
        if normalized in self._files:
            raise SericiteError(f"not a directory: {path}", kind="not_directory")
        directory = self._find_directory(normalized)
        if directory is None:
            raise SericiteError(f"no such directory: {path}", kind="file_not_found")
        return sorted((*directory.directories, *directory.files))

    def path_exists(self, path: object) -> bool:
        normalized = normalize_path(path)
        return normalized in self._files or self._find_directory(normalized) is not None
