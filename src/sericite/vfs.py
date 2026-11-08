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
    __slots__ = (
        "directories",
        "directory_count",
        "directory_name_chars",
        "file_count",
        "file_path_chars",
        "file_text_chars",
        "files",
        "name_chars",
    )

    def __init__(self) -> None:
        self.directories: dict[str, _Directory] = {}
        self.files: set[str] = set()
        self.name_chars = 0
        self.file_count = 0
        self.file_text_chars = 0
        self.file_path_chars = 0
        self.directory_count = 0
        self.directory_name_chars = 0


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

    def rename_work(self, old_path: object, new_path: object) -> int:
        return self.path_work(old_path) + self.path_work(new_path)

    def rename_allocation(self, old_path: object, new_path: object) -> int:
        if not isinstance(new_path, str):
            return 0
        return self._write_allocation(normalize_path(new_path), "")

    def copy_work(self, source_path: object, destination_path: object) -> int:
        text = ""
        if isinstance(source_path, str):
            text = self._files.get(normalize_path(source_path), "")
        return (
            self.path_work(source_path) + self.path_work(destination_path) + len(text)
        )

    def copy_allocation(self, source_path: object, destination_path: object) -> int:
        text = ""
        if isinstance(source_path, str):
            text = self._files.get(normalize_path(source_path), "")
        if not isinstance(destination_path, str):
            return len(text) * 4
        return self._write_allocation(normalize_path(destination_path), text)

    def delete_dir_work(self, path: object) -> int:
        if not isinstance(path, str):
            return 0
        normalized = normalize_path(path)
        directory = self._find_directory(normalized)
        if directory is None:
            return len(path)
        return (
            len(path)
            + directory.file_path_chars
            + directory.directory_count
            + directory.directory_name_chars
        )

    def _directory_operation_shape(
        self, source_path: object, destination_path: object
    ) -> tuple[_Directory, int, int] | None:
        if not isinstance(source_path, str) or not isinstance(destination_path, str):
            return None
        source = normalize_path(source_path)
        destination = normalize_path(destination_path)
        directory = self._find_directory(source)
        if directory is None:
            return None
        new_path_chars = directory.file_path_chars + directory.file_count * (
            len(destination) - len(source)
        )
        destination_name = self._segments(destination)[-1] if destination != "/" else ""
        directory_allocation = (
            self._missing_directory_allocation(destination)
            + (directory.directory_count + 1) * 64
            + (directory.directory_name_chars + len(destination_name)) * 4
        )
        return directory, new_path_chars, directory_allocation

    def rename_dir_work(self, old_path: object, new_path: object) -> int:
        shape = self._directory_operation_shape(old_path, new_path)
        base = self.path_work(old_path) + self.path_work(new_path)
        if shape is None:
            return base
        directory, new_path_chars, _ = shape
        return (
            base
            + 2 * (directory.file_path_chars + new_path_chars)
            + directory.directory_count
            + directory.directory_name_chars
        )

    def rename_dir_allocation(self, old_path: object, new_path: object) -> int:
        shape = self._directory_operation_shape(old_path, new_path)
        if shape is None:
            return 0
        directory, new_path_chars, directory_allocation = shape
        return directory.file_count * 64 + new_path_chars * 4 + directory_allocation

    def copy_dir_work(self, source_path: object, destination_path: object) -> int:
        shape = self._directory_operation_shape(source_path, destination_path)
        base = self.path_work(source_path) + self.path_work(destination_path)
        if shape is None:
            return base
        directory, new_path_chars, _ = shape
        return (
            base
            + 2 * (directory.file_path_chars + new_path_chars)
            + directory.file_text_chars
            + directory.directory_count
            + directory.directory_name_chars
        )

    def copy_dir_allocation(self, source_path: object, destination_path: object) -> int:
        shape = self._directory_operation_shape(source_path, destination_path)
        if shape is None:
            return 0
        directory, new_path_chars, directory_allocation = shape
        return (
            directory.file_count * 64
            + new_path_chars * 4
            + directory.file_text_chars * 4
            + directory_allocation
        )

    def _validate_write(
        self,
        path: object,
        text: object,
        *,
        overwrite: bool = True,
        require_file_slot: bool = True,
    ) -> str:
        normalized = normalize_path(path)
        if not isinstance(text, str):
            raise SericiteError("file content must be a string", kind="type_error")
        if normalized == "/" or self._find_directory(normalized) is not None:
            raise SericiteError(f"is a directory: {path}", kind="is_directory")
        if not overwrite and normalized in self._files:
            raise SericiteError(f"file already exists: {path}", kind="file_exists")
        size = len(text.encode("utf-8"))
        if size > self._max_file_bytes:
            raise SericiteError("file size limit exceeded", kind="resource_exhausted")
        if (
            require_file_slot
            and normalized not in self._files
            and len(self._files) >= self._max_files
        ):
            raise SericiteError("file count limit exceeded", kind="resource_exhausted")
        return normalized

    def _validate_new_file(
        self, path: object, text: str, *, require_file_slot: bool = True
    ) -> str:
        return self._validate_write(
            path, text, overwrite=False, require_file_slot=require_file_slot
        )

    def _require_file(self, path: object) -> tuple[str, str]:
        normalized = normalize_path(path)
        if normalized in self._files:
            return normalized, self._files[normalized]
        if self._find_directory(normalized) is not None:
            raise SericiteError(f"is a directory: {path}", kind="is_directory")
        raise SericiteError(f"no such file: {path}", kind="file_not_found")

    def _require_directory(self, path: object) -> tuple[str, _Directory]:
        normalized = normalize_path(path)
        if normalized in self._files:
            raise SericiteError(f"not a directory: {path}", kind="not_directory")
        directory = self._find_directory(normalized)
        if directory is None:
            raise SericiteError(f"no such directory: {path}", kind="file_not_found")
        if normalized == "/":
            raise SericiteError(
                "root directory cannot be modified", kind="runtime_error"
            )
        return normalized, directory

    def _validate_directory_destination(
        self, source: str, destination_path: object
    ) -> str:
        destination = normalize_path(destination_path)
        if destination == "/":
            raise SericiteError(
                "root directory cannot be modified", kind="runtime_error"
            )
        if destination.startswith(source + "/"):
            raise SericiteError(
                "cannot move or copy a directory into itself", kind="runtime_error"
            )
        if destination in self._files or self._find_directory(destination) is not None:
            raise SericiteError(
                f"path already exists: {destination_path}", kind="file_exists"
            )
        return destination

    def _directory_files(
        self, normalized: str, directory: _Directory
    ) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        pending = [(normalized, directory)]
        while pending:
            path, current = pending.pop()
            for name in current.files:
                file_path = f"{path}/{name}"
                result.append((file_path, self._files[file_path]))
            for name, child in current.directories.items():
                pending.append((f"{path}/{name}", child))
        return result

    def _commit_write(self, normalized: str, text: str) -> None:
        is_new = normalized not in self._files
        previous_text = self._files.get(normalized, "")
        self._files[normalized] = text
        segments = self._segments(normalized)
        directory = self._root
        ancestors = [directory]
        created: list[tuple[int, str]] = []
        for index, segment in enumerate(segments[:-1]):
            child = directory.directories.get(segment)
            if child is None:
                child = _Directory()
                directory.directories[segment] = child
                directory.name_chars += len(segment)
                created.append((index, segment))
            directory = child
            ancestors.append(directory)
        if is_new:
            directory.files.add(segments[-1])
            directory.name_chars += len(segments[-1])
        created_counts = [0] * len(ancestors)
        created_chars = [0] * len(ancestors)
        for index, name in created:
            created_counts[index] = 1
            created_chars[index] = len(name)
        directory_count = 0
        directory_name_chars = 0
        for index in reversed(range(len(ancestors))):
            directory_count += created_counts[index]
            directory_name_chars += created_chars[index]
            ancestor = ancestors[index]
            ancestor.directory_count += directory_count
            ancestor.directory_name_chars += directory_name_chars
            if is_new:
                ancestor.file_count += 1
                ancestor.file_path_chars += len(normalized)
            ancestor.file_text_chars += len(text) - len(previous_text)

    def _commit_delete(self, normalized: str) -> None:
        text = self._files[normalized]
        segments = self._segments(normalized)
        directory = self._root
        ancestors = [directory]
        parents: list[tuple[_Directory, str, _Directory]] = []
        for segment in segments[:-1]:
            child = directory.directories[segment]
            parents.append((directory, segment, child))
            directory = child
            ancestors.append(directory)
        name = segments[-1]
        del self._files[normalized]
        directory.files.remove(name)
        directory.name_chars -= len(name)
        pruned: list[tuple[_Directory, str, _Directory]] = []
        for parent, segment, child in reversed(parents):
            if child.files or child.directories:
                break
            del parent.directories[segment]
            parent.name_chars -= len(segment)
            pruned.append((parent, segment, child))
        pruned_chars = sum(len(item[1]) for item in pruned)
        for ancestor in ancestors:
            ancestor.file_count -= 1
            ancestor.file_text_chars -= len(text)
            ancestor.file_path_chars -= len(normalized)
            ancestor.directory_count -= len(pruned)
            ancestor.directory_name_chars -= pruned_chars

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

    def delete_file(self, path: object) -> None:
        normalized, _ = self._require_file(path)
        self._commit_delete(normalized)

    def rename_file(
        self, old_path: object, new_path: object, *, permit: AllocationPermit
    ) -> None:
        old_normalized, text = self._require_file(old_path)
        new_normalized = self._validate_new_file(
            new_path, text, require_file_slot=False
        )
        permit.consume(self, "write", self._write_allocation(new_normalized, ""))
        self._commit_write(new_normalized, text)
        self._commit_delete(old_normalized)

    def rename_file_trusted(self, old_path: object, new_path: object) -> None:
        old_normalized, text = self._require_file(old_path)
        new_normalized = self._validate_new_file(
            new_path, text, require_file_slot=False
        )
        self._commit_write(new_normalized, text)
        self._commit_delete(old_normalized)

    def copy_file(
        self,
        source_path: object,
        destination_path: object,
        *,
        permit: AllocationPermit,
    ) -> None:
        _, text = self._require_file(source_path)
        destination_normalized = self._validate_new_file(destination_path, text)
        permit.consume(
            self, "write", self._write_allocation(destination_normalized, text)
        )
        self._commit_write(destination_normalized, text)

    def copy_file_trusted(self, source_path: object, destination_path: object) -> None:
        _, text = self._require_file(source_path)
        destination_normalized = self._validate_new_file(destination_path, text)
        self._commit_write(destination_normalized, text)

    def delete_dir(self, path: object) -> None:
        normalized, directory = self._require_directory(path)
        for file_path, _ in self._directory_files(normalized, directory):
            self._commit_delete(file_path)

    def _rename_dir_plan(
        self, old_path: object, new_path: object
    ) -> tuple[str, str, list[tuple[str, str]]]:
        old_normalized, directory = self._require_directory(old_path)
        new_normalized = self._validate_directory_destination(old_normalized, new_path)
        files = self._directory_files(old_normalized, directory)
        return old_normalized, new_normalized, files

    def rename_dir(
        self, old_path: object, new_path: object, *, permit: AllocationPermit
    ) -> None:
        old_normalized, new_normalized, files = self._rename_dir_plan(
            old_path, new_path
        )
        permit.consume(
            self, "write", self.rename_dir_allocation(old_normalized, new_normalized)
        )
        for file_path, text in files:
            suffix = file_path[len(old_normalized) :]
            self._commit_write(new_normalized + suffix, text)
        for file_path, _ in files:
            self._commit_delete(file_path)

    def rename_dir_trusted(self, old_path: object, new_path: object) -> None:
        old_normalized, new_normalized, files = self._rename_dir_plan(
            old_path, new_path
        )
        for file_path, text in files:
            suffix = file_path[len(old_normalized) :]
            self._commit_write(new_normalized + suffix, text)
        for file_path, _ in files:
            self._commit_delete(file_path)

    def _copy_dir_plan(
        self, source_path: object, destination_path: object
    ) -> tuple[str, str, list[tuple[str, str]]]:
        source_normalized, directory = self._require_directory(source_path)
        destination_normalized = self._validate_directory_destination(
            source_normalized, destination_path
        )
        if len(self._files) + directory.file_count > self._max_files:
            raise SericiteError("file count limit exceeded", kind="resource_exhausted")
        files = self._directory_files(source_normalized, directory)
        return source_normalized, destination_normalized, files

    def copy_dir(
        self,
        source_path: object,
        destination_path: object,
        *,
        permit: AllocationPermit,
    ) -> None:
        source_normalized, destination_normalized, files = self._copy_dir_plan(
            source_path, destination_path
        )
        permit.consume(
            self,
            "write",
            self.copy_dir_allocation(source_normalized, destination_normalized),
        )
        for file_path, text in files:
            suffix = file_path[len(source_normalized) :]
            self._commit_write(destination_normalized + suffix, text)

    def copy_dir_trusted(self, source_path: object, destination_path: object) -> None:
        source_normalized, destination_normalized, files = self._copy_dir_plan(
            source_path, destination_path
        )
        for file_path, text in files:
            suffix = file_path[len(source_normalized) :]
            self._commit_write(destination_normalized + suffix, text)

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
