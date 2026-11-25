# Value type methods

This document lists all public methods of `list`, `tuple`, `dict`, and `str`. The method set is closed; unlisted attributes raise `attribute_error`. Indexing, slicing, iteration, and operations are in [language and modules](01-language.md).

These methods take arguments positionally. A `None` in a signature means that position can be omitted or passed `None` explicitly. Methods can be passed as bound method values and still operate on the original object when called.

## `list`

```text
list() -> list
list(value) -> list
```

Accepts `list`, `tuple`, `str`, or `dict`. `list`/`tuple` build from elements, `str` builds from characters, and `dict` builds from keys; elements are not recursively copied. Other types raise `type_error`. `list()` returns an empty list.

### `list.append`

```text
list.append(value) -> None
```

Appends a value in place to the end of the list. Raises `resource_exhausted` when the list reaches `max_list_size`.

### `list.pop`

```text
list.pop() -> any
list.pop(index) -> any
```

Removes and returns the element at the specified position; `index=-1` by default. Negative indexes are supported. `index` must be strictly `int`; an empty list or out-of-bounds index raises `index_error`, and a type error raises `type_error`.

### `list.count`

```text
list.count(value) -> int
```

Returns the number of elements structurally equal to `value`, without modifying the list.

### `list.index`

```text
list.index(value, start=None, stop=None) -> int
```

Returns the position of the first element structurally equal to `value` within the search interval. Boundary rules are the same as slicing, supporting negative indexes and out-of-bounds truncation. Not found raises `value_error`; wrong boundary types raise `type_error`.

## `tuple`

```text
tuple() -> tuple
tuple(value) -> tuple
```

Tuples are not writable. Input and ordering rules are the same as `list`.

### `tuple.count`

```text
tuple.count(value) -> int
```

Returns the number of elements structurally equal to `value`.

### `tuple.index`

```text
tuple.index(value, start=None, stop=None) -> int
```

Returns the position of the first matching element within the search interval. The rules are the same as [`list.index`](#listindex); not found raises `value_error`.

## `dict`

```text
dict() -> dict
dict(value) -> dict
dict(**entries) -> dict
dict(value, **entries) -> dict
```

`value` must be one of the following:
- another dict;
- a list or tuple of two-element lists/tuples. A key-value pair whose length is not 2 raises `value_error`.

Otherwise `type_error` is raised.

Dict copying and key-value pair construction are both shallow copies.

Dict methods follow the dict key whitelist and insertion order; see [values and literals](01-language.md#values-and-literals).

### `dict.keys`

```text
dict.keys() -> list
```

Returns a new list of keys in insertion order. Modifying the dict afterward does not change that list.

### `dict.values`

```text
dict.values() -> list
```

Returns a new list of values in insertion order. The list container is independent; the elements themselves are not copied.

### `dict.items`

```text
dict.items() -> list
```

Returns a new list of `(key, value)` two-tuples in insertion order. Modifying the dict afterward does not change the returned list and tuples.

### `dict.get`

```text
dict.get(key) -> any | None
dict.get(key, default) -> any
```

Returns the corresponding value when the key exists; otherwise returns `default`, or `None` when no default is given. Does not modify the dict. An illegal key type raises `type_error`.

### `dict.pop`

```text
dict.pop(key) -> any
dict.pop(key, default) -> any
```

Removes and returns the corresponding value when the key exists. When the key does not exist, returns `default` without modifying the dict if it is given, otherwise raises `key_error`. An illegal key type raises `type_error`.

## `str`

All string methods return new values and do not modify the original string.

### `str.strip` / `str.lstrip` / `str.rstrip`

```text
str.strip(chars=None) -> str
str.lstrip(chars=None) -> str
str.rstrip(chars=None) -> str
```

Remove characters from both ends, the left end, or the right end respectively. When `chars` is omitted or `None`, whitespace is removed; when a string is provided, any character listed in it is removed, rather than matching the whole prefix or suffix. A wrong `chars` type raises `type_error`.

### `str.split`

```text
str.split(sep=None, maxsplit=-1) -> list
```

Splits the string into a list.

- `sep=None`: splits on runs of whitespace, ignoring leading and trailing whitespace.
- `sep` a non-empty string: splits on that separator, keeping empty fields.
- `maxsplit < 0`: no limit on the number of splits.
- `maxsplit >= 0`: splits at most that many times, with the remaining text in the last item.

An empty separator, a wrong `sep` type, or a non-strict-integer `maxsplit` all raise `type_error`.

```python
print("  a  b ".split())
print("a,,b".split(","))
print("a,b,c".split(",", 1))
```

```text
['a', 'b']
['a', '', 'b']
['a', 'b,c']
```

### `str.splitlines`

```text
str.splitlines(keepends=False) -> list
```

Splits on universal newline boundaries. `keepends` must be strictly `bool`; when `True`, the trailing newline characters are kept. A trailing newline does not produce an extra empty string. A type error raises `type_error`.

### `str.join`

```text
separator.join(values) -> str
```

Joins the strings in `values` with the calling string `separator` as the separator. `values` can be a string, list, tuple, or dict; a dict is iterated over its keys.

All elements must be strictly `str`, otherwise `type_error` is raised. An empty iterable returns an empty string, and a one-element result contains no separator.

### `str.find`

```text
str.find(sub, start=None, end=None) -> int
```

Returns the position of the first occurrence of substring `sub` within the specified interval, or `-1` when absent. Boundaries follow the slice normalization rules. `sub` must be a string and the boundaries must be integers or `None`, otherwise `type_error` is raised.

### `str.replace`

```text
str.replace(old, new, count=-1) -> str
```

Replaces non-overlapping `old` substrings. A negative `count` means no limit, zero means no replacement, and a positive value limits the maximum number of replacements.

`old` and `new` must be strings and `count` must be a strict integer, otherwise `type_error` is raised. An empty `old` inserts `new` between characters and at both ends, following Python semantics.

### `str.partition`

```text
str.partition(sep) -> tuple
```

Splits at the first non-empty separator into a `(before, sep, after)` three-tuple. When not found, returns `(original string, "", "")`. An empty or non-string separator raises `type_error`.

### `str.rpartition`

```text
str.rpartition(sep) -> tuple
```

Splits at the last non-empty separator into `(before, sep, after)`. When not found, returns `("", "", original string)`. Parameter errors are the same as `partition`.
