# 语言与模块

本文定义 Sericite 脚本的语言表面，供需要核对语法和运行语义时使用。函数与方法的详细签名见[通用内建](02-builtins.zh-CN.md)、[值类型方法](03-types.zh-CN.md)和各对象专页。

Sericite 借用 Python 的一部分语法，但不是 Python，本文没有列出的语言行为不能因此推定为可用。

## 值与字面量

| 类型 | 字面量或来源 | 可变性 |
|---|---|---|
| `None` | `None` | 不可变 |
| `bool` | `True`、`False` | 不可变 |
| `int` | `0`、`42`、`-3` | 不可变 |
| `float` | `1.0`、`.5`、`1e3` | 不可变 |
| `str` | `"text"`、`'text'`、三引号字符串、f-string | 不可变 |
| `list` | `[]`、`[1, 2]`、列表推导式 | 可变 |
| `tuple` | `()`、`(1,)`、`1, 2` | 不可变 |
| `dict` | `{}`、`{"key": value}`、字典推导式 | 可变 |
| schema | 执行 `class` 语句 | 结构契约值 |
| record | 调用 schema | 字段值可变，字段集合固定 |
| module | `import` | 属性只读 |
| function | `def`、装饰器、addon、绑定方法 | 可调用值 |
| VM / VFS | `VM(...)` / `VFS()` | 有生命周期的句柄 |

单元素元组必须写尾逗号：`(1,)`。`(1)` 只是带括号的整数。元组括号在解构和 `pair = 1, 2` 这类表达式中可以省略。

字典键只允许 `str`、`int`、`float`、`bool` 和 `None`。列表、元组、字典、record、schema、函数和句柄都不能作为字典键。字典保留插入顺序。

