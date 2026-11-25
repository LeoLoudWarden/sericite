# 引擎与配额

本文定义 `SericiteEngine` 和 `SericiteLimits`。它们与本文涉及的其他公开类型都可以直接从 `sericite` 顶层包导入。

## SericiteEngine

```python
SericiteEngine(limits: SericiteLimits | None = None)
```

创建一个引擎。引擎统一执行由它创建的 root VM 以及这些 VM 的全部脚本后代。

`limits` 是新建 root VM 默认使用的整套配额；`None` 表示使用 `SericiteLimits()` 的默认值。传入其他类型报 `type_error`。`SericiteLimits` 是不可变对象，之后可以通过 root 的 `limits` 参数为某次创建选择另一整套配置。

引擎没有第三方运行时依赖，不使用 Python `exec()` 或 `eval()` 执行 Sericite 源码。编译和执行的内部结构不属于宿主 API。

## SericiteEngine.create_root

```python
engine.create_root(
    source: str | None = None,
    inputs: Iterable[str] | None = None,
    input_provider: Callable[[], str | None] | None = None,
    limits: SericiteLimits | None = None,
    addons: dict[str, Callable[..., object]] | None = None,
    output_writer: Callable[[str], object] | None = None,
    buffer_output: bool = True,
    argv: Iterable[str] | None = None,
    fs: VFSHandle | None = None,
    entry_file: str | None = None,
) -> VMHandle
```

编译并创建一台 root VM，返回与它绑定的 `VMHandle`。不要直接实例化 `VMHandle`。

### 程序来源

`source` 与 `entry_file` 必须恰好提供一个：

| 参数 | 契约 |
|---|---|
| `source` | Sericite 源码字符串。模块从工作区根 `/` 解析。UTF-8 编码后最多 4 MiB，超限报 `syntax_error` |
| `entry_file` | 工作区中的入口文件路径。必须同时提供有效的 `fs`，其文件树处于分离状态；以入口所在目录为模块解析根 |
| `fs` | 可选的 `VFSHandle`。成功创建后，分离工作区排他移入 root，旧句柄失效；缺省时创建空白 VFS |

文件函数始终以工作区根为基准，模块解析根只影响 import。`entry_file` 的读取、路径和文件错误遵循[VFS 与文件规则](03-vfs-and-files.zh-CN.md)。

创建失败不会使 `fs` 失效。`fs` 必须属于当前引擎，是有效句柄，且其文件树处于分离状态；跨引擎或其他无效句柄会被拒绝。入口读取和编译失败同样保留工作区所有权。

### 输入与输出

| 参数 | 默认 | 契约 |
|---|---|---|
| `inputs` | `None` | 预置输入的字符串可迭代对象；创建时复制并按顺序进入队列 |
| `input_provider` | `None` | 队列耗尽后调用的无参数宿主函数，返回下一行字符串或 `None` |
| `output_writer` | `None` | root 每次提交虚拟 stdout 后，以本次文本块调用的宿主函数 |
| `buffer_output` | `True` | 是否在内存中保留 root stdout；必须严格为 `bool` |

`inputs` 接受任意字符串可迭代对象，包括列表、元组和生成器。直接传入字符串时会按字符逐项入队；要提供一行输入，应使用 `[line]` 等容器。`argv` 也接受字符串可迭代对象，但明确拒绝单个字符串。两者的元素必须全部是字符串；创建时会读取并复制元素，之后宿主对原容器的修改不会影响 VM。

provider 返回 `None`、抛出 `EOFError` 或 `StopIteration` 时，VM 进入可恢复的 `waiting_input`。返回一行末尾的换行符会被移除。输入源永久关闭时，provider 应抛出 `SericiteError(kind="input_error")`，而不是用 `None` 表示永久错误。

writer 收到的字符串包含本次 `print()` 的分隔符和 `end`。输出计量、上限检查和可选缓冲先于转发；writer 返回值被忽略。`buffer_output=False` 时，`run()`、`stdout()` 和快照的缓冲视图为空，但 writer 和观察事件仍能看到已提交输出，输出上限也继续生效。

root 的 input provider 和 output writer 不会被脚本后代自动继承。它们是可信宿主回调，其内部资源消耗和外部副作用由宿主负责。

### 能力、参数与配额

| 参数 | 默认 | 契约 |
|---|---|---|
| `addons` | `None` | 字符串导入名到 Python 可调用对象的字典，经 `__addon__` 授予 |
| `argv` | `None` | root 初始 `argv` 的字符串可迭代对象；缺省为空列表 |
| `limits` | `None` | 此 root 使用的整套 `SericiteLimits`；`None` 使用引擎默认配置 |

`create_root(limits=...)` 是替换整套配置，不是与引擎默认值逐字段合并。root 的后代按脚本 VM 规则继承并只能收紧配额。

`argv` 是 root 的初始模块变量，不会自动出现在子 VM 中。它可以与 addon 导入名相同；若导入会重绑定本地内建，接收方需要使用导入别名。

