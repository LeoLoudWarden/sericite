# Sericite Language Reference

Sericite is a scripting language whose syntax is a subset of Python — it reads like Python, but **not every Python construct is legal**, and some semantics have their own rules. This document is self-contained: read it and you can start writing. It describes the language behavior for authors of **Sericite scripts**.

## 1. What it looks like

```python
name = "world"            # assignment
print("hello", name)      # prints: hello world
x = input()               # read one line (a string)
```

## 2. Types and operators

Built-in types: `int`, `float`, `str`, `bool`, `None`, `list`, `dict`, `tuple`, plus user-defined `record`s (see section 7).

### Built-in values and basic operations

```python
7 / 2        # 3.5 (division always yields float)
7 // 2       # 3
7 % 3        # 1

"ab" + "cd"
"""line1
line2"""     # multi-line string
f"{1/3:.2f}" # f-string

not x        # logical not; and / or short-circuit
1 < 2        # supports == != < <= > >=
"a" in {"a": 1}  # dict keys, list/tuple elements, or str substrings
```

Container equality compares elements recursively, with an identity fast path for the same object:

```python
nan = float("nan")
nan == nan       # False: NaN is not equal to itself
[nan] == [nan]   # False: two new containers compared element by element
lst = [nan]
lst == lst       # True: the same object
```

### Assignment and augmented assignment

`a = b = value` evaluates `value` once and then binds each name in order; multiple targets with attributes or subscripts are not supported.

Augmented assignment supports `+=`, `-=`, `*=`, `**=`, `/=`, `//=`, and `%=`. The target may be a name, a list/dict subscript, or a record field. `target += rhs` is equivalent to `target = target + rhs`, except that the target address is evaluated only once; the other operators work the same way.

All ordinary binary-operation rules also apply to augmented assignment. In particular, list `+=` and `*=` create a new concatenated or repeated list rather than modifying the original in place.

### Exponentiation

```python
2 ** 3       # 8
2 ** 3 ** 2  # 512: right-associative, equivalent to 2 ** (3 ** 2)
-2 ** 2      # -4: exponentiation binds more tightly than unary minus
(-2) ** 2    # 4
2 ** -2      # 0.25
```

`**` accepts only int/float, excluding `bool`. Two integers with a non-negative integer exponent produce an int; a float operand or a negative integer exponent produces a float.

Error contract:

- zero to a negative power: `zero_division`;
- an operation that would produce a complex value: `type_error`;
- floating-point result overflow: `conversion_error`.

### Common sequence operations

Strings, lists, and tuples support same-type `+` concatenation, bidirectional `*` repetition with integers, integer-index reads, and read-only slicing. Lists also support subscript writes.

```python
"ab" + "cd"       # "abcd"
[1, 2] + [3]      # [1, 2, 3]
(1, 2) + (3,)     # (1, 2, 3)

"=" * 3           # "==="
2 * [1, 2]        # [1, 2, 1, 2]
(1, 2) * 0        # ()
```

Zero or negative repetition produces an empty sequence of the same type. Concatenation and repetition return new sequences; list and tuple repetition is shallow, so their elements remain shared.

Slices use `value[start:stop]` or `value[start:stop:step]`:

```python
s = "abcdef"
s[1:4]      # "bcd": from index 1 up to (not including) 4
s[:3]       # "abc": start omitted
s[::2]      # "ace": step 2
s[::-1]     # "fedcba": negative step walks backwards
s[2:99]     # "cdef": out-of-range positions clip, no error
```

- All three positions may be omitted (omission means `None`); each position must be an integer or `None`.
- The default step is 1, and the step cannot be zero.
- Negative indices, out-of-range clipping, and negative steps follow Python semantics.
- Slicing always creates a new sequence.

See section 10 for compile-time restrictions such as slice assignment.

### Tuple-specific rules

A one-item tuple needs a trailing comma:

```python
empty = ()
single = (1,)
pair = 1, "x"     # parentheses are optional
```

Tuples support `len`, truth testing, iteration, membership, and structural equality, but not ordering comparisons. They cannot be assigned into, mixed with lists in concatenation, or used as dict keys; these misuses raise `type_error`.

