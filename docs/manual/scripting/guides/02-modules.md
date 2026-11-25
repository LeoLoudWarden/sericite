# Modules and capability extension

This chapter introduces the module system and explains how to use packages and external extensions. Before that, you need to understand two design ideas of Sericite: **minimal built-ins** and **explicit extension** of capabilities.

## A minimal module

The workspace contains:

```text
/
├── main.sericite
└── util.sericite
```

`/util.sericite`:

```python
value = 21

def double(number):
    return number * 2
```

`/main.sericite`:

```python
import util
from util import double

print(util.value)
print(double(10))
```

Expected output:

```text
21
20
```

## Modules

Unlike Python, Sericite has no built-in modules, and import has no implicit behavior in Sericite. `import x` means "look for `x.sericite` (or `x/__init__.sericite`) in the workspace": you can import only what is found. For anything not in the workspace, Sericite will not look anywhere else for you. The default workspace is empty.

### Imports

```python
import a_lib
import a_lib as a
import a_lib.b_lib
import a_lib.b_lib as b
from a_lib.b_lib import c_tool
```

Relative imports are supported, based on the package of the currently defining module: `.` means the current package and `..` means the parent package.

```python
# /lib/tools.sericite
from . import util       # loads lib.util
from .util import useful

# /lib/sub/mod.sericite
from ..util import useful  # loads lib.util
```

`from module import *` is not supported.

### Mechanics

1. A module is loaded only when execution actually reaches the import statement. Import can appear inside functions, conditionals, and `try`.
2. A successful import enters the cache; a repeated import returns the same module object.
3. Circular dependencies are not supported; direct or indirect circular imports raise an error.
4. Writing module attributes, such as `module.value = 100`, is not supported.

## Capability extension

Based on the design ideas, Sericite provides only minimal, platform-independent script built-ins. The following have no preset implementation:

- random number generation
- getting the time
- sending network requests
- interacting with audio devices

Such features depend on specific hardware and operating systems, and implementations differ; the language has no unified version. To use them, the runtime environment provides them on demand. Sericite presets a module named `__addon__` and extends script capabilities through `from __addon__ import`.

For example, suppose a development board has Bluetooth, an infrared transmitter, a linear motor, and a Hall sensor; the environment can correspondingly provide:

| Capability | Import name |
|---|---|
| Bluetooth pairing | `bluetooth_pair` |
| Infrared transmission | `ir_transmit` |
| Linear motor drive | `motor_drive` |
| Hall sensor read | `hall_read` |

The script imports only the ones it needs:

```python
from __addon__ import bluetooth_pair, hall_read
```

`__addon__` is just a fixed entry, and `from __addon__ import` is the fixed spelling. Which names exist in that entry, what arguments each function takes, in what order they are called, and what errors they raise are not part of the language and are not this document's responsibility. The specific organizational conventions in practice need to be agreed on separately.
