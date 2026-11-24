# 快速开始

Sericite 是一门脚本语言，它为动态化、轻量化、透明化的程序执行场景而设计。

本章介绍 Sericite 的基本类型与函数语法。

## Sericite 不是 Python

Sericite 借用 Python 语法，但只实现经过明确选择的语言表面。Sericite 源码编译为专用指令，再由 Sericite 运行时执行。它没有 Python 的模块生态、完全反射或任意对象模型，也不会因为语法相似就自动支持所有 Python 特性。

例如，以下能力不能按 Python 习惯直接带入：

- `import` Python 的内置标准库；
- `open()`、`exec()` 作为全局内建并不存在；
- 未列出的 Python 语法和方法会在编译或运行时被拒绝。

这些差异来自 Sericite 自己的语言和运行时契约，后续章节会逐项说明实际可用的功能。

**特别说明**：本文代码块的语法高亮标记为 "python"，这仅是 Markdown 的排版手段，不改变 Sericite 的语言身份。

## 一行程序

```python
name = input()
print("hello", name)
```

为程序提供一行输入 `Sericite` 时，预期输出：

```text
hello Sericite
```

这里只列程序产生的 stdout，不包含运行环境可能显示的输入回显。

## 基础类型与运算

### 数值

```python
7 / 2        # 3.5（除法恒为浮点）
7 // 2       # 3
7 % 3        # 1
a += b       # 自动转为 a = a + b

1 < 2        # 支持 == != < <= > >=
nan = float("nan")
nan == nan   # False：NaN 不等于自身

2 ** 3       # 8
2 ** 3 ** 2  # 512：右结合，即 2 ** (3 ** 2)
2 ** -2      # 0.25
```

### 字符串

```python
"ab" + "cd"
"""line1
line2"""     # 多行字符串
f"{1/3:.2f}" # f-string
"+" * 3      # "+++"
```

### 内建容器

支持 `list`、`dict`、`tuple`，无 `set`。

```python
empty = ()
single = (1,)      # 单元素元组需要尾逗号
pair = 1, "x"      # 括号可以省略

[1, 2] + [3]       # [1, 2, 3]
(1, 2) + (3,)      # (1, 2, 3)

2 * [1, 2]         # [1, 2, 1, 2]
(1, 2) * 0         # ()

[a for a in l]     # 推导式
{k: v for k, v in d.items()}

a, b = (1, 2)      # 名字解构
a, b = b, a
x, (y, z) = [3, (4, 5)]
for first, second in [(1, 2), (3, 4)]:
    print(first + second)
```

### 布尔值

```python
1 in [1, 2, 3]
"a" in {"a": 0}
"12" in "123"

True == 1    # False，bool 不是 int
1 + True     # type_error，不参与算术

if 1:        # 自动真值转换
    ...

not x
x and y or z # 短路求值，优先级 not > and > or
```

会被视为 False 的有：None、False、0、空字符串 ""、空列表 []、空元组 ()、空字典 {}。

### 对象比较

依次遵循规则：
1. 浮点数 NaN 不等于自身
2. 相同对象始终相等
3. 容器中的元素逐个、递归地比较

```python
nan = float("nan")
nan == nan       # False：NaN 不等于自身
[nan] == [nan]   # False：两个新容器逐元素比较
lst = [nan]
lst == lst       # True：同一个对象
```

## 函数

### 基础定义

```python
def add(a, b=10):           # 支持默认参数（定义时求值一次）
    return a + b
add(1, b=20)                # 21，支持关键字实参
```

### 闭包捕获

支持 `global`、`nonlocal`：

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

### 可变参数与装饰器

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

不支持 `yield`、迭代器/生成器语法；`range(4)` 返回列表 `[0, 1, 2, 3]`。
