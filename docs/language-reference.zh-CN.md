# Sericite 语言参考

Sericite 是一门脚本语言，语法是 Python 的子集——写起来就是 Python，但**不是所有 Python 写法都合法**，而且部分语义有自己的规矩。本文自完备：读完即可开写。本文描述 Sericite 0.8.0的语言行为，面向正在编写 **Sericite 脚本** 的读者；直接运行脚本及使用 CLI include 见 [CLI 参考](cli-reference.zh-CN.md)；驱动与调试 VM（单步、exec 投递、快照、状态、配额）见[虚拟机参考](vm-reference.zh-CN.md)；在 Python 中嵌入引擎见 [Sericite-PY 参考](sericite-py-reference.zh-CN.md)。

## 1. 基本样子

```python
name = "world"            # 赋值
print("hello", name)      # 输出：hello world
x = input()               # 读入一行（字符串）
```

## 2. 类型与运算

内建类型：`int`、`float`、`str`、`bool`、`None`、`list`、`dict`，以及自定义的 `record`（见第 7 节）。

```python
7 / 2        # 3.5（除法恒为浮点）
7 // 2       # 3
7 % 3        # 1
"ab" + "cd"  # 字符串拼接（只有 +，没有 * 重复、没有 f-string）
"""line1
line2""" # 多行
[1, 2] + [3] # 列表拼接
not x        # 逻辑非；and / or 短路求值
1 < 2        # 比较：== != < <= > >=（不支持链式 a < b < c）
"a" in {"a": 1}    # in / not in：dict 查键、list 查元素、str 查子串
```

增强赋值支持 `+=`、`-=`、`*=`、`/=`、`//=`、`%=`，目标可以是名字、列表/字典下标或 record 字段。`target += rhs` 等价于 `target = target + rhs`，但目标地址只求值一次；其他运算符同理。运算规则与普通二元运算完全一致，例如列表 `+=` 仍创建拼接后的新列表，而不是原地扩展。

字符串和列表支持只读切片 `value[start:stop]` 与 `value[start:stop:step]`：

```python
s = "abcdef"
s[1:4]      # "bcd"：起止于索引 1、4（不含 4）
s[:3]       # "abc"：起点省略
s[::2]      # "ace"：步长 2
s[::-1]     # "fedcba"：负步长反向
s[2:99]     # "cdef"：越界按截断处理，不报错
```

规则：三个位置都可省略，省略即为 `None`；位置只能是整数或 `None`，缺省步长为 1，步长不能为 0；不支持切片赋值。负索引、越界截断和负步长遵循 Python 语义。切片有开销：总是创建新的字符串或列表。

与 Python 的关键差异（写错会报 `type_error`）：

- `bool` 不参与算术：`True + 1` 报错。
- 跨类型大小比较报错：`1 < "a"` 报错（`==`/`!=` 可以跨类型，结果为 False/True）。
- 字典键只允许 `str/int/float/bool/None`，缺键读取报 `key_error`。
- 字符串支持整数索引读取与切片，但不能写；列表支持索引读写与切片。

## 3. 控制流

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
    print("没被 break")     # while/else

for item in [1, 2, 3]:      # for 可迭代：list、dict（键）、str（逐字符）、range() 结果
    print(item)
for k in {"a": 1, "b": 2}:
    print(k, "->", ...)     # 取值用 d[k]
else:
    print("没被 break")     # for/else

pass                        # 空语句，合法

label = "big" if x >= 10 else "small"   # 三元表达式（短路：只算被选中的分支）
```

注意：for 的循环变量只能是单个名字（`for a, b in ...` 不支持）；遍历 list 是活视图（边遍历边改会反映），遍历 dict 是键快照。

## 4. 函数

```python
def add(a, b=10):           # 支持默认参数（定义时求值一次）
    return a + b

add(1)                      # 11
add(1, b=20)                # 21，支持关键字实参

def fib(n):                 # 递归合法
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)
```

嵌套函数使用词法作用域，按引用捕获外层函数的局部变量。闭包在调用时读取最新绑定，而不是定义时的值快照：

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

同一次外层调用创建的闭包共享捕获变量，不同次外层调用的环境彼此独立。`for` 循环不会为每轮迭代创建新变量，因此循环中创建的闭包共享最终绑定；如需定义时快照，可使用 `def read(value=x): ...` 这样的默认参数。

名字在函数内任何位置被赋值，就会在整个函数内作为局部变量。内层赋值因此会遮蔽外层绑定，而不是修改它；不支持 `nonlocal` 和 `global`。模块全局仍从定义方模块解析，不会复制进闭包。

函数装饰器遵循 Python 的应用语义：

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

这等价于先定义 `double`，再执行 `double = trace(double)` 重新绑定。装饰器表达式从上到下求值；堆叠装饰器从下往上应用。

不支持：可变参数（`*args`）、仅关键字参数。

## 5. 异常

```python
try:
    x = 1 / 0
