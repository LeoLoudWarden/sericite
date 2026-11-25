# Quick start

Sericite is a scripting language designed for dynamic, lightweight, and transparent program execution.

This chapter introduces Sericite's basic types and function syntax.

## Sericite is not Python

Sericite borrows Python's syntax but implements only a deliberately chosen language surface. Sericite source is compiled into a dedicated instruction stream and executed by the Sericite runtime. It has no Python module ecosystem, full reflection, or arbitrary object model, and it does not automatically support every Python feature merely because the syntax looks similar.

For example, the following cannot be carried over from Python habits directly:

- importing Python's standard library;
- `open()` and `exec()` do not exist as global built-ins;
- unlisted Python syntax and methods are rejected at compile or runtime.

These differences come from Sericite's own language and runtime contracts; later chapters explain the actually available features one by one.

**Note**: the syntax highlighting marker in this document's code blocks is "python", which is only a Markdown typesetting device and does not change Sericite's language identity.

## A one-line program

```python
name = input()
print("hello", name)
```

Providing one line of input `Sericite` produces:

```text
hello Sericite
```

Only the program's stdout is listed here; any input echo the runtime environment might show is not included.

## Basic types and operations

### Numbers

```python
7 / 2        # 3.5 (division is always float)
7 // 2       # 3
7 % 3        # 1
a += b       # automatically a = a + b

1 < 2        # supports == != < <= > >=
nan = float("nan")
nan == nan   # False: NaN is not equal to itself

2 ** 3       # 8
2 ** 3 ** 2  # 512: right-associative, i.e. 2 ** (3 ** 2)
2 ** -2      # 0.25
```

### Strings

```python
"ab" + "cd"
"""line1
line2"""     # multiline string
f"{1/3:.2f}" # f-string
"+" * 3      # "+++"
```

### Built-in containers

`list`, `dict`, and `tuple` are supported; there is no `set`.

```python
empty = ()
single = (1,)      # a one-element tuple needs a trailing comma
pair = 1, "x"      # parentheses can be omitted

[1, 2] + [3]       # [1, 2, 3]
(1, 2) + (3,)      # (1, 2, 3)

2 * [1, 2]         # [1, 2, 1, 2]
(1, 2) * 0         # ()

[a for a in l]     # comprehension
{k: v for k, v in d.items()}

a, b = (1, 2)      # name destructuring
a, b = b, a
x, (y, z) = [3, (4, 5)]
for first, second in [(1, 2), (3, 4)]:
    print(first + second)
```

### Booleans

```python
1 in [1, 2, 3]
"a" in {"a": 0}
"12" in "123"

True == 1    # False, bool is not int
1 + True     # type_error, not arithmetic

bool("")     # False
bool([0])    # True

not x
x and y or z # short-circuit, precedence not > and > or
```

The values treated as false are: `None`, `False`, `0`, the empty string `""`, the empty list `[]`, the empty tuple `()`, and the empty dict `{}`.

### Object comparison

The rules are applied in order:
1. a float NaN is not equal to itself
2. the same object is always equal to itself
3. container elements are compared one by one, recursively

```python
nan = float("nan")
nan == nan       # False: NaN is not equal to itself
[nan] == [nan]   # False: two new containers compared element by element
lst = [nan]
lst == lst       # True: the same object
```

## Functions

### Basic definitions

```python
def add(a, b=10):           # supports default arguments (evaluated once at definition)
    return a + b
add(1, b=20)                # 21, supports keyword arguments
```

### Closure capture

`global` and `nonlocal` are supported:

```python
count = 0

def increment():
    global count
    count += 1

increment()
increment()
print(count)  # 2

def make_counter():
    count = 0
    def increment():
        nonlocal count
        count += 1
        return count
    return increment

counter = make_counter()
print(counter())  # 1
print(counter())  # 2
```

### Variadic arguments and decorators

```python
def f(**kwargs):
    return kwargs

options = {"x": 1}
print(f(**options))  # {'x': 1}

def trace(func):
    def wrapper(*args, **kwargs):
        print("before")
        result = func(*args, **kwargs)
        print("after")
        return result
    return wrapper

@trace
def double(x):
    return x * 2
```

`yield` and iterator/generator syntax are not supported; `range(4)` returns the list `[0, 1, 2, 3]`.
