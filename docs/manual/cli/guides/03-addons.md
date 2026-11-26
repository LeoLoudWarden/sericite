# Configuring addons

A Sericite program cannot call Python functions, read the real disk, or access the network by default. When a program needs these capabilities, the operator can use `--addons` to point at a trusted Python file that configures addons, initial files, and execution limits for the entry program.

Here an "addon" is a capability explicitly provided by the runtime environment. Sericite source still executes under its own language rules; the Python configuration file runs outside the sandbox.

## Granting a function

Create the following two files:

```text
project/
├── main.sericite
└── addons.py
```

`project/addons.py`:

```python
def double(number):
    return number * 2


def configure():
    return {
        "addons": {"double": double},
    }
```

`project/main.sericite`:

```python
from __addon__ import double

print(double(21))
```

When running, give the configuration file before the entry:

```bash
sericite --addons project/addons.py project/main.sericite
```

Expected output:

```text
42
```

The configuration file must define a zero-argument `configure()` and return a dict; the `addons`, `limits`, and `files` keys are all optional. The example above uses the `addons` keys to specify script import names and the values to provide the corresponding Python functions. For the complete field types and validation rules, see the [CLI reference](../reference/01-cli.md#addon-configuration).

An addon is not injected directly into the script's global namespace. Every Sericite source module that needs it must write `from __addon__ import ...`; import aliases are also allowed. For the module rules on the script side, see [modules and capability extension](../../scripting/guides/02-modules.md#capability-extension).

`--addons` works the same way with `-c`, stdin, and the REPL:

```bash
sericite --addons project/addons.py -c 'from __addon__ import double; print(double(21))'
```

## Presetting initial files

The `files` returned by `configure()` writes plain text into the program's virtual file system:

```python
def configure():
    return {
        "files": {
            "/message.txt": "hello from the initial workspace",
            "/util.sericite": "value = 42\n",
        },
    }
```

The program can then use these files:

```python
import util

print(read_file("/message.txt"))
print(util.value)
```

Each key is a virtual path and each value is the string content. Files live only in the in-memory workspace; there is no persistent mapping to a host path. Besides providing the initial data that `read_file()` needs, `files` can also preset importable modules for `-c`, stdin, or the REPL.

A Python configuration file can use `__file__` to locate and read its own resources, then put the text into `files`. It is the trusted Python, not the Sericite script, that reads the real files; whether such reads are allowed, and what they may read, is up to the configuration author.

## Setting execution limits

`limits` accepts a `SericiteLimits` and configures the entry program's quotas:

```python
from sericite import SericiteLimits


def configure():
    return {
        "limits": SericiteLimits(max_instructions=100_000),
    }
```

The entry program above can execute at most 100000 instructions. When the limit is exceeded, the program terminates with `resource_exhausted`, and a one-shot command exits with status code 1.

The default quotas are intended for development and debugging. When running programs that are not fully trusted, tighten the limits explicitly for the task instead of switching to unlimited quotas just to get rid of resource errors.

## Trust boundary

> **An addon configuration file has full host privileges. Trust it the same way you trust any Python file you run.**

The configuration file and the Python functions it grants can read environment variables and the real disk and access the network; their resource consumption and external side effects are not constrained by engine quotas. Only the operator should select the configuration file, and it should grant only the functions the program actually needs.

The engine guarantees that ungranted capabilities are unreachable, but it does not judge for the capability implementer whether an operation is reasonable. For the data boundary, startup order, and security responsibilities, see the [CLI reference](../reference/01-cli.md#addon-configuration); before executing untrusted code, also read the manual's [safety essentials](../../README.md#safety-essentials).