except zero_division as e:   # 按错误类型过滤，e 是消息字符串
    print("caught:", e)
except:                      # 裸 except 兜底
    print("wrong")
else:
    print("没出错")
finally:
    print("一定执行")

raise "出问题了"             # 抛出 raise_error 类型，可捕获
raise                        # 在 except 块内裸 raise：重新抛出当前错误
```

`except` 的过滤条件必须是可捕获的错误 kind，不是变量或任意绑定名。未知名字（包括拼写错误）会在编译期以 `validation_error` 拒绝。不可捕获的 `resource_exhausted`、`internal_error` 与 `host_error` 同样在编译期被拒绝——它们连裸 `except:` 都无法捕获。`except kind as e` 按 kind 过滤并绑定消息字符串；裸 `except:` 捕获所有可捕获错误。

可捕获 kind 的完整列表：

- 通用：`runtime_error`、`syntax_error`、`validation_error`、`type_error`、`name_error`、`arity_error`、`raise_error`、`input_error`。
- 运算与契约：`zero_division`、`conversion_error`、`index_error`、`key_error`、`attribute_error`（record 缺成员/新增字段）、`contract_error`（构造、注解、wrap 或字段写入的契约检查失败）。
- 文件与 FFI：`file_not_found`、`is_directory`、`not_directory`、`ffi_error`。

异常可跨函数传播。`resource_exhausted`（配额耗尽）、`internal_error`（引擎内部错误）与 `host_error`（宿主回调在 FFI 异常契约之外失败）是已定义的 kind，但不可捕获。

## 6. 内建函数

- `input()` / `print(...)`：一行输入 / 以空格分隔输出各个值。`print(..., end=text)` 用 `text` 替代默认的末尾换行，`end=""` 表示不追加换行；`end` 是仅关键字参数，必须是字符串。
- `len(x)`（str/list/dict）、`int(x)`、`float(x)`、`str(x)`、`range(...)`（返回 list）。
- 文件（纯文本）：`read_file(path)`、`write_file(path, text)`、`list_dir(path)`、`path_exists(path)`。路径形如 `/notes/a.txt`，目录靠路径前缀隐含。
- record 相关：`wrap(schema, d)`、`unwrap(record)`，见第 7 节。

列表与字典方法：

- `lst.append(x)`：原地追加一个元素，返回 `None`。
- `lst.pop()` / `lst.pop(i)`：删除并返回末尾或索引 `i` 处的元素；负索引与下标读取一致。空列表或无效索引报 `index_error`。
- `d.keys()` / `d.values()`：按插入顺序返回新的键/值列表；之后修改字典不会改变已返回的列表。
- `d.get(key)` / `d.get(key, default)`：返回键对应的值；键不存在时返回 `None` 或 `default`。
- `d.pop(key)` / `d.pop(key, default)`：删除并返回键对应的值；未提供默认值时，缺键报 `key_error`，否则返回默认值。

字符串方法（参数按位置传递）：

- `s.strip()` / `s.lstrip()` / `s.rstrip()`：去除两端、左端或右端空白；`s.strip(chars)` 等形式改为去除 `chars` 中列出的任意字符，而不是去除整个前后缀。
- `s.split()`：按连续空白拆分并忽略两端空白；`s.split(sep, maxsplit=-1)` 按非空字符串 `sep` 拆分，`sep=None` 时按空白拆分。`maxsplit` 限制拆分次数，负数表示不限制。
- `s.splitlines(keepends=False)`：按通用换行边界拆行；`keepends` 必须是 `bool`，为 `True` 时保留行尾换行符。
- `separator.join(values)`：用分隔符连接 `str`、列表或字典（键）中的字符串，所有元素必须是 `str`。
- `s.find(sub, start=None, end=None)`：返回子串首次出现的位置，不存在时返回 `-1`；可指定搜索区间。
- `s.replace(old, new, count=-1)`：替换不重叠的旧子串，`count` 限制替换次数，负数表示全部替换；`old` 为空串时按 Python 语义在字符间及两端插入。

字符串方法返回新值，不修改原字符串。扫描、匹配和结果构造都计入指令配额：字符串结果按实际长度分配，`split`/`splitlines` 还计入结果列表槽位。方法集合是封闭的，未列出的列表、字典或字符串方法报 `attribute_error`。

## 7. 记录（record）：自定义含成员的对象

`class` 定义一个 **schema**（结构契约）。schema 是运行期的一等值，`class` 语句每次执行到都会创建它：

```python
class Point:
    x: int
    y: int

