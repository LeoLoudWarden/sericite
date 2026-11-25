# Preparing a workspace

Every VM's file operations act on its own virtual file system (VFS). A Python host can prepare files and modules in advance, move a complete workspace into a VM, and take the results back after the session ends.

## Running a project from a workspace entry

The following example prepares an input file, a module, and an entry file:

```python
from sericite import SericiteEngine

engine = SericiteEngine()
fs = engine.create_vfs()
fs.write_file("/input.txt", "hello")
fs.write_file("/util.sericite", "suffix = '!'\n")
fs.write_file(
    "/main.sericite",
    "import util\n"
    "text = read_file('/input.txt')\n"
    "write_file('/result.txt', text + util.suffix)\n",
)

vm = engine.create_root(entry_file="/main.sericite", fs=fs)
assert vm.run() == ""

fs = vm.take_fs()
assert fs.read_file("/result.txt") == "hello!"
vm.dispose()
assert fs.path_exists("/result.txt")
```

`entry_file` must be provided together with `fs`. The engine reads and compiles the entry from the workspace and uses the entry's directory as the module resolution root; file operations such as `read_file()` and `write_file()` are still rooted at the workspace root. So the example's `import util` reads `/util.sericite` and does not search Python's module path or the real disk.

If you use `source` directly and also provide `fs`, modules resolve from the workspace root. `source` and `entry_file` must be used exactly one at a time; for the detailed parameters, see [Engine and limits](../reference/01-engine-and-limits.md#sericiteenginecreate_root).

## Workspace ownership and handles

A VFS is not a shared object that multiple execution sessions read and write together. To understand transfer, distinguish two questions:

- **Where the file tree is attached**: a detached file tree is operated on by the host through a valid `VFSHandle`; an attached file tree is owned exclusively by one VM, and both the script and the host access it through that VM.
- **Whether a host handle is still valid**: after a file tree is successfully moved into a VM, the original `VFSHandle` becomes invalid; taking the file tree back later yields a new handle.

`create_root(..., fs=fs)` commits the file-tree attachment and invalidates the original handle only after the whole creation succeeds. If source compilation, entry reading, or argument validation fails, the file tree stays detached and the original handle remains usable. After a successful creation, access files through the VM and do not keep using the original `fs`.

`take_fs()` on a terminal VM atomically takes the file tree out, detaches it again, and returns a new valid handle. The allowed states are `done`, `error`, `resource_exhausted`, and `terminated`; if the program is still waiting for input or paused, you can continue execution first, or explicitly `terminate()` before taking it back.

After taking, the original VM can still read snapshots and stdout and can be disposed, but it loses file access and no longer accepts `exec()`. Disposing the original VM does not affect the workspace that was already taken back. Failed operations do not change ownership or handle validity.

Only the file tree is transferred. The module cache, local variables, virtual IO, addons, breakpoints, the module resolution root, and accumulated resource usage all remain part of the original session. If you modify a module file after taking the workspace back and then move the workspace into a new VM, the new session re-imports the modified code.

## The host can manage files directly

Both `VFSHandle` and the host `VMHandle` provide file and directory methods. For example, after the session ends and before taking the workspace back, the host can inspect or add files:

```python
vm.write_file("/host-note.txt", "prepared by host")
assert vm.read_file("/host-note.txt") == "prepared by host"
```

The difference between the two kinds of handles:

- `VFSHandle` operates only on a workspace in the detached state;
- `VMHandle` operates on the workspace currently attached to that VM.

These are trusted host management channels and do not count against script resource metering, but the file-count, per-file-size, and total-storage limits still apply. Script-side VM handles do not provide these file proxies; a script can only operate on the current session's files or use an explicitly held detached VFS.

For all methods, path rules, and errors, see the [VFS and files reference](../reference/03-vfs-and-files.md); the common path and directory behavior is defined by the [script files reference](../../scripting/reference/04-files.md).
