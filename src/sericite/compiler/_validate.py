from __future__ import annotations

import ast

from ..errors import CATCHABLE_ERROR_KINDS, UNCATCHABLE_ERROR_KINDS, SericiteError
from ._rules import _ALLOWED_NODES, _CONTRACT_ONLY_NAMES, RESERVED_NAMES

_UNSUPPORTED_MESSAGES = {
    ast.Pow: "`**` is not supported",
    ast.MatMult: "`@` is not supported",
    ast.LShift: "`<<` is not supported",
    ast.RShift: "`>>` is not supported",
    ast.BitAnd: "`&` is not supported",
    ast.BitOr: "`|` is not supported",
    ast.BitXor: "`^` is not supported",
    ast.Invert: "`~` is not supported",
    ast.UAdd: "unary `+` is not supported",
    ast.Is: "`is` is not supported",
    ast.IsNot: "`is not` is not supported",
    ast.ListComp: "comprehensions are not supported",
    ast.SetComp: "comprehensions are not supported",
    ast.DictComp: "comprehensions are not supported",
    ast.GeneratorExp: "comprehensions are not supported",
    ast.With: "`with` statements are not supported",
    ast.AsyncWith: "`with` statements are not supported",
    ast.Lambda: "lambda expressions are not supported",
    ast.Assert: "`assert` statements are not supported",
    ast.Match: "`match` statements are not supported",
    ast.AsyncFunctionDef: "async functions are not supported",
    ast.Await: "`await` expressions are not supported",
    ast.Yield: "`yield` expressions are not supported",
    ast.YieldFrom: "`yield` expressions are not supported",
    ast.Import: "`import` statements are not supported",
    ast.ImportFrom: "`import` statements are not supported",
    ast.Delete: "`del` statements are not supported",
}


def _reject_unsupported(
    node: ast.AST, parents: dict[ast.AST, ast.AST], filename: str
) -> None:
    location = node if hasattr(node, "lineno") else parents.get(node, node)
    message = _UNSUPPORTED_MESSAGES.get(type(node), "this syntax is not supported")
    _reject(location, filename, message)


def _is_annotation_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Whether the name *is* the annotation expression itself. Reserved names hidden inside sub-expressions are rejected."""
    parent = parents.get(node)
    if isinstance(parent, ast.arg) and parent.annotation is node:
        return True
    if isinstance(parent, ast.AnnAssign) and parent.annotation is node:
        return True
    return isinstance(parent, ast.FunctionDef) and parent.returns is node


def _reject_none_annotation(annotation: ast.expr | None, filename: str) -> None:
    if isinstance(annotation, ast.Constant) and annotation.value is None:
        _reject(annotation, filename, "None is not a contract; omit the annotation")


def _validate(tree: ast.Module, filename: str) -> None:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODES:
            _reject_unsupported(node, parents, filename)
        if (
            isinstance(node, ast.Constant)
            and type(node.value)
            not in {
                str,
                int,
                float,
                bool,
                type(None),
            }
            and not (
                node.value is Ellipsis
                and isinstance(parents.get(node), ast.ExceptHandler)
                and parents[node].type is node
            )
        ):
            _reject(node, filename, "unsupported constant")
        if isinstance(node, ast.FormattedValue):
            if node.conversion not in (-1, 97, 114, 115):
                _reject(node, filename, "unsupported f-string conversion")
            if node.format_spec is not None:
                _reject(node, filename, "f-string format specs are not supported yet")
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
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Store)
            and isinstance(node.slice, ast.Slice)
        ):
            _reject(node, filename, "slice assignment is not supported")
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
            _reject_none_annotation(node.annotation, filename)
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
        if isinstance(node, ast.Call):
            seen_keywords: set[str] = set()
            for keyword in node.keywords:
                if keyword.arg is None:
                    continue
                if keyword.arg in seen_keywords:
                    _reject(
                        keyword,
                        filename,
                        f"duplicate keyword argument '{keyword.arg}'",
                    )
                seen_keywords.add(keyword.arg)
        if isinstance(node, ast.keyword) and node.arg is None:
            _reject(node, filename, "** arguments are not supported")
        if isinstance(node, ast.Dict) and any(key is None for key in node.keys):
            _reject(node, filename, "** unpacking is not supported")
        if isinstance(node, ast.Tuple):
            parent = parents.get(node)
            if not isinstance(parent, ast.ExceptHandler) or parent.type is not node:
                _reject(node, filename, "tuples are not supported")
        if isinstance(node, ast.ExceptHandler) and node.type is not None:
            filter_node = node.type
            if isinstance(filter_node, ast.Constant) and filter_node.value is Ellipsis:
                kind_nodes = []
            elif isinstance(filter_node, ast.Name):
                kind_nodes = [filter_node]
            elif isinstance(filter_node, ast.Tuple):
                if not filter_node.elts:
                    _reject(filter_node, filename, "except kind group cannot be empty")
                if any(
                    not isinstance(element, ast.Name) for element in filter_node.elts
                ):
                    _reject(
                        filter_node,
                        filename,
                        "except kind group must contain only error kind names",
                    )
                kind_nodes = filter_node.elts
            else:
                _reject(
                    filter_node,
                    filename,
                    "except clause must name error kinds or use '...'",
                )
            for kind_node in kind_nodes:
                if kind_node.id in UNCATCHABLE_ERROR_KINDS:
                    _reject(
                        kind_node,
                        filename,
                        f"error kind '{kind_node.id}' is not catchable; "
                        "it cannot be caught even by a bare 'except:'",
                    )
                if kind_node.id not in CATCHABLE_ERROR_KINDS:
                    _reject(
                        kind_node,
                        filename,
                        f"unknown error kind: '{kind_node.id}'; "
                        "use 'except <kind> as name' to filter and bind an error record, "
                        "or bare 'except:' to catch all catchable errors",
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
            _reject_none_annotation(node.returns, filename)
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
            seen_params: set[str] = set()
            for argument in args.args:
                _reject_none_annotation(argument.annotation, filename)
                if argument.arg in seen_params:
                    _reject(
                        argument,
                        filename,
                        f"duplicate parameter '{argument.arg}'",
                    )
                seen_params.add(argument.arg)
        if isinstance(node, ast.For) and not isinstance(node.target, ast.Name):
            _reject(node, filename, "for target must be a name")
        if isinstance(node, ast.Raise) and node.cause is not None:
            _reject(node, filename, "raise ... from ... is not supported")
        if isinstance(node, ast.Compare) and len(node.ops) != 1:
            _reject(node, filename, "chained comparisons are not supported")
        if isinstance(node, ast.AugAssign) and not isinstance(
            node.target, (ast.Name, ast.Subscript, ast.Attribute)
        ):
            _reject(node, filename, "unsupported augmented assignment target")
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
        kind="syntax_error",
        filename=filename,
        line=getattr(node, "lineno", None),
        column=(node.col_offset + 1 if hasattr(node, "col_offset") else None),
    )
