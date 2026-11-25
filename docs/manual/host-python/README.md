# Python Host Manual

This section collects the guides and API reference for embedding Sericite in a Python program, for developers who need an existing application to create, configure, drive, and inspect VMs.

Sericite-PY is the Python reference implementation of the Sericite language. Sericite source borrows part of Python's syntax, but it is compiled into Sericite's own instruction stream and is never executed through Python's `exec()` or `eval()`. The language itself does not depend on Python; this manual describes the public interface of the current Python host.

## Installation and preparation

The runtime environment requires Python ≥ 3.12. Install the distribution:

```bash
pip install sericite
```

The distribution name and the import package are both `sericite`, and the engine has no third-party runtime dependencies.

In this manual's examples, the outer code is Python and the string passed to `create_root()` is Sericite source. To write these scripts, see the [scripting manual](../scripting/README.md); to run programs from a terminal, prepare project files, or write a trusted addon configuration, see the [CLI manual](../cli/README.md).

## Guides

| Page | Contents |
|---|---|
| [Quick start](guides/01-quick-start.md) | Create an engine and a root VM, run the first piece of code, get output, and release resources |
| [Execution sessions and virtual IO](guides/02-sessions-and-io.md) | Keep session state, run more code, provide input, forward and buffer output |
| [Granting host capabilities](guides/03-addons.md) | Provide addons, pass pure data, translate callback errors, manage capability boundaries |
| [Preparing a workspace](guides/04-workspaces.md) | Preset files and modules, choose an entry, transfer a VFS exclusively between sessions |
| [Debugging VMs](guides/05-debugging.md) | Use breakpoints, stepping, snapshots, termination, and disposal |
| [Observing VM activity](guides/06-observation.md) | Subscribe to events across the whole VM tree, read read-only snapshots by VM ID |

When embedding for the first time, read the quick start, then pick later guides by task. When you need to grant host functions, reading the addon guide together with the security model is recommended.

## API reference

| Page | Contents |
|---|---|
| [Engine and limits](reference/01-engine-and-limits.md) | `SericiteEngine`, root creation, VFS creation, `SericiteLimits` |
| [VM handle](reference/02-vm.md) | Driving, input, debugging, snapshots, lifecycle, and host management methods of `VMHandle` |
| [VFS and files](reference/03-vfs-and-files.md) | `VFSHandle` ownership, and the 11 file and directory methods of the VM/VFS handles |
| [addon](reference/04-addons.md) | Grant names, data boundary, callback exceptions, reentrancy, and cost responsibility |
| [Observation](reference/05-observation.md) | `SericiteObservation`, `SericiteEvent`, event payloads, and delivery rules |
| [Errors and diagnostics](reference/06-errors.md) | `SericiteError`, `SericiteFrame`, call stacks, and host error handling |

## Security boundary

Sericite is responsible for language-level isolation and resource governance; the host is responsible for addon argument validation, execution time, memory, external side effects, and secret protection. When executing untrusted code in production, tighten quotas explicitly, grant only necessary capabilities, and add operating-system-level isolation such as a separate process or container. For the complete division of responsibilities, see the [security model](../../security.md).
