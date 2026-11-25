# Running multi-file projects

When the entry is a source file, the command line automatically prepares the modules the program can reach through static imports.

## A minimal project

Create the following directory:

```text
project/
├── main.sericite
└── math_utils.sericite
```

`project/math_utils.sericite`:

```python
def double(number):
    return number * 2
```

`project/main.sericite`:

```python
from math_utils import double

print(double(21))
```

Run the entry file:

```bash
sericite project/main.sericite
```

Expected output:

```text
42
```

The entry file's directory is the project root. Here the root is `project/`, so `math_utils` resolves to `project/math_utils.sericite`; running the same entry from another working directory does not change the module resolution base.

Packages, dotted modules, and relative imports use the same project root. For the specific syntax, see the scripting manual's [modules and capability extension](../../scripting/guides/02-modules.md).

## How a project directory becomes a workspace

The command line does not expose the whole project directory to the program. Instead, it builds a source snapshot at startup. The project above appears in the virtual file system as:

```text
/
├── main.sericite
└── math_utils.sericite
```

The startup scan copies only the source that is reachable through static imports, including imports inside functions and conditional branches. The actual modules are still loaded from this snapshot only when execution reaches an import statement; the program never returns to the real disk to find files, and changes made to virtual files while the program runs are not written back to the project directory.

The following `note.txt` therefore cannot be read automatically from the project directory:

```text
project/
├── main.sericite
└── note.txt
```

```python
text = read_file("/note.txt")
```

If the program genuinely needs this initial data, the operator should put it into the workspace explicitly through the addon configuration's `files`; see [Presetting initial files](03-addons.md#presetting-initial-files).

## Other entry points do not scan the current directory

Only a source-file entry builds the directory snapshot above. `-c`, stdin, and the REPL import modules only from the existing virtual file system; even if source with the same name exists in the current directory, it is not found automatically:

```bash
sericite -c 'from math_utils import double'
```

To use modules from these entry points, preset the source through the addon `files`. For the complete loading boundaries and override order, see the [CLI reference](../reference/01-cli.md#multi-file-projects).