`tuple` is an annotation-only contract name, not a conversion function. See section 7 for the complete contract-name rules.

### Name unpacking

Fixed-length, nested unpacking into names is supported:

```python
a, b = (1, 2)
a, b = b, a
x, (y, z) = [3, (4, 5)]
for first, second in [(1, 2), (3, 4)]:
    print(first + second)
```

The right-hand side may be a list, tuple, str, or dict (iterating over its keys). A length mismatch raises the catchable `value_error`; a non-iterable value raises `type_error`. Target leaves must be names; see section 10 for target forms rejected at compile time.

### Key differences from Python

These rules differ from Python:

- `bool` does not participate in arithmetic: `True + 1` raises `type_error`.
- Cross-type ordering comparison raises `type_error`: `1 < "a"` raises; `==`/`!=` may cross types, evaluating to False/True.
- Dict keys may only be `str/int/float/bool/None`; reading a missing key raises `key_error`.

## 3. Control flow

```python
if x < 0:
    print("neg")
elif x < 10:
    print("small")
else:
    print("big")

while i < 10:
    i = i + 1
    if i % 2 == 0:
        continue
    if i > 8:
        break
else:
    print("no break")     # while/else

for item in [1, 2, 3]:      # for iterates: list, tuple, dict (keys), str (chars), range() results
    print(item)
for k in {"a": 1, "b": 2}:
    print(k, "->", ...)     # values via d[k]
else:
    print("no break")     # for/else

pass                        # empty statement, legal

label = "big" if x >= 10 else "small"   # ternary (short-circuits: only the chosen branch runs)
```

A `for` target may be a single name or use the name-unpacking rules from section 2. Iterating a list is a live view (edits during iteration are visible), while iterating a dict is a snapshot of its keys.

### List and dict comprehensions

```python
squares = [x * x for x in range(6) if x % 2]
pairs = [(x, y) for x in [1, 2] for y in [3, 4]]
mapping = {key: value for key, value in [("a", 1), ("b", 2)]}
reverse = {value: key for key, value in mapping.items()}
```

Comprehensions support multiple `for` clauses, multiple `if` filters, and the name-unpacking rules from section 2, with the same iteration behavior as ordinary `for`.

**Scope.** Each comprehension has its own scope: targets neither leak nor overwrite same-named outer variables, but the comprehension can read outer variables.

```python
x = 9
result = [x for x in [1, 2]]
print(result, x)           # [1, 2] 9

def scale(factor):
    return [x * factor for x in [1, 2]]
print(scale(3))            # [3, 6]
```

**Evaluation order.** The outermost iterable is evaluated once in the enclosing scope. Later iterables, filters, and result expressions run from left to right in the comprehension scope, so they can read the current targets.

```python
x = [3, 4]
result = [x for x in x]
print(result, x)           # [3, 4] [3, 4]

pairs = [(x, y) for x in ["ab", "c"] for y in x]
print(pairs)               # [('ab', 'a'), ('ab', 'b'), ('c', 'c')]
```

**Dict results.** Dict comprehensions evaluate the key before the value, and a duplicate key retains the later value.

```python
result = {key: value for key, value in [("a", 1), ("a", 2)]}
print(result)              # {'a': 2}
```

**Resource limits.** Result containers grow item by item and remain subject to container-size and resource quotas. See section 10 for comprehension forms rejected at compile time.

## 4. Functions

```python
def add(a, b=10):           # default arguments (evaluated once at def time)
    return a + b

add(1)                      # 11
add(1, b=20)                # 21, keyword arguments supported

def fib(n):                 # recursion is legal
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)
```

Nested functions use lexical scope and capture outer function locals by reference. A closure reads the latest binding when it is called, not a snapshot from its definition:

```python
def make_reader():
    x = 1
    def read():
        return x
    x = 2
    return read

reader = make_reader()
print(reader())             # 2
```

Closures created by the same outer call share captured variables; separate outer calls have independent environments. A `for` loop does not create a fresh variable per iteration, so closures created in a loop share its final binding. Use a default argument such as `def read(value=x): ...` when a definition-time snapshot is wanted.