p = Point(1, 2)          # 按声明顺序位置构造；也支持 Point(x=1, y=2)
print(p.x)               # 点号读成员
p.x = 10                 # 点号写成员，仍受字段契约约束
```

class 体只允许字段声明，两种形式：`x`（契约 any，任意值）或 `y: int`（指定契约）。暂不支持默认值、方法、继承。可用的契约名：

- `int`/`float`/`str`/`bool`/`list`/`dict`、`any`，或另一个 schema（嵌套约束）；
- `any`/`bool`/`list`/`dict` 是仅注解位的契约名：不可调用、不可赋值；
- `int`/`float`/`str` 同时仍是转换内建。

record 的语义边界：

- **形状固定**：字段不可增删——读写不存在的字段报 `attribute_error`；字段值可改，但必须满足字段契约（违反报 `contract_error`）。
- **结构相等**：两处分别定义的同构 schema 彼此相等；record 相等要求 schema 结构相等且载荷相等；record 与 dict 永不相等——即使形状一样，dict 也没有"检疫章"。
- **相等忽略声明顺序，构造依赖声明顺序**：schema 相等按字段集合比较，`x`、`y` 谁先谁后不影响相等。但位置构造按各自 schema 的声明顺序绑定参数——字段相同而顺序颠倒的两个 schema 彼此相等，同样的位置实参却得到载荷不同的 record：

  ```python
  class A:
      x: int
      y: int

  class B:
      y: int
      x: int

  print(A == B)              # True：相等忽略声明顺序
  print(A(1, 2) == B(1, 2))  # False：构造按各自声明顺序绑定
  ```

  跨定义位置传参时建议用关键字构造（`B(x=1, y=2)`），避开顺序陷阱。
- **扒皮与套皮**：`unwrap(p)` 把 record 扒成普通 dict（浅拷贝）；`wrap(Point, d)` 把键集与 schema 严格一致的 dict 套上契约变成 record（缺/多键报 `contract_error` 并列明）。
- record 不可下标、不可迭代、不可做 dict 键，恒为真值。

注解是**真实执行的运行期契约**（不是静态类型，也没有静态检查）：

```python
def move(p: Point) -> int:
    return p.x

