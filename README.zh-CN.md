# Sericite

[![CI](https://github.com/LeoLoudWarden/sericite/actions/workflows/ci.yml/badge.svg)](https://github.com/LeoLoudWarden/sericite/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/sericite)](https://pypi.org/project/sericite/)
[![Python](https://img.shields.io/pypi/pyversions/sericite)](https://pypi.org/project/sericite/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/LeoLoudWarden/sericite/blob/main/LICENSE)

**Sericite** 是一门脚本语言及其执行引擎，围绕一个想法构建：**创建一个完全隔离、可以任意嵌套的运行环境，应当是语言自身的一种廉价的第一类操作。**

语法借用 Python 的一个子集，但 Sericite 源码会被编译为 Sericite 自己的指令流，由 Sericite 引擎逐条执行——不经过 `exec`/`eval`。每台 VM 初始能力为零：独立的虚拟 IO、独立的内存文件系统、创建子 VM。其余一切能力（网络、宿主数据、任何你选择授予的东西）都通过 FFI 逐层显式授予。

[English documentation](https://github.com/LeoLoudWarden/sericite/blob/main/README.md)

## 状态

1.0 之前的原型。引擎是 Python 参考实现（代号 **Sericite-PY**）：零运行时依赖，Python ≥ 3.12。API 与语义在 1.0 之前可能变化。

> **安全提示。** Sericite 为隔离而设计，但当前原型与宿主同进程运行，未经正式安全审计。执行对抗性代码时，不要把 Sericite 当作**唯一**的隔离边界。引擎保证什么、不保证什么，见[安全模型](https://github.com/LeoLoudWarden/sericite/blob/main/docs/security.zh-CN.md)。

## 安装

```bash
pip install sericite
```

发行包名为 `sericite`，导入包名为 `sericite`。

## 快速上手

命令行：

```bash
sericite -c 'print("hello from sericite")'
printf 'print("hello from sericite")\n' > hello.sericite
sericite hello.sericite        # hello from sericite
```

代码复用与 root 应用能力配置：

```bash
sericite --include base.sericite app.sericite
sericite --capabilities capabilities.py app.sericite
```

include 在同一 root 作用域中按序组合源码；capabilities 是操作者显式信任、只负责 FFI/配额/初始 VFS 的 Python 配置。完整契约见 [CLI 参考](docs/cli-reference.zh-CN.md)，完整应用见 [root-agent demo](demos/root-agent/README.zh-CN.md)。需要由既有宿主系统管理 VM 生命周期时，再嵌入 Python：

```python
from sericite import SericiteEngine

engine = SericiteEngine()
vm = engine.create_root("""
sub = VM("print('hello from a child VM')")
print(sub.run())
""")
print(vm.run(), end="")
```

向 VM 授予能力（FFI）：

```python
def double(x):
    return x * 2

vm = engine.create_root("print(double(21))", functions={"double": double})
print(vm.run(), end="")    # 42
```

## 一台 Sericite VM 是什么

一台廉价、自包含的工作空间：

- 看不到父级的变量、文件和句柄，也不知道自己嵌套在第几层；
- 有独立的空白内存文件系统（纯文本——结构上碰不到真实磁盘）；
- 资源配额（指令、内存、输出、子 VM 数、嵌套深度……）只能收紧不能放宽，子 VM 的消耗计入所有祖先；
- 父级可以预置文件、喂输入、逐语句或逐指令单步、查看快照、随时终止；
- 它可以创建自己的子 VM——隔离是递归的，因为不可信的代码是递归的。

廉价是实测过的：当前 Python 原型中，脚本内创建一台子 VM 约 0.088 ms，与创建一个线程同数量级，比进程便宜一到两个数量级。更多实测数字与复现脚本见[架构说明](https://github.com/LeoLoudWarden/sericite/blob/main/docs/architecture.zh-CN.md)第 6 节与 [benchmarks/](https://github.com/LeoLoudWarden/sericite/tree/main/benchmarks)。

## record：类型名只是编译期的报错标签

0.4 起，sericite 有了自定义含成员的对象。它的类型观与 VM 的隔离观是同一条戒律：**结构跨层，名字层本地。**

- schema（`class` 定义的结构契约）是匿名的：两处分别定义的同形 schema 彼此相等，不存在名义类型；
- record 只携带数据和契约。类型名是编译期、作用域本地的透明别名（同 Elm `type alias`），只用于报错文本——不参与相等、不参与契约判断，出作用域即擦除；
- 命名是接收方的本地行为：一个值在不同作用域可以有不同的名字，也可以没有名字。

设计论证见[设计说明 §3.4](https://github.com/LeoLoudWarden/sericite/blob/main/docs/design.zh-CN.md)，完整语义与示例见[语言参考 §7](https://github.com/LeoLoudWarden/sericite/blob/main/docs/language-reference.zh-CN.md)。

## 文档

| 文档 | 内容 |
|---|---|
| [设计说明](https://github.com/LeoLoudWarden/sericite/blob/main/docs/design.zh-CN.md) | Sericite 是什么、为什么存在、边界划在哪里（[English](https://github.com/LeoLoudWarden/sericite/blob/main/docs/design.md)） |
| [先例与相关工作](https://github.com/LeoLoudWarden/sericite/blob/main/docs/prior-art.zh-CN.md) | Safe-Tcl 证明了什么、停在哪里，Sericite 补什么（[English](https://github.com/LeoLoudWarden/sericite/blob/main/docs/prior-art.md)） |
| [CLI 参考](https://github.com/LeoLoudWarden/sericite/blob/main/docs/cli-reference.zh-CN.md) | 命令、include、可信能力配置与退出码（[English](https://github.com/LeoLoudWarden/sericite/blob/main/docs/cli-reference.md)） |
| [语言参考](https://github.com/LeoLoudWarden/sericite/blob/main/docs/language-reference.zh-CN.md) | Sericite 脚本的语言子集与语义（[English](https://github.com/LeoLoudWarden/sericite/blob/main/docs/language-reference.md)） |
| [宿主参考](https://github.com/LeoLoudWarden/sericite/blob/main/docs/host-reference.zh-CN.md) | Python 宿主 API、VM 驱动、FFI 与调试（[English](https://github.com/LeoLoudWarden/sericite/blob/main/docs/host-reference.md)） |
| [架构说明](https://github.com/LeoLoudWarden/sericite/blob/main/docs/architecture.zh-CN.md) | 引擎结构、设计不变量、资源配额（[English](https://github.com/LeoLoudWarden/sericite/blob/main/docs/architecture.md)） |
| [安全模型](https://github.com/LeoLoudWarden/sericite/blob/main/docs/security.zh-CN.md) | 威胁模型；引擎保证什么、不保证什么（[English](https://github.com/LeoLoudWarden/sericite/blob/main/docs/security.md)） |
| [构建手记](https://github.com/LeoLoudWarden/sericite/blob/main/docs/stages/README.zh-CN.md) | Sericite 0.1.0 逐阶段构建过程，含可运行检查点（`git checkout stage-1` … `stage-6`） |
| [幕后](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/README.zh-CN.md) | 项目由来与 AI 辅助开发过程 |

构建手记与幕后的正文文章仅中文（其索引页有英文版）；不计划全文翻译——它们是冻结的历史。

## 这个项目是怎么写出来的

Sericite 全程使用 AI 辅助开发——设计讨论、实现、测试、对抗性审查、文档起草。AI 做了什么、作者做了什么、产出如何被验证，记录在 [AI 辅助开发说明](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/ai-assisted-development.zh-CN.md)，附开发对话选编。

## 路线图

- 更多列表/字典方法、字符串方法与更多易用性语法
- 性能基准：VM 创建、每指令执行与调试成本已实测（见 [benchmarks/](https://github.com/LeoLoudWarden/sericite/tree/main/benchmarks)）；更多工作负载的覆盖待补
- 规范化的语言规范与一致性测试套件，供未来非 Python 引擎对照验证
- 原生引擎评估（包名刻意取语言级：`sericite` 在引擎重写后依然成立）

## 名字由来

Sericite 即绢云母，云母族中晶粒最细的一支：细小的丝绢鳞片层层叠置，与所有云母一样是绝缘体——这个名字保留了项目命名时的三个承诺：层叠、绝缘、轻量。（本项目曾短暂名为 Mica/MicaLang，因名字被占用而更名。）完整叙述见[设计说明](https://github.com/LeoLoudWarden/sericite/blob/main/docs/design.zh-CN.md)第 6 节。

## 许可证

[Apache-2.0](https://github.com/LeoLoudWarden/sericite/blob/main/LICENSE)——见 [NOTICE](https://github.com/LeoLoudWarden/sericite/blob/main/NOTICE)。