Assigning a name anywhere in a function makes it local throughout that function. An inner assignment therefore shadows rather than modifies the outer binding; `nonlocal` and `global` are not supported. Module globals are still resolved from the defining module rather than copied into the closure.

Function decorators follow Python's application semantics:

```python
def trace(func):
    def wrapper(x):
        print("before")
        result = func(x)
        print("after")
        return result
    return wrapper

@trace
def double(x):
    return x * 2
```

This is equivalent to defining `double`, then rebinding it with `double = trace(double)`. Decorator expressions are evaluated from top to bottom; stacked decorators are applied from bottom to top.

Not supported: variadic arguments (`*args`), keyword-only parameters.

Parameter and argument validation:

- duplicate parameter names, or duplicate keyword arguments in any call including record construction: `syntax_error` at compile time;
- one parameter receiving both a positional and a keyword value: `arity_error` at runtime.

## 5. Exceptions

### Catching errors

```python
try:
    x = 1 / 0
except zero_division as e:
    print("caught:", e.message)
else:
    print("no error")
finally:
    print("always runs")

raise "something wrong"      # raises the catchable kind raise_error
```

Use `except ... as e` to catch every catchable error and bind its record, or bare `except:` to do so without binding a value. The following independent examples show `except` clauses with and without a bound error record:

```python
try:
    value = int("bad")
except ... as e:
    print(e.kind, e.message)

try:
    value = int("bad")
except:
    print("conversion failed")
```

### Static filters and aliases

An `except` filter is static syntax, not variable evaluation or a general-purpose tuple. There are three forms:

- one catchable kind or filter alias: `except file_error`;
- a non-empty parenthesized filter containing those names: `except (file_error, input_error)`;
- `...` for every catchable kind: `except ...`.

Unknown names (including misspellings), empty filters, dynamic values, and uncatchable kinds are rejected at compile time with `syntax_error`.

The built-in filter aliases have fixed memberships:

| Filter alias | Concrete kinds caught |
|---|---|
| `file_error` | `file_not_found`, `file_exists`, `is_directory`, `not_directory`, `file_limit_error` |
| `lookup_error` | `index_error`, `key_error` |

An alias is used only for filtering at compile time. It is not a runtime value or an actual error kind. `e.kind` always contains the concrete error:

```python
try:
    read_file("/missing.txt")
except file_error as e:
    print(e.kind)               # file_not_found
```

`except` clauses are tried in source order, so put a specific kind before an alias when it needs different handling. Aliases and concrete kinds can be mixed in one parenthesized filter; duplicate members have no additional effect.

### Error records

`as e` binds a record with exactly three fields:

- `e.kind`: the actual error kind string;
- `e.message`: the readable error text;
- `e.frames`: a list of call frames described below.

The binding is an ordinary binding in the current scope: it remains after the `except` clause, and a nested `except` clause using the same name overwrites it. The record and its frame records are safe copies; mutating them does not affect the internal error.

### Catchability and special boundaries

The concrete catchable kinds are:

| Category | Kinds |
|---|---|
| General | `runtime_error`, `syntax_error`, `type_error`, `name_error`, `arity_error`, `raise_error`, `input_error`, `import_error` |
| Operations and contracts | `zero_division`, `conversion_error`, `index_error`, `key_error`, `value_error`, `attribute_error`, `contract_error` |
| Files | `file_not_found`, `file_exists`, `is_directory`, `not_directory`, `file_limit_error` |
| External-function boundary | `ffi_error` |
| Resource failure | `resource_exhausted` |

`resource_exhausted` means that a resource quota has been exhausted; a script cannot catch its own resource exhaustion.

Here `value_error` covers unpacking length mismatches and unsuccessful `index()` searches; `attribute_error` covers missing or forbidden members; `contract_error` covers construction, annotation, wrap, and field-write contract failures. `file_limit_error` is an ordinary recoverable error, so the program can handle it and continue.

A `try` cannot catch a `syntax_error` in the same source, because the source is checked before it starts running.

`input_error` means input has ended: `input()` raises it when no further line will arrive, so `except input_error` can end a read-until-EOF loop. If input is merely delayed, `input()` waits instead of raising.

`internal_error` (an unexpected internal failure) and `host_error` (an external function failed in a way that cannot be recovered safely) are always uncatchable.