addon 的完整校验、数据和异常契约见[addon 参考](04-addons.zh-CN.md)。

### 创建失败

参数形状错误通常以 `SericiteError(kind="type_error")` 报告。未知 Python 关键字参数由 Python 自身以 `TypeError` 拒绝。

参数校验、入口读取和编译全部成功后才提交 VM 创建及观察事件。失败创建不产生 `vm.created`，也不应留下可用的新 root 句柄。源码或入口编译错误使用 `syntax_error`，文件读取使用相应文件错误。

## SericiteEngine.create_vfs

```python
engine.create_vfs() -> VFSHandle
```

创建一个空的分离工作区。根目录 `/` 始终存在。返回的句柄只能在当前引擎中使用，可通过文件方法预置内容，再移交给 `create_root(fs=...)`。

不要直接实例化 `VFSHandle`。分离句柄的文件写入使用引擎默认 `limits` 中的文件约束；依附 VM 后，宿主通过 `VMHandle` 管理时使用该 VM 的配额。详见[VFS 与文件](03-vfs-and-files.zh-CN.md)。

## SericiteEngine.observe

```python
engine.observe(
    sink: Callable[[SericiteEvent], object],
) -> SericiteObservation
```

注册观察会话，接收此引擎之后提交的 root 和后代事件。sink 不可调用时报 `type_error`。完整接口见[观察参考](05-observation.zh-CN.md)。

## SericiteLimits

```python
SericiteLimits(
    max_instructions: int = 1_000_000,
    max_output_bytes: int = 1_048_576,
    max_frames: int = 100,
    max_list_size: int = 100_000,
    max_dict_size: int = 100_000,
    max_string_bytes: int = 1_048_576,
    max_int_bits: int = 4096,
    max_total_bytes: int = 67_108_864,
    max_descendant_vms: int = 1000,
    max_vm_depth: int = 8,
    max_fs_files: int = 1000,
    max_fs_file_bytes: int = 1_048_576,
    max_fs_storage_bytes: int = 67_108_864,
)
```

这是不可变 dataclass。所有字段都有默认值；使用前应评估这些值是否适合任务。默认值面向开发调试，不是运行不可信代码的安全建议。

| 字段 | 默认值 | 限制对象 |
|---|---:|---|
| `max_instructions` | 1,000,000 | 指令及按规模折算的工作量 |
| `max_output_bytes` | 1,048,576 | 每台 VM 累计提交的 stdout UTF-8 字节数 |
| `max_frames` | 100 | 调用帧数 |
| `max_list_size` | 100,000 | 单列表/元组槽位数，也参与 addon 边界规模约束 |
| `max_dict_size` | 100,000 | 单字典项数，也参与 addon 边界规模约束 |
| `max_string_bytes` | 1,048,576 | 单字符串字符数；名称保留历史“字节”叫法 |
| `max_int_bits` | 4096 | 整数位宽 |
| `max_total_bytes` | 67,108,864 | 近似内存用量高水位 |
| `max_descendant_vms` | 1000 | 每台 VM 的整棵存活后代数，不含自身 |
| `max_vm_depth` | 8 | VM 嵌套深度，root 深度为 0 |
| `max_fs_files` | 1000 | 文件操作可扩张到的 VFS 文件总数 |
| `max_fs_file_bytes` | 1,048,576 | 可写入或复制的单文件 UTF-8 字节数 |
| `max_fs_storage_bytes` | 67,108,864 | 文件操作可扩张到的 VFS 近似总存储量 |

所有字段只接受严格整数，`bool` 不被当作整数。只有 `max_instructions`、`max_output_bytes` 和 `max_total_bytes` 接受 `-1`，表示该层相应累计配额不设上限；其他字段必须是非负有限整数。非法值报 `type_error`，未知字段由 Python 抛出 `TypeError`。

### 继承与跨层约束

脚本内创建子 VM 时，配额逐项取父级上限与请求值中更严格的一项：

- 请求 `-1` 不会移除祖先的有限上限；
- 只有所有相关层级都不设上限时，该项累计用量才不受上限约束；
- 子 VM 的指令、内存和创建消耗也计入相关祖先，有限祖先始终是硬上限；
- `max_descendant_vms=0` 禁止该 VM 创建任何后代，不影响其父级创建它；
- 无限配额只取消上限检查，不停止记账，也不代表物理资源无限。

脚本侧完整继承规则见[VM 配额](../../scripting/reference/06-vm.zh-CN.md#配额)，计费模型和近似成本边界见[架构说明](../../../architecture.zh-CN.md#5-资源配额)。

三个 `max_fs_*` 字段约束一次实际调用链可扩张到的文件世界，不是随 VFS 永久携带的配额。接管已有超限工作区时，收缩或不进一步扩张的操作仍可被允许；约束拒绝变更使用普通、可捕获的 `file_limit_error`，与执行配额耗尽的 `resource_exhausted` 不同。
