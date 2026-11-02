"""Static Model consumer boundary checks; no Framework imports or execution."""

import ast
import re
from pathlib import Path

STRUCTURAL = {
    "model.core.entries",
    "model.core.structural_entries",
    "model.core.resource_row_index",
    "model.files.resource_row_index",
    "model.display.entries",
    "model.adapters.aws.entries",
    "model.configuration.ConfigurationIndex",
}
STATE = {
    "authoritative",
    "values",
    "documents",
    "files",
    "dependencies",
    "locations",
    "parts",
    "warnings",
    "provenance",
}
WRITES = {
    "update",
    "clear",
    "pop",
    "popitem",
    "setdefault",
    "append",
    "extend",
    "insert",
    "remove",
    "__setitem__",
    "__delitem__",
}
LOADERS = {
    "load_model",
    "raw_model",
    "read_model",
    "edit_base",
    "read_source_in_session",
    "load_model_in_session",
    "rebase_snapshot",
    "reference_snapshot",
    "update_observed_snapshot",
    "copy_snapshot_warnings",
}
PREFIXES = tuple(
    f"{ns}.{kind}."
    for ns in ("desired", "display", "observed")
    for kind in ("resource", "row", "reference", "stack", "artifact")
)


def model_symbol(symbol):
    return symbol == "model" or symbol.startswith("model.")


