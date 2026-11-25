# Language and modules

This document defines the language surface of Sericite scripts, for checking syntax and runtime semantics. For detailed function and method signatures, see [general built-ins](02-builtins.md), [value type methods](03-types.md), and the pages for each object.

Sericite borrows part of Python's syntax but is not Python; language behavior not listed in this document cannot therefore be assumed to be available.

## Values and literals

| Type | Literal or source | Mutability |
|---|---|---|
| `None` | `None` | Immutable |
| `bool` | `True`, `False` | Immutable |
| `int` | `0`, `42`, `-3` | Immutable |
| `float` | `1.0`, `.5`, `1e3` | Immutable |
| `str` | `"text"`, `'text'`, triple-quoted strings, f-strings | Immutable |
| `list` | `[]`, `[1, 2]`, list comprehensions | Mutable |
| `tuple` | `()`, `(1,)`, `1, 2` | Immutable |
| `dict` | `{}`, `{"key": value}`, dict comprehensions | Mutable |
| schema | executing a `class` statement | structural contract value |
| record | calling a schema | field values mutable, field set fixed |
| module | `import` | read-only attributes |
| function | `def`, decorators, addons, bound methods | callable value |
| VM / VFS | `VM(...)` / `VFS()` | handles with a lifecycle |

A one-element tuple must write a trailing comma: `(1,)`. `(1)` is just a parenthesized integer. Tuple parentheses can be omitted in destructuring and in expressions such as `pair = 1, 2`.

Dict keys may only be `str`, `int`, `float`, `bool`, and `None`. Lists, tuples, dicts, records, schemas, functions, and handles cannot be dict keys. Dicts preserve insertion order.

