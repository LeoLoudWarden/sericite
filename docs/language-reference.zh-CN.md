# Sericite 语言参考

Sericite 是一门脚本语言，语法是 Python 的子集——写起来就是 Python，但**不是所有 Python 写法都合法**，而且部分语义有自己的规矩。本文自完备：读完即可开写。本文描述该语言的行为，面向正在编写 **Sericite 脚本** 的读者。

## 1. 基本样子

```python
name = "world"            # 赋值
print("hello", name)      # 输出：hello world
x = input()               # 读入一行（字符串）
```

## 2. 类型与运算

内建类型：`int`、`float`、`str`、`bool`、`None`、`list`、`dict`、`tuple`，以及自定义的 `record`（见第 7 节）。

### 内建值与基本运算

```python
7 / 2        # 3.5（除法恒为浮点）
7 // 2       # 3
7 % 3        # 1

"ab" + "cd"
"""line1
line2"""     # 多行字符串
f"{1/3:.2f}" # f-string

not x        # 逻辑非；and / or 短路求值
1 < 2        # 支持 == != < <= > >=
"a" in {"a": 1}  # dict 查键、list/tuple 查元素、str 查子串
```

容器相等按元素递归比较，同一对象则走身份快路径：

```python
nan = float("nan")
nan == nan       # False：NaN 不等于自身
[nan] == [nan]   # False：两个新容器逐元素比较
lst = [nan]
lst == lst       # True：同一个对象
```

### 赋值与增强赋值

`a = b = value` 只对 `value` 求值一次，再依次绑定各个名字；多目标中的 attribute/subscript 形式不受支持。

增强赋值支持 `+=`、`-=`、`*=`、`**=`、`/=`、`//=`、`%=`，目标可以是名字、列表/字典下标或 record 字段。`target += rhs` 等价于 `target = target + rhs`，但目标地址只求值一次；其他运算符同理。

普通二元运算的规则同样适用于增强赋值。例如，列表的 `+=` 和 `*=` 分别创建拼接或重复后的新列表，而不是原地扩展。

### 幂运算

```python
2 ** 3       # 8
2 ** 3 ** 2  # 512：右结合，即 2 ** (3 ** 2)
-2 ** 2      # -4：幂运算优先于一元负号
(-2) ** 2    # 4
2 ** -2      # 0.25
```

`**` 只接受 int/float，`bool` 不参与。两个整数进行非负整数次幂运算时结果为 int；涉及 float 或使用负整数指数时结果为 float。

错误契约：

- 零的负数次幂：`zero_division`；
- 会产生复数的运算：`type_error`；
- 浮点结果溢出：`conversion_error`。

### 序列的共同操作

字符串、列表和元组支持同类型 `+` 拼接、与整数的双向 `*` 重复、整数索引读取和只读切片；列表另支持下标写入。

```python
"ab" + "cd"       # "abcd"
[1, 2] + [3]      # [1, 2, 3]
(1, 2) + (3,)     # (1, 2, 3)

"=" * 3           # "==="
2 * [1, 2]        # [1, 2, 1, 2]
(1, 2) * 0        # ()
```

零次或负数重复返回同类型的空序列。拼接和重复都返回新序列；列表或元组重复是浅拷贝，内部元素仍共享。

切片使用 `value[start:stop]` 或 `value[start:stop:step]`：

```python
s = "abcdef"
s[1:4]      # "bcd"：起止于索引 1、4（不含 4）
s[:3]       # "abc"：起点省略
s[::2]      # "ace"：步长 2
s[::-1]     # "fedcba"：负步长反向
s[2:99]     # "cdef"：越界按截断处理，不报错
```

- 三个位置都可省略，省略即为 `None`；位置只能是整数或 `None`。
- 缺省步长为 1，步长不能为 0。
- 负索引、越界截断和负步长遵循 Python 语义。
- 切片总是创建新序列。

切片赋值等编译期限制见第 10 节。

### 元组特有规则

单元素元组需要尾逗号：

```python
empty = ()
single = (1,)
pair = 1, "x"     # 括号可以省略
```

