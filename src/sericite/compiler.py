from __future__ import annotations

import ast

from . import isa
from .errors import SericiteError

RESERVED_NAMES = {
    "input",
    "print",
    "VM",
    "len",
    "int",
    "float",
    "str",
    "range",
    "read_file",
    "write_file",
    "list_dir",
    "path_exists",
    "keys",
    "any",
    "bool",
    "list",
    "dict",
    "wrap",
    "unwrap",
}

# Contract names that may only appear in annotation positions (not functions, not callable).
_CONTRACT_ONLY_NAMES = {"any", "bool", "list", "dict"}

_ALLOWED_NODES = {
    ast.Module,
    ast.Assign,
    ast.AnnAssign,
    ast.Expr,
    ast.If,
    ast.IfExp,
    ast.While,
    ast.For,
    ast.Break,
    ast.Continue,
    ast.FunctionDef,
    ast.ClassDef,
    ast.Return,
    ast.Raise,
    ast.Pass,
    ast.Try,
    ast.ExceptHandler,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.List,
    ast.Dict,
    ast.Subscript,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Call,
    ast.Attribute,
    ast.arguments,
    ast.arg,
    ast.keyword,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.USub,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
}

_BINARY_OPS = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Mod: "%",
}
_UNARY_OPS = {ast.USub: "-", ast.Not: "not"}
_COMPARE_OPS = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.In: "in",
    ast.NotIn: "not in",
}

VM_METHODS = {
    "run",
    "feed_input",
    "step",
    "step_instruction",
    "snapshot",
    "stdout",
    "terminate",
    "read_file",
    "write_file",
    "list_dir",
    "path_exists",
}


class _Scope:
    def __init__(
        self, node: ast.AST, code: isa.CodeUnit, parent: _Scope | None
    ) -> None:
        self.node = node
        self.code = code
        self.parent = parent
        self.children: list[_Scope] = []
        self.bound: dict[str, None] = {}
        self.loaded: dict[str, None] = {}
        self.cells: dict[str, None] = {}
        self.free: dict[str, None] = {}

    def capture(self, name: str) -> bool:
        if self.parent is None:
            return False
        if name in self.bound:
            self.cells[name] = None
            return True
        if self.parent.capture(name):
            self.free[name] = None
            return True
        return False


class _ScopeCollector(ast.NodeVisitor):
    def __init__(self, scope: _Scope) -> None:
        self.scope = scope

    def visit_Name(self, node: ast.Name) -> None:
        names = (
            self.scope.bound if isinstance(node.ctx, ast.Store) else self.scope.loaded
        )
        names[node.id] = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.bound[node.name] = None
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in node.args.defaults:
            self.visit(default)
        for argument in node.args.args:
            if argument.annotation is not None:
                self.visit(argument.annotation)
        if node.returns is not None:
            self.visit(node.returns)
        params = [argument.arg for argument in node.args.args]
        child = _Scope(
            node,
            isa.CodeUnit(name=node.name, params=params),
            self.scope,
        )
        self.scope.children.append(child)
        collector = _ScopeCollector(child)
        for param in params:
            child.bound[param] = None
        for statement in node.body:
            collector.visit(statement)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # The class name binds in the current scope; field names are not scope names —
        # only field contract annotations are evaluated at definition (and may reference outer names).
        self.scope.bound[node.name] = None
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign):
                self.visit(statement.annotation)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.scope.bound[node.name] = None
        for statement in node.body:
            self.visit(statement)


def _analyze_scopes(tree: ast.Module, code: isa.CodeUnit) -> dict[int, _Scope]:
    root = _Scope(tree, code, None)
    _ScopeCollector(root).visit(tree)
    scopes = [root]
    while scopes:
        scope = scopes.pop()
        if scope.parent is not None:
            for name in scope.loaded:
                if name not in scope.bound and scope.parent.capture(name):
                    scope.free[name] = None
        scopes.extend(scope.children)
    scopes = [root]
    result: dict[int, _Scope] = {}
    while scopes:
        scope = scopes.pop()
        scope.code.local_names = tuple(scope.bound)
        scope.code.cell_names = tuple(
            name for name in scope.bound if name in scope.cells
        )
        scope.code.free_names = tuple(scope.free)
        result[id(scope.node)] = scope
        scopes.extend(scope.children)
    return result


