# General built-ins

This document lists the script built-ins that are not tied to a specific container, file system, or VM handle. File functions are in [files and directories](04-files.md); the constructors `VM` and `VFS` are in [VM](06-vm.md) and [VFS](07-vfs.md) respectively.

In signatures, `*` means the following parameters can only be passed by keyword. Parameters without a stated default must be provided. Unless otherwise noted, built-ins do not modify their arguments.

## `input`

```text
input() -> str
```

Reads one line from stdin and returns the string, without the trailing newline.

- Returns immediately when input is available.
- When the program temporarily has no input but it may arrive later, it enters `waiting_input` rather than an exception; the controller can keep feeding input.
- Raises `input_error` when the input source is clearly closed and there will be no more input.

`input()` does not read the parent program's implicit standard input. A child program's input is provided explicitly through `run(inputs)` or `feed_input()`.

## `print`

```text
print(*values, sep=" ", end="\n") -> None
```

Renders each value to text and writes them to the current program's stdout in order.

| Parameter | Type | Meaning |
|---|---|---|
| `*values` | any value | zero or more values to output |
| `sep` | `str` | the separator between adjacent values, a single space by default |
| `end` | `str` | the trailing text, a newline by default |

With no values, only `end` is output. `sep=""` or `end=""` means no separator or no trailing text respectively. A non-string `sep` or `end` raises `type_error`.

Every call produces one complete chunk of output, including the separator and trailing text; it all counts toward the output quota. Output may first be forwarded through the VM's configured writer; see [VM output](06-vm.md#output-forwarding-and-buffering).

Containers use safe recursive rendering; cyclic or repeated structures use placeholders and are not expanded infinitely.

## `len`

```text
len(value) -> int
```

Returns the character count of a string, the element count of a list or tuple, or the key count of a dict. Other types raise `type_error`.

## `int`

```text
int(value) -> int
```

Converts an `int`, `float`, `bool`, or `str` to an integer.

- Integers pass through unchanged, still subject to the integer bit-width quota.
- Booleans become `1` or `0`.
- Floats truncate toward zero; NaN and infinities cannot be converted and raise `conversion_error`.
- Strings ignore surrounding whitespace and parse as a signed decimal integer; invalid text raises `conversion_error`.
- Other types raise `type_error`.

Allowing booleans to be converted here does not mean booleans can take part in ordinary arithmetic.

## `float`

```text
float(value) -> float
```

Converts an `int`, `float`, `bool`, or `str` to a float.

Strings ignore surrounding whitespace and accept ordinary decimal float spellings as well as implementation-supported special float texts such as `nan` and `inf`. Invalid text raises `conversion_error`; other types raise `type_error`.

## `str`

```text
str(value) -> str
```

Returns the value's string representation. Strings return themselves; other scalars, containers, records, schemas, functions, modules, and handles use Sericite's safe rendering rules.

Containers are rendered recursively, and string elements are quoted inside containers. The rendered result is subject to `max_string_bytes`, and exceeding it may raise `resource_exhausted`.

## `repr`

```text
repr(value) -> str
```

Returns a representation suitable for a single-line diagnostic. Top-level strings are also quoted, and newlines, tabs, quotes, and backslashes are escaped; containers recursively use the same rules.

`str("a\n")` contains an actual newline, while `repr("a\n")` returns a single-line text like `'a\\n'`. Rendering work and results are both subject to resource quotas.

## `range`

```text
range(stop) -> list
range(start, stop) -> list
range(start, stop, step) -> list
```

Generates values by Python `range`'s integer-interval rules, but returns a list directly rather than a lazy range object.

| Parameter | Default | Meaning |
|---|---:|---|
| `start` | `0` | the starting value, included in the result |
| `stop` | none | the ending value, excluded from the result |
| `step` | `1` | the step, which can be negative |

All three parameters must be strictly `int`; booleans are not accepted. A parameter count other than 1 to 3 raises `arity_error`; a type error raises `type_error`; a zero step also raises `type_error`. The result length is subject to `max_list_size`.

```python
print(range(4))
print(range(3, 0, -1))
```

```text
[0, 1, 2, 3]
[3, 2, 1]
```

## `wrap`

```text
wrap(schema, data) -> record
```

Constructs a record satisfying the specified schema from a dict.

| Parameter | Requirement |
|---|---|
| `schema` | a schema value created by `class` |
| `data` | a dict whose key set must exactly match the schema's field set |

A missing field, an extra field, or a field value that violates the contract raises `contract_error`. A wrong parameter type raises `type_error`. Unlike positional construction from a schema, `wrap` does not use width checks: a dict cannot have extra keys.

Returns a new record whose field containers are built in the schema's declaration order; field values are shallow-copied, not recursively deep-copied.

## `unwrap`

```text
unwrap(record) -> dict
```

Returns a new dict of the record's fields, with field order kept from the record. The operation is a shallow copy: modifying the returned dict does not change the record's field bindings, but nested mutable values are still shared.

A non-record parameter raises `type_error`.

```python
class Point:
    x: int
    y: int

point = Point(1, 2)
data = unwrap(point)
data["x"] = 10
print(point.x, data["x"])
print(wrap(Point, data))
```

```text
1 10
record(x=10, y=2)
```
