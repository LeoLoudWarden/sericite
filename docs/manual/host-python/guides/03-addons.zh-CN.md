# 授予宿主能力

Sericite 默认不提供网络、真实磁盘、随机数或宿主对象访问。需要这些能力时，Python 宿主可以把经过选择的可调用对象作为 addon 授予 root VM。

## 授予并导入函数

下面的宿主提供一个 `double` 函数：

```python
from sericite import SericiteEngine


def double(number):
    return number * 2


engine = SericiteEngine()
vm = engine.create_root(
    "from __addon__ import double\nprint(double(21))",
    addons={"double": double},
)
assert vm.run() == "42\n"
vm.dispose()
```

`addons` 字典的键是脚本使用的导入名，值必须是可调用对象。授予不会把函数直接注入全局命名空间；每个需要它的 Sericite 源码模块都要显式写 `from __addon__ import ...`。

字典键可以与 Python 函数原名不同，因此可以提供稳定或更受约束的公开名称。addon 名必须是合法且不以 `__` 开头的标识符，也允许与内建同名；后一种情况应使用导入别名，避免直接重绑定内建。名称规则和别名示例见[addon 参考](../reference/04-addons.zh-CN.md#授予函数)。

## 数据在边界上复制

参数和返回值会在 Python 与 VM 之间双向深拷贝，双方不会共享可变容器：

```python
shared = {"items": [1, 2]}


def give():
    return shared


vm = engine.create_root(
    "from __addon__ import give\n"
    "a = give()\n"
    "a['items'][0] = 99\n"
    "b = give()\n"
    "print(b['items'][0])",
    addons={"give": give},
)
assert vm.run() == "1\n"
assert shared == {"items": [1, 2]}
vm.dispose()
```

可以越界的是由 `None`、布尔值、数值、字符串、list、dict 和 tuple 递归组成的纯数据。任意 Python 对象不会因为被返回就进入脚本；违反数据契约会产生 `addon_error`。需要把 record 交给 Python 时，可先在脚本内 `unwrap()` 为 dict。完整类型和规模规则见[addon 参考](../reference/04-addons.zh-CN.md#数据边界)。

这条深拷贝边界专属于 Python 与脚本之间。脚本向子 VM 授予 Sericite 函数时，定义方环境和跨 VM record 采用另一套规则，见[脚本 VM 参考](../../scripting/reference/06-vm.zh-CN.md#addon-授予)。

## 把宿主失败翻译成脚本错误

行为良好的 addon 要么返回结果，要么抛出具有明确契约 kind 的 `SericiteError`：

```python
from sericite import SericiteEngine, SericiteError


def load(name):
    raise SericiteError("resource not found", kind="file_not_found")


engine = SericiteEngine()
vm = engine.create_root(
    "from __addon__ import load\n"
    "try:\n"
    "    load('missing')\n"
    "except file_not_found as error:\n"
    "    print(error.kind, error.message)",
    addons={"load": load},
)
assert vm.run() == "file_not_found resource not found\n"
vm.dispose()
```

普通契约 kind 可以由脚本按语言规则捕获，因此消息不应包含宿主秘密。契约之外的普通 `Exception` 则会使当前 VM 以不可捕获的 `host_error` 终止，宿主收到 `SericiteError`，原异常消息不会透传给脚本。

`BaseException`、`resource_exhausted` 以及虚拟 IO 回调的失败各有专门规则，完整异常与重入契约见[addon 参考](../reference/04-addons.zh-CN.md#异常与重入)。

## 能力实现者的责任

授予函数不仅授予一个名字，也授予这个函数实际能够造成的影响。宿主应在回调内验证参数和权限，限制输入规模、调用频率、CPU、内存、阻塞和外部副作用；回调内部的消耗不受 VM 指令配额托管。只授予脚本必要的操作，不在回调中重入同一 VM 的驱动方法。执行对抗性代码时，还应在 Sericite 之外增加操作系统级隔离。

详细信任边界见[安全模型](../../../security.zh-CN.md)，成本责任和完整重入规则见[addon 参考](../reference/04-addons.zh-CN.md)。
