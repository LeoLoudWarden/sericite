# 自定义记录对象

Sericite 支持自定义数据结构，使用点号进行成员访问。本章介绍具体使用方法。这涉及到 Sericite 如何对待自定义数据结构：**结构包含契约与数据**，契约属于 **事实约束**，从不存在 **名义类型**。也即**称呼不改变实质**。

## 一个简单记录

```python
class Point:
    x: int
    y: int

p = Point(1, 2)          # 按声明顺序位置构造
p = Point(x=1, y=2)      # 也支持
print(p.x)               # 点号读成员
p.x = 10                 # 点号写成员
```

语法上使用 `class`，只是为了尽量接近 Python 的写法，实际语义差异很大。

## 记录

### 契约与数据

每个 record 对象由两部分构成：

- 结构契约（schema）：声明这个对象包含哪些成员，这些成员必须满足什么样的类型约束。
- 成员属性（attribute）：可以通过点号访问的数据内容。

可以这么理解：`record = schema + dict`。你可以通过 `unwrap` 和 `wrap` 实现 record 和 dict 的互相转换：

```python
d = unwrap(p)            # 浅拷贝，{'x': 1, 'y': 2}
p2 = wrap(Point, d)      # 新对象
```

### 构造与相等性

1. 若两个 record 的 schema 相等，所有成员也相等，则其相等。
2. 两处分别定义的同构 schema 彼此相等，字段顺序不影响判断。

```python
class A:
    x: float
    y: float

class B:
    y: float
    x: float

print(A == B)              # True：与声明顺序无关
print(A(1, 2) == B(2, 1))  # True：按各自声明顺序绑定
```

### 类型注解

```python
class Color:
    r: int
    g: int
    b: int

class Label:
    name: str
    color: Color      # 用另一个 schema 作契约：嵌套约束
    tag: any          # any：任意值，等价于不写注解

class Bag:
    content           # 不写注解 = any
    items: list
    table: dict
    pair: tuple
    flag: bool

def f(x: Color) -> Color:            # 参数注解与返回注解
    return x

black: Color = Color(0, 0, 0)       # 带注解的赋值
```

### 注解的运行时行为

**注解是契约的一部分**，不同于 Python，Sericite 在运行期会对契约做动态检查。检查发生在以下时点：

| 时点 | 触发 | 报错前缀 |
|---|---|---|
| record 构造 | `Point(1, 2)` | `field x` |
| 字段写入 | `p.x = ...` | `field x` |
| 函数参数 | 调用 `f(...)` | `argument x of f` |
| 函数返回 | 执行 `return ...` | `return value of f` |
| 带注解的赋值 | `x: int = ...` | `annotated assignment` |

检查是**宽度**的：实参 record 只要包含期望 schema 的全部字段，且对应字段契约兼容即可通过，多余字段放行。

```python
class Point:
    x: int
    y: int

class Point3D:
    x: int
    y: int
    z: int

def show(p: Point) -> int:      # 接受任何宽于 Point 的 record
    return p.x

print(show(Point3D(1, 2, 3)))   # 1：多出的 z 被放行
```

## 为什么是这样

请看下面的例子：

工作区：

```text
/
├── main.sericite
└── util.sericite
```

`/util.sericite`：

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

`/main.sericite`：

```python
from util import mid, rot90

class Point:
    x: float
    y: float

a = Point(0.0, 0.0)
b = Point(2.0, 4.0)
midpoint = mid(a, b)      # 通过
print(midpoint)           # record(x=1.0, y=2.0)

v = Point(3.0, 4.0)
w: Point = rot90(v)       # 同样通过
print(w)                  # record(x=-4.0, y=3.0)
```

`main` 的作者从未 import `Coord`/`Vec2`。`mid` 和 `rot90` 只按结构契约收参数，`Point` 与它们同构，自然放行。

名字是接收方的本地行为，值身上没有名字：

```python
p = mid(a, b)             # 不起名
print(p.z)                # attribute_error: record {x: float, y: float} has no field 'z'

q: Point = mid(a, b)      # 接收方自己起名
print(q.z)                # attribute_error: record Point {x: float, y: float} has no field 'z'
```

在 `util` 的视角里，`mid` 的返回值是 `Coord`。但 `main` 的视角中不存在 `Coord` 标记。报错里要么是匿名结构，要么是 `main` 自己写下的 `Point`。

这便是**称呼不改变实质**：`record {x: float, y: float}`是伴随着对象的**契约事实**，`Coord`/`Vec2`/`Point`都只是某个作用域内的**局部别名**。
