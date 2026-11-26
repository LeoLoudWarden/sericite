# Granting host capabilities

Sericite does not provide network, real disk, random numbers, or host object access by default. When a program needs these capabilities, the Python host can grant selected callables to the root VM as addons.

## Granting and importing functions

The following host provides a `double` function:

```python
from sericite import SericiteEngine


def double(number):
    return number * 2


engine = SericiteEngine()
vm = engine.create_root(
    "from __addon__ import double\nprint(double(21))",
    addons={"double": double},
)
assert vm.run() == "42\n"
vm.dispose()
```

The keys of the `addons` dict are the import names the script uses, and the values must be callables. Granting does not inject the function directly into the global namespace; every Sericite source module that needs it must write `from __addon__ import ...` explicitly.

A dictionary key can differ from the Python function's original name, so you can provide a stable or more constrained public name. An addon name must be a valid identifier that does not start with `__`, and it may even collide with a built-in; in that case use an import alias to avoid directly rebinding the built-in. For the naming rules and alias examples, see the [addon reference](../reference/04-addons.md#granting-functions).

## Data is copied at the boundary

Arguments and return values are deep-copied in both directions between Python and the VM; neither side shares mutable containers:

```python
shared = {"items": [1, 2]}


def give():
    return shared


vm = engine.create_root(
    "from __addon__ import give\n"
    "a = give()\n"
    "a['items'][0] = 99\n"
    "b = give()\n"
    "print(b['items'][0])",
    addons={"give": give},
)
assert vm.run() == "1\n"
assert shared == {"items": [1, 2]}
vm.dispose()
```

What may cross the boundary is pure data recursively built from `None`, booleans, numbers, strings, lists, dicts, and tuples. An arbitrary Python object does not enter the script merely because it is returned; violating the data contract produces `addon_error`. To hand a record to Python, first `unwrap()` it to a dict inside the script. For the complete type and size rules, see the [addon reference](../reference/04-addons.md#data-boundary).

This deep-copy boundary is specific to the interface between Python and scripts. When a script grants Sericite functions to a child VM, the definer's environment and cross-VM records follow different rules; see the [script VM reference](../../scripting/reference/06-vm.md#addon-granting).

## Translating host failures into script errors

A well-behaved addon either returns a result or raises a `SericiteError` with a clear contract kind:

```python
from sericite import SericiteEngine, SericiteError


def load(name):
    raise SericiteError("resource not found", kind="file_not_found")


engine = SericiteEngine()
vm = engine.create_root(
    "from __addon__ import load\n"
    "try:\n"
    "    load('missing')\n"
    "except file_not_found as error:\n"
    "    print(error.kind, error.message)",
    addons={"load": load},
)
assert vm.run() == "file_not_found resource not found\n"
vm.dispose()
```

Ordinary contract kinds can be caught by scripts under the language rules, so the message should not contain host secrets. An ordinary `Exception` outside the contract instead terminates the current VM with an uncatchable `host_error`; the host receives a `SericiteError`, and the original exception message is not passed to the script.

`BaseException`, `resource_exhausted`, and virtual-IO callback failures each have dedicated rules; for the complete exception and reentrancy contract, see the [addon reference](../reference/04-addons.md#exceptions-and-reentrancy).

## The capability implementer's responsibility

Granting a function grants not only a name but also the impact that function can actually cause. The host should validate arguments and permissions inside the callback, and limit input size, call frequency, CPU, memory, blocking, and external side effects; consumption inside the callback is not governed by the VM instruction quota. Grant only the operations the script needs, and do not re-enter the same VM's driving methods from a callback. When executing adversarial code, also add operating-system-level isolation outside Sericite.

For cost responsibility and the complete reentrancy rules, see the [addon reference](../reference/04-addons.md).
