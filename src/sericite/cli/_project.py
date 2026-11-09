from __future__ import annotations

import ast
from pathlib import Path


def _module_package(path: str) -> str:
    parts = path.strip("/").split("/")
    if parts[-1] == "__init__.sericite":
        return ".".join(parts[:-1])
    module = ".".join([*parts[:-1], Path(parts[-1]).stem])
    return module.rpartition(".")[0]


class _ProjectLoader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.files: dict[str, str] = {}
        self.scanned: set[str] = set()
        self.queued: set[str] = set()
        self.pending: list[str] = []

    def host_path(self, virtual_path: str) -> Path | None:
        path = self.root.joinpath(*virtual_path.strip("/").split("/")).resolve()
        try:
            path.relative_to(self.root)
        except ValueError:
            return None
        return path

    def load_file(self, virtual_path: str) -> None:
        if virtual_path in self.scanned or virtual_path in self.queued:
            return
        self.queued.add(virtual_path)
        self.pending.append(virtual_path)

    def process(self) -> None:
        while self.pending:
            virtual_path = self.pending.pop()
            self.queued.remove(virtual_path)
            if virtual_path in self.scanned:
                continue
            self.scanned.add(virtual_path)
            host = self.host_path(virtual_path)
            if host is None:
                continue
            try:
                text = host.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                continue
            self.files[virtual_path] = text
            self.scan(text, virtual_path)

    def load_module(self, name: str) -> None:
        if not name:
            return
        stem = name.replace(".", "/")
        self.load_file(f"/{stem}.sericite")
        self.load_file(f"/{stem}/__init__.sericite")

    def load_module_chain(self, name: str) -> None:
        parts = name.split(".") if name else []
        for index in range(len(parts)):
            self.load_module(".".join(parts[: index + 1]))

    def resolve_from(self, module: str | None, level: int, package: str) -> str | None:
        if level == 0:
            return module
        base = package
        if not base:
            return None
        for _ in range(level - 1):
            base = base.rpartition(".")[0]
            if not base:
                return None
        return f"{base}.{module}" if module else base

    def scan(self, source: str, path: str) -> None:
        try:
            tree = ast.parse(source, filename=path)
        except (SyntaxError, RecursionError, MemoryError):
            return
        package = _module_package(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.load_module_chain(alias.name)
            elif isinstance(node, ast.ImportFrom):
                name = self.resolve_from(node.module, node.level, package)
                if not name:
                    continue
                self.load_module_chain(name)
                for alias in node.names:
                    if alias.name != "*":
                        self.load_module_chain(f"{name}.{alias.name}")


def _load_project(source_name: str, source_text: str) -> dict[str, str]:
    entry = Path(source_name).resolve()
    loader = _ProjectLoader(entry.parent)
    path = f"/{entry.name}"
    loader.files[path] = source_text
    loader.scanned.add(path)
    loader.scan(source_text, path)
    loader.process()
    return loader.files