元组支持 `len`、真值判断、迭代、成员判断和结构相等，但不支持大小比较。元组不可写入，不能与列表混合拼接，也不能作为字典键；这些误用报 `type_error`。

`tuple` 是仅注解位的契约名，不是转换函数；契约名的完整规则见第 7 节。

### 名字解构

支持固定长度、可嵌套的名字解构：

```python
a, b = (1, 2)
a, b = b, a
x, (y, z) = [3, (4, 5)]
for first, second in [(1, 2), (3, 4)]:
    print(first + second)
```

右侧可以是 list、tuple、str 或 dict（遍历其键）。长度不匹配报可捕获的 `value_error`，不可迭代值报 `type_error`。目标叶子只能是名字；编译期拒绝的目标形式见第 10 节。

### 与 Python 的关键差异

以下规则与 Python 不同：

- `bool` 不参与算术：`True + 1` 报 `type_error`。
- 跨类型大小比较报 `type_error`：`1 < "a"` 报错；`==`/`!=` 可以跨类型，结果为 False/True。
- 字典键只允许 `str/int/float/bool/None`，缺键读取报 `key_error`。

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

for item in [1, 2, 3]:      # for 可迭代：list、tuple、dict（键）、str（逐字符）、range() 结果
    print(item)
for k in {"a": 1, "b": 2}:
    print(k, "->", ...)     # 取值用 d[k]
else:
    print("没被 break")     # for/else

pass                        # 空语句，合法

label = "big" if x >= 10 else "small"   # 三元表达式（短路：只算被选中的分支）
```

`for` 的目标可以是单个名字，也可以使用第 2 节的名字解构。遍历 list 是活视图（边遍历边改会反映），遍历 dict 是键快照。

### 列表与字典推导式

```python
squares = [x * x for x in range(6) if x % 2]
pairs = [(x, y) for x in [1, 2] for y in [3, 4]]
mapping = {key: value for key, value in [("a", 1), ("b", 2)]}
reverse = {value: key for key, value in mapping.items()}
```

推导式支持多个 `for`、多个 `if` 和第 2 节的名字解构，遍历行为与普通 `for` 相同。

**作用域。** 每个推导式都有独立作用域：循环目标不会泄漏或覆盖外层同名变量，但可以读取外层变量。

```python
x = 9
result = [x for x in [1, 2]]
print(result, x)           # [1, 2] 9

def scale(factor):
    return [x * factor for x in [1, 2]]
print(scale(3))            # [3, 6]
```

**求值顺序。** 最外层可迭代表达式在外层作用域求值一次；后续可迭代表达式、条件和结果表达式在推导式作用域内从左到右求值，因此可以读取当前循环目标。

```python
x = [3, 4]
result = [x for x in x]
print(result, x)           # [3, 4] [3, 4]

pairs = [(x, y) for x in ["ab", "c"] for y in x]
print(pairs)               # [('ab', 'a'), ('ab', 'b'), ('c', 'c')]
```

**字典结果。** 字典推导式先求 key 再求 value；重复键保留后写入的值。

```python
result = {key: value for key, value in [("a", 1), ("a", 2)]}
print(result)              # {'a': 2}
```

**资源约束。** 结果容器逐项构造，并受列表/字典规模与资源配额约束。编译期不支持的推导式形式见第 10 节。

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

参数与实参校验：

- 重复参数名，或函数调用/record 构造中重复的关键字实参：编译期报 `syntax_error`；
- 同一参数同时收到位置值和关键字值：运行期报 `arity_error`。

## 5. 异常

```python
try:
    x = 1 / 0
except zero_division as e:   # 按错误类型过滤，e 是异常 record
    print("caught:", e.message)
except (name_error, type_error) as e:  # 一个分支捕获多种类型
    print("caught:", e.kind, e.message)
except ... as e:             # 捕获所有可捕获错误并绑定 e
    print("caught:", e.kind, e.message)
except:                      # 裸 except 兜底，不绑定异常值
    print("wrong")
else:
    print("没出错")
