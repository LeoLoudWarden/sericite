# 观察 VM 活动

宿主可以观察同一引擎中的 root 和所有后代 VM，包括脚本内部创建的 VM，而不必向脚本授予新能力，也不必逐层连接输出 writer。

## 订阅事件

`engine.observe(sink)` 注册一个接收 `SericiteEvent` 的可调用对象，并返回观察会话：

```python
from sericite import SericiteEngine

engine = SericiteEngine()
events = []
with engine.observe(events.append) as observation:
    root = engine.create_root("print('hello')")
    assert root.run() == "hello\n"
    snapshot = observation.snapshot(events[0].vm_id)

assert [event.kind for event in events] == [
    "vm.created",
    "vm.output",
    "vm.state_changed",
]
assert snapshot["stdout"] == "hello\n"
root.dispose()
```

观察会话是上下文管理器，离开 `with` 块即关闭。也可以显式调用 `close()`；重复关闭是空操作。会话只接收注册后产生的事件，不回放已有 VM 或历史输出。

每个事件都有单调递增的 `sequence`、`kind`、产生事件的 `vm_id`、`parent_id`、`depth` 和事件专属 `data`。主要事件为：

- `vm.created`：创建、注册、层级计数和 VFS 依附全部提交后产生；
- `vm.state_changed`：新状态和调试信息提交后产生；
- `vm.output`：一段虚拟 stdout 提交后产生；
- `vm.disposed`：显式销毁或自动回收后产生。

完整载荷见[观察参考](../reference/05-observation.zh-CN.md#事件种类)。

## 观察脚本创建的后代

不需要在脚本中调用任何观察 API：

```python
engine = SericiteEngine()
events = []
with engine.observe(events.append):
    root = engine.create_root(
        "child = VM('print(\"deep\")')\nchild.run()"
    )
    root.run()

created = [event for event in events if event.kind == "vm.created"]
output = [event for event in events if event.kind == "vm.output"]
assert [event.vm_id for event in created] == [0, 1]
assert created[1].parent_id == 0
assert created[1].depth == 1
assert [(event.vm_id, event.data["text"]) for event in output] == [(1, "deep\n")]
root.dispose()
```

输出事件归属于实际把文本写入自己虚拟 stdout 的 VM。如果父级 writer 又把这段文本写入父级 stdout，父级也会产生自己的输出事件。`buffer_output=False` 只清空缓冲视图，不会隐藏 `vm.output` 中已经提交的 `data["text"]`。

## 按 VM ID 读取快照

观察会话的 `snapshot(vm_id)` 可以读取任意存活 VM 的宿主安全快照，包括没有直接句柄的后代。快照只含安全副本，不含可操作的 VM 句柄。它也可以在 sink 回调中使用：

```python
engine = SericiteEngine()
scenes = []
observation = None


def sink(event):
    if event.kind == "vm.output":
        scenes.append(observation.snapshot(event.vm_id))


observation = engine.observe(sink)
root = engine.create_root("print('live')")
root.run()
assert scenes[0]["vm_id"] == root.snapshot()["vm_id"]
assert scenes[0]["stdout"] == "live\n"
observation.close()
root.dispose()
```

快照不赋予创建、驱动、修改或销毁权限。修改快照不会影响 VM，也不会通过保留内部引用来延长 VM 存活。

`vm.disposed` 通知到达时目标已经注销，不能再对它调用 `snapshot()`。未知 ID、已销毁 ID、非法 ID 类型以及对已关闭观察会话读取快照都会报错。

## 回调边界与关闭

普通事件在事实提交时同步投递，每个观察器收到独立的事件和嵌套 `data` 副本。sink 中允许关闭观察会话和读取只读快照；创建、驱动或销毁 VM 等同一引擎的重入操作会被拒绝。sink 抛出普通 `Exception` 时，只有当前观察会话会关闭，VM 和其他观察器继续运行。完整允许操作、故障和重入规则见[观察参考](../reference/05-observation.zh-CN.md#投递故障与重入)。

## 自动回收通知

显式 `dispose()` 会同步产生销毁事件；Python 垃圾回收产生的销毁通知则延迟投递。需要显式控制投递时点时，调用 `observation.poll()`。接收条件和后续引擎入口的冲刷规则见[观察参考](../reference/05-observation.zh-CN.md#垃圾回收通知)。

观察 sink 应保持有界、非阻塞，并在用完后关闭。其宿主侧成本不受脚本执行配额托管。