### Call frames and rethrows

Each entry in `e.frames` is a record with exactly two fields:

- `function`: the function name string;
- `line`: the source line integer, or `None` when unavailable.

Frames run from the outermost call to the failure; the last frame is the error site. A caller frame's line is the line that actually issues the call, even for a multiline call. For example, printing the list may show `[record(function='<module>', line=8), record(function='outer', line=5)]`.

Bare `raise` inside an `except` clause and saved rethrows through `finally` preserve the original frames; a new error raised in an `except` clause or `finally` gets a new trace.

## 6. Built-in functions

- `input()` / `print(...)`: read a line / write values separated by spaces. `print(..., end=text)` replaces the default trailing newline with `text`; use `end=""` for no trailing newline. `end` is keyword-only and must be a string.
- `len(x)` (str/list/dict/tuple), `int(x)`, `float(x)`, `str(x)`, `repr(x)`, `range(...)` (returns a list). `repr` quotes and escapes strings so newlines, tabs, quotes, and backslashes appear on one line; containers use the same safe rendering recursively.
- Files and directories (text only): see below.
- Records: `wrap(schema, d)`, `unwrap(record)` — see section 7.

### Files and directories

Use these built-ins to read and write text files in the current workspace, with paths such as `/notes/a.txt`:

| Operation | Purpose |
|---|---|
| `read_file(path)` | Read a text file |
| `write_file(path, text)` | Write a text file, creating missing parent directories |
| `delete_file(path)` | Delete a file |
| `rename_file(old_path, new_path)` | Rename or move a file |
| `copy_file(source_path, destination_path)` | Copy a file |
| `make_dir(path)` | Create a directory and missing parents |
| `delete_dir(path)` | Recursively delete a directory tree |
| `rename_dir(old_path, new_path)` | Recursively move a directory tree |
| `copy_dir(source_path, destination_path)` | Recursively copy a directory tree |
| `list_dir(path)` | Return sorted direct children of a directory |
| `path_exists(path)` | Check whether a file or directory exists |

**Implicit and explicit directories.** Writing a file creates missing parent directories implicitly. When deletion or rename leaves an implicit directory with no files or subdirectories, that directory is removed automatically. `make_dir` creates its target and any missing parents explicitly; they remain even when empty. The root directory always remains.

```python
write_file("/scratch/note.txt", "text")
delete_file("/scratch/note.txt")
print(path_exists("/scratch"))            # False

make_dir("/keep/empty")
print(path_exists("/keep"), path_exists("/keep/empty"))  # True True
```

**File operations**

- Delete, rename, and copy require a file source. A directory raises `is_directory`; a missing file raises `file_not_found`.
- Rename and copy create missing destination parents but refuse to overwrite an existing file, raising `file_exists`.
- Rename does not increase the number of files. Copy adds a file and is therefore subject to the file-count limit.

**Directory operations**

- `make_dir` raises `file_exists` when a file or directory already exists at the target.
- Delete, rename, and copy require a directory source. A file raises `not_directory`; a missing directory raises `file_not_found`.
- Rename and copy refuse to overwrite an existing file or directory, raising `file_exists`.
- Directory deletion, rename, and copy reject the root directory as a source or destination. Moving or copying a directory into its own tree is also forbidden. These cases raise `runtime_error`.
- Directory copy adds a whole tree and is therefore subject to file-count and memory limits.

**Common path and failure rules**

- Every operation that creates a file or directory first validates all intermediate destination path segments. If any segment is an existing file, the operation raises `not_directory`.
- Mutating operations complete path and resource checks before changing the file tree. Failure leaves no partial change. See the [VM reference](vm-reference.md) §5 for recoverable file-constraint errors and operations on an already over-limit world.

When the file errors and file-constraint errors above share the same recovery, use `except file_error` instead of listing them individually; see section 5 for its exact membership.

### List, tuple, and dict methods

