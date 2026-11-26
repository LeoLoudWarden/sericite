# 错误与诊断

Python 宿主通过 `SericiteError` 处理 Sericite 编译、运行、资源和公开 API 失败。脚本内的静态 `except` 过滤器和完整 kind 清单见[脚本错误与异常](../../scripting/reference/05-errors.zh-CN.md)。

## 捕获宿主错误

```python
from sericite import SericiteEngine, SericiteError

engine = SericiteEngine()
vm = engine.create_root("raise 'failed'")
try:
    vm.run()
except SericiteError as error:
    print(error.kind, error.message, error.filename, error.line, error.column)
    for frame in error.frames:
        print(frame.function, frame.line)
finally:
    vm.dispose()
```

`run()`、`exec()`、单步、创建和公开管理 API 的错误都以这个异常类型或其 kind 表达；未知 Python 关键字等纯 Python 调用错误仍可能由 Python 自身抛出 `TypeError`。`KeyboardInterrupt`、`SystemExit` 等 `BaseException` 不应被当作普通脚本错误吞掉。

## SericiteError

```python
SericiteError(
    message: str,
    *,
    kind: str = "runtime_error",
    filename: str | None = None,
    line: int | None = None,
    column: int | None = None,
)
```

它继承 Python `Exception`。addon 可以构造并抛出具有具体契约 kind 的错误；宿主通常不需要为捕获错误而自行构造它。

| 属性 | 类型 | 含义 |
|---|---|---|
| `message` | `str` | 安全、可读的错误消息 |
| `kind` | `str` | 实际错误 kind，不是 `file_error` 等过滤器组名 |
| `filename` | `str \| None` | 宿主可见的逻辑源码身份，可能含引擎内 VM ID |
| `line` | `int \| None` | 错误行号，无法提供或脱敏时为 `None` |
| `column` | `int \| None` | 错误列号，无法提供或脱敏时为 `None` |
| `frames` | `tuple[SericiteFrame, ...]` | 错误最初捕获调用栈的那台 VM 的安全调用栈 |

`str(error)` 组合可用的位置、kind 和 message。不要把宿主 traceback、真实路径或秘密主动写入 addon 抛出的消息；普通契约 kind 可能由脚本捕获并读取。

## SericiteFrame

`SericiteFrame` 是 frozen dataclass，从 `sericite` 顶层导入：

```python
SericiteFrame(function: str, line: int | None)
```

- `function` 是安全函数名；跨 VM 的外来代码使用授予名等安全显示名。
- `line` 是源码行号；来自其他 VM 的定义侧代码会脱敏为 `None`。
- `error.frames` 从最外层调用排列到实际错误点，最后一帧是错误点；调用方帧指向实际发起调用的行。
- 编译期尚未进入 VM 执行的错误没有运行时调用栈，`frames` 为空元组。

每帧的行号和名称遵守与脚本异常 record 相同的跨层脱敏原则。宿主 `SericiteError.filename` 可以包含 `<sericite:vm_N>` 形式的引擎标识，这类宿主诊断字段不会进入脚本异常 record。

## 快照中的错误

`VMHandle.snapshot()["error"]` 和 `observation.snapshot()["error"]` 返回 `None` 或字典：

```python
{
    "kind": "raise_error",
    "message": "failed",
    "line": 1,
    "column": None,
    "frames": [{"function": "<module>", "line": 1}],
}
```

这里的 `frames` 是 dict 列表，不是 `SericiteFrame` 元组。它对应快照所属 VM 的安全视图，而 `SericiteError.frames` 对应错误最初捕获到调用栈的 VM。跨 VM 传播不会把另一层的完整执行状态拼接到当前视图中。

## 可捕获性与终态

脚本错误 kind 分为三类宿主需要特别区分的行为：

| 类别 | 脚本侧行为 | 宿主侧处理 |
|---|---|---|
| 普通可捕获 kind | 可由匹配的静态 `except` 捕获 | 未捕获时由驱动方法抛出 `SericiteError` |
| `resource_exhausted` | 当前 VM 或祖先的耗尽可能不能被该 VM 自己捕获；来自另一台已终止 VM 时可以由仍存活父级捕获 | 可以且应该捕获，检查状态并停止或销毁目标 |
| `host_error`、`internal_error` | 始终不可被脚本捕获，包括裸 `except` | 可以且应该捕获，视为 addon 治理失败或引擎实现失败 |

未捕获的普通错误通常使目标进入 `error`；配额耗尽进入 `resource_exhausted`。`host_error` 和 `internal_error` 在状态视图上也表现为错误终态，具体 kind 从异常或事件/快照诊断读取。

文件约束拒绝变更使用普通、可捕获的 `file_limit_error`，与执行配额耗尽的 `resource_exhausted` 不同。脚本可以在收缩文件世界后重试，宿主也不应把它误判为整个 VM 的执行预算已经耗尽。

`waiting_input` 和 `paused` 不是异常：驱动方法正常返回，目标执行状态仍可恢复。`dispose()` 销毁运行中的目标时不执行目标脚本的 `finally`，因此不能把脚本清理块当作宿主资源安全的唯一保障。

## addon 与进程级异常

addon 的契约错误、非契约异常和 `BaseException` 分别遵循不同的传播与安全消息规则，完整契约见[addon 异常与重入](04-addons.zh-CN.md#异常与重入)。观察 sink 的普通 `Exception` 只关闭出故障的观察会话，不终止 VM，见[观察故障](05-observation.zh-CN.md#投递故障与重入)。

捕获 `resource_exhausted`、`host_error` 和 `internal_error` 后应按失败策略处理，不要把它们当作普通业务分支继续盲目驱动。