class BoundaryVisitor(ast.NodeVisitor):
    def __init__(self):
        self.names = {}
        self.kinds = {}
        self.found = set()

    def reject(self, node, rule):
        self.found.add((node.lineno, rule))

    def symbol(self, node):
        if isinstance(node, ast.Name):
            return self.names.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return self.symbol(node.value) + "." + node.attr
        if (
            isinstance(node, ast.Call)
            and node.args
            and self.symbol(node.func) in {"importlib.import_module", "__import__"}
        ):
            value = node.args[0]
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and model_symbol(value.value)
            ):
                return value.value
        if isinstance(node, ast.Call) and len(node.args) >= 2:
            first, second = node.args[:2]
            if (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and first.value.startswith("model/")
                and isinstance(second, ast.Constant)
                and isinstance(second.value, str)
            ):
                return second.value
        return ""

    def kind(self, node):
        saved = self.kinds.get(ast.unparse(node))
        if saved:
            return saved
        if isinstance(node, ast.Name) and node.id == "snapshot":
            return "snapshot"
        if isinstance(node, ast.Attribute):
            parent = self.kind(node.value)
            if node.attr == "snapshot":
                return "snapshot"
            if parent == "snapshot" and node.attr in STATE:
                return "state"
            if parent == "view" and node.attr.startswith("_"):
                return "state"
            if parent == "state":
                return "state"
        if isinstance(node, ast.Subscript) and self.kind(node.value) == "state":
            return "state"
        if isinstance(node, ast.Call):
            name = self.symbol(node.func)
            if model_symbol(name):
                if name.endswith(".ModelView"):
                    return "view"
                if name.rsplit(".", 1)[-1] in LOADERS | {"ModelSnapshot"}:
                    return "snapshot"
        return None

    def check_symbol(self, node, symbol):
        if symbol == "model.publish_transaction":
            self.reject(node, "model-unrestricted-write")
        if model_symbol(symbol) and any(
            p.startswith("_") for p in symbol.split(".")[1:]
        ):
            self.reject(node, "model-private-api")
        if symbol in STRUCTURAL:
            self.reject(node, "model-structural-api")

    def visit_Import(self, node):
        for alias in node.names:
            self.names[alias.asname or alias.name.split(".")[0]] = (
                alias.name if alias.asname else alias.name.split(".")[0]
            )
            self.check_symbol(node, alias.name)

    def visit_ImportFrom(self, node):
        module = node.module or ""
        for alias in node.names:
            name = module + "." + alias.name
            self.names[alias.asname or alias.name] = name
            self.check_symbol(node, name)
            if model_symbol(module) and alias.name == "*":
                self.reject(node, "model-wildcard-import")

    def visit_Attribute(self, node):
        self.check_symbol(node, self.symbol(node))
        kind = self.kind(node.value)
        if (
            kind == "snapshot"
            and node.attr in {"_replace", "__dict__"}
            or kind == "view"
            and node.attr.startswith("_")
        ):
            self.reject(node, "model-private-state")
        self.generic_visit(node)

    def visit_Assign(self, node):
        self.visit(node.value)
        for target in node.targets:
            self.write(target)
            self.kinds[ast.unparse(target)] = self.kind(node.value)
            if isinstance(target, ast.Name):
                self.names[target.id] = self.symbol(node.value) or target.id
            self.visit(target)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.visit(node.value)
        self.write(node.target)
        self.kinds[ast.unparse(node.target)] = (
            self.kind(node.value) if node.value else None
        )
        if isinstance(node.target, ast.Name) and node.value is not None:
            self.names[node.target.id] = self.symbol(node.value) or node.target.id
        self.visit(node.target)

    def write(self, node):
        if isinstance(node, (ast.Tuple, ast.List)):
            for child in node.elts:
                self.write(child)
        elif (
            isinstance(node, ast.Subscript)
            and self.kind(node.value) == "state"
            or isinstance(node, ast.Attribute)
            and self.kind(node.value) in {"snapshot", "state", "view"}
        ):
            self.reject(node, "model-state-write")

    def visit_AugAssign(self, node):
        self.write(node.target)
        if self.kind(node.target) == "state":
            self.reject(node, "model-state-write")
        self.generic_visit(node)

    def visit_Delete(self, node):
        for target in node.targets:
            self.write(target)
        self.generic_visit(node)

    def visit_Call(self, node):
        name = self.symbol(node.func)
        if (
            name in {"setattr", "delattr", "getattr"}
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            target, field = node.args[0], node.args[1].value
            self.check_symbol(node, self.symbol(target) + "." + field)
            if self.kind(target) in {"snapshot", "view"}:
                if name != "getattr":
                    self.reject(node, "model-state-write")
                elif (
                    field in {"_replace", "__dict__"}
                    or self.kind(target) == "view"
                    and field.startswith("_")
                ):
                    self.reject(node, "model-private-state")
        if (
            name in {"re.compile", "re.match", "re.fullmatch", "re.search"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            pattern = node.args[0].value
            if re.compile(pattern).groups and any(
                prefix in pattern
                for prefix in (
                    r"desired\.row\.",
                    r"observed\.row\.",
                    r"desired\.resource\.",
                    r"desired\.reference\.",
                )
            ):
                self.reject(node, "model-key-grammar")
        if model_symbol(name) and name.endswith(".ModelSnapshot"):
            self.reject(node, "model-snapshot-construction")
        if (
            name in {"dataclasses.replace", "copy.replace"}
            and node.args
            and self.kind(node.args[0]) == "snapshot"
        ):
            self.reject(node, "model-snapshot-construction")
        if isinstance(node.func, ast.Attribute):
            method, receiver = node.func.attr, node.func.value
            if method in WRITES and self.kind(receiver) == "state":
                self.reject(node, "model-state-write")
            if (
                method in {"startswith", "removeprefix"}
                and node.args
                and (
                    ast.unparse(receiver) in {"key", "model_key"}
                    or "consumer" in ast.unparse(receiver).lower()
                )
            ):
                arg = node.args[0]
                strings = (
                    [arg]
                    if isinstance(arg, ast.Constant)
                    else arg.elts
                    if isinstance(arg, (ast.Tuple, ast.List))
                    else []
                )
                if any(
                    isinstance(s, ast.Constant)
                    and isinstance(s.value, str)
                    and s.value.startswith(PREFIXES)
                    for s in strings
                ):
                    self.reject(node, "model-key-grammar")
            if (
                method in {"rpartition", "rsplit", "split"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "-"
            ):
                expression = ast.unparse(receiver).lower()
                if (
                    expression in {"row", "row_id", "rid"}
                    or expression.endswith(".row_id")
                    or "consumerkey" in expression
                    or "consumer_key" in expression
                    or ".split('.')" in expression
                ):
                    self.reject(node, "model-row-owner")
            if (
                method == "split"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "."
            ):
                expression = ast.unparse(receiver).lower()
                if (
                    expression in {"key", "model_key"}
                    or "consumerkey" in expression
                    or "consumer_key" in expression
                ):
                    self.reject(node, "model-key-grammar")
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        names, kinds = self.names.copy(), self.kinds.copy()
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            self.names.pop(arg.arg, None)
            self.kinds.pop(arg.arg, None)
            if arg.annotation and self.symbol(arg.annotation).endswith(
                ".ModelSnapshot"
            ):
                self.kinds[arg.arg] = "snapshot"
        for child in node.body:
            self.visit(child)
        self.names, self.kinds = names, kinds

    visit_AsyncFunctionDef = visit_FunctionDef


def violations(source, path="consumer.py"):
    parts = Path(path).parts
    if parts and parts[0] in {"model", "tests"} or parts == ("contracts", "model.py"):
        return []
    visitor = BoundaryVisitor()
    visitor.visit(ast.parse(source, filename=str(path)))
    return sorted(visitor.found)


def check_sources(root):
    found = []
    for path in sorted(Path(root).rglob("*.py")):
        relative = path.relative_to(root)
        for line, rule in violations(path.read_text(encoding="utf-8-sig"), relative):
            found.append(f"{relative.as_posix()}:{line}: {rule}")
    if found:
        raise AssertionError("\n".join(found))