- `lst.append(x)`: append one item in place and return `None`.
- `lst.pop()` / `lst.pop(i)`: remove and return the last item or the item at `i`; negative indices work as in indexing. An empty list or invalid index raises `index_error`.
- `seq.count(x)`: count elements structurally equal to `x` in a list or tuple.
- `seq.index(x, start=None, stop=None)`: return the first matching position in a list or tuple; an optional search range may be supplied, and no match raises `value_error`.
- `d.keys()` / `d.values()`: return a new list of keys or values in insertion order; later dict mutations do not change that list.
- `d.items()`: return a new list of `(key, value)` pairs in insertion order; later dict mutations do not change that list.
- `d.get(key)` / `d.get(key, default)`: return the value for `key`, or `None`/`default` when absent.
- `d.pop(key)` / `d.pop(key, default)`: remove and return the value for `key`; a missing key raises `key_error` unless a default is supplied.

### String methods

- `s.strip()` / `s.lstrip()` / `s.rstrip()`: remove whitespace from both ends, the left, or the right. Forms such as `s.strip(chars)` instead remove any of the individual characters listed in `chars`, not a whole prefix or suffix.
- `s.split()`: split on runs of whitespace and ignore whitespace at the ends. `s.split(sep, maxsplit=-1)` splits on a non-empty string `sep`; `sep=None` selects whitespace splitting. `maxsplit` limits the number of splits, with a negative value meaning no limit.
- `s.splitlines(keepends=False)`: split at universal line boundaries. `keepends` must be a `bool`; when true, line endings are retained.
- `separator.join(values)`: join strings from a `str`, list, tuple, or dict (its keys) using the separator; every item must be a `str`.
- `s.find(sub, start=None, end=None)`: return the first position of the substring, or `-1` when absent; an optional search range may be supplied.
- `s.replace(old, new, count=-1)`: replace non-overlapping occurrences, with `count` limiting replacements and a negative value replacing all. An empty `old` inserts between characters and at both ends, following Python semantics.
- `s.partition(sep)` / `s.rpartition(sep)`: split at the first/last non-empty separator into a `(before, sep, after)` tuple:

```python
"a=b=c".partition("=")   # ("a", "=", "b=c")
"a=b=c".rpartition("=")  # ("a=b", "=", "c")
"abc".partition("=")     # ("abc", "", "")
"abc".rpartition("=")    # ("", "", "abc")
```

String methods return new values rather than modifying the original string. These are closed list, tuple, dict, and string method sets: unlisted methods raise `attribute_error`.

## 7. Records: custom objects with members

`class` defines a **schema** (a structural contract). A schema is a first-class runtime value — the `class` statement creates it each time it executes:

```python
class Point:
    x: int
    y: int

p = Point(1, 2)          # positional construction in declaration order; Point(x=1, y=2) works too
print(p.x)               # dot access reads a member
p.x = 10                 # dot assignment writes, still checked against the field contract
```

A class body only allows field declarations, in two forms: `x` (contract `any`, any value) or `y: int` (a specific contract). Defaults, methods, and inheritance are not supported yet. Available contract names:

- `int`/`float`/`str`/`bool`/`list`/`dict`/`tuple`, `any`, or another schema (nested constraint);
- `any`/`bool`/`list`/`dict`/`tuple` are annotation-only contract names: they cannot be called or assigned;
- `int`/`float`/`str` remain conversion builtins.

`None` is a value, not a contract. Parameter, return, field, and annotated-assignment positions cannot use an explicit `None` annotation; doing so raises `syntax_error`. Omit the annotation when no contract check is intended.

Record semantics:

- **Fixed shape**: fields can never be added or removed — reading or writing an unknown field raises `attribute_error`; field values are mutable but must satisfy their contract (violations raise `contract_error`).
- **Structural equality**: two separately written identical class bodies produce equal schemas; records are equal when their schemas are structurally equal and their payloads are equal; a record never equals a dict — even with the same shape, a dict carries no contract.
- **Equality ignores declaration order; construction depends on it**: schema equality compares the field set — the order of `x` and `y` makes no difference. Positional construction, however, binds arguments in each schema's own declaration order — two schemas with the same fields in reversed order are equal, yet the same positional call produces records with different payloads:

  ```python
  class A:
      x: int
      y: int

  class B:
      y: int
      x: int

  print(A == B)              # True: equality ignores declaration order
  print(A(1, 2) == B(1, 2))  # False: construction binds in each schema's order
  ```

  Prefer keyword construction (`B(x=1, y=2)`) when passing arguments across separately defined schemas.
