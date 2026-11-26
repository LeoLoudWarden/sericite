# Errors and diagnostics

A Python host handles Sericite compile, runtime, resource, and public-API failures through `SericiteError`. For the static `except` filters and the complete kind list inside scripts, see [script errors and exceptions](../../scripting/reference/05-errors.md).

## Catching host errors

```python
from sericite import SericiteEngine, SericiteError

engine = SericiteEngine()
vm = engine.create_root("raise 'failed'")
try:
    vm.run()
except SericiteError as error:
    print(error.kind, error.message, error.filename, error.line, error.column)
    for frame in error.frames:
        print(frame.function, frame.line)
finally:
    vm.dispose()
```

Errors from `run()`, `exec()`, stepping, creation, and public management APIs are all expressed through this exception type or its `kind`; purely Python call errors such as unknown keywords may still be raised by Python itself as `TypeError`. `BaseException` such as `KeyboardInterrupt` and `SystemExit` should not be swallowed as ordinary script errors.

## SericiteError

```python
SericiteError(
    message: str,
    *,
    kind: str = "runtime_error",
    filename: str | None = None,
    line: int | None = None,
    column: int | None = None,
)
```

It inherits Python's `Exception`. An addon can construct and raise it with a specific contract kind; the host normally does not need to construct it just to catch errors.

| Attribute | Type | Meaning |
|---|---|---|
| `message` | `str` | The safe, readable error message |
| `kind` | `str` | The actual error kind, not a filter-group name such as `file_error` |
| `filename` | `str \| None` | The host-visible logical source identity; may contain an in-engine VM ID |
| `line` | `int \| None` | The error line number; `None` when unavailable or redacted |
| `column` | `int \| None` | The error column number; `None` when unavailable or redacted |
| `frames` | `tuple[SericiteFrame, ...]` | The safe call stack of the VM where the error first captured the stack |

`str(error)` combines the available location, kind, and message. Do not write the host traceback, real paths, or secrets into the message an addon raises; an ordinary contract kind may be caught and read by the script.

## SericiteFrame

`SericiteFrame` is a frozen dataclass imported from the top-level `sericite` package:

```python
SericiteFrame(function: str, line: int | None)
```

- `function` is the safe function name; foreign code across VMs uses a safe display name such as the granted name.
- `line` is the source line number; defining-side code from another VM is redacted to `None`.
- `error.frames` is ordered from the outermost call to the actual error point, with the last frame being the error point; caller frames point at the line that actually made the call.
- A compile-time error that never entered VM execution has no runtime call stack, and `frames` is an empty tuple.

Each frame's line and name follow the same cross-layer redaction principle as the script exception record. The host's `SericiteError.filename` may contain an engine identity of the form `<sericite:vm_N>`; such host diagnostic fields do not enter the script exception record.

## Errors in snapshots

`VMHandle.snapshot()["error"]` and `observation.snapshot()["error"]` return `None` or a dictionary:

```python
{
    "kind": "raise_error",
    "message": "failed",
    "line": 1,
    "column": None,
    "frames": [{"function": "<module>", "line": 1}],
}
```

Here `frames` is a list of dicts, not a tuple of `SericiteFrame`. It corresponds to the safe view of the VM the snapshot belongs to, while `SericiteError.frames` corresponds to the VM where the error first captured the call stack. Cross-VM propagation does not splice another layer's complete execution state into the current view.

## Catchability and terminal states

Script error kinds fall into three categories the host needs to distinguish:

| Category | Script-side behavior | Host-side handling |
|---|---|---|
| Ordinary catchable kind | Catchable by a matching static `except` | The driving method raises `SericiteError` when uncaught |
| `resource_exhausted` | Exhaustion of the current VM or an ancestor cannot be caught by that VM itself; coming from another terminated VM, it can be caught by a still-live parent | Can and should be caught; inspect the state and stop or dispose the target |
| `host_error`, `internal_error` | Always uncatchable by the script, including a bare `except` | Can and should be caught; treat as addon governance failure or engine implementation failure |

An uncaught ordinary error usually puts the target into `error`; quota exhaustion puts it into `resource_exhausted`. `host_error` and `internal_error` also appear as error terminal states in the state view, with the specific kind read from the exception or from event/snapshot diagnostics.

A file constraint that refuses a change uses the ordinary, catchable `file_limit_error`, unlike the `resource_exhausted` of an exhausted execution quota. The script can retry after shrinking the file world, and the host should not mistake it for the whole VM's execution budget being exhausted.

`waiting_input` and `paused` are not exceptions: the driving method returns normally and the target's execution state is still recoverable. `dispose()` destroying a running target does not run the target script's `finally`, so a script cleanup block cannot be the only guarantee of host resource safety.

## Addons and process-level exceptions

An addon's contract errors, non-contract exceptions, and `BaseException` each follow different propagation and safe-message rules; for the complete contract, see [addon exceptions and reentrancy](04-addons.md#exceptions-and-reentrancy). An observation sink's ordinary `Exception` only closes the failed observation session and does not terminate the VM; see [observation failure](05-observation.md#delivery-failure-and-reentrancy).

After catching `resource_exhausted`, `host_error`, and `internal_error`, handle them according to a failure policy rather than blindly driving on as ordinary business branches.
