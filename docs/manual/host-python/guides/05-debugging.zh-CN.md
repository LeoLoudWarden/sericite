# 调试 VM

Python 宿主可以通过 `VMHandle` 设置断点、逐步执行和读取快照，不需要在被调试脚本中插入额外代码。

## 在语句入口暂停

下面的程序在第二行执行前暂停：

```python
from sericite import SericiteEngine

engine = SericiteEngine()
vm = engine.create_root("x = 1\nx += 1\nprint(x)")
vm.add_breakpoint(2)

assert vm.run() == ""
snapshot = vm.snapshot()
assert snapshot["state"] == "paused"
assert snapshot["locals"]["x"] == 1
assert snapshot["next_line"] == 2
assert snapshot["breakpoint"] == {"line": 2, "path": None}

assert vm.run() == "2\n"
assert vm.snapshot()["state"] == "done"
vm.dispose()
```

断点命中发生在语句第一条指令执行前，因此第二行的 `x += 1` 尚未生效。`run()` 正常返回，不抛出异常，也不执行目标脚本的 `except` 或 `finally`。再次调用 `run()` 会恢复执行，只豁免当前断点一次；循环再次到达同一位置时仍会暂停。

`add_breakpoint(line, path=None)` 中：

- `path=None` 匹配当前主源码及其函数；
- 显式 `path` 匹配目标 VM 自己的入口文件或 import 模块，路径按 VFS 规则规范化；
- 其他 VM 授予的外来代码不会误命中目标断点。

`remove_breakpoint()` 幂等删除位置，`breakpoints()` 按添加顺序返回纯数据字典。只有实际语句入口可以命中；空行、注释、多行语句的非起始行和不产生指令的 `pass` 不会暂停。详细绑定规则见[VM 断点参考](../reference/02-vm.zh-CN.md#断点)。

## 单步与快照

`step()` 执行一条语句并返回快照：

```python
vm = engine.create_root("x = 10\nx += 5\nprint(x)")

snapshot = vm.step()
assert snapshot["state"] == "ready"
assert snapshot["locals"]["x"] == 10

snapshot = vm.step()
assert snapshot["locals"]["x"] == 15

snapshot = vm.step()
assert snapshot["state"] == "done"
assert snapshot["stdout"] == "15\n"
vm.dispose()
```

函数内部的语句和断点可能影响实际停止位置。`step_instruction()` 则只执行一条 Sericite 内部指令，适合需要更细粒度的调试器；内部指令是调试粒度，不是脚本源码中的公开运算 API。

`snapshot()` 不推进执行，只返回当前执行状态的安全副本：其中只含安全值，不含可继续操作的 VM 句柄，修改返回字典也不会修改 VM。上面的示例读取了 `state`、`locals`、`next_line`、`breakpoint` 和 `stdout`；宿主快照还提供 `vm_id`、`parent_id`、`depth` 等诊断字段。

完整字段、错误诊断和复杂值的安全表示见[VM 快照参考](../reference/02-vm.zh-CN.md#快照)。

## 终止与销毁

`terminate()` 把 `ready`、`waiting_input` 或 `paused` 的当前目标标记为 `terminated`，用于放弃当前程序的执行状态；对其他状态是空操作。终态后仍可读取快照和 stdout，或取回 VFS。

`dispose()` 则销毁目标及其全部存活后代，并释放存活 VM 数量槽位：

```python
vm = engine.create_root("child = VM('while True:\\n    pass')")
vm.run()
vm.dispose()
vm.dispose()
```

`dispose()` 可以在任意状态调用，重复调用是空操作。运行中的目标在当前指令安全退出后停止，不执行目标脚本的 `finally`。销毁后句柄失效，除重复销毁外的其他操作会报 `runtime_error`。

彻底不可达的 VM 最终也会自动回收，但时机不保证。需要确定释放时点时，使用 `dispose()`。宿主管理动作不计入目标脚本资源计量，但实际执行仍受目标配额约束；完整生命周期见[VM 参考](../reference/02-vm.zh-CN.md#生命周期)。