p: Point = Point(1, 2)
```

注解在三个时点检查，报错措辞分别指认责任位置：

- 参数注解：调用时检查（argument）；
- 返回注解：返回时检查（return value）；
- 带注解的赋值：赋值时检查（annotated assignment）。

检查是**宽度**的：实参 record 只要包含期望 schema 的全部字段且契约兼容即可通过，多余字段允许存在。dict 不会在注解位自动套皮。

报错中的名字是**编译期、作用域本地的标签**，只用于诊断，不参与任何相等或契约判断：`class Point` 的类名、`p: Point` 的注解文本会成为该作用域内相关报错的显示名。标签不进入值本身，出作用域即失效；没有标签的值按结构显示（`record {x: int} ...`）。经过分支、循环或异常路径时，只有能确定同一标签才会保留，否则退回匿名结构显示。

宽度检查放行带额外字段的值时，属性报错仍保留接收方写下的注解标签。例如 `p: Point = Coord(1, 2)` 后的 `p.z` 可显示为 `record Point {x: int, y: int} has no field 'z'`——`Point` 只是诊断标签，不表示值的 schema 被改写。

跨 VM 与跨 FFI 边界的只有结构。record 与 schema 不能跨宿主 FFI 边界（授予宿主的函数收到 record 会报 `ffi_error`，先 `unwrap`）；经授予函数在父子 VM 之间按引用传递，契约检查跨 VM 依然成立，但子 VM 中的报错只使用授予名（`functions={"f": ...}` 里的 `f`）与结构描述，定义方的函数名和类型标签不会出现。

## 8. 创建虚拟机（VM）

在 sericite 里可以创建新的 VM，VM 内跑的代码也还是 sericite：

```python
sub = VM("print('hi')")          # 源码字符串
out = sub.run()                  # 运行并取回它的全部输出（字符串）
print(out)                       # 'hi\n'
```

VM 是相互隔离的工作空间：看不到你的变量，碰不到你的文件。创建时可以收紧配额、授予函数：

```python
sub = VM(code, max_instructions=10000, functions={"double": double})
```

同一台 VM 可以反复驱动：喂输入、预置和读取文件、逐语句或逐指令单步、查看快照、用 `sub.exec(code)` 投递新源码、随时终止。VM 状态、驱动方法、exec 投递、配额字段与授予语义的完整契约见[虚拟机参考](vm-reference.zh-CN.md)。

## 9. 明确不能写（编译期直接拒绝）

`import`、`del`、`*args/**kwargs`、链式比较、切片赋值、元组、f-string、双下划线名称、class 字段默认值/方法/继承、语句级裸注解赋值（`x: T` 不赋值；class 体字段声明 `y: int` 是唯一例外）。内建名（`print`/`len`/`wrap` 等）与契约名（`any/bool/list/dict`）不可重新绑定，契约名只能出现在注解位。

CLI 的 `--include` 不属于语言语法：它只是在编译前按序组合同一 root 的源码，不提供模块、命名空间或 `import` 语义；详见 [CLI 参考](cli-reference.zh-CN.md)。

## 10. 一个完整例子

```python
# 库存小账本：一条程序走一遍 Sericite 的主要特性。
# 每一节对应语言参考的一个章节，注释里标了出处。

# ---------- record：结构契约（第 7 节） ----------
class Item:
    sku: str
    name: str
    qty: int
    price: float

class SkuRef:
    sku: str

# 构造：位置实参按声明顺序，关键字实参任意顺序
apple = Item("A-1", "apple", 3, 0.5)
milk = Item(sku="M-2", name="milk", qty=10, price=1.25)

# 点号读写成员，写也受契约约束
milk.qty = milk.qty - 1
print("milk left:", milk.qty)        # 9

# 结构相等：schema 按字段集合比较，与声明顺序无关
class ItemRev:
    price: float
    qty: int
    name: str
    sku: str
print("same schema:", Item == ItemRev)   # True

# 注解是运行期契约（第 7 节）：宽度检查，多余字段放行
def describe(ref: SkuRef) -> str:
    return "sku=" + ref.sku
print(describe(apple))               # sku=A-1（Item 是 SkuRef 的宽实现）

# 扒皮与套皮
raw = unwrap(apple)
print("unwrapped:", raw)             # {'sku': 'A-1', 'name': 'apple', 'qty': 3, 'price': 0.5}
clone = wrap(Item, raw)
print("round trip:", clone == apple)  # True

# ---------- 函数：默认参数、关键字实参、递归（第 4 节） ----------
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

# ---------- 装饰器（第 4 节）：等价于 double = logged(double) ----------
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

print("double:", double(21))         # 42，前后各一行日志

# ---------- 闭包（第 4 节）：按引用捕获，读到最新绑定 ----------
def make_reader():
    x = 1
    def read():
        return x
    x = 2
    return read
print("closure:", make_reader()())   # 2，不是 1

# ---------- 控制流（第 3 节） ----------
inv = [apple, milk, Item("B-3", "bread", 0, 2.0)]

# for/else：没有 break 就执行 else
sold_out = False
for it in inv:
    if it.qty == 0:
        sold_out = True
        break
else:
    print("no sold-out items")
if sold_out:
    print("some item is sold out")

# while/else：没被 break 就执行 else；continue / pass 也合法
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
    pass                             # 空分支占位
else:
    print("flag off")

# ---------- 异常（第 5 节） ----------
def parse_qty(text):
    try:
        return int(text)
    except conversion_error as e:
        print("  bad number:", e)
        return 0
    finally:
        print("  parse done")

print("parse:", parse_qty("12"), parse_qty("oops"))   # 12  0

# 按类型过滤 + raise 字符串（raise_error，向上传播）
def load_config():
    try:
        text = read_file("/config.txt")
    except file_not_found:
        raise "config missing"       # raise_error，可被捕获
    return text

try:
    load_config()
except raise_error as e:
    print("config:", e)

# 自定义 raise + 兜底 except
try:
    raise "demo error"
except zero_division:
    print("won't happen")
except:
    print("caught by bare except")

# ---------- 文件与子 VM（第 6、8 节） ----------
write_file("/report.txt", "inventory ok")
print("report exists:", path_exists("/report.txt"))   # True
print("files:", list_dir("/"))                        # ['report.txt']

# 子 VM 是隔离工作区：喂输入、读它的输出；资源配额只能比当前更严
checker_code = """
a = int(input())
b = int(input())
print("sum from sub:", a + b)
"""
checker = VM(checker_code, max_instructions=1000)
sub_out = checker.run(["7", "8"])
print("sub vm says: " + sub_out)     # sum from sub: 15

# 授予宿主函数给它用（按引用保留定义方环境）
def times_ten(x):
    return x * 10
worker = VM("""
n = int(input())
print(times_ten(n))
""", functions={"times_ten": times_ten})
print("worker says: " + worker.run(["6"]))   # 60

# 收尾：汇总并打印最终结果
grand = total_value(inv)
print("grand total:", grand)
print("factorial(5):", factorial(5))
```
