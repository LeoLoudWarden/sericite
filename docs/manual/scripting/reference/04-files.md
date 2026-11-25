# Files and directories

All file contents are `str`; reads and writes are Unicode text, with no binary interface. Scripts cannot access the real disk through these functions.

A detached VFS handle provides the same-named methods with the same path, return, and error contracts as this document; for ownership rules, see [VFS](07-vfs.md).

## Paths

All `path` parameters must be `str`, otherwise `type_error` is raised. Paths resolve from the whole workspace root, not from the current module's directory.

Normalization rules:

- `/` is the root directory; both absolute and relative spellings resolve from this root.
- Repeated `/` and empty path segments are ignored.
- `.` segments are ignored.
- `..` removes the previous segment; going up at the root still stays at the root.
- `list_dir` lists only direct children and returns a sorted list of names without the path prefix.

```text
notes/./draft.txt       -> /notes/draft.txt
/notes/../today.txt     -> /today.txt
../../outside.txt       -> /outside.txt
```

The leading dot of a relative import belongs to module syntax and must not be confused with the path segments here.

## Implicit and explicit directories

`write_file`, `rename_file`, `copy_file`, and directory moves/copies implicitly create missing target parent directories. An implicit directory is removed automatically once it becomes empty.

`make_dir` explicitly creates the target and missing parent directories. An explicit directory is kept even when empty. The root always exists.

All mutating operations complete path and resource checks before committing. A failure leaves no partial file or directory changes; failures and retries still consume execution resources normally.

## `read_file`

```text
read_file(path) -> str
```

Reads all text of the specified file.

| Situation | Error |
|---|---|
| File does not exist | `file_not_found` |
| Path is a directory | `is_directory` |
| Path is not a string | `type_error` |

## `write_file`

```text
write_file(path, text) -> None
```

Writes `text` to the file. If the file exists, its whole content is replaced; if not, the file is created, and missing parent directories are created implicitly. `text` must be `str`.

| Situation | Error |
|---|---|
| Target path is a directory | `is_directory` |
| An intermediate path segment is a file | `not_directory` |
| `text` is not a string | `type_error` |
| File-count, per-file, or total-storage limit refuses the change | `file_limit_error` |

## `delete_file`

```text
delete_file(path) -> None
```

Deletes a file. A missing source raises `file_not_found`, and a directory source raises `is_directory`. Implicit parent directories that become empty are removed automatically as a result.

## `rename_file`

```text
rename_file(old_path, new_path) -> None
```

Renames or moves a file and implicitly creates missing target parent directories.

- Source does not exist: `file_not_found`.
- Source is a directory: `is_directory`.
- Target already exists, whether file or directory: `file_exists`, no overwrite.
- A target intermediate path segment is a file: `not_directory`.
- After normalization the source and target are the same: the target already exists, so `file_exists` is raised.

Renaming does not increase the file count, but path and directory metadata growth may still be subject to the file storage quota.

## `copy_file`

```text
copy_file(source_path, destination_path) -> None
```

Copies the file text and implicitly creates missing target parent directories. Source and target error rules are the same as `rename_file`. Copying adds a file, so it is subject to the file-count, per-file-size, and total-storage limits; the source file stays unchanged.

## `make_dir`

```text
make_dir(path) -> None
```

Explicitly creates the directory and missing parent directories. A target that is already a file or directory raises `file_exists`, including when the target is already a directory created by this function; an intermediate path segment that is a file raises `not_directory`.

The root always exists, so calling it on the root also raises `file_exists`.

## `delete_dir`

```text
delete_dir(path) -> None
```

Recursively deletes the whole directory tree, including explicit empty directories. A missing source raises `file_not_found`, and a file source raises `not_directory`. The root cannot be a deletion source and raises `runtime_error`.

## `rename_dir`

```text
rename_dir(old_path, new_path) -> None
```

Recursively renames or moves a directory tree without overwriting an existing target.

| Situation | Error |
|---|---|
| Source does not exist | `file_not_found` |
| Source is a file | `not_directory` |
| Target already exists | `file_exists` |
| Root as source or target | `runtime_error` |
| Target is inside the source directory | `runtime_error` |
| A target intermediate path segment is a file | `not_directory` |

Target parent directories are created as needed. After the move, the directory keeps its explicit/implicit property and its whole subtree.

## `copy_dir`

```text
copy_dir(source_path, destination_path) -> None
```

Recursively copies the whole directory tree. Path and error rules are the same as `rename_dir`, but the source stays unchanged. Copying adds all files and directories and is subject to the file-count, per-file-size, total-storage, and general resource quotas.

## `list_dir`

```text
list_dir(path) -> list
```

Returns a sorted list of the direct children's names, including both files and directories, without recursing. An empty directory returns `[]`.

A missing directory raises `file_not_found`, and a file path raises `not_directory`.

## `path_exists`

```text
path_exists(path) -> bool
```

Returns `True` when the file or directory exists, otherwise `False`. The root always returns `True`. This function does not distinguish files from directories; a non-string path raises `type_error`.

## File limits and error recovery

A program's file operations are constrained by `max_fs_files`, `max_fs_file_bytes`, and `max_fs_storage_bytes`; see [VM limits](06-vm.md#limits). When these constraints refuse a change, they produce `file_limit_error`.

If several kinds of file failures are handled the same way, use the fixed filter `except file_error`; its members are in the [errors reference](05-errors.md#fixed-filter-groups).