def compile_source(source: object, filename: str) -> isa.CodeUnit:
    if not isinstance(source, str):
        raise SericiteError("VM source must be a string", filename=filename)
    try:
        tree = ast.parse(source, filename=filename, mode="exec")
    except SyntaxError as exc:
        raise SericiteError(
            exc.msg or "invalid syntax",
            kind="syntax_error",
            filename=filename,
            line=exc.lineno,
            column=exc.offset,
        ) from None
    except RecursionError:
        raise SericiteError(
            "source nesting too deep",
            kind="validation_error",
            filename=filename,
        ) from None
    except MemoryError:
        raise SericiteError(
            "source too large to compile",
            kind="validation_error",
            filename=filename,
        ) from None
    try:
        _validate(tree, filename)
        code = isa.CodeUnit(name="<module>", params=[])
        scopes = _analyze_scopes(tree, code)
        compiler = _Compiler(filename, scopes)
        compiler.compile_body(tree.body, code)
        compiler.emit(code, isa.LOAD_CONST, None, 0)
        compiler.emit(code, isa.RETURN, None, 0)
        _analyze_stack(code, filename)
    except RecursionError:
        raise SericiteError(
            "source nesting too deep",
            kind="validation_error",
            filename=filename,
        ) from None
    except MemoryError:
        raise SericiteError(
            "source too large to compile",
            kind="validation_error",
            filename=filename,
        ) from None
    return code


_STACK_DELTAS = {
    isa.LOAD_CONST: 1,
    isa.LOAD_NAME: 1,
    isa.LOAD_DEREF: 1,
    isa.DUP: 1,
    isa.STORE_NAME: -1,
    isa.STORE_DEREF: -1,
    isa.POP: -1,
    isa.GET_ITER: -1,
    isa.LOAD_INDEX: -1,
    isa.BINARY_OP: -1,
    isa.COMPARE_OP: -1,
    isa.STORE_INDEX: -3,
    isa.UNARY_OP: 0,
    isa.LOAD_ATTR: 0,
    isa.STORE_ATTR: -2,
    isa.CHECK_ANNOT: -1,
}


def _analyze_stack(code: isa.CodeUnit, filename: str) -> None:
    instrs = code.instrs
    if not instrs:
        return
    depths: list[int | None] = [None] * len(instrs)
    depths[0] = 0
    worklist = [0]
    while worklist:
        i = worklist.pop()
        depth = depths[i]
        assert depth is not None
        instr = instrs[i]
        successors: list[tuple[int, int]] = []
        if instr.op == isa.JUMP:
            successors.append((instr.arg, depth))
        elif instr.op == isa.JUMP_IF_FALSE:
            successors.append((instr.arg, depth - 1))
            successors.append((i + 1, depth - 1))
        elif instr.op in (isa.JUMP_IF_TRUE_KEEP, isa.JUMP_IF_FALSE_KEEP):
            successors.append((instr.arg, depth))
            successors.append((i + 1, depth - 1))
        elif instr.op == isa.FOR_ITER:
            successors.append((instr.arg[1], depth))
            successors.append((i + 1, depth + 1))
        elif instr.op in (isa.RETURN, isa.RAISE):
            pass
        else:
            if instr.op == isa.BUILD_LIST:
                delta = 1 - instr.arg
            elif instr.op == isa.BUILD_DICT:
                delta = 1 - 2 * instr.arg
            elif instr.op == isa.MAKE_SCHEMA:
                delta = 1 - len(instr.arg)
            elif instr.op == isa.MAKE_FUNCTION:
                delta = 1 - (instr.arg[1] + instr.arg[2])
            elif instr.op == isa.CALL:
                delta = -instr.arg
            elif instr.op == isa.CALL_KW:
                delta = -(instr.arg[0] + len(instr.arg[1]))
            else:
                delta = _STACK_DELTAS[instr.op]
            successors.append((i + 1, depth + delta))
        for target, target_depth in successors:
            if target >= len(instrs):
                raise SericiteError(
                    "compiler produced a jump out of range",
                    kind="internal_error",
                    filename=filename,
                )
            if depths[target] is None:
                depths[target] = target_depth
                worklist.append(target)
            elif depths[target] != target_depth:
                raise SericiteError(
                    "compiler produced inconsistent stack depths",
                    kind="internal_error",
                    filename=filename,
                )
    for handler in code.handlers:
        start_depth = depths[handler.start]
        if start_depth is not None:
            handler.stack_depth = start_depth


