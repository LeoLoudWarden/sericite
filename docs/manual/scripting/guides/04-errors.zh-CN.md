# 异常处理

本章讲解捕获错误、主动抛出错误、检查异常信息和执行清理。

## 一个错误处理的例子

```python
def parse_count(text):
    try:
        value = int(text)
    except conversion_error as e:
        print("invalid:", e.message)
        return 0
    else:
        print("valid")
        return value
    finally:
        print("finished")

print(parse_count("12"))
print(parse_count("bad"))
```

语法与 Python 类似，含：try、except、else 与 finally。

## 异常

Sericite 中错误的种类是固定的，其中部分错误为可恢复错误，可被捕获。它们彼此独立、没有继承关系，因此无法靠继承关系批量捕获；语言为此内建了若干集合，每个集合固定包含若干相关的错误种类，`except` 使用分组即可一次匹配整组。

### 错误的结构

`as e` 绑定一个固定含三个字段的 record：

- `e.kind`：实际错误 kind 的字符串
- `e.message`：可读错误文本
- `e.frames`：调用栈 list

`e.frames` 中每项都是固定含两个字段的 record：

- `function`：函数名字符串；
- `line`：源码行号整数，无法提供时为 `None`。

受 Sericite 的设计约束，并非所有错误都能提供完整的调用栈诊断信息。

### 捕获错误

```python
except conversion_error:              # 捕获一种错误
except file_error:                    # 捕获一组相关错误
except (file_error, input_error):     # 多个错误种类或分组，可以混写
except ... as e:                      # 捕获所有可捕获错误，并绑定错误对象
except:                               # 捕获所有可捕获错误，不绑定错误对象
```

`except` 的过滤条件是静态语法，这些名字必须直接写出，不能用变量代替。通过分组捕获时，`e.kind` 仍是实际发生的错误种类，而不是分组名。

### 主动抛出错误

可使用 `raise` 抛出自定义错误。在 Sericite 中，无法抛出任意错误。只有字符串可以 `raise`，固定作为 `raise_error` 抛出：

```python
try:
    raise "operation failed"
except raise_error as e:
    print(e.message)
    raise               # 裸 raise：重抛当前错误，保留原始调用栈
```
