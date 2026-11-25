# 值类型方法

本文列出 `list`、`tuple`、`dict` 和 `str` 的全部公开方法。方法集合是封闭的，未列出的属性报 `attribute_error`。索引、切片、迭代和运算见[语言与模块](01-language.zh-CN.md)。

这些方法按位置传参。签名中的 `None` 表示可以省略该位置，也可以显式传 `None`。方法可以作为绑定方法值传递，调用时仍操作原对象。

## `list`

```text
list() -> list
list(value) -> list
```

接受 `list`、`tuple`、`str`、`dict`。`list/tuple` 按元素构造，`str` 按字符构造，`dict` 按键构造，元素本身不递归复制。其他类型报 `type_error`。`list()` 返回空列表。

### `list.append`

```text
list.append(value) -> None
```

在列表末尾原地追加一个值。列表达到 `max_list_size` 时报 `resource_exhausted`。

### `list.pop`

```text
list.pop() -> any
list.pop(index) -> any
```

删除并返回指定位置的元素，默认 `index=-1`。支持负索引。`index` 必须严格为 `int`；空列表或越界报 `index_error`，类型错误报 `type_error`。

### `list.count`

```text
list.count(value) -> int
```

返回列表中与 `value` 结构相等的元素数，不修改列表。

### `list.index`

```text
list.index(value, start=None, stop=None) -> int
```

返回搜索区间内首个与 `value` 结构相等的元素位置。边界规则与切片相同，支持负索引和越界截断。找不到报 `value_error`，边界类型错误报 `type_error`。

## `tuple`

```text
tuple() -> tuple
tuple(value) -> tuple
```

元组不可写入。输入和顺序规则同 `list`。

### `tuple.count`

```text
tuple.count(value) -> int
```

返回元组中与 `value` 结构相等的元素数。

### `tuple.index`

```text
tuple.index(value, start=None, stop=None) -> int
```

返回搜索区间内首个匹配元素的位置。规则与 [`list.index`](#listindex) 相同，找不到报 `value_error`。

## `dict`

```text
dict() -> dict
dict(value) -> dict
dict(**entries) -> dict
dict(value, **entries) -> dict
```

`value` 需为以下之一：
- 另一个 dict；
- 由二元 list/tuple 组成的 list/tuple。键值对长度不是 2 报 `value_error`。

否则报 `type_error`。

字典复制和键值对构造都是浅拷贝。

字典方法遵循字典键白名单和插入顺序，见[值与字面量](01-language.zh-CN.md#值与字面量)。

### `dict.keys`

```text
dict.keys() -> list
```

按插入顺序返回键的新列表。之后修改字典不会改变该列表。

### `dict.values`

```text
dict.values() -> list
```

按插入顺序返回值的新列表。列表容器独立，元素本身不复制。

### `dict.items`

```text
dict.items() -> list
```

按插入顺序返回 `(key, value)` 二元元组的新列表。之后修改字典不会改变已返回的列表和元组。

### `dict.get`

```text
dict.get(key) -> any | None
dict.get(key, default) -> any
```

键存在时返回对应值；不存在时返回 `default`，未提供默认值则返回 `None`。不修改字典。非法键类型报 `type_error`。

### `dict.pop`

```text
dict.pop(key) -> any
dict.pop(key, default) -> any
```

键存在时删除并返回对应值。键不存在时，如果提供 `default` 就返回它且不修改字典，否则报 `key_error`。非法键类型报 `type_error`。

## `str`

所有字符串方法返回新值，不修改原字符串。

### `str.strip` / `str.lstrip` / `str.rstrip`

```text
str.strip(chars=None) -> str
str.lstrip(chars=None) -> str
str.rstrip(chars=None) -> str
```

分别去除两端、左端或右端字符。`chars` 省略或为 `None` 时去除空白；提供字符串时，去除其中列出的任意字符，而不是匹配整个前后缀。`chars` 类型错误报 `type_error`。

### `str.split`

```text
str.split(sep=None, maxsplit=-1) -> list
```

把字符串拆成列表。

- `sep=None`：按连续空白拆分，忽略两端空白。
- `sep` 为非空字符串：按该分隔符拆分，保留空字段。
- `maxsplit < 0`：不限制拆分次数。
- `maxsplit >= 0`：最多拆分指定次数，剩余文本留在最后一项。

空分隔符、`sep` 类型错误或 `maxsplit` 非严格整数均报 `type_error`。

```python
print("  a  b ".split())
print("a,,b".split(","))
print("a,b,c".split(",", 1))
```

```text
['a', 'b']
['a', '', 'b']
['a', 'b,c']
```

### `str.splitlines`

```text
str.splitlines(keepends=False) -> list
```

按通用换行边界拆行。`keepends` 必须严格为 `bool`；为 `True` 时保留行尾换行符。末尾换行不会额外产生空字符串。类型错误报 `type_error`。

### `str.join`

```text
separator.join(values) -> str
```

以调用方法的字符串 `separator` 为分隔符，连接 `values` 中的字符串。`values` 可以是字符串、列表、元组或字典；字典遍历键。

所有元素必须严格为 `str`，否则报 `type_error`。空可迭代对象返回空字符串，单元素结果不含分隔符。

### `str.find`

```text
str.find(sub, start=None, end=None) -> int
```

返回子串 `sub` 在指定区间内首次出现的位置，不存在时返回 `-1`。边界遵循切片规范化规则。`sub` 必须为字符串，边界必须为整数或 `None`，否则报 `type_error`。

### `str.replace`

```text
str.replace(old, new, count=-1) -> str
```

替换不重叠的 `old` 子串。`count` 为负数时不限制次数，为零时不替换，正数限制最多替换次数。

`old` 和 `new` 必须为字符串，`count` 必须严格为整数，否则报 `type_error`。`old` 为空串时按 Python 语义在字符之间及两端插入。

### `str.partition`

```text
str.partition(sep) -> tuple
```

按首个非空分隔符拆成 `(before, sep, after)` 三元元组。未找到时返回 `(原字符串, "", "")`。分隔符为空或不是字符串时报 `type_error`。

### `str.rpartition`

```text
str.rpartition(sep) -> tuple
```

按最后一个非空分隔符拆成 `(before, sep, after)`。未找到时返回 `("", "", 原字符串)`。参数错误与 `partition` 相同。
