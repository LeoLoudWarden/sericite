# Sericite CLI 参考

[English](cli-reference.md)

本文面向直接运行 Sericite 程序的操作者，描述 `sericite` 命令行与 `python -m sericite` 的共同行为。脚本语法见[语言参考](language-reference.zh-CN.md)；VM 驱动与调试见[虚拟机参考](vm-reference.zh-CN.md)；在 Python 中嵌入引擎见 [Sericite-PY 参考](sericite-py-reference.zh-CN.md)。

## 1. 三种使用形态

```bash
sericite app.sericite
sericite --capabilities capabilities.py app.sericite
```

- **纯 CLI**：运行只使用内建能力的 Sericite 程序。
- **CLI + 能力配置**：Python 文件只提供可信 FFI、配额和初始 VFS，应用主体仍运行在 root Sericite VM 中。
- **Python 嵌入**：既有宿主系统直接使用 `SericiteEngine` API；这不经过 CLI，详见 [Sericite-PY 参考](sericite-py-reference.zh-CN.md)。

`sericite` 是已安装的命令；在源码开发环境中也可写成 `uv run sericite`。`python -m sericite` 使用同一入口。

## 2. 命令与参数

```text
sericite [-h] [--version] [--capabilities FILE] [--include FILE ...]
         (SOURCE_FILE | -c SOURCE)
```

| 参数 | 含义 |
|---|---|
| `-h`, `--help` | 显示帮助并退出 |
| `--version` | 显示运行时版本 |
| `SOURCE_FILE` | 读取并运行 UTF-8 源文件；`-` 表示从 stdin 读取完整源码 |
| `-c SOURCE`, `--command SOURCE` | 直接执行命令行中的源码字符串 |
| `--capabilities FILE` | 从可信 Python 文件调用 `configure()`，配置 root VM |
| `--include FILE` | 在主源码前组合一个文件；可重复，顺序即命令行顺序 |

`SOURCE_FILE` 与 `-c` 互斥且必须提供一个。文件路径按当前工作目录解析；以横线开头的文件名可放在 `--` 后。`.sericite` 是约定后缀，不做强制校验。

```bash
sericite -c 'print("hello")'
printf 'print("hello")\n' | sericite -
sericite --include base.sericite --include util.sericite app.sericite
sericite --capabilities capabilities.py -c 'run()'
```

当前不支持 REPL、脚本 argv 或独立的逐字段配额参数。`python -m sericite` 的参数与上述一致。

## 3. include：同一 root 的源码组合

`--include` 是 CLI 的代码复用入口，不是 Sericite 的 `import`——真正的模块系统需要另行设计，不承诺与 include 有相同语义：

1. 按参数顺序读取所有 include，最后接主文件、命令字符串或 stdin 源码。
2. 所有文本组合成**一个编译单元**，在同一个 root VM、同一个模块全局作用域中运行。
3. 函数、变量和副作用按顺序共享；主源码可以直接调用 include 定义的函数。
4. 不去重、不缓存、不创建命名空间或子 VM；重复 include 会重复执行。
5. 整体编译成功后才执行。任一文件编译失败时，所有文件都没有运行副作用。
6. 合并后的源码仍受引擎的 4MB 上限约束。

例如 `math_utils.sericite`：

```python
def double(x):
    return x * 2
```

运行：

```bash
sericite --include math_utils.sericite -c 'print(double(21))'
# 42
```

错误诊断按源码来源标记位置：

- include 与主文件映射回原始文件及其局部行号；
- 命令字符串显示为 `<command>`，stdin 源码显示为 `<stdin>`；
- 嵌套 VM 的错误仍使用 `<sericite:vm_N>`。

## 4. capabilities：可信 Python 启动配置

### 4.1 配置入口

`--capabilities FILE` 指定的 Python 文件必须定义无参数 `configure()`。加载该文件即执行其顶层代码（`runpy.run_path`），随后 CLI 在创建引擎和执行任何 Sericite 代码之前调用 `configure()` 一次：

