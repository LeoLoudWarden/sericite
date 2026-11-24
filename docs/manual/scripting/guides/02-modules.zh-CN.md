# 模块与功能拓展

本章介绍模块系统，讲解如何使用包以及外部拓展。在此之前，你需要先理解 Sericite 的两个设计理念：能力的 **内建最小化** 与 **显式拓展**。

## 一个最小模块

工作区中有：

```text
/
├── main.sericite
└── util.sericite
```

`/util.sericite`：

```python
value = 21

def double(number):
    return number * 2
```

`/main.sericite`：

```python
import util
from util import double

print(util.value)
print(double(10))
```

预期输出：

```text
21
20
```

## 模块

和 Python 不同，Sericite 没有内置模块，导入在 Sericite 里没有隐式行为。`import x` 就是"在工作区里找 `x.sericite`（或 `x/__init__.sericite`）"：找到才有得导入，工作区里没有的东西，Sericite 不会替你去任何别处找。默认工作区是空的。

### 导入

```python
import a_lib
import a_lib as a
import a_lib.b_lib
import a_lib.b_lib as b
from a_lib.b_lib import c_tool
```

支持相对导入：以当前定义模块的包为基准，`.` 表示当前包，`..` 表示上一级包。

```python
# /lib/tools.sericite
from . import util       # 加载 lib.util
from .util import useful

# /lib/sub/mod.sericite
from ..util import useful  # 加载 lib.util
```

不支持 `from module import *`。

### 机制

1. 实际执行到 import 语句时才加载模块。import 可以出现在函数、条件和 `try` 中。
2. import 成功后进入缓存；重复 import 返回同一个模块对象。
3. 不支持循环依赖，直接或间接循环导入均会报错。
4. 不支持写入模块的属性，如 `module.value = 100`。

## 能力拓展

基于设计理念，Sericite 只提供最小化的，平台无关的脚本内建。下面这些没有预制实现：

- 随机数生成
- 获取时间
- 发送网络请求
- 与音频设备交互

这类功能依赖具体硬件和操作系统，实现各不相同，语言里没有统一版本；要用，就由运行环境按需提供。Sericite 预置了一个名为 `__addon__` 的模块，通过 `from __addon__ import` 来拓展脚本的能力。

比如，假设一块开发板上有蓝牙、红外发射器、线性马达和霍尔元件，环境可以对应提供：

| 能力 | 导入名 |
|---|---|
| 蓝牙配对 | `bluetooth_pair` |
| 红外发射 | `ir_transmit` |
| 线性马达驱动 | `motor_drive` |
| 霍尔元件读取 | `hall_read` |

脚本按需导入自己用到的那几项：

```python
from __addon__ import bluetooth_pair, hall_read
```

`__addon__` 只是一个固定的入口，`from __addon__ import` 是固定的写法。入口里具体有哪些名字、每个函数收什么参数、以什么顺序调用、会报什么错，这些不写在语言里，也不在本文的职责内。在实务中的具体组织规范需要自行约定。
