# 安全注意事项

Sericite 鼓励你通过创建隔离的运行环境来解决问题。尽管如此，你有必要对 Sericite 的安全模型做大致的了解，清楚编写代码时需要注意什么。

## 隔离与配额

### 环境隔离

前面的示例已经展示，父程序不会自动看到子程序创建的文件。反过来，子程序也不能直接读取父程序的变量和文件。下面的子程序尝试做这两件事，分别产生错误：

```python
secret = "parent secret"
write_file("/secret.txt", "parent file")

source = """
try:
    print(secret)
except name_error as e:
    print("variable:", e.kind)

try:
    print(read_file("/secret.txt"))
except file_not_found as e:
    print("file:", e.kind)
"""

program = VM(source)
print(program.run(), end="")

print("parent variable:", secret)
print("parent file:", read_file("/secret.txt"))
program.dispose()
```

预期输出：

```text
variable: name_error
file: file_not_found
parent variable: parent secret
parent file: parent file
```

这种隔离是 Sericite 提供的基本保证，不依赖子程序的自觉。父程序的变量和文件从一开始就不在子程序的运行世界中。只有父程序通过 fs、addons 等方式显式提供的内容，才会成为子程序可以访问的一部分。

### 执行限额

环境隔离只限制子程序能够访问什么，并不限制它运行多久、消耗多少资源。如果没有执行限额，一个 `while True` 就能让 `run()` 永远不返回；不断累积数据或产生输出，也会持续占用内存。隔离得再彻底，也阻止不了这种消耗。

因此，Sericite 的安全模型不仅包括环境隔离，也包括执行限额：前者决定子程序能碰到什么，后者决定它最多能消耗多少。

创建 VM 时，可以为指令数、内存和输出等设置上限。例如，下面的子程序包含一个无限循环，但最多只能执行 1000 条指令：

```python
program = VM("""
while True:
    pass
""", max_instructions=1000)

try:
    program.run()
except resource_exhausted as e:
    print("stopped:", e.kind)

print("state:", program.snapshot()["state"])
program.dispose()
```

预期输出：

```text
stopped: resource_exhausted
state: resource_exhausted
```

达到指令上限后，子程序停止执行，进入 `resource_exhausted` 状态；调用它的程序可以捕获这个错误并进行处理。尽管 `VM(...)` 为每项配额都提供了默认值，但不要把默认值当作安全建议。执行不完全可信的代码时，应根据任务需要显式设置限额。

## 为什么是这样

请看下面的场景：

Alice 正在编写一个支持模组的应用，其中一个模组由 Bob 开发。Alice 希望使用这个模组，但不希望它直接访问自己的全部变量、文件和其他能力，于是把它作为独立程序放进 VM 中运行，只提供必要的工作区、addon 和执行限额。

> 这里的“不可信”并不是认定 Bob 有恶意，而是说 Alice 不愿意让模组与自己的业务代码拥有相同的访问范围。
> 
> 审核和隔离并不矛盾：审核是为了发现问题，隔离则限制未发现的问题能够造成什么影响。现实中的模组可能热更新，第三方依赖也会不断变化；开发者通常没有精力持续审查所有并非自己编写的实现。即使审查过某个版本，也不等于可以信任它之后的所有版本。

Bob 的模组又需要一项数据分析功能，这个功能由 Carol 以可执行代码的形式提供。Bob 取得 Carol 的代码后，面临着与 Alice 相同的问题：如果直接在自己的运行空间中执行，Carol 的代码就能使用 Bob 当前拥有的文件和能力，其中可能包括 Alice 授予 Bob 的内容。

因此，Bob 也可以创建一台 VM，把 Carol 的代码放进去，只提供这项数据分析功能实际需要的工作区和能力，并设置相应的执行限额：

```text
Alice 的应用
└── Bob 的模组：独立 VM
    └── Carol 的数据分析代码：独立 VM
```

Alice 负责约束 Bob 的模组，Bob 则在自己的边界内进一步约束 Carol 的代码。Carol 不会因为 Bob 使用了这段代码，就自动获得 Bob 或 Alice 的整个运行世界；Bob 也不能通过创建子 VM 放宽 Alice 已经设置的执行限额。

Sericite 中的 VM 是天然可嵌套的：**外部代码还可能继续运行外部代码，隔离的需求也会随之一层层出现。**

## 常见坏习惯

### 滥用授予

授予函数时，函数定义环境中能够访问的内容也可能随之暴露：

```python
write_file("/secret.txt", "parent secret")

def read_parent_file(path):
    return read_file(path)

source = """
from __addon__ import read_parent_file
print(read_parent_file("/secret.txt"))
"""

program = VM(source, addons={"read_parent_file": read_parent_file})
print(program.run(), end="")
program.dispose()
```

预期输出：

```text
parent secret
```

子程序的工作区里并没有 `/secret.txt`，但 `read_parent_file()` 中的 `read_file()` 仍然读取定义它的父工作区。

Sericite 的隔离并没有被突破，但每个 addon 都会在隔离边界上创造信息开口。授予前应看清函数实际能够读取、修改或控制什么，只提供子程序确实需要的能力。

### 粗放管理

Sericite 最终会回收彻底不可达的 VM，但不保证回收时机。等待回收期间，VM 仍然占用存活数量限额，反复创建 VM 时可能因此意外出现 `resource_exhausted`。

需要确定释放时，应显式调用 `dispose()`。可以用 `finally` 覆盖正常结束和错误退出的情况：

```python
program = VM('raise "failed"')

try:
    program.run()
except raise_error as e:
    print("child:", e.message)
finally:
    program.dispose()
```

预期输出：

```text
child: failed
```

`dispose()` 会销毁这个 VM 及其仍然存活的后代，不必逐层手动清理。

### 虚拟机乱伦

VM 句柄可以经授予函数跨越隔离边界，一台 VM 甚至可以因此取得指向自己的句柄：

```python
def get_vm():
    return vm_a

vm_a = VM("""
from __addon__ import get_vm

myself = get_vm()
""", addons={"get_vm": get_vm})

vm_a.run()
vm_a.dispose()
```

类似地，不同 VM 也可以互相持有对方的句柄，形成交叉引用。这是一种**语义合法、但实现欠正确**的写法。Sericite 不会阻止它，它也没有突破安全模型：句柄是经 addon 显式授予的，执行限额与驱动限制仍然有效，彻底不可达的循环引用最终也能被回收。

但合法不等于合理。**VM 句柄代表观察和控制一个程序的能力**，随意传递会让程序的能力边界与生命周期变得难以理解。普通业务逻辑如果依赖这种结构，通常说明代码的所有权关系或职责划分存在问题。

**Sericite 不会阻止你写出糟糕的代码**。除非有明确理由，不要把 VM 当作普通数据在隔离边界之间传递。
