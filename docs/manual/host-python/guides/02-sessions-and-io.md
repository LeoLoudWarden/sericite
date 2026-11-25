# Execution sessions and virtual IO

A VM represents a persistent execution session, not a one-shot function call. `run()`, input waits, breakpoint pauses, stepping, and repeated `exec()` all drive the same execution space.

## Running more code

`exec()` compiles a new piece of source and executes it in the same module scope:

```python
from sericite import SericiteEngine

engine = SericiteEngine()
vm = engine.create_root("x = 40", argv=["demo", "first"])

assert vm.run() == ""
assert vm.exec("x += 2") == ""
output = vm.exec("print(argv)\nprint(x)")
print(output, end="")
vm.dispose()
```

Expected output:

```text
['demo', 'first']
42
```

The `argv` given at creation is copied as a list of strings, and later `exec()` calls can still access it. Module-level variables, functions, schemas, loaded modules, addons, the VFS, input and output configuration, breakpoints, and accumulated resource usage also persist across deliveries. Only creating another VM starts a brand-new session.

`exec()` discards the old program that has not finished executing and its execution state, so do not use it to recover `waiting_input` or `paused`; for those two states, provide input and continue `run()`, or recover with a stepping method. When compilation fails, the old program and its execution state stay unchanged. For the complete rules, see [`VMHandle.exec`](../reference/02-vm.md#vmhandleexec).

## Cumulative output vs. new output

With the default `buffer_output=True`:

- `run()` returns the currently retained cumulative stdout;
- `exec()` returns only the stdout newly produced by this delivery;
- `stdout()` and the snapshot's `stdout` return the currently retained cumulative text.

```python
vm = engine.create_root('print("first")')
assert vm.run() == "first\n"
assert vm.exec('print("second")') == "second\n"
assert vm.run() == "first\nsecond\n"
assert vm.stdout() == "first\nsecond\n"
vm.dispose()
```

So calling `run()` repeatedly can return text you have already read. When you only need this run's output, record the length before the call, or use the new-output semantics of `exec()` for that task.

## Providing input

### Preset and line-by-line input

`create_root(inputs=...)` accepts an iterable of strings, and `run(inputs)` accepts a list or tuple of strings. You can also use `feed_input()` after the input runs out:

```python
vm = engine.create_root("""
a = input()
b = input()
print(a + b)
""")

assert vm.run(["2"]) == ""
assert vm.snapshot()["state"] == "waiting_input"

vm.feed_input("3")
assert vm.run() == "23\n"
assert vm.snapshot()["state"] == "done"
vm.dispose()
```

An exhausted input queue does not mean the program failed. When there is no more input, the VM keeps its execution state and enters `waiting_input`; later input wakes it, but `feed_input()` itself does not execute the script — you still need to call `run()` or a stepping method.

### Fetching input on demand

`input_provider` is called on demand after the queue is exhausted, which is handy for connecting the host's own data source:

```python
lines = iter(["2", "3"])
vm = engine.create_root(
    "a = input()\nb = input()\nprint(a + b)",
    input_provider=lambda: next(lines, None),
)
assert vm.run() == "23\n"
vm.dispose()
```

When the provider returns a string, that string becomes one line of input; when it returns `None`, raises `EOFError`, or raises `StopIteration`, the VM enters `waiting_input` and can still be resumed later. If the input source is permanently closed, the provider can raise `SericiteError(kind="input_error")` so the script treats it as an ordinary input error.

A provider returning any other type is a callback contract error. An input callback must not re-enter the same VM's driving methods; for the callback exception rules, see the [addon reference](../reference/04-addons.md#exceptions-and-reentrancy).

## Forwarding output live

`output_writer` receives a text chunk after every script `print()` commits output:

```python
chunks = []
vm = engine.create_root(
    'print("a", end="")\nprint("b")',
    output_writer=chunks.append,
)
assert vm.run() == "ab\n"
assert chunks == ["a", "b\n"]
vm.dispose()
```

The text the writer receives includes this call's separator and `end`. Output first goes through metering, the limit check, and optional buffering, and then to the writer; text rejected by the output limit is not forwarded.

If the host will consume all output immediately and does not want root to keep historical text, disable buffering:

```python
chunks = []
vm = engine.create_root(
    'print("live")',
    output_writer=chunks.append,
    buffer_output=False,
)
assert vm.run() == ""
assert vm.stdout() == ""
assert chunks == ["live\n"]
vm.dispose()
```

Disabling buffering does not disable output metering, and it does not affect the writer receiving text. A root's writer only handles the root's own output; child VMs do not inherit it automatically. To forward descendant output, each layer's script should configure its own `output_writer` explicitly; see [script VM output rules](../../scripting/reference/06-vm.md#output-forwarding-and-buffering).

The host writer and input provider are both trusted callbacks; their execution time, memory, blocking, and external side effects are managed by the host. To observe the whole VM tree without connecting a writer at each layer, use the [observation interface](06-observation.md).
