# VFS and files

`VFSHandle` is a plain-text in-memory workspace handle held by a Python host. It can prepare files in advance, move exclusively into a VM, and be taken back after that VM reaches a terminal state.

A handle is returned by [`SericiteEngine.create_vfs`](01-engine-and-limits.md#sericiteenginecreate_vfs) or [`VMHandle.take_fs`](02-vm.md#vmhandletake_fs) and should not be instantiated directly. The common authority for file paths, directory behavior, and public file errors is the [script files and directories reference](../../scripting/reference/04-files.md). For a complete handoff example, see [Preparing a workspace](../guides/04-workspaces.md).

## Ownership and state

The attachment state of the file tree and the validity of a `VFSHandle` are two different dimensions. A file tree has only two attachment states:

| File tree state | Meaning | Host access |
|---|---|---|
| Detached | Not yet attached to a VM | Through a valid `VFSHandle` |
| Attached | Exclusively owned by one VM | Through that VM's `VMHandle` |

A `VFSHandle` itself is either valid or invalidated. A successful VM creation permanently invalidates the original handle that moved the file tree in; calling its file methods afterward raises `runtime_error`. The file tree attaching to a VM and the old handle becoming invalid are two results of the same commit, not two successive phases of the file tree.

A VFS is attached to at most one VM at any time, and there is no shared write permission. What is transferred is the file tree, not the module cache, virtual IO, local variables, addons, breakpoints, the module resolution root, or accumulated resource usage.

### Moving into a VM

```python
engine.create_root(source=source, fs=workspace)
engine.create_root(entry_file="/main.sericite", fs=workspace)
```

`fs` must be a valid handle in the current engine, and its file tree must be detached. After the whole creation succeeds, the file tree attaches to the new VM and the old handle is permanently invalidated. If entry reading, source compilation, argument, or quota checking fails, the file tree stays detached and the original handle remains usable.

When no `fs` is provided, the root gets an empty VFS. Using `entry_file` requires an explicit `fs`; `source` and `entry_file` cannot be provided together.

### Taking back from a VM

```python
workspace = vm.take_fs()
```

It can only be taken from a VM in `done`, `error`, `resource_exhausted`, or `terminated`. A session waiting for input or paused at a breakpoint can continue executing, or you can `terminate()` first and then take it back.

On success, the file tree becomes detached again and a new valid handle is returned. After taking, the original VM no longer accepts `exec()`, and functions defined by the original VM, as well as host file-management calls made through the original VM, cannot keep accessing the transferred workspace. Failed operations keep ownership and handle validity unchanged; disposing the original VM does not affect the taken-back workspace.

## File and directory methods

`VFSHandle` and the host `VMHandle` provide the following same-named methods. Arguments can be passed by keyword using the names in the table.

| Method | Returns | Detailed contract |
|---|---|---|
| `read_file(path: str)` | `str` | [`read_file`](../../scripting/reference/04-files.md#read_file) |
| `write_file(path: str, text: str)` | `None` | [`write_file`](../../scripting/reference/04-files.md#write_file) |
| `delete_file(path: str)` | `None` | [`delete_file`](../../scripting/reference/04-files.md#delete_file) |
| `rename_file(old_path: str, new_path: str)` | `None` | [`rename_file`](../../scripting/reference/04-files.md#rename_file) |
| `copy_file(source_path: str, destination_path: str)` | `None` | [`copy_file`](../../scripting/reference/04-files.md#copy_file) |
| `make_dir(path: str)` | `None` | [`make_dir`](../../scripting/reference/04-files.md#make_dir) |
| `delete_dir(path: str)` | `None` | [`delete_dir`](../../scripting/reference/04-files.md#delete_dir) |
| `rename_dir(old_path: str, new_path: str)` | `None` | [`rename_dir`](../../scripting/reference/04-files.md#rename_dir) |
| `copy_dir(source_path: str, destination_path: str)` | `None` | [`copy_dir`](../../scripting/reference/04-files.md#copy_dir) |
| `list_dir(path: str)` | `list[str]` | [`list_dir`](../../scripting/reference/04-files.md#list_dir) |
| `path_exists(path: str)` | `bool` | [`path_exists`](../../scripting/reference/04-files.md#path_exists) |

The two kinds of handles operate on different objects:

- `VFSHandle` provides file methods only while the handle is valid and the file tree is detached; an invalid handle or a file tree attached to a VM is rejected with `runtime_error`.
- The host `VMHandle` operates only on the workspace currently attached to that VM; a disposed VM or one whose VFS has been taken is rejected with `runtime_error`.

Host calls do not execute scripts and provide no streaming file handles, byte mode, or real-disk path mapping. Paths are logical paths inside the workspace, and file contents must be strings.

## Limits and metering

Host file management is a trusted channel and does not count against script resource metering, but the file constraints themselves still apply:

- Expanding operations on a `VFSHandle` use the file-count, per-file-size, and total-storage constraints in the engine's default `SericiteLimits`.
- Expanding operations on a `VMHandle` use that VM's corresponding limits.
- File constraints are judged against the current file world before and after the operation, allowing shrinkage and operations that do not expand already-over-limit items further.
- A refused change raises an ordinary `file_limit_error`, does not terminate the VM, and keeps the operation atomic.

These are host management rules; they do not mean scripts can use them to bypass their own execution metering. When a script calls file built-ins or detached-VFS methods inside the script, it is still metered by the caller and by the execution environment the file operation actually belongs to.
