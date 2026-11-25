# Safety notes

Sericite encourages you to solve problems by creating isolated execution environments. Even so, you should have a general understanding of Sericite's security model and know what to watch for when writing code.

## Isolation and quotas

### Environment isolation

Earlier examples showed that a parent program does not automatically see files created by a child program. Conversely, a child program cannot directly read the parent's variables and files. The following child program attempts both and produces an error for each:

```python
secret = "parent secret"
write_file("/secret.txt", "parent file")

source = """
try:
    print(secret)
except name_error as e:
    print("variable:", e.kind)

try:
    print(read_file("/secret.txt"))
except file_not_found as e:
    print("file:", e.kind)
"""

program = VM(source)
print(program.run(), end="")

print("parent variable:", secret)
print("parent file:", read_file("/secret.txt"))
program.dispose()
```

Expected output:

```text
variable: name_error
file: file_not_found
parent variable: parent secret
parent file: parent file
```

This isolation is a basic guarantee Sericite provides and does not depend on the child program's cooperation. The parent's variables and files are simply not in the child program's execution world from the start. Only content the parent program explicitly provides through `fs`, `addons`, and so on becomes part of what the child program can access.

### Execution limits

Environment isolation only limits what a child program can access; it does not limit how long it runs or how much it consumes. Without execution limits, one `while True` can make `run()` never return; continuously accumulating data or producing output also keeps consuming memory. No matter how thorough the isolation, it cannot stop that kind of consumption.

Therefore, Sericite's security model includes not only environment isolation but also execution limits: the former determines what a child program can touch, and the latter determines the most it can consume.

When creating a VM, you can set upper bounds on instruction count, memory, output, and so on. For example, the following child program contains an infinite loop but can execute at most 1000 instructions:

```python
program = VM("""
while True:
    pass
""", max_instructions=1000)

try:
    program.run()
except resource_exhausted as e:
    print("stopped:", e.kind)

print("state:", program.snapshot()["state"])
program.dispose()
```

Expected output:

```text
stopped: resource_exhausted
state: resource_exhausted
```

After reaching the instruction limit, the child program stops executing and enters the `resource_exhausted` state; the program that called it can catch this error and handle it. Although `VM(...)` provides default values for every quota, do not treat the defaults as a safety recommendation. When executing code that is not fully trusted, set limits explicitly for the task.

## Why it is this way

Consider the following scenario:

Alice is writing an application that supports modules, one of which is developed by Bob. Alice wants to use this module but does not want it to directly access all of her variables, files, and other capabilities, so she runs it in a VM as an independent program and provides only the necessary workspace, addons, and execution limits.

"Untrusted" here does not mean Alice has concluded that Bob is malicious; it means Alice does not want the module to have the same access scope as her own business code.

Auditing and isolation do not contradict each other: auditing is for finding problems, and isolation limits the impact of problems that were not found. Real-world modules may be hot-updated, and third-party dependencies keep changing; developers usually cannot continuously audit every implementation they did not write themselves. Even if a version was reviewed, that does not mean all later versions can be trusted.

Bob's module then needs a data-analysis feature provided by Carol as executable code. After Bob takes Carol's code, he faces the same problem as Alice: if he executes it directly in his own execution space, Carol's code can use the files and capabilities Bob currently holds, which may include content Alice granted to Bob.

So Bob can also create a child VM, put Carol's code inside, provide only the workspace and capabilities the data-analysis feature actually needs, and set the corresponding execution limits:

```text
Alice's application
└── Bob's module: an independent VM
    └── Carol's data-analysis code: an independent VM
```

Alice is responsible for constraining Bob's module, and Bob further constrains Carol's code within his own boundary. Carol does not automatically gain Bob's or Alice's whole execution world just because Bob uses this code; and Bob cannot loosen the execution limits Alice has already set by creating a child VM.

VMs in Sericite are naturally nestable: **external code may keep running external code, and the need for isolation appears layer by layer accordingly.**

## Common bad habits

### Misusing grants

When granting a function, the content accessible in the function's defining environment can be exposed along with it:

```python
write_file("/secret.txt", "parent secret")

def read_parent_file(path):
    return read_file(path)

source = """
from __addon__ import read_parent_file
print(read_parent_file("/secret.txt"))
"""

program = VM(source, addons={"read_parent_file": read_parent_file})
print(program.run(), end="")
program.dispose()
```

Expected output:

```text
parent secret
```

The child program's workspace has no `/secret.txt`, but the `read_file()` inside `read_parent_file()` still reads the parent workspace where it was defined.

Sericite's isolation is not breached, but every addon creates an information opening at the isolation boundary. Before granting, look carefully at what the function can actually read, modify, or control, and provide only the capabilities the child program genuinely needs.

### Sloppy management

Sericite eventually collects VMs that are completely unreachable, but it does not guarantee the collection timing. While waiting to be collected, a VM still occupies a live-count quota, so repeatedly creating VMs can unexpectedly produce `resource_exhausted`.

Call `dispose()` explicitly when you need a definite release. You can use `finally` to cover both normal completion and error exit:

```python
program = VM('raise "failed"')

try:
    program.run()
except raise_error as e:
    print("child:", e.message)
finally:
    program.dispose()
```

Expected output:

```text
child: failed
```

`dispose()` destroys this VM and its still-live descendants; there is no need to clean up layer by layer manually.

### VM incest

A VM handle can cross the isolation boundary through a granted function, and one VM can even obtain a handle pointing to itself:

```python
def get_vm():
    return vm_a

vm_a = VM("""
from __addon__ import get_vm

myself = get_vm()
""", addons={"get_vm": get_vm})

vm_a.run()
vm_a.dispose()
```

Similarly, different VMs can hold each other's handles and form cross-references. This is **semantically legal but implementation-wise questionable**. Sericite does not prevent it, and it does not breach the security model: the handles are explicitly granted through addons, execution limits and driving restrictions still apply, and even a completely unreachable reference cycle can eventually be collected.

But legal does not mean reasonable. **A VM handle represents the ability to observe and control a program**; passing it around casually makes a program's capability boundaries and lifecycle hard to understand. If ordinary business logic depends on such a structure, it usually indicates a problem with code ownership or responsibility division.

**Sericite will not stop you from writing bad code.** Unless there is a clear reason, do not pass VMs around as ordinary data across isolation boundaries.
