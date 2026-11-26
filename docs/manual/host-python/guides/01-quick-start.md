# Quick start

This chapter creates a root VM inside a Python program, runs a piece of Sericite source, and gets its virtual output.

## Running your first code

After installing `sericite`, create the following Python program:

```python
from sericite import SericiteEngine

engine = SericiteEngine()
vm = engine.create_root("""
name = input()
print("hello", name)
""")

output = vm.run(["world"])
print(output, end="")
print("state:", vm.snapshot()["state"])
vm.dispose()
```

Expected output:

```text
hello world
state: done
```

`create_root()` compiles the source and returns a `VMHandle`. `run(["world"])` provides one line of input to the script and then drives the VM until the program finishes, waits for more input, hits a breakpoint, or fails.

Here `print()` writes to the VM's own virtual stdout, not automatically to the Python process's standard output. By default the engine retains this text, so `run()` returns `"hello world\n"`, and the example then displays it with Python's `print()`.

## Root VMs and the engine

One `SericiteEngine` can create and manage multiple VMs. A VM created directly by the host is a root VM; the root or other scripts can also create descendants through the Sericite built-in `VM()`. All levels are executed by the same engine rather than embedding another Python interpreter at each level.

`VMHandle` is the host's entry point for controlling that VM and is bound to the engine that created it. While you hold the handle, you can keep executing code, provide input, read snapshots, set breakpoints, or dispose the VM. For creating and driving child VMs from inside a script, see [isolated execution spaces](../../scripting/guides/06-vm.md).

A new VM has, by default:

- its own virtual input and output;
- an empty plain-text in-memory file system;
- the ability to create its own child VMs.

It does not automatically see Python variables, the real disk, the network, or other objects in the host process. `argv` is the root's initial module variable, an empty list by default; other capabilities must be configured or granted explicitly.

## Source and workspace entry

The most direct approach is to pass the source string to `source`:

```python
vm = engine.create_root("print(6 * 7)")
assert vm.run() == "42\n"
vm.dispose()
```

`source` and `entry_file` must be used exactly one at a time. `entry_file` reads the entry from an explicitly provided VFS; for preparing a multi-file workspace and transferring VFS ownership, see [Preparing a workspace](04-workspaces.md), and for the complete creation parameters see [Engine and limits](../reference/01-engine-and-limits.md).

## Handling failures

When a script fails to compile or run, the creation or driving method raises `SericiteError` into Python. `kind` is the stable error category and `message` is a readable diagnostic:

```python
from sericite import SericiteEngine, SericiteError

engine = SericiteEngine()
vm = engine.create_root("raise 'failed'")
try:
    vm.run()
except SericiteError as error:
    print(error.kind, error.message)
finally:
    vm.dispose()
```

Expected output:

```text
raise_error failed
```

`dispose()` in `finally` ensures that both the success path and the error path release the VM and its live descendants. A VM that becomes completely unreachable is eventually collected by Python's garbage collector, but the timing is not guaranteed; dispose explicitly when you need a definite release point.

## Next steps

- To deliver code multiple times or handle input waits, read [Execution sessions and virtual IO](02-sessions-and-io.md).
- To call Python functions, read [Granting host capabilities](03-addons.md).
- Before executing code that is not fully trusted, read the manual's [safety essentials](../../README.md#safety-essentials) and set [execution limits](../reference/01-engine-and-limits.md#sericitelimits) for the task.
