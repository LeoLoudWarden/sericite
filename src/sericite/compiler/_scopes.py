from __future__ import annotations

import ast

from .. import isa


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
        collector = _ScopeCollector(child)
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
