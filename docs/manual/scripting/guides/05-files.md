# File system

Sericite provides a plain-text file system for scripts, letting you read and write files and manage directories in a uniform way.

## Why it is this way

File interfaces and behaviors differ across platforms. Sericite uniformly defines the path spelling and operation rules and does not hand those differences directly to the script. File content is text only: what you write is a string, and what you read back is a string. This way, the same script handles files the same way on every platform.

## A file read/write example

```python
path = "scratch/note.txt"
write_file(path, "text")      # write a string, auto-creating missing parent directories
read_file(path)               # 'text': reads a string
list_dir("scratch")           # ['note.txt']: lists directory contents
path_exists(path)             # True: checks whether the path exists
```

## Files and directories

### Common operations

File operations:

```python
read_file(path)
write_file(path, text)
delete_file(path)
rename_file(old_path, new_path)
copy_file(source_path, destination_path)
```

Directory operations:

```python
make_dir(path)
delete_dir(path)
rename_dir(old_path, new_path)
copy_dir(source_path, destination_path)
list_dir(path)
```

In particular, there is `path_exists(path)`, which checks whether a file or directory exists.

### Path resolution

Suppose the initial workspace is empty, and the following code runs:

```python
notes_path = "/notes"
ideas_path = notes_path + "/ideas"

make_dir(ideas_path)
make_dir("/archive")

write_file(ideas_path + "/./draft.txt", "a new idea")
write_file(ideas_path + "/../today.txt", "finish the report")
write_file(ideas_path + "/../../archive/old.txt", "old report")
```

The directory structure becomes:

```text
/
├── archive
│   └── old.txt
└── notes
    ├── ideas
    │   └── draft.txt
    └── today.txt
```

`make_dir(ideas_path)` creates `/notes` and `/notes/ideas` at the same time. All three writes start from `ideas_path`: `.` does not change the current directory, and each `..` goes up one level, so the files are written into `ideas`, `notes`, and `archive` respectively.

### Implicit and explicit directories

Writing a file auto-creates missing parent directories; `make_dir` explicitly creates directories. The two differ in how they are treated after becoming empty:

```python
write_file("/scratch/draft.txt", "draft")  # implicitly creates /scratch
write_file("/archive/old.txt", "old")      # implicitly creates /archive
make_dir("/keep/empty")                    # explicitly creates /keep and /keep/empty

delete_file("/scratch/draft.txt")
rename_file("/archive/old.txt", "/old.txt")

path_exists("/scratch")      # False: the emptied implicit directory is removed
path_exists("/archive")      # False: after the file moves out, /archive is also removed
path_exists("/keep")         # True: an explicit directory is kept even when empty
path_exists("/keep/empty")   # True
path_exists("/")             # True: the root always remains
```

## Path resolution is not module resolution

The leading dot in a relative import means the current or parent package; `.` and `..` in a file path are ordinary path segments. The two look similar but resolve from different bases.

Suppose the initial workspace is as follows, where both `__init__.sericite` files are empty:

```text
/
├── main.sericite
└── lib
    ├── __init__.sericite
    └── sub
        ├── __init__.sericite
        ├── mod.sericite
        └── util.sericite
```

`/lib/sub/util.sericite`:

```python
prefix = "util: "
```

`/lib/sub/mod.sericite`:

```python
from . import util               # the current package is lib.sub, so this imports lib.sub.util

text = read_file("./input.txt")  # resolved from the root: reads /input.txt
write_file("./output.txt", util.prefix + text)  # writes /output.txt
```

`/main.sericite`:

```python
write_file("/input.txt", "hello")
import lib.sub.mod

print(read_file("/output.txt"))
```

Expected output:

```text
util: hello
```

Do not read `"./input.txt"` as `/lib/sub/input.txt` just because the code lives in `/lib/sub/mod.sericite`. The module's location affects relative imports, but file operations still resolve paths from the workspace root.