finally:
    print("一定执行")

raise "出问题了"             # 抛出 raise_error 类型，可捕获
raise                        # 在 except 块内裸 raise：重新抛出当前错误
```

`except` 的过滤条件是静态语法，不是变量求值或通用元组，共有三种形式：

- 单个可捕获 kind：`except kind`；
- 非空的 kind 括号组：`except (kind1, kind2)`；
- `...`，表示全部可捕获 kind：`except ...`。

编译期以 `syntax_error` 拒绝：未知名字（含拼写错误）、空组、组内出现不可捕获 kind。

`as e` 绑定一个固定含三个字段的 record：

- `e.kind`：字符串，实际发生的错误类型；
- `e.message`：字符串，可读错误文本；
- `e.frames`：调用栈 list，每项是 record，固定含两个字段：
  - `function`：函数名字符串；
  - `line`：源码行号整数；其他工作空间定义的代码不显示行号，固定为 `None`。

  栈从最外层调用排列到实际错误点，最后一帧是错误点。调用方帧的行号是实际发起该调用的那一行；调用跨多行时，不会退回到语句或表达式的起始行。例如打印结果可能类似 `[record(function='<module>', line=8), record(function='outer', line=5)]`。

裸 `except:` 捕获所有可捕获错误但不绑定值；`except ... as e` 则同时兜底并绑定异常 record。`as e` 是当前作用域中的普通绑定，handler 结束后仍然保留，嵌套的同名 handler 会覆盖它。

裸 `raise` 与 `finally` 暂存重抛保留原始调用栈；handler 或 `finally` 中新产生的错误则使用新调用栈。

`e` 及其帧 record 是安全副本：修改它们不影响内部错误。

调用栈只包含当前工作空间中的调用。其他工作空间定义的函数以授予名显示，`line` 为 `None`。

注意：裸 `except:` 和 `except ...` 只能处理**可捕获**的错误。可捕获 kind 的完整列表：

- 通用：`runtime_error`、`syntax_error`、`type_error`、`name_error`、`arity_error`、`raise_error`、`input_error`、`import_error`。
- 运算与契约：`zero_division`、`conversion_error`、`index_error`、`key_error`、`value_error`（解构长度不匹配或 `index()` 未找到值）、`attribute_error`（record 缺成员/新增字段）、`contract_error`（构造、注解、wrap 或字段写入的契约检查失败）。
- 文件与外部函数：`file_not_found`、`file_exists`、`is_directory`、`not_directory`、`ffi_error`。
- 文件操作约束拒绝：`file_limit_error`，普通且可捕获，不终止 VM。
- 其他执行会话的资源失败：`resource_exhausted`，仅当错误来自 `VM()` 隔离的另一台已终止 VM 时可捕获；当前 VM 或祖先的执行账户耗尽不可捕获。

```python
try:
    sub = VM("while True: pass", max_instructions=100)  # 在 VM() 里隔离死循环，配额设小
    sub.run()                                           # 循环耗尽配额 → resource_exhausted
except resource_exhausted as e:
    print("caught:", e.message)      # 可以被捕获

