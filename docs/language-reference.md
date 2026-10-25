# Sericite Language Reference

Sericite is a scripting language whose syntax is a subset of Python — it reads like Python, but **not every Python construct is legal**, and some semantics have their own rules. This document is self-contained: read it and you can start writing. It describes the language behavior of Sericite 0.4.4.

## 1. What it looks like

```python
name = "world"            # assignment
print("hello", name)      # prints: hello world
x = input()               # read one line (a string)
```

## 2. Types and operators

Built-in types: `int`, `float`, `str`, `bool`, `None`, `list`, `dict`, plus user-defined `record`s (see section 7).

```python
7 / 2        # 3.5 (division always yields float)
7 // 2       # 3
7 % 3        # 1
"ab" + "cd"  # string concatenation (only +; no * repetition, no f-strings, no slicing)
"""line1
line2""" # multi-line
[1, 2] + [3] # list concatenation
not x        # logical not; and / or short-circuit
1 < 2        # comparison: == != < <= > >= (no chaining like a < b < c)
"a" in {"a": 1}    # in / not in: dict keys, list elements, str substrings
```

Key differences from Python (mistakes raise `type_error`):

- `bool` does not participate in arithmetic: `True + 1` is an error.
- Cross-type ordering comparison is an error: `1 < "a"` raises (`==`/`!=` may cross types, evaluating to False/True).
- Dict keys may only be `str/int/float/bool/None`; reading a missing key raises `key_error`.
- Strings support integer-index reads only (`s[0]`); no writes, no slicing. Lists support indexed reads and writes.

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

for item in [1, 2, 3]:      # for iterates: list, dict (keys), str (chars), range() results
    print(item)
for k in {"a": 1, "b": 2}:
    print(k, "->", ...)     # values via d[k]
else:
    print("no break")     # for/else

pass                        # empty statement, legal

label = "big" if x >= 10 else "small"   # ternary (short-circuits: only the chosen branch runs)
```

Note: the for loop variable must be a single name (`for a, b in ...` is not supported). Iterating a list is a live view (edits during iteration are visible); iterating a dict is a snapshot of its keys.

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

## 5. Exceptions

```python
try:
    x = 1 / 0
except zero_division as e:   # filter by error kind; e is the message string
    print("caught:", e)
except:                      # bare except catches everything catchable
    print("wrong")
else:
    print("no error")
finally:
    print("always runs")

raise "something wrong"      # raises kind raise_error, catchable
raise                        # bare raise inside except: re-raise the current error
```

An `except` filter must name a defined error kind; it is not a variable or an arbitrary binding name. Unknown names, including misspellings, are rejected at compile time with a `validation_error`. Use `except kind as e` to filter by kind and bind the message string, or bare `except:` to catch everything catchable.

The catchable kinds are:

- General: `runtime_error`, `syntax_error`, `validation_error`, `type_error`, `name_error`, `arity_error`, `raise_error`, `input_error`.
- Operations and contracts: `zero_division`, `conversion_error`, `index_error`, `key_error`, `attribute_error` (missing/forbidden record member), `contract_error` (construction, annotation, wrap, or field-write contract failure).
- Files and FFI: `file_not_found`, `is_directory`, `not_directory`, `ffi_error`.

Exceptions propagate across functions. `resource_exhausted` (quota exhaustion) and `internal_error` are defined kinds but are not catchable.

## 6. Built-in functions

- `input()` / `print(...)`: read a line / write values separated by spaces. `print(..., end=text)` replaces the default trailing newline with `text`; use `end=""` for no trailing newline. `end` is keyword-only and must be a string.
- `len(x)` (str/list/dict), `int(x)`, `float(x)`, `str(x)`, `range(...)` (returns a list).
- Files (text only): `read_file(path)`, `write_file(path, text)`, `list_dir(path)`, `path_exists(path)`. Paths look like `/notes/a.txt`; directories exist implicitly via path prefixes.
- Records: `wrap(schema, d)`, `unwrap(record)` — see section 7.

List and dict methods:

- `lst.append(x)`: append one item in place and return `None`.
- `lst.pop()` / `lst.pop(i)`: remove and return the last item or the item at `i`; negative indices work as in indexing. An empty list or invalid index raises `index_error`.
- `d.keys()` / `d.values()`: return a new list of keys or values in insertion order; later dict mutations do not change that list.
- `d.get(key)` / `d.get(key, default)`: return the value for `key`, or `None`/`default` when absent.
- `d.pop(key)` / `d.pop(key, default)`: remove and return the value for `key`; a missing key raises `key_error` unless a default is supplied.

These are closed method sets: other list/dict methods raise `attribute_error`, and strings still have no methods.

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

A class body only allows field declarations, in two forms: `x` (contract `any`, any value) or `y: int` (a specific contract). A contract can be `int/float/str/bool/list/dict`, `any`, or another schema (nested constraint). `any/bool/list/dict` are annotation-only contract names — they cannot be called or assigned; `int/float/str` remain conversion builtins. Defaults, methods, and inheritance are not supported yet.

Record semantics:

- **Fixed shape**: fields can never be added or removed — reading or writing an unknown field raises `attribute_error`; field values are mutable but must satisfy their contract (violations raise `contract_error`).
- **Structural equality**: two separately written identical class bodies produce equal schemas; records are equal when their schemas are structurally equal and their payloads are equal; a record never equals a dict — even with the same shape, a dict carries no contract.
- **Equality ignores declaration order; construction depends on it**: schema equality compares the field set — the order of `x` and `y` makes no difference; positional construction, however, binds arguments in each schema's own declaration order. Two schemas with the same fields in reversed order are equal, yet the same positional call produces records with different payloads. Prefer keyword construction when passing arguments positionally across separately defined schemas.
- **Wrap/unwrap**: `unwrap(p)` peels a record into a plain dict (a shallow copy); `wrap(Point, d)` wraps a dict whose keys exactly match the schema into a record (missing/extra keys raise `contract_error` naming them).
- Records are not indexable, not iterable, not usable as dict keys, and always truthy.

Annotations are **runtime contracts that actually execute** (not static types; there is no static checking):

```python
def move(p: Point) -> int:
    return p.x