- **Wrap/unwrap**: `unwrap(p)` peels a record into a plain dict (a shallow copy); `wrap(Point, d)` wraps a dict whose keys exactly match the schema into a record (missing/extra keys raise `contract_error` naming them).
- Records are not indexable, not iterable, not usable as dict keys, and always truthy.

Annotations are **runtime contracts that actually execute** (not static types; there is no static checking):

```python
def move(p: Point) -> int:
    return p.x

p: Point = Point(1, 2)
```

Annotations are checked at three points, and the error messages name the responsible position:

- Parameter annotations: checked at call time (argument);
- Return annotations: checked at return time (return value);
- Annotated assignments: checked at assignment time (annotated assignment).

The check is **width-based**: an argument record passes as long as it contains every field the expected schema requires, with compatible contracts; extra fields are fine. Dicts are never auto-wrapped at annotation positions.

Names in error messages are **compile-time, scope-local labels**, used only as diagnostics — they play no role in equality or contract checks. A class name or annotation text becomes the display name for related errors in that scope. Labels never enter values and disappear at scope exit; unlabeled values display structurally (`record {x: int} ...`). Across branches, loops, and exception paths, a label is retained only when the same label can be established; otherwise the value falls back to an anonymous structural display.

When width checking accepts a value with extra fields, attribute errors still retain the annotation label written by the receiver. For example, after `p: Point = Coord(1, 2)`, `p.z` can report `record Point {x: int, y: int} has no field 'z'` — `Point` is only a diagnostic label and does not mean the value's schema was rewritten.

## 8. Creating VMs

Sericite code can create new VMs, and the code inside a VM is also sericite:

```python
sub = VM("print('hi')")          # source code string
out = sub.run()                  # run and get back all of its output (a string)
print(out)                       # 'hi\n'
sub.dispose()                    # release when done
```

VMs are mutually isolated environments for running code: a VM cannot see your variables or touch your files. At creation you can tighten quotas and grant functions.

The same VM can be driven repeatedly: deliver new source with `exec()`, feed input, set breakpoints, or single-step execution; you can also take snapshots at any time. Variables and imported modules persist across `exec()` deliveries, and resource usage accumulates; create another VM when a fresh environment is required. The full contract is in the [VM reference](vm-reference.md).

```python
sub = VM("", max_instructions=10000, functions={"double": double})
try:
    sub.exec(code)
except syntax_error as e:
    print("compile failed:", e.message)
except ... as e:
    print("execute failed:", e.message)
finally:
    sub.dispose()
```

VMs can be garbage-collected automatically, but using `dispose()` for explicit cleanup is the better practice.

To preserve files across independent VM executions, create a transferable workspace with `VFS()`. Its handle supports the same file methods listed in section 6; `VM(code, fs=fs)` moves the workspace into a new VM, and `take_fs()` retrieves it after a terminal state. Variables and imported modules do not move with the files. See the [VM reference](vm-reference.md) §§2–4 for the complete rules.

## 9. Modules and import

Modules and packages load from the current workspace. Each module has its own global namespace but shares that workspace with its importer.

### Modules, packages, and file paths

For example, suppose the current workspace contains:

```text
/
├── main.sericite
├── util.sericite
└── lib/
    ├── __init__.sericite
    ├── math.sericite
    ├── util.sericite
    └── sub/
        ├── __init__.sericite
        └── mod.sericite
```

Module names resolve from the workspace root by default: `util` maps to `/util.sericite`, and `lib.math` maps to `/lib/math.sericite`. The target may also be a package: `lib.math` can map to `/lib/math/__init__.sericite`.

Every intermediate directory must be a package with an `__init__.sericite`; namespace packages without an initializer are not supported. If both a module file and a package exist for the same name, or a parent is not a package, the import fails with `import_error`.

### Entry files and module resolution roots

`VM(source=code, fs=fs)` executes string code that has no file identity, resolving modules from the workspace root. `VM(entry_file=path, fs=fs)` instead executes an entry file from the workspace and uses the entry file's directory as the module resolution root:

