# VFS

A VFS is a plain-text in-memory workspace handle. `VFS()` creates a workspace detached from a VM; you can write files into it in advance, hand it exclusively to a VM, and take the workspace back to keep reading after the VM reaches a terminal state.

For file paths, method parameters, returns, and file errors, see [files and directories](04-files.md).

## Construction

```text
VFS() -> VFS
```

Creates an empty detached workspace. The root directory `/` always exists. The constructor takes no arguments.

## Ownership and lifecycle

A VFS handle is in one of the following three states:

| State | Meaning | Can file methods be called |
|---|---|---|
| Detached | not yet attached to a VM and not consumed by an old handle | Yes |
| Attached | exclusively owned by a VM | No; accessed through that VM's file built-ins |
| Consumed | the old handle was invalidated when a VM was successfully created | No |

A VFS is attached to at most one VM at any time and does not share write permission. What is transferred is the file tree, not the module cache, input/output, local variables, the module resolution root, or the execution account.

### Moving into a VM

```text
VM(source, fs=workspace) -> VM
VM(entry_file=path, fs=workspace) -> VM
```

`fs` must be a valid detached VFS. After the whole creation succeeds, the workspace attaches to the new VM and the original handle permanently becomes the consumed state. Using the original handle afterward raises `runtime_error`.

A failed creation does not consume the VFS: when source or entry compilation fails, entry reading fails, or quota checking fails, the workspace still belongs to the original detached handle. `entry_file` must be used explicitly together with `fs`.

### Taking back from a VM

```text
vm.take_fs() -> VFS
```

Returns a new detached handle; the original VM loses file access and no longer accepts `exec()`. The VFS can only be taken from a VM in `done`, `error`, `resource_exhausted`, or `terminated`.

On failure, ownership is unchanged. After taking, you can dispose the original VM without affecting the detached VFS. For the complete target-state constraints, see [`VM.take_fs`](06-vm.md#vmtake_fs).

## File methods

The following methods can only be called on a detached, unconsumed handle:

| Method | Returns | Detailed contract |
|---|---|---|
| `vfs.read_file(path)` | `str` | [`read_file`](04-files.md#read_file) |
| `vfs.write_file(path, text)` | `None` | [`write_file`](04-files.md#write_file) |
| `vfs.delete_file(path)` | `None` | [`delete_file`](04-files.md#delete_file) |
| `vfs.rename_file(old_path, new_path)` | `None` | [`rename_file`](04-files.md#rename_file) |
| `vfs.copy_file(source_path, destination_path)` | `None` | [`copy_file`](04-files.md#copy_file) |
| `vfs.make_dir(path)` | `None` | [`make_dir`](04-files.md#make_dir) |
| `vfs.delete_dir(path)` | `None` | [`delete_dir`](04-files.md#delete_dir) |
| `vfs.rename_dir(old_path, new_path)` | `None` | [`rename_dir`](04-files.md#rename_dir) |
| `vfs.copy_dir(source_path, destination_path)` | `None` | [`copy_dir`](04-files.md#copy_dir) |
| `vfs.list_dir(path)` | `list` | [`list_dir`](04-files.md#list_dir) |
| `vfs.path_exists(path)` | `bool` | [`path_exists`](04-files.md#path_exists) |

Arguments can be passed by keyword using the names in the table. A wrong argument shape raises `type_error`. File operations are still subject to the caller's general execution resource constraints; file-count, size, and storage constraints take effect according to the actual call chain.

A VFS has no handle-style streaming interface and no arbitrary attributes. Unlisted methods raise `attribute_error`.

## Complete handoff example

```python
workspace = VFS()
workspace.write_file("/input.txt", "hello")
workspace.write_file(
    "/main.sericite",
    "text = read_file(\"/input.txt\")\n"
    "write_file(\"/result.txt\", text + \"!\")\n",
)

program = VM(entry_file="/main.sericite", fs=workspace)
program.run()

result = program.take_fs()
print(result.read_file("/result.txt"))
program.dispose()
print(result.path_exists("/result.txt"))
```

```text
hello!
True
```

The taken-back `result` is a new valid detached handle; the `workspace` used when creating the VM has been consumed and can no longer be used to access files.
