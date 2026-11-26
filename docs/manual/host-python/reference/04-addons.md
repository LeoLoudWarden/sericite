# addon

An addon is a capability that a Python host explicitly grants to a root VM. The host provides functions through `create_root(addons=...)`, and the script imports them explicitly through the preloaded module `__addon__`.

This document defines only the boundary between Python and the VM. For the definer's environment, closures, and cross-VM reference rules when a script grants Sericite functions to a lower layer, see the [script VM reference](../../scripting/reference/06-vm.md#addon-granting).

## Granting functions

```python
engine.create_root(
    source,
    addons={"public_name": callback},
)
```

`addons` must be `None` or a dictionary. Each key is an import name and each value must be callable; the whole table is validated together when the root is created, and an invalid dictionary shape, name, or value raises `type_error`.

An import name must be a valid string identifier that does not start with `__`. It may collide with a built-in or with `argv`, but a built-in rebinding caused by a direct import is rejected by the compiler, so the receiver should use an alias:

```python
from __addon__ import len as host_len
```

`__addon__` is not a VFS file and provides no arbitrary Python module search. Every source module that needs an addon writes:

```python
from __addon__ import public_name
```

Import aliases, retention across `exec()`, and further re-granting by the script to a child program are supported. A name that was not granted is reported with `import_error`. Addons are no longer injected directly into the global namespace; there is no name fallback that omits the import.

A Python callback can receive positional arguments, keyword arguments, and variadic arguments expanded by the script; the actual call forms it accepts are up to that Python callable. The engine copies and validates the arguments first and only then calls the callback; an argument boundary failure does not call it.

## Data boundary

Arguments and return values are deep-copied in both directions. Only the following built-in types themselves and their recursive combinations are allowed; same-named subclasses or arbitrary Python objects are not automatically whitelisted:

| Category | Allowed types |
|---|---|
| Null and scalars | `None`, `bool`, `int`, `float`, `str` |
| Containers | `list`, `dict`, `tuple` |

- list/tuple types are preserved in both directions.
- dict keys and values are both subject to the boundary; keys of a dict returned by the host can only be `str`, `int`, `float`, `bool`, or `None`.
- Nested containers are copied item by item; the script and the host do not share mutable containers.
- records/schemas, modules, VM/VFS handles, functions, and other objects cannot cross the host boundary.
- To hand a record to the host, first `unwrap()` it to a dict inside the script.

Return values are also subject to the current VM's string-character count, integer bit width, list/tuple size, dict size, total node count, and nesting depth. The copying work for arguments and return values is charged to the engine by node, and returned structures are also subject to the memory quota.

Violating the data or copy contract uses the catchable `addon_error`.

## Exceptions and reentrancy

### Callback failure

| Callback behavior | Engine behavior |
|---|---|
| Returns normally | Validates and deep-copies the return value |
| Raises `SericiteError` with a specific contract kind | Propagates with the original kind; script catchability follows the language rules |
| Raises `SericiteError(kind="resource_exhausted")` | Treated as the current VM's own quota exhaustion, entering the corresponding terminal state; not script-catchable |
| Raises an ordinary `Exception` outside the contract | The current VM terminates with an uncatchable `host_error`; the host receives `SericiteError` |
| Raises other `BaseException` such as `KeyboardInterrupt` or `SystemExit` | Passes through the driving call unchanged, handed back to the host |

A contract kind should come from an actual error name in the [script error registry](../../scripting/reference/05-errors.md#catchable-kinds). `file_error` and `lookup_error` are compile-time filter groups, not actual kinds an addon callback should raise. `host_error` and `internal_error` describe governance or implementation failures and should not be used as normal business return values.

An ordinary contract error can be caught by the script, so its `message` is the host's own responsibility to keep free of secrets. If the failure should let the script recover, do not use `resource_exhausted`; use `runtime_error`, `addon_error`, or another ordinary kind that matches the actual semantics.

A host exception outside the contract does not pass the original exception text or traceback to the script. The safe `host_error` message contains the addon name and the host exception type name, but not the original exception message. The script cannot catch it through a specific filter, `except ...`, or a bare `except`.

### Reentrancy

Calling `run()`, `exec()`, `step()`, or `step_instruction()` again on the same VM from inside a callback is rejected; the same scheduling loop cannot be nested. When later execution is needed, return from the current callback and let the outer host drive it.

Observation callbacks use stricter, independent reentrancy rules; see the [observation reference](05-observation.md#delivery-failure-and-reentrancy).

### Virtual IO callbacks

A root's `input_provider` and `output_writer` are also trusted host code, but they are not functions imported through `__addon__`.

- An input provider signals a temporary input wait with `None`, `EOFError`, or `StopIteration`; a permanent close should raise `SericiteError(kind="input_error")`.
- A provider must return a string or `None`, and a writer must synchronously accept one string.
- A provider returning any other type, a writer raising an untranslated ordinary `Exception`, and similar unexpected failures are currently converted by the unified execution path into an uncatchable `internal_error`; they are not the addon callback's `host_error`.
- The host should catch and translate its own expected errors rather than relying on unexpected exceptions to pass diagnostics to the script.
- A writer failure happens on the `print()` path that triggered it; output and output events already committed are not retracted.

For creation parameters, see the [engine reference](01-engine-and-limits.md#input-and-output); for usage, see [execution sessions and virtual IO](../guides/02-sessions-and-io.md).

## Cost and trust responsibility

The CPU, memory, blocking, and external side effects inside a host callback are not governed by the engine's instruction quota. The engine is responsible for the cost of call dispatch, argument and return-value copying, and engine-side result construction.

Granting an addon is therefore an explicit promise of trust. The capability implementer should, on their own:

- validate arguments and permissions and limit input size, call frequency, and external resources;
- avoid unnecessary file, network, device, or secret access;
- prevent untrusted input from triggering process-level behavior such as `sys.exit()`;
- add operating-system-level isolation such as a separate process or container for genuinely adversarial code.

The engine guarantees that ungranted capabilities are unreachable, but it does not judge for the capability implementer whether a granted operation is safe.