```python
from sericite import SericiteLimits


def double(x):
    return x * 2


def configure():
    return {
        "functions": {"double": double},
        "limits": SericiteLimits(max_instructions=100_000),
        "files": {"/message.txt": "hello from the initial VFS"},
    }
```

返回 dict，三个键都可省略；空 dict 等价于不配置：

| 键 | 类型与作用 |
|---|---|
| `functions` | `dict[str, callable]`；授予 root 的宿主函数，沿用 FFI 数据与异常契约 |
| `limits` | `SericiteLimits`；该 root 的整套配额配置 |
| `files` | `dict[str, str]`；运行前写入 root VFS 的虚拟路径与纯文本 |

- 未知键、缺少可调用的 `configure()`、返回非 dict 或字段类型错误都会使启动失败。
- `functions` 的授予名仍由引擎校验。
- `files` 通过公开 VM 句柄写入，仍受文件数、单文件字节等限制。

FFI 的完整规则见 [Sericite-PY 参考](sericite-py-reference.zh-CN.md)，配额字段见[虚拟机参考](vm-reference.zh-CN.md)第 5 节，不在此复制。

配置文件可用 `__file__` 定位自己的资源。它不是 Sericite 模块，不要求所在目录成为 Python 包；CLI 也不提供 Sericite 模块搜索路径。

### 4.2 信任边界

> **能力配置文件拥有完整宿主权限。像运行任何 Python 文件一样信任它。**

- 它可以 import 第三方库、读取环境变量和真实磁盘、访问网络。
- 其中的 Python **不在 Sericite 沙箱内执行**，其 CPU、内存和外部副作用也不由引擎计量（成本责任见 [Sericite-PY 参考](sericite-py-reference.zh-CN.md)第 5.4 节）。
- 只允许操作者选择配置文件；不要让模型或 Sericite 源码决定加载哪一个。

主源码与 include 仍在 root VM 中执行，不因配置文件存在而得到宿主权限。它们只能调用显式授予的函数；`files` 也只预置 root 的内存 VFS，不映射真实磁盘。

执行顺序固定为：

```text
读取源码 → 执行 configure() → 创建并编译 root → 预置 VFS → 运行 → 输出
```

配置文件不能接管会话循环或 VM 驱动。需要这种嵌入行为时使用 Python API，而不是扩展 CLI 配置钩子。

## 5. 输入、输出与退出码

- 文件和 `-c` 模式中，脚本 `input()` 从宿主 stdin 逐行读取；EOF 后仍请求输入会以 `input_error` 失败。
- `sericite -` 会消费全部 stdin 作为源码，因此同一 stdin 不能再提供运行输入。
- root 每次 `print()` 产生的 stdout 会立即写到宿主 stdout 并 flush，包括 `end=""` 的无换行输出；不必等程序结束。子 VM 输出仍由父 VM 用 `sub.run()` 等接口显式取得，不直接写到宿主。
- 编译/运行错误写 stderr；运行失败时，root 已产生的 stdout 不丢失。配置错误也只写 stderr。

| 退出码 | 含义 |
|---:|---|
| 0 | root 正常完成 |
| 1 | 文件/配置读取或校验失败、编译/运行错误、输入耗尽（`input_error`） |
| 2 | 命令行用法错误 |

`KeyboardInterrupt`、`SystemExit` 等进程级事件不当作普通脚本或配置错误吞掉。

## 6. 编辑器中的 `.sericite`

Sericite 借用 Python 语法子集。尚未安装专门扩展时，可在 VS Code 工作区设置中临时关联：

```json
{
  "files.associations": {
    "*.sericite": "python"
  }
}
```

这只提供高亮、缩进和括号匹配；Python linter 不了解 Sericite 的白名单、内建函数和运行期契约，不能代替 CLI 的真实编译诊断。

完整 root 驱动示例见 [`demos/root-agent/`](../demos/root-agent/README.zh-CN.md)。
