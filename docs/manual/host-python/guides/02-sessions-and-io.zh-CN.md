# 执行会话与虚拟 IO

一台 VM 表示一段持续的执行会话，而不是一次性的函数调用。`run()`、输入等待、断点暂停、单步和多次 `exec()` 都驱动同一个运行空间。

## 继续执行后续代码

`exec()` 编译一段新源码，并在同一个模块作用域中执行：

```python
from sericite import SericiteEngine

engine = SericiteEngine()
vm = engine.create_root("x = 40", argv=["demo", "first"])

assert vm.run() == ""
assert vm.exec("x += 2") == ""
output = vm.exec("print(argv)\nprint(x)")
print(output, end="")
vm.dispose()
```

预期输出：

```text
['demo', 'first']
42
```

创建时的 `argv` 会被复制为字符串列表，之后的 `exec()` 仍然可以访问它。模块级变量、函数、schema、已加载模块、addon、VFS、输入输出配置、断点和累计资源用量也会跨投递保留。只有创建另一台 VM，才会开始一段全新会话。

`exec()` 会丢弃尚未执行完的旧程序及其执行状态，因此不要用它恢复 `waiting_input` 或 `paused`；这两种状态应提供输入后继续 `run()`，或使用单步方法恢复。编译失败时，旧程序及其执行状态保持不变。完整规则见[`VMHandle.exec`](../reference/02-vm.zh-CN.md#vmhandleexec)。

## 区分累计输出与新增输出

默认 `buffer_output=True` 时：

- `run()` 返回当前保留的累计 stdout；
- `exec()` 只返回本次投递新增的 stdout；
- `stdout()` 和快照中的 `stdout` 返回当前保留的累计文本。

```python
vm = engine.create_root('print("first")')
assert vm.run() == "first\n"
assert vm.exec('print("second")') == "second\n"
assert vm.run() == "first\nsecond\n"
assert vm.stdout() == "first\nsecond\n"
vm.dispose()
```

因此，重复调用 `run()` 可能再次取得已经读过的文本。只需要本次输出时，可以记录调用前长度，或按任务使用 `exec()` 的新增输出语义。

## 提供输入

### 预置与逐行补充

`create_root(inputs=...)` 接受字符串可迭代对象，`run(inputs)` 接受字符串列表或元组。也可以在输入不足后使用 `feed_input()`：

```python
vm = engine.create_root("""
a = input()
b = input()
print(a + b)
""")

assert vm.run(["2"]) == ""
assert vm.snapshot()["state"] == "waiting_input"

vm.feed_input("3")
assert vm.run() == "23\n"
assert vm.snapshot()["state"] == "done"
vm.dispose()
```

输入队列耗尽并不意味着程序失败。没有更多输入时，VM 保留执行状态并进入 `waiting_input`；后续输入会把它唤醒，但 `feed_input()` 本身不执行脚本，仍需调用 `run()` 或单步方法。

### 按需取得输入

`input_provider` 在队列耗尽后按需调用，适合连接宿主自己的数据源：

```python
lines = iter(["2", "3"])
vm = engine.create_root(
    "a = input()\nb = input()\nprint(a + b)",
    input_provider=lambda: next(lines, None),
)
assert vm.run() == "23\n"
vm.dispose()
```

provider 返回字符串时，该字符串成为一行输入；返回 `None`、抛出 `EOFError` 或 `StopIteration` 时，VM 进入 `waiting_input`，以后仍可恢复。若输入源已经永久关闭，provider 可以抛出 `SericiteError(kind="input_error")`，让脚本按普通输入错误处理。

provider 返回其他类型属于回调契约错误。输入回调不得重入同一 VM 的驱动方法；回调异常规则见[addon 参考](../reference/04-addons.zh-CN.md#异常与重入)。

## 实时转发输出

`output_writer` 在每次脚本 `print()` 提交输出后收到一个文本块：

```python
chunks = []
vm = engine.create_root(
    'print("a", end="")\nprint("b")',
    output_writer=chunks.append,
)
assert vm.run() == "ab\n"
assert chunks == ["a", "b\n"]
vm.dispose()
```

writer 收到的文本包含本次调用的分隔符和 `end`。输出先经过计量、上限检查和可选缓冲，再交给 writer；被输出上限拒绝的文本不会转发。

如果宿主会立即处理全部输出，不希望 root 长期保留历史文本，可以关闭缓冲：

```python
chunks = []
vm = engine.create_root(
    'print("live")',
    output_writer=chunks.append,
    buffer_output=False,
)
assert vm.run() == ""
assert vm.stdout() == ""
assert chunks == ["live\n"]
vm.dispose()
```

关闭缓冲不会关闭输出计量，也不会影响 writer 收到文本。root 的 writer 只处理 root 自己的输出；子 VM 不会自动继承它。需要转发后代输出时，应由各层脚本显式配置自己的 `output_writer`，见[脚本 VM 输出规则](../../scripting/reference/06-vm.zh-CN.md#输出转发与缓冲)。

宿主 writer 和 input provider 都是可信回调，其执行耗时、内存、阻塞和外部副作用由宿主管理。需要观察整棵 VM 树而不逐层连接 writer 时，使用[观察接口](06-observation.zh-CN.md)。
