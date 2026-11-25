# Debugging VMs

A Python host can set breakpoints, step through execution, and read snapshots through `VMHandle`, without inserting extra code into the script being debugged.

## Pausing at statement entry

The following program pauses before the second line executes:

```python
from sericite import SericiteEngine

engine = SericiteEngine()
vm = engine.create_root("x = 1\nx += 1\nprint(x)")
vm.add_breakpoint(2)

assert vm.run() == ""
snapshot = vm.snapshot()
assert snapshot["state"] == "paused"
assert snapshot["locals"]["x"] == 1
assert snapshot["next_line"] == 2
assert snapshot["breakpoint"] == {"line": 2, "path": None}

assert vm.run() == "2\n"
assert vm.snapshot()["state"] == "done"
vm.dispose()
```

A breakpoint hit happens before the statement's first instruction executes, so the second line's `x += 1` has not taken effect yet. `run()` returns normally, raises no exception, and does not run the target script's `except` or `finally`. Calling `run()` again resumes execution and exempts the current breakpoint only once; reaching the same location again in a loop still pauses.

In `add_breakpoint(line, path=None)`:

- `path=None` matches the current main source and its functions;
- an explicit `path` matches the target VM's own entry file or imported modules, with the path normalized by VFS rules;
- foreign code granted by another VM will not accidentally hit the target's breakpoints.

`remove_breakpoint()` idempotently removes a location, and `breakpoints()` returns plain-data dictionaries in the order they were added. Only actual statement entries can be hit; blank lines, comments, non-starting lines of multiline statements, and a `pass` that produces no instruction do not pause. For the detailed binding rules, see the [VM breakpoint reference](../reference/02-vm.md#breakpoints).

## Stepping and snapshots

`step()` executes one statement and returns a snapshot:

```python
vm = engine.create_root("x = 10\nx += 5\nprint(x)")

snapshot = vm.step()
assert snapshot["state"] == "ready"
assert snapshot["locals"]["x"] == 10

snapshot = vm.step()
assert snapshot["locals"]["x"] == 15

snapshot = vm.step()
assert snapshot["state"] == "done"
assert snapshot["stdout"] == "15\n"
vm.dispose()
```

Statements inside functions and breakpoints may affect the actual stopping location. `step_instruction()` executes a single Sericite internal instruction, which is useful for debuggers that need finer granularity; internal instructions are a debugging granularity, not a public operation API in script source.

`snapshot()` does not advance execution; it returns a safe copy of the current execution state: it contains only safe values, no VM handles that could continue operating, and modifying the returned dictionary does not modify the VM. The examples above read `state`, `locals`, `next_line`, `breakpoint`, and `stdout`; host snapshots also provide diagnostic fields such as `vm_id`, `parent_id`, and `depth`.

For the complete fields, error diagnostics, and the safe representation of complex values, see the [VM snapshot reference](../reference/02-vm.md#snapshot).

## Terminating and disposing

`terminate()` marks the current target in `ready`, `waiting_input`, or `paused` as `terminated`, to abandon the current program's execution state; for other states it is a no-op. After a terminal state you can still read snapshots and stdout, or take back the VFS.

`dispose()` destroys the target and all its live descendants and releases live-VM-count slots:

```python
vm = engine.create_root("child = VM('while True:\\n    pass')")
vm.run()
vm.dispose()
vm.dispose()
```

`dispose()` can be called in any state, and repeated calls are no-ops. A running target stops after the current instruction exits safely, without running the target script's `finally`. After disposal the handle is invalid; operations other than repeated disposal raise `runtime_error`.

A VM that becomes completely unreachable is eventually collected automatically, but the timing is not guaranteed. Use `dispose()` when you need a definite release point. Host management actions do not count against the target script's resource metering, but actual execution is still subject to the target's quotas; for the complete lifecycle, see the [VM reference](../reference/02-vm.md#lifecycle).
