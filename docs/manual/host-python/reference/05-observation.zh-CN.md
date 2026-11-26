# 观察

Python 宿主可以观察同一引擎内的每台 VM，包括脚本内部创建的后代，而不必授予脚本新能力或直接持有后代句柄。观察接口只属于宿主，不会暴露为 Sericite 内建或脚本 VM 方法。

## 订阅

```python
engine.observe(
    sink: Callable[[SericiteEvent], object],
) -> SericiteObservation
```

注册一个可调用对象并返回观察会话。sink 不可调用时报 `type_error`。

观察会话只接收注册后产生的事件，不回放既有 VM 或历史事件。推荐使用上下文管理器：

```python
with engine.observe(events.append) as observation:
    root = engine.create_root("print('hello')")
    root.run()
    snapshot = observation.snapshot(root.snapshot()["vm_id"])
```

离开 `with` 块会调用 `close()`。

## SericiteEvent

`SericiteEvent` 是 frozen dataclass，从 `sericite` 顶层导出：

```python
SericiteEvent(
    sequence: int,
    kind: str,
    vm_id: int,
    parent_id: int | None,
    depth: int,
    data: dict[str, object],
)
```

| 字段 | 含义 |
|---|---|
| `sequence` | 引擎内单调递增的事件序号 |
| `kind` | 下表列出的事件种类 |
| `vm_id` | 产生事件的 VM 的引擎内 ID |
| `parent_id` | 父 VM 的引擎内 ID，root 为 `None` |
| `depth` | VM 嵌套深度，root 为 0 |
| `data` | 事件专属宿主侧数据字典 |

frozen 约束事件字段的重新赋值，不把 `data` 变成不可变映射。引擎为每个观察会话提供独立的事件对象和嵌套 `data` 深拷贝；修改其中一份不会影响其他观察器或引擎。

## 事件种类

| `kind` | `data` 与产生时机 |
|---|---|
| `vm.created` | `state`、`filename`、`limits`、`addons`。`limits` 是该 VM 的 `SericiteLimits`，`addons` 是排序后的授予名元组。创建、注册、父级与祖先计数、VFS 依附全部提交后产生；创建失败不产生事件 |
| `vm.state_changed` | `old_state`、`new_state`、`reason`。断点暂停另含 `breakpoint={"line": int, "path": str \| None}`，终态错误另含 `error_kind`。只有状态真实变化时才产生 |
| `vm.output` | `text`，一段已提交的虚拟 stdout 文本。输出计量和 stdout 缓冲之后、输出转发之前产生；被输出上限拒绝的文本不产生事件 |
| `vm.disposed` | `reason`、`state`。显式销毁使用 `reason="dispose"`、`state="terminated"`；自动回收使用 `reason="gc"` 并保留回收前状态 |

可观察的状态变化原因包括 `exec`、`resume`、`breakpoint`、`input`、`output_writer`、`return`、`error`、`terminate`、`dispose`。脚本捕获异常本身不产生终态变化，重复销毁已销毁 VM 也不会产生额外事件。

输出事件归属于实际把文本提交到自身虚拟 stdout 的 VM。子程序向父程序转发输出，每台真实写入的 VM 都会产生各自的事件。`buffer_output=False` 时，`data["text"]` 仍报告已提交输出，尽管 `stdout()` 和快照中的缓冲视图为空。

输出事件只表示文本已经提交。随后的 output writer 失败不会撤回该事件。

## SericiteObservation

### 状态属性

```python
observation.closed -> bool
observation.failed -> bool
observation.failure -> str | None
```

- `closed` 表示会话是否已关闭。
- `failed` 表示 sink 普通异常是否已经使会话故障关闭。
- `failure` 保存宿主侧字符串 `"ExceptionType: message"`；异常自身无法渲染时只保存异常类名，未故障时为 `None`。

这些属性只描述观察会话，不表示被观察 VM 是否失败。

### SericiteObservation.close

```python
observation.close() -> None
```

幂等关闭会话，并立即停止后续投递，包括当前分发过程中尚未交付的事件。关闭一个会话不会关闭其他会话。

### SericiteObservation.poll

```python
observation.poll() -> None
```

冲刷引擎已经排队的 GC 销毁通知，按序号向仍符合接收条件的观察会话投递。需要在显式时点处理通知时调用它，而不是依赖另一次无关引擎操作。

观察回调中不得调用 `poll()`。对已关闭会话调用 `poll()` 不会重新打开它。

### SericiteObservation.snapshot

```python
observation.snapshot(vm_id: int) -> dict[str, object]
```

按引擎内 ID 读取任意存活 VM 的[宿主安全快照](02-vm.zh-CN.md#快照)，也可以在观察回调中使用。宿主无需取得后代句柄即可读取事件提交后的执行状态。

返回值只有安全值，不包含可操作的 VM 句柄或内部上下文，不赋予驱动或修改权限，也不通过缓存引用延长 VM 存活。修改返回字典不会修改 VM。

`vm_id` 必须是非负严格整数，`bool` 也会被拒绝；类型非法报 `type_error`。ID 未知或已销毁、以及对已关闭观察会话调用快照，均报 `runtime_error`。`vm.disposed` 通知在注销之后到达，因此此时目标已经不能再快照。

### 上下文管理器

```python
observation.__enter__() -> SericiteObservation
observation.__exit__(...) -> None
```

`with` 进入时返回自身，退出时关闭。通常直接使用 `with engine.observe(...)`，不需要手动调用这两个方法。

## 投递、故障与重入

普通事件随执行事实同步投递。观察不执行脚本代码，也不改变 VM 的指令或内存计量。事件产生前已注册且仍打开的每个会话都会收到同一事实，但各自得到独立副本。

sink 抛出普通 `Exception` 时，引擎只关闭该观察会话，VM 和其他观察器继续运行。这类故障遵循上述 `failed`/`failure` 状态，不按 addon 的 `host_error` 规则终止 VM。`KeyboardInterrupt`、`SystemExit` 等其他 `BaseException` 仍是进程级事件，向宿主传播。

观察回调不得重入同一引擎的操作。下列操作会以 `runtime_error` 拒绝：

- 创建 VM 或 VFS；
- 驱动、喂输入、销毁 VM 或操作 VFS；
- 注册另一个观察会话；
- 调用 `poll()`。

回调中允许关闭观察会话和调用只读 `observation.snapshot(vm_id)`。对不同引擎的操作不受此限制。

sink 应保持有界、非阻塞，用完后关闭。观察回调和待投递通知都是宿主侧成本，不属于脚本执行计量。

## 垃圾回收通知

显式 `dispose()` 同步产生 `vm.disposed(reason="dispose")`，不会再额外排队 GC 事件。

自动回收采用延迟投递：Python 回收回调注销 VM 并排队纯数据通知，但绝不调用 sink。排队的 `vm.disposed(reason="gc")` 由以下入口按相对序号投递：

- 显式 `observation.poll()`；
- 后续会冲刷观察事件的安全引擎入口。

已关闭会话不再接收排队通知；通知排队后才注册的会话也不会收到旧事件。事件通知时点不等于 Python 实际回收时点，自动 VM 回收本身也不保证立即发生。