# 直接写在当前脚本里的死循环（不经 VM() 隔离）不可捕获。
```

`input_error` 表示输入已经结束：不会再有新的输入行时，`input()` 抛出它，脚本可以捕获。因此可以用 `except input_error` 结束读到结尾的循环；如果输入只是暂时没到，`input()` 会等待，不会报错。

`internal_error`（意外的内部失败）与 `host_error`（外部函数发生无法安全恢复的失败）始终不可捕获。

## 6. 内建函数

- `input()` / `print(...)`：一行输入 / 以空格分隔输出各个值。`print(..., end=text)` 用 `text` 替代默认的末尾换行，`end=""` 表示不追加换行；`end` 是仅关键字参数，必须是字符串。
- `len(x)`（str/list/dict/tuple）、`int(x)`、`float(x)`、`str(x)`、`repr(x)`、`range(...)`（返回 list）。`repr` 为字符串加引号并转义换行、制表符、引号和反斜杠，使任意文本可用单行显示；容器递归使用同一套安全渲染。
- 文件与目录（纯文本）：见下文。
- record 相关：`wrap(schema, d)`、`unwrap(record)`，见第 7 节。

### 文件与目录

当前工作空间提供纯文本文件系统，路径形如 `/notes/a.txt`。脚本通过以下内建读写它：

| 操作 | 用途 |
|---|---|
| `read_file(path)` | 读取文本文件 |
| `write_file(path, text)` | 写入文本文件，并创建缺失的父目录 |
| `delete_file(path)` | 删除文件 |
| `rename_file(old_path, new_path)` | 重命名或移动文件 |
| `copy_file(source_path, destination_path)` | 复制文件 |
| `make_dir(path)` | 创建目录及缺失的父目录 |
| `delete_dir(path)` | 递归删除目录树 |
| `rename_dir(old_path, new_path)` | 递归移动目录树 |
| `copy_dir(source_path, destination_path)` | 递归复制目录树 |
| `list_dir(path)` | 列出目录的直接子项并排序 |
| `path_exists(path)` | 检查文件或目录是否存在 |

**隐式目录与显式目录。** 写入文件时会隐式创建缺失的父目录。删除或重命名使隐式目录不再含任何文件或子目录时，该目录会自动移除。`make_dir` 会显式创建目标及缺失的父目录；它们即使为空也会保留。根目录始终保留。

```python
write_file("/scratch/note.txt", "text")
delete_file("/scratch/note.txt")
print(path_exists("/scratch"))            # False

