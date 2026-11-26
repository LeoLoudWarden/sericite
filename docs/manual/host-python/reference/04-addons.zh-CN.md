# addon

addon 是 Python 宿主显式授予 root VM 的能力。宿主通过 `create_root(addons=...)` 提供函数，脚本通过预加载模块 `__addon__` 显式导入。

本文只定义 Python 与 VM 之间的边界。脚本向下一层授予 Sericite 函数时的定义方环境、闭包和跨 VM 引用规则见[脚本 VM 参考](../../scripting/reference/06-vm.zh-CN.md#addon-授予)。

## 授予函数

```python
engine.create_root(
    source,
    addons={"public_name": callback},
)
```

`addons` 必须是 `None` 或字典。每个键是导入名，每个值必须可调用；创建 root 时统一校验整张表，字典形状、名称或值无效报 `type_error`。

导入名必须是合法且不以 `__` 开头的字符串标识符。它可以与内建或 `argv` 同名，但直接导入造成的内建重绑定会被编译器拒绝，接收方应使用别名：

```python
from __addon__ import len as host_len
```

`__addon__` 不是 VFS 文件，也不提供任意 Python 模块搜索。每个需要 addon 的源码模块都写：

```python
from __addon__ import public_name
```

支持 import 别名、跨 `exec()` 保留和由脚本继续向子程序授予转授。没有授予的名字以 `import_error` 报告。addon 不再直接注入全局命名空间，不存在省略 import 的名字回退。

Python 回调可以接收位置参数、关键字参数以及脚本展开的可变参数，实际能接受的调用形式由该 Python callable 自己决定。引擎先复制并验证参数，再调用回调；参数边界失败时不会调用它。

## 数据边界

参数和返回值双向深拷贝。只允许以下内建类型本身及其递归组合，不把同名子类或任意 Python 对象自动纳入白名单：

| 类别 | 允许类型 |
|---|---|
| 空值与标量 | `None`、`bool`、`int`、`float`、`str` |
| 容器 | `list`、`dict`、`tuple` |

- list/tuple 类型在两个方向都保留。
- dict 的键和值都受边界约束；宿主返回的 dict 键只能是 `str`、`int`、`float`、`bool` 或 `None`。
- 嵌套容器逐项复制，脚本和宿主不共享可变容器。
- record/schema、模块、VM/VFS 句柄、函数及其他对象不能越过宿主边界。
- 需要把 record 交给宿主时，先在脚本内用 `unwrap()` 转成 dict。

返回值还受当前 VM 的字符串字符数、整数位宽、list/tuple 大小、dict 大小、总节点数和嵌套深度约束。参数和返回值的复制工作按节点计入引擎工作量，返回结构同时受内存配额约束。

违反数据或复制契约使用可捕获的 `addon_error`。

## 异常与重入

### 回调失败

| 回调行为 | 引擎行为 |
|---|---|
| 正常返回 | 验证并深拷贝返回值 |
| 抛具体契约 kind 的 `SericiteError` | 按原 kind 传播，脚本可捕获性遵守语言规则 |
| 抛 `SericiteError(kind="resource_exhausted")` | 视为当前 VM 自身配额耗尽，进入相应终态，脚本不可捕获 |
| 抛契约之外的普通 `Exception` | 当前 VM 以不可捕获的 `host_error` 终止，宿主收到 `SericiteError` |
| 抛 `KeyboardInterrupt`、`SystemExit` 等其他 `BaseException` | 原样穿透驱动调用，交还宿主处理 |

契约 kind 应来自[脚本错误注册表](../../scripting/reference/05-errors.zh-CN.md#可捕获-kind)中的实际错误名。`file_error`、`lookup_error` 是编译期过滤器组，不是 addon 回调应抛出的实际 kind。`host_error` 和 `internal_error` 描述治理或实现故障，不应作为正常业务返回值使用。

普通契约错误可由脚本捕获，因此其 `message` 由宿主自行保证不包含秘密。若失败应当允许脚本恢复，不要使用 `resource_exhausted`，可改用 `runtime_error`、`addon_error` 或其他符合实际语义的普通 kind。

契约外宿主异常不会把原异常文本或 traceback 透传给脚本。`host_error` 的安全消息包含 addon 名和宿主异常类型名，不包含原异常消息。脚本无法通过具体过滤器、`except ...` 或裸 `except` 捕获它。

### 重入

回调中对同一 VM 再调用 `run()`、`exec()`、`step()` 或 `step_instruction()` 会被拒绝，不能嵌套驱动同一调度循环。需要后续执行时，应从当前回调返回，再由外层宿主驱动。

观察回调使用更严格、独立的重入规则，见[观察参考](05-observation.zh-CN.md#投递故障与重入)。

### 虚拟 IO 回调

root 的 `input_provider` 和 `output_writer` 也是可信宿主代码，但不是通过 `__addon__` 导入的函数。

- input provider 以 `None`、`EOFError` 或 `StopIteration` 表示暂时等待输入；永久关闭应抛 `SericiteError(kind="input_error")`。
- provider 必须返回字符串或 `None`，writer 必须同步接受一个字符串。
- provider 返回其他类型、writer 抛出未翻译的普通 `Exception` 等意外失败，当前由统一执行路径转换为不可捕获的 `internal_error`；它们不是 addon 回调的 `host_error`。
- 宿主应自行捕获并翻译预期错误，不依赖意外异常向脚本传递诊断。
- writer 的失败发生在触发它的 `print()` 路径上，已经提交的输出和输出事件不会撤回。

创建参数见[引擎参考](01-engine-and-limits.zh-CN.md#输入与输出)，用法见[执行会话与虚拟 IO](../guides/02-sessions-and-io.zh-CN.md)。

## 成本与信任责任

宿主回调内部的 CPU、内存、阻塞和外部副作用不由引擎指令配额托管。引擎负责调用派发、参数和返回值复制以及引擎侧结果构造的成本。

因此，授予 addon 是显式信任承诺。能力实现者应自行：

- 验证参数和权限，限制输入规模、调用频率和外部资源；
- 避免不必要的文件、网络、设备或秘密访问；
- 防止不可信输入触发 `sys.exit()` 等进程级行为；
- 为真正对抗性的代码增加独立进程、容器等操作系统级隔离。

引擎保证未授予能力不可达，但不替能力实现者判断已授予操作是否安全。
