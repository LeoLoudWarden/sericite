from __future__ import annotations

import ast

from .. import isa
from ..errors import SericiteError


class _Scope:
    def __init__(
        self, node: ast.AST, code: isa.CodeUnit, parent: _Scope | None
    ) -> None:
        self.node = node
        self.code = code
        self.parent = parent
        self.children: list[_Scope] = []
        self.params: set[str] = set()
        self.bound: dict[str, None] = {}
        self.assigned: dict[str, None] = {}
        self.loaded: dict[str, None] = {}
        self.cells: dict[str, None] = {}
        self.free: dict[str, None] = {}
        self.globals: dict[str, ast.Global] = {}
        self.nonlocals: dict[str, ast.Nonlocal] = {}

    def capture(self, name: str) -> bool:
        if name in self.globals or self.parent is None:
            return False
        if name in self.nonlocals:
            if self.parent.capture(name):
                self.free[name] = None
                return True
            return False
        if name in self.bound:
            self.cells[name] = None
            return True
        if self.parent.capture(name):
            self.free[name] = None
            return True
        return False


class _ScopeCollector(ast.NodeVisitor):
    def __init__(self, scope: _Scope, filename: str) -> None:
        self.scope = scope
        self.filename = filename

    def _error(self, node: ast.AST, message: str) -> None:
        raise SericiteError(
            message,
            kind="syntax_error",
            filename=self.filename,
            line=getattr(node, "lineno", None),
            column=(node.col_offset + 1 if hasattr(node, "col_offset") else None),
        )

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.scope.bound[node.id] = None
            self.scope.assigned[node.id] = None
        else:
            self.scope.loaded[node.id] = None

    def _declare(
        self,
        node: ast.Global | ast.Nonlocal,
        declared: dict[str, ast.Global] | dict[str, ast.Nonlocal],
        other: dict[str, ast.Global] | dict[str, ast.Nonlocal],
        kind: str,
        other_kind: str,
    ) -> None:
        for name in node.names:
            if name in other:
                self._error(node, f"name '{name}' is {other_kind} and {kind}")
            if name in self.scope.params:
                self._error(node, f"name '{name}' is parameter and {kind}")
            if name in self.scope.assigned:
                self._error(
                    node, f"name '{name}' is assigned to before {kind} declaration"
                )
            if name in self.scope.loaded:
                self._error(node, f"name '{name}' is used prior to {kind} declaration")
            declared[name] = node

    def visit_Global(self, node: ast.Global) -> None:
        self._declare(
            node, self.scope.globals, self.scope.nonlocals, "global", "nonlocal"
        )

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self._declare(
            node, self.scope.nonlocals, self.scope.globals, "nonlocal", "global"
        )

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            if node.target.id in self.scope.globals:
                self._error(
                    node.target, f"annotated name '{node.target.id}' can't be global"
                )
            if node.target.id in self.scope.nonlocals:
                self._error(
                    node.target, f"annotated name '{node.target.id}' can't be nonlocal"
                )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.bound[node.name] = None
        self.scope.assigned[node.name] = None
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in node.args.defaults:
            self.visit(default)
        for argument in (
            *node.args.args,
            node.args.vararg,
            node.args.kwarg,
        ):
            if argument is not None and argument.annotation is not None:
                self.visit(argument.annotation)
        if node.returns is not None:
            self.visit(node.returns)
        params = [argument.arg for argument in node.args.args]
        vararg = node.args.vararg.arg if node.args.vararg is not None else None
        kwarg = node.args.kwarg.arg if node.args.kwarg is not None else None
        child = _Scope(
            node,
            isa.CodeUnit(
                name=node.name,
                params=params,
                vararg=vararg,
                kwarg=kwarg,
            ),
            self.scope,
        )
        self.scope.children.append(child)
        collector = _ScopeCollector(child, self.filename)
        for param in [*params, vararg, kwarg]:
            if param is not None:
                child.params.add(param)
                child.bound[param] = None
        for statement in node.body:
            collector.visit(statement)

    def _visit_comprehension(
        self, node: ast.ListComp | ast.DictComp, name: str
    ) -> None:
        generators = node.generators
        self.visit(generators[0].iter)
        input_name = "$comp_input"
        child = _Scope(
            node,
            isa.CodeUnit(name=name, params=[input_name]),
            self.scope,
        )
        self.scope.children.append(child)
        child.bound[input_name] = None
        collector = _ScopeCollector(child, self.filename)
        for index, generator in enumerate(generators):
            collector.visit(generator.target)
            if index > 0:
                collector.visit(generator.iter)
            for condition in generator.ifs:
                collector.visit(condition)
        if isinstance(node, ast.ListComp):
            collector.visit(node.elt)
        else:
            collector.visit(node.key)
            collector.visit(node.value)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node, "<listcomp>")

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node, "<dictcomp>")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            self.scope.bound[name] = None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.scope.bound[alias.asname or alias.name] = None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # The class name binds in the current scope; field names are not scope names —
        # only field contract annotations are evaluated at definition (and may reference outer names).
        self.scope.bound[node.name] = None
        self.scope.assigned[node.name] = None
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign):
                self.visit(statement.annotation)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.scope.bound[node.name] = None
            self.scope.assigned[node.name] = None
        for statement in node.body:
            self.visit(statement)


def _analyze_scopes(tree: ast.Module, code: isa.CodeUnit) -> dict[int, _Scope]:
    root = _Scope(tree, code, None)
    _ScopeCollector(root, code.filename).visit(tree)
    scopes = [root]
    while scopes:
        scope = scopes.pop()
        for name, declaration in scope.nonlocals.items():
            if scope.parent is None:
                raise SericiteError(
                    "nonlocal declaration not allowed at module level",
                    kind="syntax_error",
                    filename=root.code.filename,
                    line=declaration.lineno,
                    column=declaration.col_offset + 1,
                )
            if not scope.parent.capture(name):
                raise SericiteError(
                    f"no binding for nonlocal '{name}' found",
                    kind="syntax_error",
                    filename=root.code.filename,
                    line=declaration.lineno,
                    column=declaration.col_offset + 1,
                )
            scope.free[name] = None
        if scope.parent is not None:
            for name in scope.loaded:
                if (
                    name not in scope.bound
                    and name not in scope.globals
                    and name not in scope.nonlocals
                    and scope.parent.capture(name)
                ):
                    scope.free[name] = None
        scopes.extend(scope.children)
    scopes = [root]
    result: dict[int, _Scope] = {}
    while scopes:
        scope = scopes.pop()
        local_names = tuple(
            name
            for name in scope.bound
            if name not in scope.globals and name not in scope.nonlocals
        )
        scope.code.local_names = local_names
        scope.code.global_names = tuple(scope.globals)
        scope.code.cell_names = tuple(
            name for name in local_names if name in scope.cells
        )
        scope.code.free_names = tuple(scope.free)
        result[id(scope.node)] = scope
        scopes.extend(scope.children)
    return result
