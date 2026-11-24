# 通用内建

本文列出不依附于特定容器、文件系统或 VM 句柄的脚本内建。文件函数见[文件与目录](04-files.zh-CN.md)，构造器 `VM` 和 `VFS` 分别见 [VM](06-vm.zh-CN.md) 与 [VFS](07-vfs.zh-CN.md)。

签名中的 `*` 表示其后的参数只能用关键字传入。未注明默认值的参数必须提供。除特别说明外，内建不修改参数本身。

## `input`

```text
input() -> str
```

从 stdin 读取一行并返回字符串，不返回行尾换行符。

- 输入可用时立即返回。
- 程序暂时没有输入但以后仍可能提供时，进入 `waiting_input`，不是异常，可由控制方继续喂输入。
- 输入源明确关闭、不会再有输入时抛 `input_error`。

`input()` 不读取父程序的隐式标准输入。子程序的输入由 `run(inputs)` 或 `feed_input()` 显式提供。

## `print`

```text
print(*values, sep=" ", end="\n") -> None
```

把各个值渲染为文本，依次写入当前程序的 stdout。

| 参数 | 类型 | 含义 |
|---|---|---|
| `*values` | 任意值 | 要输出的零个或多个值 |
| `sep` | `str` | 相邻值之间的分隔符，默认一个空格 |
| `end` | `str` | 末尾文本，默认换行 |

没有值时只输出 `end`。`sep=""` 或 `end=""` 分别表示无分隔符或无末尾文本。`sep`、`end` 不是字符串时报 `type_error`。

每次调用产生一段完整输出，包含分隔符和末尾文本；全部计入输出配额。输出可先经 VM 配置的 writer 转发，详见 [VM 输出](06-vm.zh-CN.md#输出转发与缓冲)。

容器使用安全递归渲染，循环或重复结构使用占位符，不会无限展开。

## `len`

```text
len(value) -> int
```

返回字符串字符数、列表元素数、元组元素数或字典键数。其他类型报 `type_error`。

## `int`

```text
int(value) -> int
```

把 `int`、`float`、`bool` 或 `str` 转成整数。

- 整数保持不变，仍检查整数位宽配额。
- 布尔值变为 `1` 或 `0`。
- 浮点数向零截断；NaN 和无穷值不能转换，报 `conversion_error`。
- 字符串忽略两端空白，按十进制整数解析，可带符号；无效文本报 `conversion_error`。
- 其他类型报 `type_error`。

这里允许转换布尔值，不表示布尔值可以参与普通算术。

## `float`

```text
float(value) -> float
```

把 `int`、`float`、`bool` 或 `str` 转成浮点数。

字符串忽略两端空白，接受常规十进制浮点写法以及实现支持的 `nan`、`inf` 等特殊浮点文本。无效文本报 `conversion_error`，其他类型报 `type_error`。

## `str`

```text
str(value) -> str
```

返回值的字符串表示。字符串返回自身；其他标量、容器、record、schema、函数、模块和句柄使用 Sericite 的安全渲染规则。

容器递归渲染，字符串元素在容器内带引号。渲染结果受 `max_string_bytes` 约束，超限可能报 `resource_exhausted`。

## `repr`

```text
repr(value) -> str
```

返回适合单行诊断的表示。顶层字符串也会带引号，并转义换行、制表符、引号和反斜杠；容器递归使用相同规则。

`str("a\n")` 会包含实际换行，而 `repr("a\n")` 返回形如 `'a\\n'` 的单行文本。渲染工作和结果都受资源配额约束。

## `range`

```text
range(stop) -> list
range(start, stop) -> list
range(start, stop, step) -> list
```

按 Python `range` 的整数区间规则生成值，但直接返回列表，而不是惰性 range 对象。

| 参数 | 默认 | 含义 |
|---|---:|---|
| `start` | `0` | 起始值，包含在结果中 |
| `stop` | 无 | 终止值，不包含在结果中 |
| `step` | `1` | 步长，可为负数 |

三个参数必须严格为 `int`，布尔值不接受。参数数量不是 1 到 3 个报 `arity_error`；类型错误报 `type_error`；步长为零也报 `type_error`。结果长度受 `max_list_size` 约束。

```python
print(range(4))
print(range(3, 0, -1))
```

```text
[0, 1, 2, 3]
[3, 2, 1]
```

## `wrap`

```text
wrap(schema, data) -> record
```

用字典构造满足指定 schema 的 record。

| 参数 | 要求 |
|---|---|
| `schema` | 由 `class` 创建的 schema 值 |
| `data` | 字典，键集必须与 schema 字段集严格一致 |

字典缺少字段、包含额外字段或字段值不满足契约时报 `contract_error`。参数类型错误报 `type_error`。与 schema 的位置构造不同，`wrap` 不使用宽度检查：字典不能有多余键。

返回新 record，其字段容器按 schema 声明顺序建立；字段值本身浅复制，不递归深拷贝。

## `unwrap`

```text
unwrap(record) -> dict
```

返回 record 字段的新字典，字段顺序保持 record 的顺序。该操作是浅拷贝：修改返回字典不会改变 record 的字段绑定，但嵌套的可变值仍然共享。

参数不是 record 时报 `type_error`。

```python
class Point:
    x: int
    y: int

point = Point(1, 2)
data = unwrap(point)
data["x"] = 10
print(point.x, data["x"])
print(wrap(Point, data))
```

```text
1 10
record(x=10, y=2)
```
