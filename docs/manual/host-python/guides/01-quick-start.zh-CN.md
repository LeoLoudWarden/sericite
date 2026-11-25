# 快速开始

本章在 Python 程序中创建一台 root VM，运行一段 Sericite 源码，并取得它的虚拟输出。

## 运行第一段代码

安装 `sericite` 后，创建以下 Python 程序：

```python
from sericite import SericiteEngine

engine = SericiteEngine()
vm = engine.create_root("""
name = input()
print("hello", name)
""")

output = vm.run(["world"])
print(output, end="")
print("state:", vm.snapshot()["state"])
vm.dispose()
```

预期输出：

```text
hello world
state: done
```

`create_root()` 编译源码并返回一个 `VMHandle`。`run(["world"])` 为脚本提供一行输入，然后驱动 VM，直到程序完成、等待更多输入、遇到断点或发生错误。

这里的 `print()` 写入 VM 自己的虚拟 stdout，不会自动写入 Python 进程的标准输出。默认情况下，引擎保留这些文本，因此 `run()` 返回 `"hello world\n"`，示例再用 Python 的 `print()` 显示它。

## root VM 与引擎

一个 `SericiteEngine` 可以创建和管理多台 VM。宿主直接创建的是 root VM；root 或其他脚本还可以通过 Sericite 内建的 `VM()` 创建后代。所有层级都由同一个引擎执行，而不是在每层再嵌入一个 Python 解释器。

`VMHandle` 是宿主控制这台 VM 的入口，与创建它的引擎绑定。保留句柄后，可以继续执行代码、提供输入、读取快照、设置断点或销毁 VM。脚本内部创建和驱动子 VM 的方法见[独立运行空间](../../scripting/guides/06-vm.zh-CN.md)。

新 VM 默认拥有：

- 独立的虚拟输入和输出；
- 空白的纯文本内存文件系统；
- 创建自己的子 VM 的能力。

它不会自动看到 Python 变量、真实磁盘、网络或宿主进程中的其他对象。`argv` 是 root 的初始模块变量，默认为空列表；其他能力需要显式配置或授予。

## 源码与工作区入口

最直接的方式是把源码字符串传给 `source`：

```python
vm = engine.create_root("print(6 * 7)")
assert vm.run() == "42\n"
vm.dispose()
```

`source` 与 `entry_file` 必须恰好选择一种。`entry_file` 从显式提供的 VFS 读取入口；准备多文件工作区和移交 VFS 所有权见[准备工作区](04-workspaces.zh-CN.md)，完整创建参数见[引擎与配额](../reference/01-engine-and-limits.zh-CN.md)。

## 处理失败

脚本编译或运行失败时，创建或驱动方法会向 Python 抛出 `SericiteError`。`kind` 是稳定的错误类别，`message` 是可读诊断：

```python
from sericite import SericiteEngine, SericiteError

engine = SericiteEngine()
vm = engine.create_root("raise 'failed'")
try:
    vm.run()
except SericiteError as error:
    print(error.kind, error.message)
finally:
    vm.dispose()
```

预期输出：

```text
raise_error failed
```

`finally` 中的 `dispose()` 确保正常结束和错误路径都释放 VM 及其存活后代。彻底不可达的 VM 最终也会由 Python 垃圾回收处理，但回收时机不保证；需要确定释放时点时，应显式销毁。

## 下一步

- 需要多次投递代码或处理输入等待时，阅读[执行会话与虚拟 IO](02-sessions-and-io.zh-CN.md)。
- 需要调用 Python 函数时，阅读[授予宿主能力](03-addons.zh-CN.md)。
- 执行不完全可信的代码前，阅读[安全模型](../../../security.zh-CN.md)，并根据任务设置[执行配额](../reference/01-engine-and-limits.zh-CN.md#sericitelimits)。
