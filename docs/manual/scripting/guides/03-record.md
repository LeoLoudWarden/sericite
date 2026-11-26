# Custom record objects

Sericite supports custom data structures with dot member access. This chapter shows how to use them. It involves how Sericite treats custom data structures: **a structure contains a contract and data**; the contract is a **factual constraint**; there are no **nominal types**. In other words, **a name does not change the substance**.

## A simple record

```python
class Point:
    x: int
    y: int

p = Point(1, 2)          # positional construction in declaration order
p = Point(x=1, y=2)      # also supported
print(p.x)               # read a member via dot
p.x = 10                 # write a member via dot
```

The syntax uses `class` only to stay as close to Python's spelling as possible; the actual semantics differ greatly.

## Records

### Contracts and data

Every record object consists of two parts:

- a structural contract (schema): declares which members this object contains and what type constraints those members must satisfy;
- member attributes: the data content accessible via dot.

You can think of it as `record = schema + dict`. You can convert between records and dicts with `unwrap` and `wrap`:

```python
d = unwrap(p)            # shallow copy, {'x': 1, 'y': 2}
p2 = wrap(Point, d)      # a new object
```

### Construction and equality

1. Two records are equal if their schemas are equal and all their members are equal.
2. Two isomorphic schemas defined separately are equal, and field order does not affect the judgment.

```python
class A:
    x: int
    y: int

class B:
    y: int
    x: int

print(A == B)              # True: independent of declaration order
print(A(1, 2) == B(2, 1))  # True: bound by each declaration order
```

### Type annotations

```python
class Color:
    r: int
    g: int
    b: int

class Label:
    name: str
    color: Color      # use another schema as the contract: nested constraint
    tag: any          # any: any value, equivalent to omitting the annotation

class Bag:
    content           # no annotation = any
    items: list
    table: dict
    pair: tuple
    flag: bool

def f(x: Color) -> Color:            # parameter annotation and return annotation
    return x

black: Color = Color(0, 0, 0)       # annotated assignment
```

### Runtime behavior of annotations

**Annotations are part of the contract.** Unlike Python, Sericite checks contracts dynamically at runtime. Checks happen at these points:

| When | Trigger | Error prefix |
|---|---|---|
| record construction | `Point(1, 2)` | `field x` |
| field write | `p.x = ...` | `field x` |
| function argument | calling `f(...)` | `argument x of f` |
| function return | executing `return ...` | `return value of f` |
| annotated assignment | `x: int = ...` | `annotated assignment` |

The check is a **width** check: an actual record passes as long as it contains all fields of the expected schema and the corresponding field contracts are compatible; extra fields are allowed through.

```python
class Point:
    x: int
    y: int

class Point3D:
    x: int
    y: int
    z: int

def show(p: Point) -> int:      # accepts any record wider than Point
    return p.x

print(show(Point3D(1, 2, 3)))   # 1: the extra z is allowed through
```

## Why it is this way

Look at the following example:

Workspace:

```text
/
├── main.sericite
└── util.sericite
```

`/util.sericite`:

```python
class Coord:
    x: float
    y: float

class Vec2:
    x: float
    y: float

def mid(a: Coord, b: Coord):
    c_x = (a.x + b.x) / 2
    c_y = (a.y + b.y) / 2
    return Coord(c_x, c_y)

def rot90(v: Vec2):
    x_new = v.x * 0 - v.y * 1
    y_new = v.x * 1 + v.y * 0
    return Vec2(x_new, y_new)
```

`/main.sericite`:

```python
from util import mid, rot90

class Point:
    x: float
    y: float

a = Point(0.0, 0.0)
b = Point(2.0, 4.0)
midpoint = mid(a, b)      # passes
print(midpoint)           # record(x=1.0, y=2.0)

v = Point(3.0, 4.0)
w: Point = rot90(v)       # also passes
print(w)                  # record(x=-4.0, y=3.0)
```

The author of `main` never imports `Coord`/`Vec2`. `mid` and `rot90` accept arguments only by structural contract; `Point` is isomorphic to them and is naturally allowed through.

Names are a local act of the receiver; the value itself carries no name:

```python
p = mid(a, b)             # no name given
print(p.z)                # attribute_error: record {x: float, y: float} has no field 'z'

q: Point = mid(a, b)      # the receiver names it themselves
print(q.z)                # attribute_error: record Point {x: float, y: float} has no field 'z'
```

From `util`'s viewpoint, `mid`'s return value is `Coord`. But from `main`'s viewpoint, no `Coord` label exists. The error shows either the anonymous structure or the `Point` that `main` itself wrote.

This is what "a name does not change the substance" means: `record {x: float, y: float}` is the **contractual fact** carried by the object, while `Coord`/`Vec2`/`Point` are just **local aliases** within some scope.
