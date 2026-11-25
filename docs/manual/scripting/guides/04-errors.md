# Error handling

This chapter explains catching errors, raising errors, inspecting exception information, and running cleanup.

## An error-handling example

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

The syntax is similar to Python and includes `try`, `except`, `else`, and `finally`.

## Exceptions

The kinds of errors in Sericite are fixed. Some of them are recoverable errors that can be caught. They are independent of one another with no inheritance relationship, so they cannot be caught in bulk through inheritance; the language builds in several groups for this, each fixed to a set of related error kinds, and an `except` can match a whole group at once by using the group.

### The structure of errors

`as e` binds a record with exactly three fields:

- `e.kind`: the string of the actual error kind
- `e.message`: the readable error text
- `e.frames`: the call stack list

Each item in `e.frames` is a record with exactly two fields:

- `function`: the function name string;
- `line`: the source line number integer, or `None` when unavailable.

Due to Sericite's design constraints, not every error can provide a complete call-stack diagnostic.

### Catching errors

```python
except conversion_error:              # catch one kind of error
except file_error:                    # catch a group of related errors
except (file_error, input_error):     # several kinds or groups, mixable
except ... as e:                      # catch all catchable errors and bind the error object
except:                               # catch all catchable errors without binding
```

The `except` filter condition is static syntax: these names must be written directly and cannot be replaced by a variable. When catching through a group, `e.kind` is still the actual error kind that occurred, not the group name.

### Raising errors

You can use `raise` to throw a custom error. In Sericite you cannot throw an arbitrary error. Only strings can be raised, fixed to be thrown as `raise_error`:

```python
try:
    raise "operation failed"
except raise_error as e:
    print(e.message)
    raise               # bare raise: re-raise the current error, keeping the original call stack
```
