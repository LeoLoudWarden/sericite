# Errors and exceptions

Sericite uses fixed error kinds. A kind is a string identifier, not an instantiable exception class, and there is no inheritance hierarchy. Scripts match kinds through static `except` filters and read diagnostics through the exception record.

## Catching and cleanup

```python
try:
    value = int(text)
except conversion_error as error:
    print(error.message)
else:
    print(value)
finally:
    print("finished")
```

- When the `try` body has no error, `else` runs, then `finally` runs.
- When a catchable error occurs, `except` branches are tried in source order, and `else` is skipped after a hit.
- `finally` runs on normal completion, on error propagation, and on early exit via `return`, `break`, or `continue`.
- The same source cannot catch its own compile-time `syntax_error`, because execution has not begun; a controller can catch compile errors of child VM source.
- A VM breakpoint pause is not an exception and does not trigger the target script's `except` or `finally`. Forcefully disposing a running target also does not run the target script's `finally`.

## Static filters

Legal forms:

```python
except conversion_error:
    pass
except file_error:
    pass
except (file_error, input_error):
    pass
except ... as error:
    pass
except:
    pass
```

Filter names must be written directly and cannot be replaced by variables, attributes, or runtime expressions. The parenthesized form must be non-empty; members can only be concrete kinds or fixed filter groups, and they can be mixed and repeated.

`except ...` and a bare `except` both match all catchable kinds; the former can bind the exception record with `as`, while the latter does not bind. Unknown names, empty filters, dynamic filters, and explicitly written uncatchable kinds all raise `syntax_error`.

Group names only participate in compile-time filtering and are not runtime kinds. `error.kind` is always the actual error, not `file_error` or `lookup_error`.

## The exception record

`except ... as error` binds a record with three fields:

| Field | Type | Meaning |
|---|---|---|
| `kind` | `str` | the actual error kind |
| `message` | `str` | the safe error text for scripts |
| `frames` | `list` | the current program's call stack |

Each item in `frames` is a record with two fields:

| Field | Type | Meaning |
|---|---|---|
| `function` | `str` | the safe function name |
| `line` | `int` or `None` | the source line number, or `None` when unavailable |

Frames are ordered from the outermost call to the actual error point, with the last frame being the error point. Caller frames point at the line that actually made the call. Each program exposes only its own safe stack; foreign code across VMs uses the granted name and hides defining-side line numbers.

The exception binding is an ordinary binding in the current scope; it remains after leaving `except`, and a nested same-named binding overrides it. The exception record and frame records are safe copies; modifying them does not change the internal error.

## Raising and re-raising

```text
raise message
raise
```

`raise message` accepts only a string and produces `raise_error`. Other values raise `type_error`. Exception objects, custom kinds, and `raise ... from ...` are not supported.

A bare `raise` inside an `except` branch re-raises the current error, keeping the original call stack. A re-raise after finally has stashed the exception also keeps the original stack; a new error raised inside `except` or `finally` uses a new call stack.

## Catchable kinds

The table below lists the concrete kinds a script can write in `except`. "Catchable" is still subject to runtime rules such as the source of resource errors.

| kind | Typical meaning |
|---|---|
| `runtime_error` | general runtime failure, invalid lifecycle, or object-state operation |
| `syntax_error` | source parsing, language whitelist, or static filter validation failed |
| `type_error` | unsupported type in an operation, call, conversion, or API parameter |
| `name_error` | the name is undefined in the current lexical scope |
| `arity_error` | wrong argument count, repeated binding, or unknown keyword for a user function |
| `raise_error` | the script raised it via `raise "text"` |
| `input_error` | the input source is clearly closed and there will be no more input |
| `import_error` | module, package, relative import, circular import, or export resolution failed |
| `zero_division` | division by zero, modulo by zero, or zero to a negative power |
| `conversion_error` | numeric conversion or format-specifier conversion failed |
| `index_error` | a sequence subscript or `list.pop()` index is out of bounds |
| `key_error` | a dict key is missing, or `dict.pop()` without a default has a missing key |
| `value_error` | destructuring length mismatch, or a sequence `index()` did not find the value |
| `attribute_error` | a member of a module, record, VM, VFS, or container does not exist or is inaccessible |
| `contract_error` | record construction, field write, annotation, or `wrap()` contract failed |
| `file_not_found` | a file or directory source does not exist |
| `file_exists` | the target of a non-overwriting operation already exists, or the `make_dir()` target already exists |
| `is_directory` | a file operation met a directory |
| `not_directory` | a directory operation met a file, or an intermediate path segment is a file |
| `file_limit_error` | a file-count, per-file-size, or file-storage constraint refused the change |
| `addon_error` | an addon's data-boundary or value-copy contract was violated |
| `resource_exhausted` | instructions, memory, output, call frames, size, VM count, depth, or another resource was exhausted |

`file_limit_error` is an ordinary recoverable error. After handling it you can shrink the file world and retry; the session does not terminate merely because of this error.

## Fixed filter groups

| Group name | Expanded concrete kinds |
|---|---|
| `file_error` | `file_not_found`, `file_exists`, `is_directory`, `not_directory`, `file_limit_error` |
| `lookup_error` | `index_error`, `key_error` |

When a specific error needs priority handling, put its branch before the group:

```python
try:
    value = read_file(path)
except file_not_found:
    value = ""
except file_error as error:
    print(error.kind)
```

## Source boundary of resource errors

`resource_exhausted` can be written in `except`, but it cannot be used to break out of your own quota:

- Resource exhaustion of the current program or any ancestor cannot be caught by that program itself.
- A `resource_exhausted` passed from another terminated child program can be caught by a still-live parent program.
- The file-constraint `file_limit_error` is not execution-account exhaustion and is caught as an ordinary error.

## Uncatchable kinds

| kind | Meaning |
|---|---|
| `host_error` | an out-of-contract failure occurred in an addon implementation outside the script and cannot be safely recovered |
| `internal_error` | an internal invariant or unexpected implementation failure in the Sericite engine |

These two kinds cannot be caught by a specific filter, `except ...`, or a bare `except`. They describe governance or implementation failures and should not be used as ordinary business control flow.