```python
sub = VM(entry_file="/project/main.sericite", fs=fs)
```

In that entry, `import util` uses `/project/util.sericite`, and `import lib.math` uses `/project/lib/math.sericite`. Relative imports also resolve within their current package before landing under this directory.

Entry paths follow ordinary file-path normalization. The module resolution root changes only import resolution, not the root used by file operations such as `read_file()`. See the [VM reference](vm-reference.md) §§2–4 for entry-loading timing, session persistence, and how module roots relate to workspace transfers.

### Import forms and bindings

```python
import util
import util as u
from util import answer
from util import answer as value

import lib.math
import lib.math as math
from lib.math import double
```

`import util` binds only the module object, while `from util import answer` binds only the named attribute; other module names do not spill into the current scope.

`import lib.math` binds the top-level package `lib` and, after loading it successfully, exposes `math` as its attribute. `import lib.math as math` binds the target module directly. `from pkg import child` first checks an existing package export, then attempts to load the submodule `pkg.child` when no such export exists.

See section 10 for compile-time restrictions such as wildcard imports.

### Relative imports

Relative imports are based on the defining module's package: `.` means the current package and `..` its parent.

```python
# /lib/math.sericite
from . import util       # loads lib.util
from .util import answer

# /lib/sub/mod.sericite
from ..util import answer  # loads lib.util
```

An entry module outside a package cannot use relative imports, and escaping the top-level package raises `import_error`. A relative form is resolved to a canonical module name, then loaded under the same rules as an absolute import.

### Execution environment and scope

- Import loads a module when execution reaches the statement and may appear in functions, conditionals, and `try`; imported bindings follow ordinary lexical scope.
- A module function reads globals from its defining module.

### Cache, failures, and errors

- After a canonical module name executes successfully in a VM, it is cached; repeated imports return the same module object, and the cache lasts for that VM's lifetime. Transferring the workspace to another VM does not carry the cache; the new VM loads modules again from the transferred files.
- Changing a source file does not automatically reload a cached module.
- Failed imports are not cached, so the import can be retried after fixing the file; output and file side effects that already happened are not rolled back.
- Direct and indirect circular imports, missing modules, and missing requested exports raise the catchable `import_error`; syntax, runtime, and resource errors raised by the module itself retain their original kinds.

### Module objects

Module objects support attribute reads but not attribute writes.

## 10. Explicitly not writable (rejected at compile time)

- `from x import *`, `del`, and dunder names
- `*args`/`**kwargs`, chained comparisons, and slice assignment
- starred unpacking, list targets, and subscript/attribute unpacking leaves
- set comprehensions and generator expressions
- class field defaults, methods, and inheritance
- annotated assignments without a value at statement level (`x: T`) — class-body field declarations like `y: int` are the exception
- rebinding builtin names (`print`/`len`/`wrap` etc.) or contract names (`any`/`bool`/`list`/`dict`/`tuple`) — contract names may only appear in annotation positions

## 11. A complete example