p: Point = Point(1, 2)
```

Parameter annotations are checked at call time, return annotations at return time, and annotated assignments at assignment time; the three error messages name the responsible position (argument / return value / annotated assignment). Dicts are never auto-wrapped at annotation positions. The check is **width-based**: an argument record passes as long as it contains every field the expected schema requires, with compatible contracts; extra fields are fine.

Names in error messages are **compile-time, scope-local labels**: a class name or annotation text becomes the display name for related errors in that scope (e.g. `record Point {x: int} has no field 'y'`). Labels never enter values and disappear at scope exit; unlabeled values display structurally (`record {x: int} ...`). Across branches, loops, and exception paths, a label is retained only when the same label can be established; otherwise the value falls back to an anonymous structural display. Labels are diagnostics only — they play no role in equality or contract checks.

When width checking accepts a value with extra fields, attribute errors still retain the variable's annotation label while listing the value's actual, complete schema. Thus, after `p: Point = Coord(1, 2)`, `p.z` can report `record Point {x: int, y: int} has no field 'z'`; `Point` is only a diagnostic label and does not mean the value's schema was rewritten.

Records and schemas cannot cross the host FFI boundary (a host function receiving a record raises `ffi_error` — `unwrap` first); they pass between parent and child VMs by reference through granted functions, and contract checks still hold across VMs. Only structure crosses VMs: when a granted function reports an error inside a child VM, it does so under the granted name (the key in `functions={"f": ...}`) with structural descriptions — the definition-side function name and type labels never appear in the child's error text.

## 8. Creating VMs

Sericite code can create new VMs, and the code inside a VM is also sericite:

```python
sub = VM("print('hi')")          # source code string
out = sub.run()                  # run and get back all of its output (a string)
print(out)                       # 'hi\n'
```

VMs are mutually isolated workspaces: a VM cannot see your variables or touch your files — it has its own empty filesystem. Configuration:

```python
sub = VM(code, max_instructions=10000)   # quotas can only be tightened
sub.write_file("/input.txt", "data")     # preset a file for it
sub.feed_input("one line")               # feed input()
out = sub.run()
print(sub.read_file("/result.txt"))      # retrieve the file it wrote
```

Debugging: `sub.step()` single-steps statement by statement (returns a state snapshot dict), `sub.step_instruction()` steps instruction by instruction, `sub.snapshot()` shows locals/state, `sub.terminate()` kills it.

Granting functions to a VM (so it can call your functions, including ones granted to you):

```python
def double(x):
    return x * 2
sub = VM("print(double(21))", functions={"double": double})
sub.run()                        # prints 42
```

A granted sericite function retains its definition-side module variables, closure cells, and already-granted functions by reference, and builtins (`print`/`read_file` and other IO/filesystem services) also resolve back to the VM that defined it — a function value carries its whole world with it. Mutable state reachable through those environments is shared capability: only grant functions whose reachable state the child VM may observe or modify.

## 9. Explicitly not writable (rejected at compile time)

`import`, `del`, string methods, `*args/**kwargs`, chained comparisons, slicing, tuples, f-strings, dunder names, class field defaults/methods/inheritance, annotated assignments without a value at statement level (`x: T` — class-body field declarations like `y: int` are the exception). Builtin names (`print`/`len`/`wrap` etc.) and contract names (`any/bool/list/dict`) cannot be rebound; contract names may only appear in annotation positions.

## 10. A complete example

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
        print("  bad number:", e)
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
    print("config:", e)

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

# Grant it a host function (kept by reference to its defining environment)
def times_ten(x):
    return x * 10
worker = VM("""
n = int(input())
print(times_ten(n))
""", functions={"times_ten": times_ten})
print("worker says: " + worker.run(["6"]))   # 60

# Wrap up: aggregate and print the final results
grand = total_value(inv)
print("grand total:", grand)
print("factorial(5):", factorial(5))
```