make_dir("/keep/empty")
print(path_exists("/keep"), path_exists("/keep/empty"))  # True True
```

**文件操作**

- 删除、重命名和复制要求源路径是文件。源路径为目录时报 `is_directory`，文件不存在时报 `file_not_found`。
- 重命名和复制会创建缺失的目标父目录，但不覆盖已有文件；目标文件已存在时报 `file_exists`。
- 重命名不增加文件数；复制会新增文件，因此受文件数限制。

**目录操作**

- `make_dir` 的目标已有文件或目录时报 `file_exists`。
- 删除、重命名和复制要求源路径是目录。源路径为文件时报 `not_directory`，目录不存在时报 `file_not_found`。
- 重命名和复制不覆盖已有文件或目录；目标已存在时报 `file_exists`。
- 删除、重命名和复制目录时，根目录不能作为源或目标；也禁止把目录移动或复制到自身内部。这些情况报 `runtime_error`。
- 复制目录会新增整棵目录树，因此受文件数与内存限制。

**公共路径与失败规则**

- 所有会创建文件或目录的操作都先校验目标的中间路径段；任一段已是文件时报 `not_directory`。
- 变更操作会在修改文件树之前完成路径与资源检查，失败不会留下部分变更。
- 文件数、单文件大小与文件总存储量是当前 VM 对操作的约束，不是 VFS 自己的账户。约束拒绝变更时抛出普通、可捕获的 `file_limit_error`，VM 不终止；可以删除、缩小或改走其他逻辑后再试，失败与重试仍会计量。
- 已有世界超过当前 VM 的限制时，可以读取、删除、重命名或进行不扩大规模的覆盖，但不能新增或扩大内容。

### 列表、元组与字典方法

- `lst.append(x)`：原地追加一个元素，返回 `None`。
- `lst.pop()` / `lst.pop(i)`：删除并返回末尾或索引 `i` 处的元素；负索引与下标读取一致。空列表或无效索引报 `index_error`。
- `seq.count(x)`：统计列表或元组中与 `x` 结构相等的元素数。
- `seq.index(x, start=None, stop=None)`：返回列表或元组中首个匹配元素的位置；可指定搜索区间，找不到时报 `value_error`。
- `d.keys()` / `d.values()`：按插入顺序返回新的键/值列表；之后修改字典不会改变已返回的列表。
- `d.items()`：按插入顺序返回新的 `(key, value)` 二元元组列表；之后修改字典不会改变已返回的列表。
- `d.get(key)` / `d.get(key, default)`：返回键对应的值；键不存在时返回 `None` 或 `default`。
- `d.pop(key)` / `d.pop(key, default)`：删除并返回键对应的值；未提供默认值时，缺键报 `key_error`，否则返回默认值。

### 字符串方法

- `s.strip()` / `s.lstrip()` / `s.rstrip()`：去除两端、左端或右端空白；`s.strip(chars)` 等形式改为去除 `chars` 中列出的任意字符，而不是去除整个前后缀。
- `s.split()`：按连续空白拆分并忽略两端空白；`s.split(sep, maxsplit=-1)` 按非空字符串 `sep` 拆分，`sep=None` 时按空白拆分。`maxsplit` 限制拆分次数，负数表示不限制。
- `s.splitlines(keepends=False)`：按通用换行边界拆行；`keepends` 必须是 `bool`，为 `True` 时保留行尾换行符。
- `separator.join(values)`：用分隔符连接 `str`、列表、元组或字典（键）中的字符串，所有元素必须是 `str`。
- `s.find(sub, start=None, end=None)`：返回子串首次出现的位置，不存在时返回 `-1`；可指定搜索区间。
- `s.replace(old, new, count=-1)`：替换不重叠的旧子串，`count` 限制替换次数，负数表示全部替换；`old` 为空串时按 Python 语义在字符间及两端插入。
- `s.partition(sep)` / `s.rpartition(sep)`：按首个/最后一个非空分隔符拆成 `(before, sep, after)` 三元元组：

```python
"a=b=c".partition("=")   # ("a", "=", "b=c")
"a=b=c".rpartition("=")  # ("a=b", "=", "c")
"abc".partition("=")     # ("abc", "", "")
"abc".rpartition("=")    # ("", "", "abc")
```

字符串方法返回新值，不修改原字符串。上述列表、元组、字典和字符串方法集合都是封闭的；未列出的方法报 `attribute_error`。

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

- `int`/`float`/`str`/`bool`/`list`/`dict`/`tuple`、`any`，或另一个 schema（嵌套约束）；
- `any`/`bool`/`list`/`dict`/`tuple` 是仅注解位的契约名：不可调用、不可赋值；
- `int`/`float`/`str` 同时仍是转换内建。

`None` 是值，不是契约。参数、返回值、字段和带注解的赋值都不能写显式 `None` 注解，否则报 `syntax_error`；不需要契约检查时省略注解。

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

## 8. 创建虚拟机（VM）

在 sericite 里可以创建新的 VM，VM 内跑的代码也还是 sericite：

```python
sub = VM("print('hi')")          # 源码字符串
out = sub.run()                  # 运行并取回它的全部输出（字符串）
print(out)                       # 'hi\n'
sub.dispose()                    # 用完释放
```

VM 是相互隔离的工作空间：看不到你的变量，碰不到你的文件。创建时可以收紧配额、授予函数。

同一台 VM 可以反复驱动：`exec()` 投递新源码、喂输入、单步执行；也可以随时查看快照。完整契约见[虚拟机参考](vm-reference.zh-CN.md)。

```python
sub = VM("", max_instructions=10000, functions={"double": double})
try:
    sub.exec(code)
except syntax_error as e:
    print("编译失败:", e.message)
except ... as e:
    print("运行失败:", e.message)
finally:
    sub.dispose()
```

VM 可以被自动回收，但使用 `dispose()` 手动清理是更好的做法。

## 9. 模块与 import

模块与包从当前工作空间的文件系统加载。每个模块都有独立的全局命名空间，但与导入它的代码共用工作空间。

### 模块、包与文件路径

例如，当前工作空间中有以下文件：

```text
/
├── main.sericite
├── util.sericite
└── lib/
    ├── __init__.sericite
    ├── math.sericite
    ├── util.sericite
    └── sub/
        ├── __init__.sericite
        └── mod.sericite