字符串是 Unicode 文本，没有独立的字节类型。`max_string_bytes` 虽以字节命名，实际限制的是字符数；文件内容和输出的相关配额使用 UTF-8 字节数，见 [VM 配额](06-vm.zh-CN.md#配额)。

## 名字与保留名

名字用于变量、参数、函数、schema、模块绑定和字段。双下划线开头的名字及属性不可用；专用模块名 `__addon__` 只能出现在规定的导入语法中，不能作为普通值引用。

下列内建名不能被重新绑定，也不能由导入直接覆盖：

```text
input print VM VFS len int float str repr range
read_file write_file delete_file rename_file copy_file
make_dir delete_dir rename_dir copy_dir list_dir path_exists
any bool list dict tuple wrap unwrap
```

`int`、`float`、`str`、`bool`、`list`、`dict` 和 `tuple` 既可直接调用，也可作为契约名。`any` 只能作为契约名出现在注解位。可调用内建不能先保存为普通变量再间接调用。

## 运算与求值

### 算术

| 运算 | 支持的操作数与结果 |
|---|---|
| `a + b` | 数值相加；同类型字符串、列表或元组拼接 |
| `a - b` | 数值相减 |
| `a * b` | 数值相乘；字符串、列表或元组与整数双向重复 |
| `a / b` | 数值相除，结果为 `float` |
| `a // b` | 向下取整改除 |
| `a % b` | 取模 |
| `a ** b` | 幂运算，右结合 |
| `-a` | 数值取负 |
| `not a` | 对真值取反，结果为 `bool` |

`bool` 不是算术中的整数：`True + 1` 报 `type_error`。不同类型的序列不能拼接。零或负数重复产生同类型空序列。拼接、重复和切片都创建新序列；列表和元组的新序列只浅拷贝元素。

两个整数进行非负整数次幂时结果为 `int`；涉及 `float` 或使用负整数指数时结果为 `float`。幂运算优先于一元负号：`-2 ** 2` 等于 `-(2 ** 2)`。

主要错误：

- 除数或模数为零：`zero_division`；
- 零的负数次幂：`zero_division`；
- 运算会产生复数：`type_error`；
- 浮点幂运算溢出：`conversion_error`；
- 类型不支持该运算：`type_error`；
- 整数位宽、字符串或序列规模超限：`resource_exhausted`。

增强赋值支持 `+=`、`-=`、`*=`、`**=`、`/=`、`//=`、`%=`。目标可以是名字、列表/字典下标或 record 字段。目标地址只求值一次，再按普通二元运算和写入规则处理。列表的 `+=`、`*=` 也创建新列表，不是原地扩展。

### 比较与成员判断

支持 `==`、`!=`、`<`、`<=`、`>`、`>=`、`in`、`not in`。不支持 `is`、`is not` 和链式比较。

- `==` 与 `!=` 可跨类型比较；类型不同通常分别为 `False` 和 `True`。
- 容器和 record 递归按结构比较。容器与自身比较走身份快路径。
- NaN 不等于自身，包括 record 字段和容器元素中的 NaN；同一个容器对象仍等于自身。
- 环状容器按余归纳结构比较，不因无限递归而展开。
- 大小比较只支持数值之间或字符串之间；其他组合报 `type_error`。
- `list`、`tuple` 和 `str` 的成员判断检查元素或子串，`dict` 检查键。
- schema 按字段名和字段契约比较，忽略字段声明顺序；record 还要求 schema 和载荷都相等。record 与字典即使形状相同也不相等。

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

### 真值与短路

`None`、`False`、数值零、空字符串、空列表、空元组和空字典为假，其他值为真。record 恒为真。

`not` 返回布尔值。`and` 和 `or` 短路求值并返回决定结果的操作数，不强制转成 `bool`。条件表达式只执行选中的分支。

优先级由低到高为：

1. `or`
2. `and`
3. `not`
4. 比较与成员判断
5. `+`、`-`
6. `*`、`/`、`//`、`%`
7. 一元 `-`
8. `**`

幂运算在指数位置允许一元负号，例如 `2 ** -2`。复杂表达式应使用括号明确意图。

## 赋值、索引与切片

### 赋值与解构

```python
name = value
first = second = value
items[0] = value
mapping["key"] = value
point.x = value
```

链式赋值只对右侧求值一次。多目标形式不允许混入下标或属性目标。

固定长度名字解构支持列表、元组、字符串和字典；字典遍历键。解构可以嵌套，但叶子只能是名字：

```python
a, b = (1, 2)
x, (y, z) = [3, (4, 5)]
```

长度不匹配报 `value_error`，不可迭代值报 `type_error`。不支持带星号解构、列表目标或下标/属性解构叶子。

带注解赋值写作 `name: Contract = value`，在赋值时检查契约。语句级裸注解 `name: Contract` 不合法；class 体中的字段声明是唯一例外。

### 下标

字符串、列表和元组接受整数下标，支持负索引；越界报 `index_error`。只有列表支持下标写入。字典按键读取，缺键报 `key_error`，写入可新增或替换键。

下标位置必须严格为 `int`，`bool` 不作为下标整数。record 不可下标，使用点号访问字段。

### 切片

字符串、列表和元组支持只读切片：

```python
value[start:stop]
value[start:stop:step]
```

三个位置都可省略；每个位置只能是 `int` 或 `None`。缺省步长为 1，步长不能为零。负索引、越界截断和负步长遵循 Python 的切片规则，结果总是新序列。切片赋值不合法。

## 控制流

支持：

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

- `while`/`else` 和 `for`/`else` 的 `else` 只在循环没有由 `break` 退出时执行。
- `for` 可遍历 `list`、`tuple`、`dict`、`str` 和 `range()` 返回的列表。
- `for` 目标可以是名字或固定长度名字解构。
- 遍历列表使用活视图，循环中的修改会影响后续遍历；遍历字典使用开始时的键快照。
- `pass` 是空语句。
- 不支持 `with`、`match`、`async`、`await`、`yield`、`lambda`、`assert`、`del` 和生成器语法。

### 推导式

支持列表和字典推导式：

```python
squares = [x * x for x in range(6) if x % 2]
pairs = [(x, y) for x in [1, 2] for y in [3, 4]]
reverse = {value: key for key, value in mapping.items()}
```

每个推导式有独立作用域：循环目标不泄漏到外部，也不覆盖外部同名绑定，但可以读取外层变量。支持多个 `for`、多个 `if` 和名字解构。

最外层可迭代表达式在外层作用域求值一次；后续可迭代表达式、条件和结果表达式从左到右在推导式作用域中求值。字典推导式先求键再求值，重复键保留后写入的值。结果受列表、元组和字典规模及资源配额约束。

集合推导式和生成器表达式不合法。

## 函数

### 定义与参数

```python
def function(a, b=default, *args, **kwargs):
    return a
```

参数按以下顺序组成：

1. 普通位置/关键字参数；
2. 可选的 `*args`，把剩余位置实参收集为元组；
3. 可选的 `**kwargs`，把额外关键字实参收集为字典。

普通参数可有默认值，默认值在函数定义时求值一次。不支持仅位置参数 `/`、仅关键字参数和 keyword-only 默认值的额外形式。

调用支持位置实参、关键字实参、`*iterable` 和 `**mapping`：

```python
def collect(a, *args, **kwargs):
    return [a, args, kwargs]

print(collect(1, *[2, 3], x=4))
```

```text
[1, (2, 3), {'x': 4}]
```

`*` 可展开列表、元组、字符串或字典；字典展开其键。`**` 只接受字典，且所有键必须是字符串。实参表达式按源码从左到右求值。

错误规则：

- 重复参数名、重复显式关键字标签：`syntax_error`；
- 缺参、多参、未知关键字、同一参数重复绑定：`arity_error`；
- `*`/`**` 展开值类型错误：`type_error`；
- 参数或返回契约不满足：`contract_error`。

`return` 不带值时返回 `None`；函数自然结束也返回 `None`。递归合法，调用帧数受 `max_frames` 限制。

### 词法作用域与闭包

模块级绑定属于定义模块。函数内没有 `global` 或 `nonlocal` 声明时，任何被赋值的名字在整个函数内都是局部名字；局部未绑定不会回退到同名模块变量。

嵌套函数按引用捕获外层函数的局部变量，调用时读取最新绑定。同一次外层调用产生的闭包共享捕获单元，不同次调用的环境独立。`for` 不会为每轮迭代创建新绑定；需要定义时快照可使用默认参数。

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

- `global name` 读写当前定义模块的模块级绑定。
- `nonlocal name` 绑定最近的外层函数变量，可穿过没有绑定该名字的中间函数。
- 模块级 `global` 合法；模块级或找不到外层绑定的 `nonlocal` 报 `syntax_error`。
- 声明与参数、同一名字的其他声明或冲突的词法使用同时出现时，编译期拒绝。

普通赋值、增强赋值、解构、循环、导入、函数定义和异常绑定都服从这些声明。

### 装饰器

```python
@decorator
def function():
    pass
```

等价于先定义函数，再执行 `function = decorator(function)`。装饰器表达式从上到下求值，堆叠装饰器从下往上应用。装饰器结果重新绑定函数名，因此应是可调用值才能继续调用。

## record 与 schema

### 定义与构造

`class` 定义一个运行期 schema。它只包含字段声明，不支持继承、方法、装饰器或字段默认值：

```python
class Point:
    x: int
    y: int

class Bag:
    content
```

`content` 的契约为 `any`。class 体也可只写 `pass`，创建没有字段的空 schema。每次执行到 `class` 语句都会创建一个 schema 值。

调用 schema 构造 record：

```text
Schema(field1, field2, ...) -> record
Schema(name=value, ...) -> record
```

位置实参按字段声明顺序绑定，关键字实参按字段名绑定，两者可组合。所有字段必须恰好提供一次；缺字段、多字段、未知字段、重复绑定或字段契约失败均报 `contract_error`。构造错误不是 `arity_error`。

字段通过 `record.field` 读取和写入。字段集合固定，不可增删；不存在的字段报 `attribute_error`，写入不满足字段契约报 `contract_error`。record 不可迭代、不可下标、不可作为字典键。

### 契约

可用契约为：

- `int`、`float`、`str`、`bool`、`list`、`dict`、`tuple`；
- `any`，接受任意值；
- 另一个 schema，形成嵌套结构契约。

`None` 是值，不是契约。显式 `None` 注解在参数、返回值、字段和带值注解赋值中均报 `syntax_error`；不需要检查时省略注解或使用 `any`。

注解会真实地在运行期检查：

| 位置 | 检查时点 | 责任位置 |
|---|---|---|
| `def f(x: Contract)` | 调用时 | 参数 |
| `def f(...) -> Contract` | 返回时 | 返回值 |
| `x: Contract = value` | 赋值时 | 带注解赋值 |
| `record.field = value` | 字段写入时 | 字段 |
| schema 构造 / `wrap()` | 构造时 | 字段 |

检查是宽度的：当期望契约是 schema 时，实际 record 只要包含全部期望字段且对应契约兼容即可，多余字段允许存在。字典不会自动包装成 record。

### 结构相等与诊断标签

schema 相等只看字段名和契约，不看声明顺序；位置构造却仍按各自的声明顺序绑定。因此跨定义位置传参时优先使用关键字构造。

类名和注解名只是编译期、作用域本地的诊断标签，用于错误文本。它们不进入值、不参与相等或契约判断，离开定义作用域后失效。没有可用标签时按结构显示。控制流无法确定同一标签时也会退回匿名结构。

`wrap(schema, data)` 和 `unwrap(record)` 在字典与 record 之间转换，详见[通用内建-wrap](02-builtins.zh-CN.md#wrap)和[通用内建-unwrap](02-builtins.zh-CN.md#unwrap)。

## f-string 与格式化

支持普通插值、多片段、多行、嵌套 f-string、转义花括号、调试形式和动态格式说明符：

```python
name = "world"
value = 12.345
print(f"hello {name}")
print(f"{value:.2f}")
print(f"{value=}")
print(f"{value:{width}.{precision}f}")
```

最后两例要求 `width` 和 `precision` 已经定义。`{expr=}` 输出表达式文本、等号和值的 `repr`。

转换符：

| 形式 | 含义 |
|---|---|
| `{value}` | 默认字符串渲染 |
| `{value!s}` | 先经 `str()` 语义转换 |
| `{value!r}` | 先经安全 `repr` 渲染 |
| `{value!a}` | 类似 `!r`，并对非 ASCII 字符递归转义 |

转换先于格式说明符执行。带非空格式说明符且没有显式转换时，只接受 `str`、`int`、`float`。

格式说明符依次为：

```text
[[fill]align][sign][z][#][0][width][grouping][.precision][type]
```

- 对齐：`<`、`>`、`^`、`=`；`=` 只适用于数值。
- 符号：`+`、`-`、空格；`z` 控制浮点负零；`#` 为备用形式。
- 分组：`,` 或 `_`。
- 字符串类型：空或 `s`，可用宽度和精度截断，但不能使用数值专用选项。
- 整数类型：空、`b`、`c`、`d`、`o`、`x`、`X`；整数使用这些整数形式时不能有精度。整数也可用浮点类型。
- 浮点类型：空、`e`、`E`、`f`、`F`、`g`、`G`、`%`。

非法格式说明符报 `conversion_error`；该类型不支持的呈现类型报 `type_error`；结果超限报 `resource_exhausted`。

## 模块与包

### 模块解析

| 模块名 | 文件形式 | 包形式 |
|---|---|---|
| `util` | `/util.sericite` | `/util/__init__.sericite` |
| `lib.math` | `/lib/math.sericite` | `/lib/math/__init__.sericite` |

每个中间目录都必须是含 `__init__.sericite` 的包，不支持 namespace package。同一模块名同时存在文件和包、父级不是包、模块不存在或指定导出不存在，均报 `import_error`。

`VM(source=...)` 从工作区根解析模块。`VM(entry_file=...)` 从入口文件所在目录解析模块，模块根在会话中保留。模块根只影响导入，不改变文件函数的根；文件路径始终以整个工作区根为基准。

### 导入形式与绑定

```python
import util
import util as u
import lib.math
import lib.math as math
from util import answer
from util import answer as value
from lib.math import double
```

- `import util` 绑定模块对象。
- `import lib.math` 绑定顶层包 `lib`，成功后把 `math` 挂到包的属性上。
- `import lib.math as math` 直接绑定目标模块。
- `from util import answer` 只绑定指定导出。
- `from pkg import child` 先读取包的已有导出；不存在时尝试加载子模块 `pkg.child`。
- 模块支持点号读取，不支持属性写入。
- 不支持通配符导入。

相对导入以当前定义模块的包为基准：`.` 表示当前包，`..` 表示上一级包。

```python
from . import util
from .util import answer
from ..util import answer
```

包外入口模块不能使用相对导入，越过顶层包报 `import_error`。

### 执行、缓存与失败

导入在实际执行到语句时发生，可以位于函数、条件和 `try` 中。绑定遵循普通词法作用域。每个模块有独立全局命名空间；模块函数的全局名字始终从自己的定义模块读取。

同一 VM 中，同一规范模块名成功执行后进入缓存，重复导入返回同一个模块对象。修改文件不会重新加载缓存；VFS 移交不会携带模块缓存。

直接或间接循环导入报 `import_error`。导入失败不缓存失败结果，修复后可以重试，但失败前的输出和文件副作用不回滚。模块自身的语法、运行和资源错误保留原 kind。

## `__addon__`：授予能力入口

每台 VM 都有预加载的内建模块 `__addon__`，只能通过以下形式导入：

```python
from __addon__ import name
from __addon__ import name as local_name
from __addon__ import first, second as alias
```

该模块不对应 VFS 文件，不能被工作区中的同名文件覆盖。每个源码模块必须自行导入；导入不会进入其他模块的全局命名空间。导入名和别名遵循普通词法作用域，成功导入在后续 `exec()` 所复用的模块作用域中保留。

只允许绝对 `from __addon__ import ...`。以下形式不合法：`import __addon__`、`import __addon__.http`、相对导入、从包中导入 `__addon__`、通配符导入和双下划线导出名。

缺失导出的普通错误为 `import_error`。addon 自身的调用契约由提供方定义；数据边界违规使用 `addon_error`。创建 VM 和转授 addon 见 [VM](06-vm.zh-CN.md#addon-授予)。

## 编译期拒绝的常见形式

除正文已经列出的限制外，以下形式也不可用：

- `@`、位移、按位运算、一元 `+`、`is`、`is not`；
- 字面量中的 `*`/`**` 展开；字典字面量的 `**` 展开；
- 链式比较、切片赋值、带星号解构；
- 集合、集合推导式、生成器表达式；
- `lambda`、`with`、`assert`、`match`、`async`、`await`、`yield`、`del`；
- class 继承、方法、装饰器、字段默认值；
- 语句级裸注解赋值；
- 通配符导入和双下划线名称；
- 重绑定内建名或在注解位以外使用 `any`。

这些错误通常报 `syntax_error`。同一份源码不能用自身的 `try` 捕获自己的编译错误，因为编译先于执行；父程序创建或驱动子程序时可以捕获子源码的 `syntax_error`。