```python
# A tiny inventory ledger: one program that walks through Sericite's main features.
# Each section matches a chapter of this reference, noted in the comments.

# ---------- records: structural contracts (section 7) ----------
class Item:
    sku: str
    name: str
    qty: int
    price: float

class SkuRef:
    sku: str

# Construction: positional args follow declaration order; keyword args work in any order
apple = Item("A-1", "apple", 3, 0.5)
milk = Item(sku="M-2", name="milk", qty=10, price=1.25)

# Dot access reads and writes members; writes are still checked against the contract
milk.qty = milk.qty - 1
print("milk left:", milk.qty)        # 9

# Structural equality: schemas compare by field set, independent of declaration order
class ItemRev:
    price: float
    qty: int
    name: str
    sku: str
print("same schema:", Item == ItemRev)   # True

# Annotations are runtime contracts (section 7): width-based check, extra fields allowed
def describe(ref: SkuRef) -> str:
    return "sku=" + ref.sku
print(describe(apple))               # sku=A-1 (Item passes as SkuRef because the check is width-based)

# Wrap and unwrap
raw = unwrap(apple)
print("unwrapped:", raw)             # {'sku': 'A-1', 'name': 'apple', 'qty': 3, 'price': 0.5}
clone = wrap(Item, raw)
print("round trip:", clone == apple)  # True

# ---------- functions: default args, keyword args, recursion (section 4) ----------
def restock(qty: int, step: int = 5) -> int:
    return qty + step

def total_value(items: list) -> float:
    total = 0.0
    for it in items:
        total = total + it.qty * it.price
    return total

def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

print("restock:", restock(3), restock(3, step=20))   # 8  23

# ---------- decorators (section 4): equivalent to double = logged(double) ----------
def logged(func):
    def wrapper(x):
        print("  [log] in:", x)
        result = func(x)
        print("  [log] out:", result)
        return result
    return wrapper

@logged
def double(x):
    return x * 2

print("double:", double(21))         # 42, with a log line before and after

# ---------- closures (section 4): captured by reference, reads the latest binding ----------
def make_reader():
    x = 1
    def read():
        return x
    x = 2
    return read
print("closure:", make_reader()())   # 2, not 1

# ---------- control flow (section 3) ----------
inv = [apple, milk, Item("B-3", "bread", 0, 2.0)]

# for/else: the else runs only when there was no break
sold_out = False
for it in inv:
    if it.qty == 0:
        sold_out = True
        break
else:
    print("no sold-out items")
if sold_out:
    print("some item is sold out")

# while/else: the else runs only when there was no break; continue / pass are legal too
n = 6
while n > 0:
    n = n - 1
    if n % 2 == 0:
        continue
    if n == 1:
        break
else:
    print("loop exhausted")
print("stopped at", n)               # 1

flag = False
if flag:
    pass                             # empty branch placeholder
else:
    print("flag off")

# ---------- exceptions (section 5) ----------
def parse_qty(text):
    try:
        return int(text)
    except conversion_error as e:
        print("  bad number:", e.message)
        return 0
    finally:
        print("  parse done")

print("parse:", parse_qty("12"), parse_qty("oops"))   # 12  0

# filter by kind + raise a string (a raise_error), which propagates up
def load_config():
    try:
        text = read_file("/config.txt")
    except file_not_found:
        raise "config missing"       # raise_error, catchable
    return text

try:
    load_config()
except raise_error as e:
    print("config:", e.message)

# custom raise + bare except as the catch-all
try:
    raise "demo error"
except zero_division:
    print("won't happen")
except:
    print("caught by bare except")

# ---------- files and sub-VMs (sections 6 and 8) ----------
write_file("/report.txt", "inventory ok")
print("report exists:", path_exists("/report.txt"))   # True
print("files:", list_dir("/"))                        # ['report.txt']

# A sub-VM is an isolated workspace: feed it input, read its output; quotas can only tighten
checker_code = """
a = int(input())
b = int(input())
print("sum from sub:", a + b)
"""
checker = VM(checker_code, max_instructions=1000)
sub_out = checker.run(["7", "8"])
print("sub vm says: " + sub_out)     # sum from sub: 15

# Grant it a function (kept by reference to its defining environment)
def times_ten(x):
    return x * 10
worker = VM("""
n = int(input())
print(times_ten(n))
""", functions={"times_ten": times_ten})
print("worker says: " + worker.run(["6"]))   # 60

# A sub-VM has its own filesystem: preset a file, then retrieve the file it wrote
fs = VFS()
fs.write_file("/input.txt", "hello")         # configure a detached workspace first
proc = VM("""
text = read_file("/input.txt")
write_file("/output.txt", text + "!")
""", fs=fs)
proc.run()
fs = proc.take_fs()
print(fs.read_file("/output.txt"))           # hello!

# Single-step (by statement or instruction) and inspect snapshots
dbg = VM("x = 1\ny = x + 1\nprint(y)")
s = dbg.step()                                # run one statement and return a snapshot
print(s["state"], s["last_line"])             # ready 1
s = dbg.step_instruction()                    # run one instruction
print(s["last_line"])                         # 2
print(dbg.snapshot()["state"])                # ready (snapshot does not advance)
dbg.run()
print(dbg.snapshot()["state"])                # done

# Wrap up: aggregate and print the final results
grand = total_value(inv)
print("grand total:", grand)
print("factorial(5):", factorial(5))
```
