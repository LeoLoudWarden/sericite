# 脚本手册

这里收录 Sericite 脚本语言的手册，包括按任务组织的指南和按查询对象组织的 API 参考。

第一次学习语言时，先读[脚本指南](guides/01-quick-start.zh-CN.md)。指南按任务组织示例和解释；API 参考按查询对象组织精确契约，两者不互相替代。

## 指南

| 页面 | 内容 |
|---|---|
| [快速开始](guides/01-quick-start.zh-CN.md) | 基本类型、运算、赋值、函数、闭包、装饰器 |
| [模块与功能拓展](guides/02-modules.zh-CN.md) | 模块导入与相对导入、能力拓展入口 `__addon__` |
| [自定义记录对象](guides/03-record.zh-CN.md) | record 与 schema、契约与注解、宽度检查、结构相等 |
| [异常处理](guides/04-errors.zh-CN.md) | 捕获与抛出、错误 record、静态过滤器 |
| [文件系统](guides/05-files.zh-CN.md) | 文件与目录操作、路径解析、隐式与显式目录 |
| [独立运行空间](guides/06-vm.zh-CN.md) | 子 VM 构造、移交工作区、授予能力、驱动与单步 |
| [安全注意事项](guides/07-vm-safety.zh-CN.md) | 环境隔离、执行限额、常见坏习惯 |

## API 参考

| 页面 | 内容 |
|---|---|
| [语言与模块](reference/01-language.zh-CN.md) | 值、运算、赋值、控制流、函数、record/schema、f-string、模块、`__addon__` |
| [通用内建](reference/02-builtins.zh-CN.md) | `input`、`print`、转换、渲染、`range`、`wrap`、`unwrap` |
| [值类型方法](reference/03-types.zh-CN.md) | `list`、`tuple`、`dict`、`str` 的全部公开方法 |
| [文件与目录](reference/04-files.zh-CN.md) | 路径和目录共同规则、11 个文件与目录接口 |
| [错误与异常](reference/05-errors.zh-CN.md) | 捕获和抛出、异常 record、全部错误 kind、固定过滤器组 |
| [VM](reference/06-vm.zh-CN.md) | 子 VM 构造、状态、驱动、调试、快照、配额和 addon 授予 |
| [VFS](reference/07-vfs.zh-CN.md) | 分离工作区、排他移交和 VFS 文件方法 |

## 签名记法

参考中的签名描述脚本调用契约，不是 Python 类型注解语法：

```text
function(required, optional=default) -> ReturnType
object.method(argument) -> ReturnType
```

- `->` 右侧是返回类型或返回值类别。
- `any` 表示任意脚本值，不是 Python 的 `typing.Any` 对象。
- `A | B` 表示返回值是 `A` 或 `B` 之一；例如 `any | None` 表示可能返回任意值，也可能返回 `None`。
- 可选参数写出默认值；多种调用形式分行列出。
- 内建页的 `*` 表示后续参数必须使用关键字。用户函数中的 `*args`、`**kwargs` 则是可变参数，见[函数](reference/01-language.zh-CN.md#函数)。
- `list`、`dict`、`tuple` 表示对应内建容器；需要更具体元素类型时在正文中说明。
- 文档只承诺列出的参数名称和调用形式，不把 Python 中同名 API 的其他形式带入 Sericite。

## 内容与边界

- 通用规则只在权威页面完整展开。例如文件路径规则在文件页，VFS 页只列同名方法并链接过去。
- 每个公开接口列出使用所需的参数、返回和主要错误；资源耗尽等通用可能性集中在 VM 和错误页说明。
- 示例中的代码块使用 `python` 标记仅为了语法高亮，语言仍是 Sericite。
