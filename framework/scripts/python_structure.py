"""Check Python structure without importing Framework or third-party packages."""

import argparse
import ast
from pathlib import Path


class StructureVisitor(ast.NodeVisitor):
    def __init__(self):
        self.functions = 0
        self.violations = []

    def visit_FunctionDef(self, node):
        if self.functions:
            self.violations.append((node.lineno, "nested-function"))
        self.functions += 1
        self.generic_visit(node)
        self.functions -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Import(self, node):
        if self.functions:
            self.violations.append((node.lineno, "function-import"))

    visit_ImportFrom = visit_Import


def violations(source):
    visitor = StructureVisitor()
    visitor.visit(ast.parse(source))
    return sorted(visitor.violations)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root", nargs="?", type=Path, default=Path(__file__).resolve().parent
    )
    args = parser.parse_args(argv)
    failed = False
    for path in sorted(args.root.rglob("*.py")):
        try:
            found = violations(path.read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError) as error:
            print(f"{path}:{getattr(error, 'lineno', 1)}: parse-error: {error}")
            failed = True
            continue
        for line, kind in found:
            print(f"{path}:{line}: {kind}")
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