Strings are Unicode text; there is no separate byte type. Although `max_string_bytes` is named in bytes, it actually limits the character count; the related quotas for file content and output use UTF-8 byte counts, see [VM limits](06-vm.md#limits).

## Names and reserved names

Names are used for variables, parameters, functions, schemas, module bindings, and fields. Names and attributes starting with double underscores are unavailable; the dedicated module name `__addon__` may only appear in the prescribed import syntax and cannot be referenced as an ordinary value.

The following built-in names cannot be rebound and cannot be overridden directly by imports:

```text
input print VM VFS len int float str repr range
read_file write_file delete_file rename_file copy_file
make_dir delete_dir rename_dir copy_dir list_dir path_exists
any bool list dict tuple wrap unwrap
```

`int`, `float`, and `str` can be called directly and can also serve as contract names. `any`, `bool`, `list`, `dict`, and `tuple` can only appear as contract names in annotation positions. The other built-ins can only be called directly, not saved as ordinary variables and then called indirectly.

## Operations and evaluation

### Arithmetic

| Operation | Supported operands and result |
|---|---|
| `a + b` | numeric addition; concatenation of strings, lists, or tuples of the same type |
| `a - b` | numeric subtraction |
| `a * b` | numeric multiplication; repetition of a string, list, or tuple by an integer in either direction |
| `a / b` | numeric division, result is `float` |
| `a // b` | floor division |
| `a % b` | modulo |
| `a ** b` | power, right-associative |
| `-a` | numeric negation |
| `not a` | truthiness negation, result is `bool` |

`bool` is not an integer in arithmetic: `True + 1` raises `type_error`. Sequences of different types cannot be concatenated. Repetition by zero or a negative number produces an empty sequence of the same type. Concatenation, repetition, and slicing all create new sequences; new sequences from lists and tuples copy their elements only shallowly.

Two integers raised to a non-negative integer power yield an `int`; involving a `float` or using a negative integer exponent yields a `float`. Power binds before unary minus: `-2 ** 2` equals `-(2 ** 2)`.

Main errors:

- zero divisor or modulus: `zero_division`;
- zero to a negative power: `zero_division`;
- an operation that would produce complex numbers: `type_error`;
- floating-point power overflow: `conversion_error`;
- a type that does not support the operation: `type_error`;
- integer bit width or string/sequence size exceeded: `resource_exhausted`.

Augmented assignment supports `+=`, `-=`, `*=`, `**=`, `/=`, `//=`, and `%=`. The target can be a name, a list/dict subscript, or a record field. The target address is evaluated once, then handled by the ordinary binary-operation and write rules. A list's `+=` and `*=` also create a new list rather than extending in place.

### Comparison and membership

`==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, and `not in` are supported. `is`, `is not`, and chained comparisons are not.

- `==` and `!=` can compare across types; different types are usually `False` and `True` respectively.
- Containers and records are compared recursively by structure. Comparing a container with itself takes an identity fast path.
- NaN is not equal to itself, including NaN in record fields and container elements; the same container object is still equal to itself.
- Cyclic containers are compared by coinductive structure and do not expand through infinite recursion.
- Ordering comparisons are only supported between numbers or between strings; other combinations raise `type_error`.
- Membership on `list`, `tuple`, and `str` checks elements or substrings; membership on `dict` checks keys.
- Schemas are compared by field names and field contracts, ignoring field declaration order; records additionally require both the schema and the payload to be equal. A record is not equal to a dict even when the shape is the same.

```python
nan = float("nan")
print(nan == nan)

items = [nan]
print(items == items)
print([nan] == [nan])
```

```text
False
True
False
```

### Truthiness and short-circuiting

`None`, `False`, numeric zero, the empty string, the empty list, the empty tuple, and the empty dict are false; other values are true. A record is always true.

`not` returns a boolean. `and` and `or` short-circuit and return the operand that decided the result, without coercing to `bool`. A conditional expression executes only the selected branch.

Precedence from low to high:

1. `or`
2. `and`
3. `not`
4. comparison and membership
5. `+`, `-`
6. `*`, `/`, `//`, `%`
7. unary `-`
8. `**`

Power allows a unary minus in the exponent position, for example `2 ** -2`. Use parentheses to make complex expressions clear.

## Assignment, indexing, and slicing

### Assignment and destructuring

```python
name = value
first = second = value
items[0] = value
mapping["key"] = value
point.x = value
```

Chained assignment evaluates the right side only once. Multi-target forms do not allow mixing in subscript or attribute targets.

Fixed-length name destructuring supports lists, tuples, strings, and dicts; a dict is iterated over its keys. Destructuring can nest, but leaves can only be names:

```python
a, b = (1, 2)
x, (y, z) = [3, (4, 5)]
```

A length mismatch raises `value_error`, and a non-iterable value raises `type_error`. Starred destructuring, list targets, and subscript/attribute destructuring leaves are not supported.

An annotated assignment is written `name: Contract = value` and checks the contract at assignment time. A bare statement-level annotation `name: Contract` is invalid; the field declaration in a `class` body is the only exception.

### Subscripting

Strings, lists, and tuples accept integer subscripts, including negative indexes; out of bounds raises `index_error`. Only lists support subscript writes. Dicts are read by key, a missing key raises `key_error`, and writes can add or replace keys.

The subscript position must be strictly `int`; `bool` is not accepted as a subscript integer. Records cannot be subscripted; access fields via dot.

### Slicing

Strings, lists, and tuples support read-only slicing:

```python
value[start:stop]
value[start:stop:step]
```

All three positions can be omitted; each position can only be `int` or `None`. The default step is 1, and the step cannot be zero. Negative indexes, out-of-bounds truncation, and negative steps follow Python's slicing rules; the result is always a new sequence. Slice assignment is invalid.

## Control flow

Supported:

```python
if condition:
    pass
elif other_condition:
    pass
else:
    pass

while condition:
    break
else:
    pass

for item in iterable:
    continue
else:
    pass

result = yes_value if condition else no_value
```

- The `else` of `while`/`else` and `for`/`else` runs only when the loop did not exit via `break`.
- `for` can iterate over `list`, `tuple`, `dict`, `str`, and the list returned by `range()`.
- A `for` target can be a name or fixed-length name destructuring.
- Iterating a list uses a live view; modifications inside the loop affect later iteration. Iterating a dict uses a snapshot of its keys from the start.
- `pass` is the empty statement.
- `with`, `match`, `async`, `await`, `yield`, `lambda`, `assert`, `del`, and generator syntax are not supported.

### Comprehensions

List and dict comprehensions are supported:

```python
squares = [x * x for x in range(6) if x % 2]
pairs = [(x, y) for x in [1, 2] for y in [3, 4]]
reverse = {value: key for key, value in mapping.items()}
```

Each comprehension has its own scope: loop targets do not leak outside and do not overwrite outer bindings of the same name, but outer variables can be read. Multiple `for`s, multiple `if`s, and name destructuring are supported.

The outermost iterable expression is evaluated once in the outer scope; later iterable expressions, conditions, and result expressions are evaluated left to right in the comprehension scope. A dict comprehension evaluates the key before the value, and repeated keys keep the later-written value. Results are subject to list, tuple, and dict size and resource quotas.

Set comprehensions and generator expressions are invalid.

## Functions

### Definition and parameters

```python
def function(a, b=default, *args, **kwargs):
    return a
```

Parameters are composed in this order:

1. ordinary positional/keyword parameters;
2. an optional `*args`, collecting remaining positional arguments into a tuple;
3. an optional `**kwargs`, collecting extra keyword arguments into a dict.

Ordinary parameters may have defaults, and the default value is evaluated once at function definition. Positional-only `/`, keyword-only parameters, and additional keyword-only default forms are not supported.

Calls support positional arguments, keyword arguments, `*iterable`, and `**mapping`:

```python
def collect(a, *args, **kwargs):
    return [a, args, kwargs]

print(collect(1, *[2, 3], x=4))
```

```text
[1, (2, 3), {'x': 4}]
```

`*` can expand a list, tuple, string, or dict; a dict expands its keys. `**` accepts only a dict, and all keys must be strings. Argument expressions are evaluated left to right in source order.

Error rules:

- duplicate parameter names, duplicate explicit keyword labels: `syntax_error`;
- missing arguments, extra arguments, unknown keywords, the same parameter bound twice: `arity_error`;
- wrong `*`/`**` expansion value type: `type_error`;
- parameter or return contract not satisfied: `contract_error`.

`return` without a value returns `None`; a function falling off the end also returns `None`. Recursion is legal, and call-frame count is limited by `max_frames`.

### Lexical scope and closures

Module-level bindings belong to the defining module. Without a `global` or `nonlocal` declaration in a function, any name assigned anywhere in that function is local throughout the function; an unbound local does not fall back to a module variable of the same name.

Nested functions capture the enclosing function's local variables by reference and read the latest binding at call time. Closures produced by the same outer call share a capture cell, and environments of different calls are independent. `for` does not create a new binding per iteration; use default parameters when you need a snapshot at definition time.

```python
count = 0

def increment():
    global count
    count += 1


def make_counter():
    count = 0
    def next_value():
        nonlocal count
        count += 1
        return count
    return next_value
```

- `global name` reads and writes the current defining module's module-level binding.
- `nonlocal name` binds the nearest enclosing function variable and can pass through intermediate functions that do not bind that name.
- A module-level `global` is legal; a module-level `nonlocal` or a `nonlocal` with no enclosing binding raises `syntax_error`.
- A declaration that coincides with a parameter, another declaration of the same name, or a conflicting lexical use is rejected at compile time.

Ordinary assignment, augmented assignment, destructuring, loops, imports, function definitions, and exception bindings all obey these declarations.

### Decorators

```python
@decorator
def function():
    pass
```

This is equivalent to defining the function first, then executing `function = decorator(function)`. Decorator expressions are evaluated top to bottom, and stacked decorators are applied bottom to top. The decorator result rebinds the function name, so it should be a callable value for the function to remain callable.

## Records and schemas

### Definition and construction

`class` defines a runtime schema. It contains only field declarations and does not support inheritance, methods, decorators, or field defaults:

```python
class Point:
    x: int
    y: int

class Bag:
    content
```

The contract of `content` is `any`. A class body may also be just `pass`, creating an empty schema with no fields. Every execution reaching a `class` statement creates a schema value.

Calling a schema constructs a record:

```text
Schema(field1, field2, ...) -> record
Schema(name=value, ...) -> record
```

Positional arguments bind by field declaration order, keyword arguments bind by field name, and the two can be combined. Every field must be provided exactly once; a missing field, an extra field, an unknown field, a repeated binding, or a field contract failure all raise `contract_error`. Construction errors are not `arity_error`.

Fields are read and written through `record.field`. The field set is fixed and cannot be added to or removed; a nonexistent field raises `attribute_error`, and a write that violates the field contract raises `contract_error`. Records cannot be iterated, subscripted, or used as dict keys.

### Contracts

Available contracts:

- `int`, `float`, `str`, `bool`, `list`, `dict`, `tuple`;
- `any`, accepting any value;
- another schema, forming a nested structural contract.

`None` is a value, not a contract. An explicit `None` annotation in parameters, return values, fields, and annotated assignments with a value raises `syntax_error`; omit the annotation or use `any` when no check is needed.

Annotations are genuinely checked at runtime:

| Position | Checked when | Responsibility position |
|---|---|---|
| `def f(x: Contract)` | at call time | argument |
| `def f(...) -> Contract` | at return time | return value |
| `x: Contract = value` | at assignment time | annotated assignment |
| `record.field = value` | at field write time | field |
| schema construction / `wrap()` | at construction time | field |

The check is a width check: when the expected contract is a schema, the actual record passes as long as it contains all expected fields and the corresponding contracts are compatible; extra fields are allowed. A dict is not automatically wrapped into a record.

### Structural equality and diagnostic labels

Schema equality looks only at field names and contracts, not declaration order; positional construction, however, still binds by each declaration order. So prefer keyword construction when passing values across definition sites.

Class names and annotation names are only compile-time, scope-local diagnostic labels used in error text. They do not enter values, do not participate in equality or contract checks, and expire outside the defining scope. When no label is available, the structure is shown. When control flow cannot determine a single label, it also falls back to the anonymous structure.

`wrap(schema, data)` and `unwrap(record)` convert between dicts and records; see [general built-ins `wrap`](02-builtins.md#wrap) and [general built-ins `unwrap`](02-builtins.md#unwrap).

## f-strings and formatting

Ordinary interpolation, multiple fragments, multiple lines, nested f-strings, escaped braces, debug forms, and dynamic format specifiers are supported:

```python
name = "world"
value = 12.345
print(f"hello {name}")
print(f"{value:.2f}")
print(f"{value=}")
print(f"{value:{width}.{precision}f}")
```

The last two examples require `width` and `precision` to be defined. `{expr=}` outputs the expression text, an equals sign, and the value's `repr`.

Conversion specifiers:

| Form | Meaning |
|---|---|
| `{value}` | default string rendering |
| `{value!s}` | converted through `str()` semantics first |
| `{value!r}` | rendered through safe `repr` first |
| `{value!a}` | like `!r`, and recursively escapes non-ASCII characters |

Conversion runs before the format specifier. With a non-empty format specifier and no explicit conversion, only `str`, `int`, and `float` are accepted.

The format specifier is, in order:

```text
[[fill]align][sign][z][#][0][width][grouping][.precision][type]
```

- Alignment: `<`, `>`, `^`, `=`; `=` applies only to numbers.
- Sign: `+`, `-`, space; `z` controls floating-point negative zero; `#` is the alternate form.
- Grouping: `,` or `_`.
- String types: empty or `s`, which can use width and precision truncation but not number-only options.
- Integer types: empty, `b`, `c`, `d`, `o`, `x`, `X`; integers using these integer forms cannot have a precision. Integers can also use float types.
- Float types: empty, `e`, `E`, `f`, `F`, `g`, `G`, `%`.

An invalid format specifier raises `conversion_error`; a presentation type not supported by that type raises `type_error`; a result over the limit raises `resource_exhausted`.

## Modules and packages

### Module resolution

| Module name | File form | Package form |
|---|---|---|
| `util` | `/util.sericite` | `/util/__init__.sericite` |
| `lib.math` | `/lib/math.sericite` | `/lib/math/__init__.sericite` |

Every intermediate directory must be a package containing `__init__.sericite`; namespace packages are not supported. The same module name existing as both file and package, a parent that is not a package, a missing module, or a missing named export all raise `import_error`.

`VM(source=...)` resolves modules from the workspace root. `VM(entry_file=...)` resolves modules from the entry file's directory, and the module root is retained for the session. The module root only affects imports; it does not change the root of file functions. File paths are always based on the whole workspace root.

### Import forms and bindings

```python
import util
import util as u
import lib.math
import lib.math as math
from util import answer
from util import answer as value
from lib.math import double
```

- `import util` binds the module object.
- `import lib.math` binds the top-level package `lib`, and after success mounts `math` onto the package's attribute.
- `import lib.math as math` binds the target module directly.
- `from util import answer` binds only the specified export.
- `from pkg import child` first reads the package's existing export; if absent, it tries to load the submodule `pkg.child`.
- Modules support dot reads but not attribute writes.
- Wildcard imports are not supported.

Relative imports are based on the package of the currently defining module: `.` means the current package and `..` means the parent package.

```python
from . import util
from .util import answer
from ..util import answer
```

An entry module outside a package cannot use relative imports, and going above the top-level package raises `import_error`.

### Execution, caching, and failure

Import happens when execution actually reaches the statement and can appear inside functions, conditionals, and `try`. Bindings follow ordinary lexical scope. Each module has an independent global namespace; a module function's global names are always read from its own defining module.

Within the same VM, a successfully executed canonical module name enters the cache, and a repeated import returns the same module object. Modifying a file does not reload the cache; transferring the VFS does not carry the module cache.

Direct or indirect circular imports raise `import_error`. A failed import does not cache the failure, so it can be retried after a fix, but output and file side effects before the failure are not rolled back. A module's own syntax, runtime, and resource errors keep their original kind.

## `__addon__`: the capability entry point

Every VM has the preloaded built-in module `__addon__`, which can only be imported in the following forms:

```python
from __addon__ import name
from __addon__ import name as local_name
from __addon__ import first, second as alias
```

This module corresponds to no VFS file and cannot be overridden by a same-named file in the workspace. Every source module must import it itself; an import does not enter another module's global namespace. Import names and aliases follow ordinary lexical scope, and a successful import persists in the module scope reused by later `exec()`.

Only absolute `from __addon__ import ...` is allowed. The following forms are invalid: `import __addon__`, `import __addon__.http`, relative imports, importing `__addon__` from a package, wildcard imports, and double-underscore export names.

A missing export is an ordinary `import_error`. An addon's own call contract is defined by its provider; data-boundary violations use `addon_error`. For creating child VMs and re-granting addons, see [VM](06-vm.md#addon-granting).

## Commonly rejected compile-time forms

Besides the limits already listed, the following forms are also unavailable:

- `@`, bit shifts, bitwise operations, unary `+`, `is`, `is not`;
- `*`/`**` expansion in literals; `**` expansion in dict literals;
- chained comparisons, slice assignment, starred destructuring;
- sets, set comprehensions, generator expressions;
- `lambda`, `with`, `assert`, `match`, `async`, `await`, `yield`, `del`;
- class inheritance, methods, decorators, field defaults;
- bare statement-level annotations;
- wildcard imports and double-underscore names;
- rebinding built-in names or treating annotation-only contract names as ordinary values.

These errors usually report `syntax_error`. The same source cannot catch its own compile-time error with its own `try`, because compilation happens before execution; a parent program creating or driving a child program can catch the child source's `syntax_error`.
