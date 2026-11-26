# 错误与异常

Sericite 使用固定的错误 kind。kind 是字符串标识，不是可实例化的异常类，也没有继承层次。脚本通过静态 `except` 过滤器匹配 kind，通过异常 record 读取诊断信息。

## 捕获与清理

```python
try:
    value = int(text)
except conversion_error as error:
    print(error.message)
else:
    print(value)
finally:
    print("finished")
```

- `try` 体无错误时执行 `else`，然后执行 `finally`。
- 发生可捕获错误时按源码顺序尝试 `except` 分支，命中后跳过 `else`。
- `finally` 在正常完成、错误传播以及 `return`、`break`、`continue` 提前退出时执行。
- 同一份源码不能捕获自己的编译期 `syntax_error`，因为尚未开始执行；控制方可以捕获 VM 源码的编译错误。
- VM 断点暂停不是异常，不触发目标脚本的 `except` 或 `finally`。强制销毁运行中的目标也不执行目标脚本的 `finally`。

## 静态过滤器

合法形式：

```python
except conversion_error:
    pass
except file_error:
    pass
except (file_error, input_error):
    pass
except ... as error:
    pass
except:
    pass
```

过滤名字必须直接写出，不能用变量、属性或运行时表达式代替。括号形式必须非空，成员只能是具体 kind 或固定过滤器组，可以混写和重复。

`except ...` 与裸 `except` 都匹配全部可捕获 kind；前者可用 `as` 绑定异常 record，后者不绑定。未知名字、空过滤器、动态过滤器和显式写出的不可捕获 kind 均报 `syntax_error`。

分组名只参与编译期过滤，不是运行期 kind。`error.kind` 始终是实际错误，而不是 `file_error` 或 `lookup_error`。

## 异常 record

`except ... as error` 绑定一个含三个字段的 record：

| 字段 | 类型 | 含义 |
|---|---|---|
| `kind` | `str` | 实际错误 kind |
| `message` | `str` | 面向脚本的安全错误文本 |
| `frames` | `list` | 当前程序的调用栈 |

`frames` 中每项是含两个字段的 record：

| 字段 | 类型 | 含义 |
|---|---|---|
| `function` | `str` | 安全函数名 |
| `line` | `int` 或 `None` | 源码行号，无法提供时为 `None` |

帧从最外层调用排列到实际错误点，最后一帧是错误点。调用方帧指向实际发起调用的行。每个程序只暴露自己的安全栈；跨 VM 的外来代码使用授予名并隐藏定义侧行号。

异常绑定是当前作用域中的普通绑定，离开 `except` 后仍保留，嵌套同名绑定会覆盖它。异常 record 和帧 record 是安全副本，修改它们不会改变内部错误。

## 主动抛出与重抛

```text
raise message
raise
```

`raise message` 只接受字符串，并产生 `raise_error`。其他值报 `type_error`。不支持异常对象、自定义 kind 和 `raise ... from ...`。

`except` 分支内的裸 `raise` 重抛当前错误，保留原始调用栈。`finally` 暂存后的重抛也保留原栈；在 `except` 或 `finally` 中新产生的错误使用新调用栈。

## 可捕获 kind

下表列出脚本可在 `except` 中写出的具体 kind。“可捕获”仍受资源错误来源等运行规则约束。

| kind | 典型含义 |
|---|---|
| `runtime_error` | 一般运行失败、无效生命周期或对象状态操作 |
| `syntax_error` | 源码解析、语言白名单或静态过滤器校验失败 |
| `type_error` | 运算、调用、转换或 API 参数类型不受支持 |
| `name_error` | 当前词法作用域中名字未定义 |
| `arity_error` | 用户函数实参数量、重复绑定或未知关键字错误 |
| `raise_error` | 脚本通过 `raise "text"` 主动抛出 |
| `input_error` | 输入源明确关闭，不会再有输入 |
| `import_error` | 模块、包、相对导入、循环导入或导出解析失败 |
| `zero_division` | 除零、模零或零的负数次幂 |
| `conversion_error` | 数值转换或格式说明符转换失败 |
| `index_error` | 序列下标或 `list.pop()` 索引越界 |
| `key_error` | 字典缺键，或无默认值的 `dict.pop()` 缺键 |
| `value_error` | 解构长度不匹配，或序列 `index()` 找不到值 |
| `attribute_error` | 模块、record、VM、VFS 或容器的成员不存在或不可访问 |
| `contract_error` | record 构造、字段写入、注解或 `wrap()` 契约失败 |
| `file_not_found` | 文件或目录源不存在 |
| `file_exists` | 不覆盖操作的目标已存在，或 `make_dir()` 目标已存在 |
| `is_directory` | 文件操作遇到目录 |
| `not_directory` | 目录操作遇到文件，或中间路径段是文件 |
| `file_limit_error` | 文件数、单文件大小或文件存储约束拒绝变更 |
| `addon_error` | addon 的数据边界或值复制契约被违反 |
| `resource_exhausted` | 指令、内存、输出、调用帧、规模、VM 数量或深度等资源耗尽 |

`file_limit_error` 是普通可恢复错误。处理后可以收缩文件世界并重试，不会仅因该错误终止会话。

## 固定过滤器组

| 组名 | 展开后的具体 kind |
|---|---|
| `file_error` | `file_not_found`、`file_exists`、`is_directory`、`not_directory`、`file_limit_error` |
| `lookup_error` | `index_error`、`key_error` |

需要优先处理某个具体错误时，把它的分支放在组之前：

```python
try:
    value = read_file(path)
except file_not_found:
    value = ""
except file_error as error:
    print(error.kind)
```

## 资源错误的来源边界

`resource_exhausted` 可以写在 `except` 中，但不能借此突破自己的配额：

- 当前程序或任一祖先的资源耗尽不能被该程序自己捕获。
- 另一台已终止子程序传来的 `resource_exhausted` 可以被仍存活的父程序捕获。
- 文件约束的 `file_limit_error` 不属于执行账户耗尽，按普通错误捕获。

## 不可捕获 kind

| kind | 含义 |
|---|---|
| `host_error` | 脚本外 addon 的实现发生契约外失败，无法安全恢复 |
| `internal_error` | Sericite 引擎内部不变量或意外实现失败 |

这两个 kind 不能被具体过滤器、`except ...` 或裸 `except` 捕获。它们描述治理或实现故障，不应作为正常业务控制流。
