# Observing VM activity

A host can observe the root and all descendant VMs in the same engine, including VMs created inside scripts, without granting the script new capabilities and without connecting an output writer at each layer.

## Subscribing to events

`engine.observe(sink)` registers a callable that receives `SericiteEvent` and returns an observation session:

```python
from sericite import SericiteEngine

engine = SericiteEngine()
events = []
with engine.observe(events.append) as observation:
    root = engine.create_root("print('hello')")
    assert root.run() == "hello\n"
    snapshot = observation.snapshot(events[0].vm_id)

assert [event.kind for event in events] == [
    "vm.created",
    "vm.output",
    "vm.state_changed",
]
assert snapshot["stdout"] == "hello\n"
root.dispose()
```

The observation session is a context manager; leaving the `with` block closes it. You can also call `close()` explicitly; repeated closing is a no-op. A session only receives events produced after registration and does not replay existing VMs or historical output.

Every event has a monotonically increasing `sequence`, a `kind`, the `vm_id` that produced it, `parent_id`, `depth`, and event-specific `data`. The main events are:

- `vm.created`: produced after creation, registration, hierarchy accounting, and VFS attachment are all committed;
- `vm.state_changed`: produced after a new state and debug information are committed;
- `vm.output`: produced after a chunk of virtual stdout is committed;
- `vm.disposed`: produced after explicit disposal or automatic collection.

For the complete payloads, see the [observation reference](../reference/05-observation.md#event-kinds).

## Observing script-created descendants

No observation API needs to be called inside the script:

```python
engine = SericiteEngine()
events = []
with engine.observe(events.append):
    root = engine.create_root(
        "child = VM('print(\"deep\")')\nchild.run()"
    )
    root.run()

created = [event for event in events if event.kind == "vm.created"]
output = [event for event in events if event.kind == "vm.output"]
assert [event.vm_id for event in created] == [0, 1]
assert created[1].parent_id == 0
assert created[1].depth == 1
assert [(event.vm_id, event.data["text"]) for event in output] == [(1, "deep\n")]
root.dispose()
```

An output event belongs to the VM that actually writes the text to its own virtual stdout. If a parent writer then writes that text to the parent's stdout, the parent also produces its own output event. `buffer_output=False` only clears the buffered view; it does not hide the `data["text"]` already committed in `vm.output`.

## Reading snapshots by VM ID

An observation session's `snapshot(vm_id)` can read the host-safe snapshot of any live VM, including descendants for which you hold no direct handle. Snapshots contain only safe copies, with no operable VM handles. It can also be used inside the sink callback:

```python
engine = SericiteEngine()
scenes = []
observation = None


def sink(event):
    if event.kind == "vm.output":
        scenes.append(observation.snapshot(event.vm_id))


observation = engine.observe(sink)
root = engine.create_root("print('live')")
root.run()
assert scenes[0]["vm_id"] == root.snapshot()["vm_id"]
assert scenes[0]["stdout"] == "live\n"
observation.close()
root.dispose()
```

Snapshots grant no permission to create, drive, modify, or destroy. Modifying a snapshot does not affect the VM, and it does not keep the VM alive by retaining internal references.

By the time a `vm.disposed` notification arrives, the target has already been deregistered and `snapshot()` can no longer be called on it. Unknown IDs, disposed IDs, invalid ID types, and reading snapshots from a closed observation session all raise errors.

## Callback boundaries and closing

Ordinary events are delivered synchronously as the fact commits, and each observer receives an independent event and nested `data` copy. Inside the sink, closing the observation session and reading read-only snapshots are allowed; re-entrant operations on the same engine, such as creating, driving, or disposing a VM, are rejected. When the sink raises an ordinary `Exception`, only that observation session closes, and the VM and other observers keep running. For the complete allowed operations, failure, and reentrancy rules, see the [observation reference](../reference/05-observation.md#delivery-failure-and-reentrancy).

## Garbage-collection notifications

Explicit `dispose()` produces a disposal event synchronously; disposal notifications produced by Python's garbage collector are delivered later. To control the delivery point explicitly, call `observation.poll()`. For the receiving conditions and the flushing rules on later engine entries, see the [observation reference](../reference/05-observation.md#garbage-collection-notifications).

An observation sink should stay bounded and non-blocking and be closed when done. Its host-side cost is not governed by script execution quotas.
