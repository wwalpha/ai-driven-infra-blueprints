"""Side-effect-free IT entry discovery; Python sources are the only inventory."""

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Discovery:
    cases: dict
    owners: dict
    suites: tuple
    errors: list


def dotted(node):
    return ast.unparse(node) if isinstance(node, (ast.Name, ast.Attribute)) else ""


def pytest_entry(tests, symbol, trees, seen=None):
    """Resolve fixture re-exports without importing fixtures or running their setup."""
    seen = set() if seen is None else seen
    if symbol in seen:
        return False
    if symbol in {"support.pytest_cli.run", "pytest.main"}:
        return True
    seen.add(symbol)
    module, _, name = symbol.rpartition(".")
    path = tests / (module.replace(".", "/") + ".py")
    if not module.startswith("support.") or not path.is_file():
        return False
    if path not in trees:
        trees[path] = ast.parse(path.read_text(encoding="utf-8"))
    tree = trees[path]
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    return pytest_entry(
                        tests, (node.module or "") + "." + alias.name, trees, seen
                    )
        elif isinstance(node, ast.FunctionDef) and node.name == name:
            imports = {
                a.asname or a.name: (n.module or "") + "." + a.name
                for n in tree.body
                if isinstance(n, ast.ImportFrom)
                for a in n.names
            }
            return any(
                isinstance(call, ast.Call)
                and pytest_entry(
                    tests,
                    imports.get(dotted(call.func), dotted(call.func)),
                    trees,
                    seen,
                )
                for call in ast.walk(node)
            )
    return False


def discover(tests):
    tests = Path(tests)
    cases, owners, modules, errors = {}, {}, {}, []
    trees = {}
    paths = sorted((tests / "integrations").rglob("*.py"))
    suites = tuple(
        p.relative_to(tests).as_posix() for p in paths if p.name.endswith(".checks.py")
    )
    if not suites:
        errors.append("No integration suites discovered")
    for path in paths:
        relative = path.relative_to(tests).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as error:
            errors.append(f"cannot discover {relative}: {error}")
            continue
        functions, aliases, imports = {}, {}, {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imports[alias.asname or alias.name] = (
                        (node.module or "") + "." + alias.name
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports[alias.asname or alias.name] = alias.name
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.endswith(".checks")
            ):
                errors.append(f"IT module dependency: {relative}: {node.value}")
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                errors.append(f"unsupported class IT entry: {relative}::{node.name}")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in functions:
                    errors.append(f"duplicate IT definition: {relative}::{node.name}")
                functions[node.name] = node
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if target.id in aliases or target.id in functions:
                            errors.append(
                                f"duplicate IT alias: {relative}::{target.id}"
                            )
                        aliases[target.id] = node.value.id
        pytest_runner = any(
            isinstance(node, ast.Call)
            and (
                pytest_entry(
                    tests, imports.get(dotted(node.func), dotted(node.func)), trees
                )
                or dotted(node.func) == "pytest.main"
            )
            for node in ast.walk(tree)
        )
        for name, node in functions.items():
            decorators = [
                dotted(d.func if isinstance(d, ast.Call) else d)
                for d in node.decorator_list
            ]
            marked = any(
                imports.get(d) == "support.it_case_receipt.it_case" or d == "it_case"
                for d in decorators
            )
            if marked:
                if (
                    not decorators
                    or decorators[0] != "it_case"
                    or not isinstance(node.decorator_list[0], ast.Name)
                    or imports.get("it_case") != "support.it_case_receipt.it_case"
                    or isinstance(node, ast.AsyncFunctionDef)
                ):
                    errors.append(
                        f"missing outer completion decorator: {relative}::{name}"
                    )
                cases[relative, name] = "direct"
            elif (
                name.startswith("check_") or pytest_runner and name.startswith("test_")
            ):
                if not pytest_runner:
                    errors.append(
                        f"missing outer completion decorator / unknown execution: {relative}::{name}"
                    )
                cases[relative, name] = "pytest"
        for name, target in aliases.items():
            if name.startswith(("check_", "test_")):
                if (
                    not pytest_runner
                    or target not in functions
                    or (relative, target) in cases
                ):
                    errors.append(f"ambiguous IT alias: {relative}::{name}")
                cases[relative, name] = "pytest"
        markers = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and dotted(node.func) == "module_complete"
        ]
        if markers or "support.it_case_receipt.module_complete" in imports.values():
            expected = ast.parse("module_complete(__file__)").body[0]
            if (
                len(markers) != 1
                or imports.get("module_complete")
                != "support.it_case_receipt.module_complete"
                or not tree.body
                or ast.dump(tree.body[-1]) != ast.dump(expected)
            ):
                errors.append(
                    f"missing terminal module completion: {relative}::__module__"
                )
            cases[relative, "__module__"] = "module"
        modules[relative] = (tree, functions, aliases, imports)
        if relative in suites and not any(file == relative for file, _ in cases):
            errors.append(f"empty IT suite: {relative}")
    if not cases:
        errors.append("empty IT discovery")
    # Follow function references as well as calls: parametrized callbacks are passed by name.
    # Runtime receipts prove actual execution; static reachability alone never proves a PASS.
    module_names = {
        path.removesuffix(".py").replace("/", "."): path for path in modules
    }
    reachable = set()
    for suite in suites:
        pending = [
            (suite, "__module__"),
            *(
                (suite, name)
                for (file, name), mode in cases.items()
                if file == suite and mode == "pytest"
            ),
        ]
        reached = set()
        while pending:
            key = pending.pop()
            if key in reached or key[0] not in modules:
                continue
            reached.add(key)
            file, name = key
            tree, functions, aliases, imports = modules[file]
            if key in cases:
                owners.setdefault(key, set()).add(suite)
            name = aliases.get(name, name)
            if name == "__module__":
                nodes = [
                    n
                    for n in tree.body
                    if not isinstance(
                        n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                    )
                ]
            elif name in functions:
                nodes = [functions[name]]
            else:
                continue
            for root in nodes:
                for node in ast.walk(root):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        names = (
                            [a.name for a in node.names]
                            if isinstance(node, ast.Import)
                            else [
                                node.module or "",
                                *(
                                    (node.module or "") + "." + a.name
                                    for a in node.names
                                ),
                            ]
                        )
                        pending.extend(
                            (module_names[value], "__module__")
                            for value in names
                            if value in module_names
                        )
                    value = dotted(node)
                    if not value:
                        continue
                    target = aliases.get(value, value)
                    if target in functions:
                        pending.append((file, target))
                    first, _, rest = value.partition(".")
                    resolved = imports.get(first, "") + ("." + rest if rest else "")
                    module, _, function = resolved.rpartition(".")
                    if module in module_names:
                        pending.append((module_names[module], function))
        reachable.update(reached)
    for file, (_tree, functions, _aliases, _imports) in modules.items():
        for name in functions:
            if (
                name.startswith("test_")
                and (file, name) not in cases
                and (file, name) not in reachable
            ):
                errors.append(f"unknown test helper responsibility: {file}::{name}")
    for key, mode in cases.items():
        if key not in owners:
            errors.append(f"orphan IT entry: {'::'.join(key)} ({mode})")
    return Discovery(cases, owners, suites, errors)
