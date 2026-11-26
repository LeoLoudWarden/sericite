# Sericite

[![CI](https://github.com/LeoLoudWarden/sericite/actions/workflows/ci.yml/badge.svg)](https://github.com/LeoLoudWarden/sericite/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/sericite)](https://pypi.org/project/sericite/)
[![Python](https://img.shields.io/pypi/pyversions/sericite)](https://pypi.org/project/sericite/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/LeoLoudWarden/sericite/blob/main/LICENSE)

**Sericite** 是一门脚本语言及其执行引擎，围绕一个想法构建：**创建一个完全隔离、可以任意嵌套的 VM，应当是语言自身的一种廉价的第一类操作。**

语法借用 Python 的一个子集，但源码会被编译为 Sericite 自己的指令流执行——不经过 Python `exec`/`eval`。

[English documentation](https://github.com/LeoLoudWarden/sericite/blob/main/README.md)

## 状态

1.0 之前的原型。引擎是 Python 参考实现（代号 **Sericite-PY**），零运行时依赖，需要 Python ≥ 3.12。API 与语义在 1.0 之前可能变化。

> **安全提示。** Sericite 为隔离而设计，但当前原型与宿主同进程运行，未经正式安全审计。执行对抗性代码时，不要把 Sericite 当作**唯一**的隔离边界。引擎保证什么、不保证什么，见[安全模型](https://github.com/LeoLoudWarden/sericite/blob/main/docs/security.zh-CN.md)。

## 安装

```bash
pip install sericite
```

## 你的第一个隔离程序

创建 `play.sericite`。新建的 VM 会查找一个在它创建前写入的文件，再把答案留在自己的工作区：

```python
write_file("/before.txt", "already here")

vm = VM("""
print(path_exists("/before.txt"))
write_file("/answer.txt", "42")
""")

print(vm.run(), end="")
workspace = vm.take_fs()
print(workspace.read_file("/answer.txt"))
```

运行：

```bash
sericite play.sericite
```

输出：

```text
False
42
```

## 不可信代码竞技场

九份互不信任的程序参加排序比赛。正确的算法按指令数排名；偷答案、死循环和输出洪泛只会导致当前提交出局，裁判继续运行。

```bash
git clone https://github.com/LeoLoudWarden/sericite.git
cd sericite
sericite --addons demos/sorting-arena/addons.py demos/sorting-arena/arena.sericite
```

输出节选（每次运行都会生成新的随机测试）：

```text
  RANK  CONTESTANT                  TOTAL INSTRUCTIONS
  1     quicksort               15,383
  ...
  DQ    answer-thief            file_not_found
  DQ    output-flood            resource_exhausted
  DQ    infinite-loop           resource_exhausted
  ...
  The arena survived every submission. The scoreboard only counts correct code.
```

[它是怎么做到的](https://github.com/LeoLoudWarden/sericite/blob/main/demos/sorting-arena/README.zh-CN.md)

## 了解更多

| 下一步 | 中文 | English |
|---|---|---|
| 阅读在线手册 | [Sericite 手册](https://sericite.readthedocs.io/en/latest/zh-CN/) | [Sericite manual](https://sericite.readthedocs.io/en/latest/) |
| 看更多完整应用 | [更多演示](https://github.com/LeoLoudWarden/sericite/blob/main/demos/README.zh-CN.md) | [More demos](https://github.com/LeoLoudWarden/sericite/blob/main/demos/README.md) |
| 学习编写 Sericite 程序 | [Sericite 脚本手册](https://github.com/LeoLoudWarden/sericite/blob/main/docs/manual/scripting/README.zh-CN.md) | [Sericite scripting manual](https://github.com/LeoLoudWarden/sericite/blob/main/docs/manual/scripting/README.md) |
| 从终端运行程序 | [Sericite 命令行手册](https://github.com/LeoLoudWarden/sericite/blob/main/docs/manual/cli/README.zh-CN.md) | [Sericite CLI manual](https://github.com/LeoLoudWarden/sericite/blob/main/docs/manual/cli/README.md) |
| 嵌入 Python 应用 | [Sericite-PY 手册](https://github.com/LeoLoudWarden/sericite/blob/main/docs/manual/host-python/README.zh-CN.md) | [Sericite-PY manual](https://github.com/LeoLoudWarden/sericite/blob/main/docs/manual/host-python/README.md) |

## 文档

| 中文 | English |
|---|---|
| [设计说明](https://github.com/LeoLoudWarden/sericite/blob/main/docs/design.zh-CN.md) | [Design notes](https://github.com/LeoLoudWarden/sericite/blob/main/docs/design.md) |
| [先例与相关工作](https://github.com/LeoLoudWarden/sericite/blob/main/docs/prior-art.zh-CN.md) | [Prior art](https://github.com/LeoLoudWarden/sericite/blob/main/docs/prior-art.md) |
| [架构说明](https://github.com/LeoLoudWarden/sericite/blob/main/docs/architecture.zh-CN.md) | [Architecture](https://github.com/LeoLoudWarden/sericite/blob/main/docs/architecture.md) |
| [安全模型](https://github.com/LeoLoudWarden/sericite/blob/main/docs/security.zh-CN.md) | [Security model](https://github.com/LeoLoudWarden/sericite/blob/main/docs/security.md) |
| [性能基准](https://github.com/LeoLoudWarden/sericite/tree/main/benchmarks) | [Benchmarks](https://github.com/LeoLoudWarden/sericite/tree/main/benchmarks) |
| [构建手记](https://github.com/LeoLoudWarden/sericite/blob/main/docs/stages/README.zh-CN.md) | [Build journal](https://github.com/LeoLoudWarden/sericite/blob/main/docs/stages/README.md) |
| [幕后](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/README.zh-CN.md) | [Behind the scenes](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/README.md) |
| [AI 辅助开发](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/ai-assisted-development.zh-CN.md) | [AI-assisted development](https://github.com/LeoLoudWarden/sericite/blob/main/docs/behind-the-scenes/ai-assisted-development.md) |

每篇文档的定位与读者指引集中在[文档索引](https://github.com/LeoLoudWarden/sericite/blob/main/docs/README.zh-CN.md)维护。

## 路线图

- 更多列表/字典方法、字符串方法与易用性语法
- 覆盖更多工作负载的性能基准
- 规范化的语言规范与一致性测试套件，供未来引擎对照验证
- 原生引擎评估

## 名字由来

Sericite 即绢云母，一种晶粒细小的云母：丝绢般的薄片层层叠置，而且绝缘。这个名字对应层叠、隔离与轻量。

## 许可证

[Apache-2.0](https://github.com/LeoLoudWarden/sericite/blob/main/LICENSE)——见 [NOTICE](https://github.com/LeoLoudWarden/sericite/blob/main/NOTICE)。
