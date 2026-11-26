# Observation

A Python host can observe every VM in the same engine, including descendants created inside scripts, without granting the script new capabilities or holding descendant handles directly. The observation interface belongs only to the host and is not exposed as a Sericite built-in or script VM method.

## Subscribing

```python
engine.observe(
    sink: Callable[[SericiteEvent], object],
) -> SericiteObservation
```

Register a callable and return an observation session. A non-callable sink raises `type_error`.

An observation session only receives events produced after registration and does not replay existing VMs or historical events. Using a context manager is recommended:

```python
with engine.observe(events.append) as observation:
    root = engine.create_root("print('hello')")
    root.run()
    snapshot = observation.snapshot(root.snapshot()["vm_id"])
```

Leaving the `with` block calls `close()`.

## SericiteEvent

`SericiteEvent` is a frozen dataclass exported from the top-level `sericite` package:

```python
SericiteEvent(
    sequence: int,
    kind: str,
    vm_id: int,
    parent_id: int | None,
    depth: int,
    data: dict[str, object],
)
```

| Field | Meaning |
|---|---|
| `sequence` | The monotonically increasing in-engine event sequence number |
| `kind` | The event kind listed in the table below |
| `vm_id` | The in-engine ID of the VM that produced the event |
| `parent_id` | The parent VM's in-engine ID; `None` for the root |
| `depth` | The VM nesting depth; 0 for the root |
| `data` | The event-specific host-side data dictionary |

Frozen constrains reassigning the event fields; it does not turn `data` into an immutable mapping. The engine provides each observation session with an independent event object and a deep copy of the nested `data`; modifying one of them does not affect other observers or the engine.

## Event kinds

| `kind` | `data` and when it is produced |
|---|---|
| `vm.created` | `state`, `filename`, `limits`, `addons`. `limits` is the VM's `SericiteLimits`, and `addons` is the sorted tuple of granted names. Produced after creation, registration, parent and ancestor accounting, and VFS attachment are all committed; a failed creation produces no event |
| `vm.state_changed` | `old_state`, `new_state`, `reason`. A breakpoint pause also includes `breakpoint={"line": int, "path": str \| None}`, and a terminal error also includes `error_kind`. Produced only when the state genuinely changes |
| `vm.output` | `text`, a chunk of committed virtual-stdout text. Produced after output metering and stdout buffering, before output forwarding; text rejected by the output limit produces no event |
| `vm.disposed` | `reason`, `state`. Explicit disposal uses `reason="dispose"` and `state="terminated"`; automatic collection uses `reason="gc"` and keeps the pre-collection state |

Observable state-change reasons include `exec`, `resume`, `breakpoint`, `input`, `output_writer`, `return`, `error`, `terminate`, and `dispose`. A script catching an exception does not by itself produce a terminal state change, and disposing an already-disposed VM produces no additional event.

An output event belongs to the VM that actually commits the text to its own virtual stdout. When a child program forwards output to its parent program, every VM that actually writes produces its own event. With `buffer_output=False`, `data["text"]` still reports the committed output, even though `stdout()` and the buffered view in snapshots are empty.

An output event only means the text has been committed. A later output-writer failure does not retract that event.

## SericiteObservation

### State attributes

```python
observation.closed -> bool
observation.failed -> bool
observation.failure -> str | None
```

- `closed` says whether the session has been closed.
- `failed` says whether an ordinary sink exception has already failed and closed the session.
- `failure` holds the host-side string `"ExceptionType: message"`; when the exception itself cannot be rendered, only the exception class name is kept, and it is `None` when not failed.

These attributes describe only the observation session; they do not say whether an observed VM failed.

### SericiteObservation.close

```python
observation.close() -> None
```

Idempotently close the session and immediately stop later delivery, including events not yet delivered during the current dispatch. Closing one session does not close others.

### SericiteObservation.poll

```python
observation.poll() -> None
```

Flush the engine's queued GC disposal notifications and deliver them by sequence to observation sessions that still satisfy the receiving conditions. Call it when you need to process notifications at an explicit point rather than relying on another unrelated engine operation.

`poll()` must not be called inside an observation callback. Calling `poll()` on a closed session does not reopen it.

### SericiteObservation.snapshot

```python
observation.snapshot(vm_id: int) -> dict[str, object]
```

Read the [host-safe snapshot](02-vm.md#snapshot) of any live VM by in-engine ID; it can also be used inside an observation callback. The host can read the execution state after events commit without holding a descendant handle.

The returned value contains only safe values, no operable VM handles or internal context, grants no driving or modification permission, and does not keep the VM alive through cached references. Modifying the returned dictionary does not modify the VM.

`vm_id` must be a non-negative strict integer, and `bool` is also rejected; an illegal type raises `type_error`. An unknown or disposed ID, and reading snapshots from a closed observation session, all raise `runtime_error`. A `vm.disposed` notification arrives after deregistration, so the target can no longer be snapshotted at that point.

### Context manager

```python
observation.__enter__() -> SericiteObservation
observation.__exit__(...) -> None
```

Entering `with` returns the session itself, and exiting closes it. Usually you use `with engine.observe(...)` directly and do not need to call these two methods manually.

## Delivery, failure, and reentrancy

Ordinary events are delivered synchronously as the execution fact commits. Observation executes no script code and does not change a VM's instruction or memory metering. Every session that was registered before the event and is still open receives the same fact, each with its own independent copy.

When the sink raises an ordinary `Exception`, the engine closes only that observation session; the VM and other observers keep running. This kind of failure follows the `failed`/`failure` state above and does not terminate the VM by the addon `host_error` rules. Other `BaseException` such as `KeyboardInterrupt` and `SystemExit` remain process-level events and propagate to the host.

An observation callback must not re-enter operations on the same engine. The following operations are rejected with `runtime_error`:

- creating a VM or VFS;
- driving, feeding input to, or disposing a VM, or operating on a VFS;
- registering another observation session;
- calling `poll()`.

Inside the callback, closing the observation session and calling the read-only `observation.snapshot(vm_id)` are allowed. Operations on a different engine are not subject to this restriction.

The sink should stay bounded and non-blocking and be closed when done. Observation callbacks and pending notifications are host-side costs, not part of script execution metering.

## Garbage-collection notifications

Explicit `dispose()` synchronously produces `vm.disposed(reason="dispose")` and does not additionally queue a GC event.

Automatic collection uses delayed delivery: the Python collection callback deregisters the VM and queues a plain-data notification, but never calls the sink. The queued `vm.disposed(reason="gc")` is delivered by the following entries, in relative sequence order:

- explicit `observation.poll()`;
- a later safe engine entry that flushes observation events.

A closed session no longer receives queued notifications; a session registered after the notification was queued also does not receive that old event. The event notification point is not the same as the actual Python collection point, and automatic VM collection itself is not guaranteed to happen immediately.