def _is_annotation_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Whether the name *is* the annotation expression itself. Reserved names hidden inside sub-expressions are rejected."""
    parent = parents.get(node)
    if isinstance(parent, ast.arg) and parent.annotation is node:
        return True
    if isinstance(parent, ast.AnnAssign) and parent.annotation is node:
        return True
    return isinstance(parent, ast.FunctionDef) and parent.returns is node


def _validate(tree: ast.Module, filename: str) -> None:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODES:
            _reject(node, filename, f"unsupported syntax: {type(node).__name__}")
        if isinstance(node, ast.Constant) and type(node.value) not in {
            str,
            int,
            float,
            bool,
            type(None),
        }:
            _reject(node, filename, "unsupported constant")
        if isinstance(node, ast.Name):
            if node.id.startswith("__"):
                _reject(node, filename, "dunder names are not available")
            parent = parents.get(node)
            # A bare field declaration in a class body is a field name, not a name reference
            is_bare_field = isinstance(parent, ast.Expr) and isinstance(
                parents.get(parent), ast.ClassDef
            )
            if node.id in RESERVED_NAMES and not is_bare_field:
                is_call_func = isinstance(parent, ast.Call) and parent.func is node
                if node.id in _CONTRACT_ONLY_NAMES:
                    if not _is_annotation_name(node, parents):
                        _reject(
                            node,
                            filename,
                            f"'{node.id}' can only be used as a contract "
                            "in annotations",
                        )
                elif not is_call_func and not _is_annotation_name(node, parents):
                    _reject(
                        node,
                        filename,
                        f"builtin '{node.id}' can only be called directly",
                    )
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            _reject(node, filename, "dunder attributes are not available")
        if isinstance(node, ast.ClassDef):
            if node.name.startswith("__"):
                _reject(node, filename, "dunder names are not available")
            if node.name in RESERVED_NAMES:
                _reject(
                    node,
                    filename,
                    f"builtin '{node.name}' cannot be redefined",
                )
            if node.bases or node.keywords or node.decorator_list:
                _reject(
                    node,
                    filename,
                    "class does not support bases, keywords, or decorators",
                )
            seen: set[str] = set()
            for statement in node.body:
                if isinstance(statement, ast.Pass):
                    continue
                if isinstance(statement, ast.Expr) and isinstance(
                    statement.value, ast.Name
                ):
                    field_name = statement.value.id
                elif isinstance(statement, ast.Assign) or (
                    isinstance(statement, ast.AnnAssign) and statement.value is not None
                ):
                    _reject(
                        statement,
                        filename,
                        "field defaults are not supported yet",
                    )
                elif (
                    isinstance(statement, ast.AnnAssign)
                    and statement.simple
                    and isinstance(statement.target, ast.Name)
                ):
                    field_name = statement.target.id
                else:
                    _reject(
                        statement,
                        filename,
                        "class body only allows field declarations",
                    )
                if field_name in seen:
                    _reject(
                        statement,
                        filename,
                        f"duplicate field: {field_name}",
                    )
                seen.add(field_name)
        if isinstance(node, ast.AnnAssign):
            parent = parents.get(node)
            if not isinstance(parent, ast.ClassDef):
                if not isinstance(node.target, ast.Name):
                    _reject(
                        node,
                        filename,
                        "annotated assignment target must be a name",
                    )
                if node.value is None:
                    _reject(
                        node,
                        filename,
                        "annotated assignment requires a value",
                    )
        if isinstance(node, ast.keyword) and node.arg is None:
            _reject(node, filename, "** arguments are not supported")
        if isinstance(node, ast.Dict) and any(key is None for key in node.keys):
            _reject(node, filename, "** unpacking is not supported")
        if (
            isinstance(node, ast.ExceptHandler)
            and node.type is not None
            and not isinstance(node.type, ast.Name)
        ):
            _reject(
                node,
                filename,
                "except clause must name an error kind",
            )
        if isinstance(node, ast.FunctionDef):
            if node.name.startswith("__"):
                _reject(node, filename, "dunder names are not available")
            if node.name in RESERVED_NAMES:
                _reject(
                    node,
                    filename,
                    f"builtin '{node.name}' cannot be redefined",
                )
            args = node.args
            if (
                args.kw_defaults
                or args.vararg
                or args.kwarg
                or args.kwonlyargs
                or getattr(args, "posonlyargs", [])
            ):
                _reject(
                    node,
                    filename,
                    "only positional parameters with optional defaults are supported",
                )
        if isinstance(node, ast.For) and not isinstance(node.target, ast.Name):
            _reject(node, filename, "for target must be a name")
        if isinstance(node, ast.Raise) and node.cause is not None:
            _reject(node, filename, "raise ... from ... is not supported")
        if isinstance(node, ast.Compare) and len(node.ops) != 1:
            _reject(node, filename, "chained comparisons are not supported")
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, (ast.Name, ast.Subscript, ast.Attribute)):
                    _reject(node, filename, "unsupported assignment target")
            if len(node.targets) > 1 and any(
                isinstance(target, (ast.Subscript, ast.Attribute))
                for target in node.targets
            ):
                _reject(
                    node,
                    filename,
                    "multiple targets with subscript or attribute are not supported",
                )


def _reject(node: ast.AST, filename: str, message: str) -> None:
    raise SericiteError(
        message,
        kind="validation_error",
        filename=filename,
        line=getattr(node, "lineno", None),
        column=(node.col_offset + 1 if hasattr(node, "col_offset") else None),
    )


def _assigned_names(body: list[ast.stmt]) -> set[str]:
    names: set[str] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        if isinstance(node, ast.ExceptHandler) and node.name is not None:
            names.add(node.name)
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in body:
        visit(statement)
    return names


class _Compiler:
    def __init__(self, filename: str, scopes: dict[int, _Scope]) -> None:
        self._filename = filename
        self._scopes = scopes
        self._loops: list[tuple[int, list[int], int]] = []
        self._finally_stack: list[list[ast.stmt]] = []
        self._function_depth = 0
        self._tmp_counter = 0
        # Compile-time label table (diagnostics only): name -> label text, pushed/popped with the function scope.
        self._label_stack: list[dict[str, str]] = [{}]

    def _set_labels(self, labels: dict[str, str]) -> None:
        self._label_stack[-1] = labels

    @staticmethod
    def _without_labels(labels: dict[str, str], names: set[str]) -> dict[str, str]:
        return {name: label for name, label in labels.items() if name not in names}

    @staticmethod
    def _merge_labels(environments: list[dict[str, str]]) -> dict[str, str]:
        first, *rest = environments
        return {
            name: label
            for name, label in first.items()
            if all(labels.get(name) == label for labels in rest)
        }

    def _propagate_label(self, name: str, value: ast.AST) -> None:
        labels = self._label_stack[-1]
        source: str | None = None
        if isinstance(value, ast.Name):
            source = labels.get(value.id)
        elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            source = labels.get(value.func.id)
        if source is None:
            labels.pop(name, None)
        else:
            labels[name] = source

    def _attr_hint(self, value: ast.AST) -> str | None:
        if isinstance(value, ast.Name):
            return self._label_stack[-1].get(value.id)
        return None

    def _store_name(self, code: isa.CodeUnit, name: str, line: int) -> None:
        op = isa.STORE_DEREF if name in code.cell_names else isa.STORE_NAME
        self.emit(code, op, name, line)

    def _compile_finally_exits(
        self, code: isa.CodeUnit, line: int, bodies: list[list[ast.stmt]]
    ) -> None:
        for body in reversed(bodies):
            self._finally_stack.pop()
            try:
                self.compile_body(body, code)
            finally:
                self._finally_stack.append(body)

    def emit(self, code: isa.CodeUnit, op: str, arg: object, line: int) -> int:
        code.instrs.append(isa.Instr(op=op, arg=arg, line=line))
        return len(code.instrs) - 1

    def compile_body(self, body: list[ast.stmt], code: isa.CodeUnit) -> None:
        for statement in body:
            first = len(code.instrs)
            self.compile_statement(statement, code)
            if len(code.instrs) > first:
                code.instrs[first].stmt_start = True

    def compile_statement(self, node: ast.stmt, code: isa.CodeUnit) -> None:
        line = node.lineno
        if isinstance(node, ast.Assign):
            self.compile_expression(node.value, code)
            targets = node.targets
            for target in targets[:-1]:
                self.emit(code, isa.DUP, None, line)
                assert isinstance(target, ast.Name)
                self._store_name(code, target.id, line)
                self._propagate_label(target.id, node.value)
            last = targets[-1]
            if isinstance(last, ast.Name):
                self._store_name(code, last.id, line)
                self._propagate_label(last.id, node.value)
            elif isinstance(last, ast.Attribute):
                self.compile_expression(last.value, code)
                self.emit(
                    code,
                    isa.STORE_ATTR,
                    (last.attr, self._attr_hint(last.value)),
                    line,
                )
            else:
                assert isinstance(last, ast.Subscript)
                self.compile_expression(last.value, code)
                self.compile_expression(last.slice, code)
                self.emit(code, isa.STORE_INDEX, None, line)
            return
        if isinstance(node, ast.AnnAssign):
            label = ast.unparse(node.annotation)
            self.compile_expression(node.value, code)
            self.compile_expression(node.annotation, code)
            self.emit(code, isa.CHECK_ANNOT, label, line)
            assert isinstance(node.target, ast.Name)
            self._store_name(code, node.target.id, line)
            self._label_stack[-1][node.target.id] = label
            return
        if isinstance(node, ast.Expr):
            self.compile_expression(node.value, code)
            self.emit(code, isa.POP, None, line)
            return
        if isinstance(node, ast.If):
            entry_labels = self._label_stack[-1].copy()
            self.compile_expression(node.test, code)
            jump_false = self.emit(code, isa.JUMP_IF_FALSE, None, line)
            self.compile_body(node.body, code)
            body_labels = self._label_stack[-1]
            jump_end = self.emit(code, isa.JUMP, None, line)
            code.instrs[jump_false].arg = len(code.instrs)
            self._set_labels(entry_labels.copy())
            self.compile_body(node.orelse, code)
            else_labels = self._label_stack[-1]
            self._set_labels(self._merge_labels([body_labels, else_labels]))
            code.instrs[jump_end].arg = len(code.instrs)
            return
        if isinstance(node, ast.While):
            entry_labels = self._label_stack[-1].copy()
            head_labels = self._without_labels(entry_labels, _assigned_names(node.body))
            self._set_labels(head_labels.copy())
            start = len(code.instrs)
            self.compile_expression(node.test, code)
            jump_false = self.emit(code, isa.JUMP_IF_FALSE, None, line)
            breaks: list[int] = []
            self._loops.append((start, breaks, len(self._finally_stack)))
            self.compile_body(node.body, code)
            self._loops.pop()
            self.emit(code, isa.JUMP, start, line)
            end = len(code.instrs)
            code.instrs[jump_false].arg = end
            self._set_labels(head_labels)
            self.compile_body(node.orelse, code)
            self._set_labels(
                self._without_labels(entry_labels, _assigned_names([node]))
            )
            real_end = len(code.instrs)
            for index in breaks:
                code.instrs[index].arg = real_end
            return
        if isinstance(node, ast.For):
            self._compile_for(node, code)
            return
        if isinstance(node, ast.Break):
            if not self._loops:
                self._outside_loop(node)
            _, breaks, finally_depth = self._loops[-1]
            self._compile_finally_exits(code, line, self._finally_stack[finally_depth:])
            index = self.emit(code, isa.JUMP, None, line)
            breaks.append(index)
            return
        if isinstance(node, ast.Continue):
            if not self._loops:
                self._outside_loop(node)
            start, _, finally_depth = self._loops[-1]
            self._compile_finally_exits(code, line, self._finally_stack[finally_depth:])
            self.emit(code, isa.JUMP, start, line)
            return
        if isinstance(node, ast.Pass):
            return
        if isinstance(node, ast.Raise):
            if node.exc is None:
                self.emit(code, isa.RAISE, None, line)
            else:
                self.compile_expression(node.exc, code)
                self.emit(code, isa.RAISE, True, line)
            return
        if isinstance(node, ast.FunctionDef):
            analyzed = self._scopes[id(node)].code
            param_labels = tuple(
                ast.unparse(argument.annotation)
                if argument.annotation is not None
                else None
                for argument in node.args.args
            )
            child = isa.CodeUnit(
                name=analyzed.name,
                params=analyzed.params,
                local_names=analyzed.local_names,
                cell_names=analyzed.cell_names,
                free_names=analyzed.free_names,
                param_labels=param_labels,
                return_label=(
                    ast.unparse(node.returns) if node.returns is not None else None
                ),
            )
            self._function_depth += 1
            loop_stack, self._loops = self._loops, []
            finally_stack, self._finally_stack = self._finally_stack, []
            self._label_stack.append(
                {
                    argument.arg: label
                    for argument, label in zip(node.args.args, param_labels)
                    if label is not None
                }
            )
            try:
                self.compile_body(node.body, child)
            finally:
                self._loops = loop_stack
                self._finally_stack = finally_stack
                self._label_stack.pop()
                self._function_depth -= 1
            self.emit(child, isa.LOAD_CONST, None, 0)
            self.emit(child, isa.RETURN, None, 0)
            _analyze_stack(child, self._filename)
            decorators: list[tuple[str, int]] = []
            for decorator in node.decorator_list:
                decorator_name = f"$decorator_{self._tmp_counter}"
                self._tmp_counter += 1
                decorator_line = getattr(decorator, "lineno", line)
                self.compile_expression(decorator, code)
                self.emit(code, isa.STORE_NAME, decorator_name, decorator_line)
                decorators.append((decorator_name, decorator_line))
            for default in node.args.defaults:
                self.compile_expression(default, code)
            for argument in node.args.args:
                if argument.annotation is not None:
                    self.compile_expression(argument.annotation, code)
                else:
                    self.emit(code, isa.LOAD_CONST, None, line)
            if node.returns is not None:
                self.compile_expression(node.returns, code)
            else:
                self.emit(code, isa.LOAD_CONST, None, line)
            self.emit(
                code,
                isa.MAKE_FUNCTION,
                (child, len(node.args.defaults), len(node.args.args) + 1),
                line,
            )
            if decorators:
                target_name = f"$decorated_{self._tmp_counter}"
                self._tmp_counter += 1
                self.emit(code, isa.STORE_NAME, target_name, line)
                for decorator_name, decorator_line in reversed(decorators):
                    self.emit(code, isa.LOAD_NAME, decorator_name, decorator_line)
                    self.emit(code, isa.LOAD_NAME, target_name, line)
                    self.emit(code, isa.CALL, 1, decorator_line)
                    self.emit(code, isa.STORE_NAME, target_name, line)
                self.emit(code, isa.LOAD_NAME, target_name, line)
            self._store_name(code, node.name, line)
            self._label_stack[-1].pop(node.name, None)
            return
        if isinstance(node, ast.Return):
            if self._function_depth == 0:
                raise SericiteError(
                    "return outside function",
                    kind="validation_error",
                    filename=self._filename,
                    line=line,
                )
            if node.value is not None:
                self.compile_expression(node.value, code)
            else:
                self.emit(code, isa.LOAD_CONST, None, line)
            self._compile_finally_exits(code, line, list(self._finally_stack))
            self.emit(code, isa.RETURN, None, line)
            return
        if isinstance(node, ast.Try):
            self._compile_try(node, code)
            return
        if isinstance(node, ast.ClassDef):
            names: list[str] = []
            for statement in node.body:
                if isinstance(statement, ast.Pass):
                    continue
                if isinstance(statement, ast.Expr):
                    names.append(statement.value.id)  # type: ignore[union-attr]
                    self.emit(code, isa.LOAD_NAME, "any", statement.lineno)
                else:
                    assert isinstance(statement, ast.AnnAssign)
                    names.append(statement.target.id)  # type: ignore[union-attr]
                    self.compile_expression(statement.annotation, code)
            self.emit(code, isa.MAKE_SCHEMA, tuple(names), line)
            self._store_name(code, node.name, line)
            self._label_stack[-1][node.name] = node.name
            return
        raise SericiteError(
            f"unsupported statement: {type(node).__name__}",
            kind="validation_error",
            filename=self._filename,
            line=line,
        )

    def _compile_for(self, node: ast.For, code: isa.CodeUnit) -> None:
        line = node.lineno
        entry_labels = self._label_stack[-1].copy()
        iter_name = f"$for_{self._tmp_counter}"
        self._tmp_counter += 1
        self.compile_expression(node.iter, code)
        self.emit(code, isa.GET_ITER, iter_name, line)
        head_labels = self._without_labels(
            entry_labels, _assigned_names(node.body) | {node.target.id}
        )
        self._set_labels(head_labels.copy())
        start = len(code.instrs)
        for_iter = self.emit(code, isa.FOR_ITER, (iter_name, None), line)
        self._store_name(code, node.target.id, line)
        self._label_stack[-1].pop(node.target.id, None)
        breaks: list[int] = []
        self._loops.append((start, breaks, len(self._finally_stack)))
        self.compile_body(node.body, code)
        self._loops.pop()
        self.emit(code, isa.JUMP, start, line)
        end = len(code.instrs)
        code.instrs[for_iter].arg = (iter_name, end)
        self._set_labels(head_labels)
        self.compile_body(node.orelse, code)
        self._set_labels(self._without_labels(entry_labels, _assigned_names([node])))
        real_end = len(code.instrs)
        for index in breaks:
            code.instrs[index].arg = real_end

    def _compile_try(self, node: ast.Try, code: isa.CodeUnit) -> None:
        line = node.lineno
        if not node.handlers and not node.finalbody:
            raise SericiteError(
                "try requires at least one except or finally clause",
                kind="validation_error",
                filename=self._filename,
                line=line,
            )
        entry_labels = self._label_stack[-1].copy()
        assigned = _assigned_names([node])
        exit_labels = self._without_labels(entry_labels, assigned)
        body_assigned = _assigned_names(node.body)
        has_finally = bool(node.finalbody)
        if has_finally:
            self._finally_stack.append(node.finalbody)
        body_start = len(code.instrs)
        self.compile_body(node.body, code)
        body_labels = self._label_stack[-1].copy()
        body_end = len(code.instrs)
        body_exit = self.emit(code, isa.JUMP, None, line)
        handler_entries: list[
            tuple[int, int, int, tuple[str, ...] | None, str | None]
        ] = []
        handler_exits: list[int] = []
        for handler in node.handlers:
            target = len(code.instrs)
            kinds = (
                None if handler.type is None else (handler.type.id,)  # type: ignore[union-attr]
            )
            handler_entries.append((body_start, body_end, target, kinds, handler.name))
            handler_labels = self._without_labels(entry_labels, body_assigned)
            if handler.name is not None:
                handler_labels.pop(handler.name, None)
            self._set_labels(handler_labels)
            self.compile_body(handler.body, code)
            handler_exits.append(self.emit(code, isa.JUMP, None, line))
        else_label = len(code.instrs)
        code.instrs[body_exit].arg = else_label
        self._set_labels(body_labels)
        self.compile_body(node.orelse, code)
        after_else = len(code.instrs)
        for index in handler_exits:
            code.instrs[index].arg = after_else
        for start, stop, target, kinds, bind in handler_entries:
            code.handlers.append(
                isa.Handler(
                    start=start,
                    end=stop,
                    target=target,
                    kinds=kinds,
                    bind=bind,
                )
            )
        if not has_finally:
            self._set_labels(exit_labels)
            return
        self._finally_stack.pop()
        finally_labels = self._without_labels(entry_labels, assigned)
        self._set_labels(finally_labels.copy())
        self.compile_body(node.finalbody, code)
        normal_labels = self._label_stack[-1].copy()
        normal_exit = self.emit(code, isa.JUMP, None, line)
        catch_target = len(code.instrs)
        error_name = f"$err_{self._tmp_counter}"
        self._tmp_counter += 1
        self._set_labels(finally_labels)
        self.compile_body(node.finalbody, code)
        self._set_labels(normal_labels)
        self.emit(code, isa.RAISE, ("saved", error_name), line)
        end = len(code.instrs)
        code.instrs[normal_exit].arg = end
        code.handlers.append(
            isa.Handler(
                start=body_start,
                end=after_else,
                target=catch_target,
                kinds=None,
                bind=None,
                error_name=error_name,
            )
        )

    def compile_expression(self, node: ast.AST, code: isa.CodeUnit) -> None:
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Constant):
            self.emit(code, isa.LOAD_CONST, node.value, line)
            return
        if isinstance(node, ast.Name):
            op = (
                isa.LOAD_DEREF
                if node.id in code.cell_names or node.id in code.free_names
                else isa.LOAD_NAME
            )
            self.emit(code, op, node.id, line)
            return
        if isinstance(node, ast.List):
            for element in node.elts:
                self.compile_expression(element, code)
            self.emit(code, isa.BUILD_LIST, len(node.elts), line)
            return
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                self.compile_expression(key, code)
                self.compile_expression(value, code)
            self.emit(code, isa.BUILD_DICT, len(node.keys), line)
            return
        if isinstance(node, ast.BinOp):
            self.compile_expression(node.left, code)
            self.compile_expression(node.right, code)
            self.emit(code, isa.BINARY_OP, _BINARY_OPS[type(node.op)], line)
            return
        if isinstance(node, ast.UnaryOp):
            self.compile_expression(node.operand, code)
            self.emit(code, isa.UNARY_OP, _UNARY_OPS[type(node.op)], line)
            return
        if isinstance(node, ast.BoolOp):
            keep_op = (
                isa.JUMP_IF_FALSE_KEEP
                if isinstance(node.op, ast.And)
                else isa.JUMP_IF_TRUE_KEEP
            )
            self.compile_expression(node.values[0], code)
            jumps: list[int] = []
            for value in node.values[1:]:
                jumps.append(self.emit(code, keep_op, None, line))
                self.compile_expression(value, code)
            end = len(code.instrs)
            for index in jumps:
                code.instrs[index].arg = end
            return
        if isinstance(node, ast.Compare):
            self.compile_expression(node.left, code)
            self.compile_expression(node.comparators[0], code)
            self.emit(code, isa.COMPARE_OP, _COMPARE_OPS[type(node.ops[0])], line)
            return
        if isinstance(node, ast.IfExp):
            self.compile_expression(node.test, code)
            jump_false = self.emit(code, isa.JUMP_IF_FALSE, None, line)
            self.compile_expression(node.body, code)
            jump_end = self.emit(code, isa.JUMP, None, line)
            code.instrs[jump_false].arg = len(code.instrs)
            self.compile_expression(node.orelse, code)
            code.instrs[jump_end].arg = len(code.instrs)
            return
        if isinstance(node, ast.Subscript):
            self.compile_expression(node.value, code)
            self.compile_expression(node.slice, code)
            self.emit(code, isa.LOAD_INDEX, None, line)
            return
        if isinstance(node, ast.Attribute):
            self.compile_expression(node.value, code)
            self.emit(
                code,
                isa.LOAD_ATTR,
                (node.attr, self._attr_hint(node.value)),
                line,
            )
            return
        if isinstance(node, ast.Call):
            self.compile_expression(node.func, code)
            for argument in node.args:
                self.compile_expression(argument, code)
            if node.keywords:
                for keyword in node.keywords:
                    self.compile_expression(keyword.value, code)
                self.emit(
                    code,
                    isa.CALL_KW,
                    (len(node.args), tuple(kw.arg for kw in node.keywords)),
                    line,
                )
            else:
                self.emit(code, isa.CALL, len(node.args), line)
            return
        raise SericiteError(
            f"unsupported expression: {type(node).__name__}",
            kind="validation_error",
            filename=self._filename,
            line=line,
        )

    def _outside_loop(self, node: ast.stmt) -> None:
        raise SericiteError(
            f"{type(node).__name__.lower()} outside loop",
            kind="validation_error",
            filename=self._filename,
            line=node.lineno,
        )
