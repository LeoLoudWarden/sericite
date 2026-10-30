from __future__ import annotations

import ast

from .. import isa
from ..errors import SericiteError
from ._rules import _BINARY_OPS, _COMPARE_OPS, _UNARY_OPS
from ._scopes import _Scope
from ._stack import _analyze_stack


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
        self._finally_stack: list[tuple[list[ast.stmt], list[tuple[int, int]]]] = []
        self._function_depth = 0
        self._tmp_counter = 0
        # Compile-time diagnostic labels, pushed/popped with the function scope.
        self._label_stack: list[dict[str, isa._DiagnosticLabel]] = [{}]

    def _set_labels(self, labels: dict[str, isa._DiagnosticLabel]) -> None:
        self._label_stack[-1] = labels

    @staticmethod
    def _without_labels(
        labels: dict[str, isa._DiagnosticLabel], names: set[str]
    ) -> dict[str, isa._DiagnosticLabel]:
        return {name: label for name, label in labels.items() if name not in names}

    @staticmethod
    def _merge_labels(
        environments: list[dict[str, isa._DiagnosticLabel]],
    ) -> dict[str, isa._DiagnosticLabel]:
        first, *rest = environments
        return {
            name: label
            for name, label in first.items()
            if all(labels.get(name) == label for labels in rest)
        }

    def _propagate_label(self, name: str, value: ast.AST) -> None:
        labels = self._label_stack[-1]
        source: isa._DiagnosticLabel | None = None
        if isinstance(value, ast.Name):
            source = labels.get(value.id)
        elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            source = labels.get(value.func.id)
        if source is None:
            labels.pop(name, None)
        else:
            labels[name] = source

    def _annotation_label(self, annotation: ast.AST) -> isa._DiagnosticLabel:
        return isa._DiagnosticLabel(ast.unparse(annotation))

    def _attr_hints(self, value: ast.AST, attr: str) -> tuple[str | None, str | None]:
        if isinstance(value, ast.Name):
            label = self._label_stack[-1].get(value.id)
            if label is not None:
                return label.text, dict(label.fields).get(attr)
        return None, None

    def _store_name(self, code: isa.CodeUnit, name: str, line: int) -> None:
        op = isa.STORE_DEREF if name in code.cell_names else isa.STORE_NAME
        self.emit(code, op, name, line)

    def _compile_finally_exits(
        self,
        code: isa.CodeUnit,
        line: int,
        scopes: list[tuple[list[ast.stmt], list[tuple[int, int]]]],
    ) -> None:
        keep = len(self._finally_stack) - len(scopes)
        saved = self._finally_stack[keep:]
        try:
            for position in range(len(saved) - 1, -1, -1):
                body, exit_ranges = saved[position]
                self._finally_stack[keep:] = saved[:position]
                start = len(code.instrs)
                self.compile_body(body, code)
                exit_ranges.append((start, len(code.instrs)))
        finally:
            self._finally_stack[keep:] = saved

    def emit(
        self,
        code: isa.CodeUnit,
        op: str,
        arg: object,
        line: int,
        *,
        label: isa._DiagnosticLabel | None = None,
    ) -> int:
        code.instrs.append(isa.Instr(op=op, arg=arg, line=line, label=label))
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
                    (last.attr, *self._attr_hints(last.value, last.attr)),
                    line,
                )
            else:
                assert isinstance(last, ast.Subscript)
                self.compile_expression(last.value, code)
                self.compile_expression(last.slice, code)
                self.emit(code, isa.STORE_INDEX, None, line)
            return
        if isinstance(node, ast.AugAssign):
            target = node.target
            op = _BINARY_OPS[type(node.op)]
            if isinstance(target, ast.Name):
                load_op = (
                    isa.LOAD_DEREF
                    if target.id in code.cell_names or target.id in code.free_names
                    else isa.LOAD_NAME
                )
                self.emit(code, load_op, target.id, line)
                self.compile_expression(node.value, code)
                self.emit(code, isa.BINARY_OP, op, line)
                self._store_name(code, target.id, line)
                self._label_stack[-1].pop(target.id, None)
                return
            target_name = f"$aug_target_{self._tmp_counter}"
            self._tmp_counter += 1
            self.compile_expression(target.value, code)
            self.emit(code, isa.STORE_NAME, target_name, line)
            # Attribute reads consume the target here; subscript reads load it with
            # the index below. Keep both paths stack-neutral without a shared load.
            if isinstance(target, ast.Attribute):
                self.emit(code, isa.LOAD_NAME, target_name, line)
                attr = (target.attr, *self._attr_hints(target.value, target.attr))
                self.emit(code, isa.LOAD_ATTR, attr, line)
                self.compile_expression(node.value, code)
                self.emit(code, isa.BINARY_OP, op, line)
                self.emit(code, isa.LOAD_NAME, target_name, line)
                self.emit(code, isa.STORE_ATTR, attr, line)
                return
            assert isinstance(target, ast.Subscript)
            index_name = f"$aug_index_{self._tmp_counter}"
            self._tmp_counter += 1
            self.compile_expression(target.slice, code)
            self.emit(code, isa.STORE_NAME, index_name, line)
            self.emit(code, isa.LOAD_NAME, target_name, line)
            self.emit(code, isa.LOAD_NAME, index_name, line)
            self.emit(code, isa.LOAD_INDEX, None, line)
            self.compile_expression(node.value, code)
            self.emit(code, isa.BINARY_OP, op, line)
            self.emit(code, isa.LOAD_NAME, target_name, line)
            self.emit(code, isa.LOAD_NAME, index_name, line)
            self.emit(code, isa.STORE_INDEX, None, line)
            return
        if isinstance(node, ast.AnnAssign):
            label = self._annotation_label(node.annotation)
            self.compile_expression(node.value, code)
            self.compile_expression(node.annotation, code)
            self.emit(code, isa.CHECK_ANNOT, label.text, line)
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
                    argument.arg: self._annotation_label(argument.annotation)
                    for argument in node.args.args
                    if argument.annotation is not None
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
                    kind="syntax_error",
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
            field_labels: list[tuple[str, str | None]] = []
            for statement in node.body:
                if isinstance(statement, ast.Pass):
                    continue
                if isinstance(statement, ast.Expr):
                    name = statement.value.id  # type: ignore[union-attr]
                    label = None
                    self.emit(code, isa.LOAD_NAME, "any", statement.lineno)
                else:
                    assert isinstance(statement, ast.AnnAssign)
                    name = statement.target.id  # type: ignore[union-attr]
                    label = ast.unparse(statement.annotation)
                    self.compile_expression(statement.annotation, code)
                names.append(name)
                field_labels.append((name, label))
            self.emit(code, isa.MAKE_SCHEMA, tuple(names), line)
            self._store_name(code, node.name, line)
            self._label_stack[-1][node.name] = isa._DiagnosticLabel(
                node.name, tuple(field_labels)
            )
            return
        raise SericiteError(
            f"unsupported statement: {type(node).__name__}",
            kind="syntax_error",
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
                kind="syntax_error",
                filename=self._filename,
                line=line,
            )
        entry_labels = self._label_stack[-1].copy()
        assigned = _assigned_names([node])
        exit_labels = self._without_labels(entry_labels, assigned)
        body_assigned = _assigned_names(node.body)
        has_finally = bool(node.finalbody)
        exit_ranges: list[tuple[int, int]] = []
        if has_finally:
            self._finally_stack.append((node.finalbody, exit_ranges))
        body_start = len(code.instrs)
        self.compile_body(node.body, code)
        body_labels = self._label_stack[-1].copy()
        body_end = len(code.instrs)
        body_exit = self.emit(code, isa.JUMP, None, line)
        handler_entries: list[
            tuple[int, int, int, int, tuple[str, ...] | None, str | None]
        ] = []
        handler_exits: list[int] = []
        for handler in node.handlers:
            target = len(code.instrs)
            if handler.type is None or (
                isinstance(handler.type, ast.Constant)
                and handler.type.value is Ellipsis
            ):
                kinds = None
            elif isinstance(handler.type, ast.Name):
                kinds = (handler.type.id,)
            else:
                kinds = tuple(element.id for element in handler.type.elts)
            handler_labels = self._without_labels(entry_labels, body_assigned)
            if handler.name is not None:
                handler_labels.pop(handler.name, None)
            self._set_labels(handler_labels)
            self.compile_body(handler.body, code)
            handler_end = len(code.instrs)
            handler_entries.append(
                (body_start, body_end, target, handler_end, kinds, handler.name)
            )
            handler_exits.append(self.emit(code, isa.JUMP, None, line))
        else_label = len(code.instrs)
        code.instrs[body_exit].arg = else_label
        self._set_labels(body_labels)
        self.compile_body(node.orelse, code)
        after_else = len(code.instrs)
        for index in handler_exits:
            code.instrs[index].arg = after_else
        for start, stop, target, handler_end, kinds, bind in handler_entries:
            code.handlers.append(
                isa.Handler(
                    start=start,
                    end=stop,
                    target=target,
                    kinds=kinds,
                    bind=bind,
                    body_end=handler_end,
                    exit_ranges=tuple(exit_ranges),
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
        catch_end = len(code.instrs)
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
                body_end=catch_end,
                exit_ranges=tuple(exit_ranges),
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
        if isinstance(node, ast.JoinedStr):
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    self.compile_expression(value.value, code)
                    self.emit(code, isa.FORMAT_VALUE, None, value.lineno)
                else:
                    self.compile_expression(value, code)
            self.emit(code, isa.BUILD_STRING, len(node.values), line)
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
            if isinstance(node.slice, ast.Slice):
                for part in (node.slice.lower, node.slice.upper, node.slice.step):
                    if part is None:
                        self.emit(code, isa.LOAD_CONST, None, line)
                    else:
                        self.compile_expression(part, code)
                self.emit(code, isa.LOAD_SLICE, None, line)
            else:
                self.compile_expression(node.slice, code)
                self.emit(code, isa.LOAD_INDEX, None, line)
            return
        if isinstance(node, ast.Attribute):
            self.compile_expression(node.value, code)
            self.emit(
                code,
                isa.LOAD_ATTR,
                (node.attr, *self._attr_hints(node.value, node.attr)),
                line,
            )
            return
        if isinstance(node, ast.Call):
            label = (
                self._label_stack[-1].get(node.func.id)
                if isinstance(node.func, ast.Name)
                else None
            )
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
                    label=label,
                )
            else:
                self.emit(code, isa.CALL, len(node.args), line, label=label)
            return
        raise SericiteError(
            f"unsupported expression: {type(node).__name__}",
            kind="syntax_error",
            filename=self._filename,
            line=line,
        )

    def _outside_loop(self, node: ast.stmt) -> None:
        raise SericiteError(
            f"{type(node).__name__.lower()} outside loop",
            kind="syntax_error",
            filename=self._filename,
            line=node.lineno,
        )