```

模块名 `util` 对应 `/util.sericite`，`lib.math` 对应 `/lib/math.sericite`。目标也可以是包：`lib.math` 可对应 `/lib/math/__init__.sericite`。

每个中间目录都必须是含 `__init__.sericite` 的包，不支持无初始化文件的 namespace package。同一名字同时存在模块文件和包，或父级不是包时，导入报 `import_error`。

### 导入形式与绑定

```python
import util
import util as u
from util import answer
from util import answer as value

import lib.math
import lib.math as math
from lib.math import double
```

`import util` 只绑定模块对象；`from util import answer` 只绑定指定属性，不会把模块的其他名字倒入当前作用域。

`import lib.math` 绑定顶层包 `lib`，并在成功加载后把 `math` 挂为其属性；`import lib.math as math` 直接绑定目标模块。`from pkg import child` 优先读取包的已有导出；没有该导出时，尝试加载子模块 `pkg.child`。

通配符导入等编译期限制见第 10 节。

### 相对导入

相对导入以当前定义模块的包为基准：`.` 表示当前包，`..` 表示上一级包。

```python
# /lib/math.sericite
from . import util       # 加载 lib.util
from .util import answer

# /lib/sub/mod.sericite
from ..util import answer  # 加载 lib.util
```

包外的入口模块不能使用相对导入，越过最顶层包也会报 `import_error`。相对形式先解析为规范模块名，再按与绝对导入相同的规则加载。

### 执行环境与作用域

- import 在实际执行到语句时才加载模块，可以出现在函数、条件和 `try` 中；绑定名遵循普通词法作用域。
- 模块与导入者共用文件、输入输出、已授予函数和资源限制；模块函数的全局变量仍从自己的定义模块读取。

### 缓存、失败与错误

- 在同一工作空间中，同一规范模块名成功执行一次后进入缓存；重复 import 返回同一个模块对象，缓存随工作空间保留。
- 修改源码文件不会自动重新加载缓存模块。
- 导入失败不缓存失败结果，修复文件后可以重试；失败前的输出和文件副作用不回滚。
- 直接或间接循环导入、模块不存在、缺少指定导出均报可捕获的 `import_error`；模块自身的语法、运行和资源错误保留原 kind。

### 模块对象

模块对象支持点号读取，不支持属性写入。

## 10. 明确不能写（编译期直接拒绝）

- `from x import *`、`del` 与双下划线名称
- `*args`/`**kwargs`、链式比较与切片赋值
- 带星号解构、列表目标、下标/属性解构叶子
- 集合推导式与生成器表达式
- class 字段默认值、方法与继承
- 语句级裸注解赋值（`x: T` 不赋值）——class 体字段声明 `y: int` 是唯一例外
- 重绑定内建名（`print`/`len`/`wrap` 等）或契约名（`any`/`bool`/`list`/`dict`/`tuple`）——契约名只能出现在注解位

## 11. 一个完整例子

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
        print("  bad number:", e.message)
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
    print("config:", e.message)

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

# 授予一个函数给它用（按引用保留定义方环境）
def times_ten(x):
    return x * 10
worker = VM("""
n = int(input())
print(times_ten(n))
""", functions={"times_ten": times_ten})
print("worker says: " + worker.run(["6"]))   # 60

# 子 VM 有独立的文件系统：预置文件给它、运行后取回它写的文件
proc = VM("""
text = read_file("/input.txt")
write_file("/output.txt", text + "!")
""")
proc.write_file("/input.txt", "hello")      # 运行前预置文件
proc.run()
print(proc.read_file("/output.txt"))         # hello!

# 单步执行（逐语句/逐指令）并查看快照
dbg = VM("x = 1\ny = x + 1\nprint(y)")
s = dbg.step()                                # 执行一条语句，返回快照
print(s["state"], s["last_line"])             # ready 1
s = dbg.step_instruction()                    # 逐指令执行
print(s["last_line"])                         # 2
print(dbg.snapshot()["state"])                # ready（快照不推进执行）
dbg.run()
print(dbg.snapshot()["state"])                # done

# 收尾：汇总并打印最终结果
grand = total_value(inv)
print("grand total:", grand)
print("factorial(5):", factorial(5))
```
