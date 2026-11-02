"""Pilot CLI diagnostics shared by pytest checks; framework dispatch stays unchanged."""

import ast
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from support.worktree_test_policy import WORKTREE_CASES


class Diagnostics:
    """Keep legacy success output while retaining pytest's failure diagnostics."""

    def pytest_runtest_logreport(self, report):
        if report.failed:
            print(report.longrepr, file=sys.stderr)

    pytest_collectreport = pytest_runtest_logreport


def shared_state_writes(tree):
    """Keep direct writes to imported/module objects out of a shared interpreter."""
    sys_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "sys"
    }
    if any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and (
            getattr(node, "module", None) in {"importlib", "builtins"}
            or any(
                alias.name.split(".")[0] in {"importlib", "builtins"}
                for alias in node.names
            )
        )
        or isinstance(node, ast.Name)
        and node.id
        in {
            "__import__",
            "__builtins__",
            "getattr",
            "vars",
            "locals",
            "globals",
            "eval",
            "exec",
            "compile",
        }
        or isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in sys_names
        and node.attr == "modules"
        for node in ast.walk(tree)
    ):
        return True
    warning_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "warnings"
        for alias in node.names
        if alias.name in {"filterwarnings", "simplefilter", "resetwarnings"}
    }
    warning_modules = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "warnings"
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = node.value
            if (
                isinstance(value, ast.Name)
                and value.id in warning_names
                or isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id in warning_modules
                and value.attr in {"filterwarnings", "simplefilter", "resetwarnings"}
            ):
                warning_names.update(
                    target.id for target in node.targets if isinstance(target, ast.Name)
                )
    if any(
        isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id in warning_names
            or isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in warning_modules
            and node.func.attr in {"filterwarnings", "simplefilter", "resetwarnings"}
        )
        for node in ast.walk(tree)
    ):
        return True
    bindings = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bindings.update(
                alias.asname or alias.name.split(".")[0] for alias in node.names
            )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            bindings.update(
                item.id
                for target in targets
                for item in ast.walk(target)
                if isinstance(item, ast.Name)
            )
    for function in (
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    ):
        local = {
            arg.arg
            for arg in (
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            )
        }
        foreign = bindings | local
        foreign.update(
            alias.asname or alias.name.split(".")[0]
            for node in ast.walk(function)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        )
        for node in ast.walk(function):
            if isinstance(node, ast.Assign):
                value = node.value
                while isinstance(value, (ast.Attribute, ast.Subscript)):
                    value = value.value
                if (
                    isinstance(value, ast.Call)
                    or isinstance(value, ast.Name)
                    and value.id in foreign
                ):
                    foreign.update(
                        target.id
                        for target in node.targets
                        if isinstance(target, ast.Name)
                    )
            if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(
                node.ctx, (ast.Store, ast.Del)
            ):
                target = node
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr
                in {
                    "append",
                    "extend",
                    "insert",
                    "update",
                    "clear",
                    "pop",
                    "popitem",
                    "setdefault",
                    "add",
                    "discard",
                    "remove",
                }
            ):
                target = node.func.value
            elif (
                isinstance(node, ast.Call)
                and ast.unparse(node.func) == "setattr"
                and node.args
            ):
                target = node.args[0]
            elif isinstance(node, ast.Call) and ast.unparse(node.func) == "globals":
                return True
            else:
                continue
            text = ast.unparse(target)
            protected = ("os.environ", "sys.path", "sys.argv")
            if text in protected or any(
                text.startswith(name + "[") for name in protected
            ):
                continue
            while isinstance(target, (ast.Attribute, ast.Subscript)):
                target = target.value
            if isinstance(target, ast.Name) and target.id in foreign:
                return True
    return False


def groupable(path):
    """Only the plain pytest_cli entry has identical import and direct semantics."""
    path = Path(path).resolve()
    tests = Path(__file__).resolve().parents[1]
    if (
        path.is_relative_to(tests)
        and path.relative_to(tests).as_posix() in WORKTREE_CASES
    ):
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"))
    permissions = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "PYTEST_GROUP_SAFE"
            for target in node.targets
        )
    ]
    if (
        len(permissions) != 1
        or len(permissions[0].targets) != 1
        or not isinstance(permissions[0].value, ast.Constant)
        or permissions[0].value.value is not True
    ):
        return False
    if any(
        isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(child, ast.Call)
            and not (
                ast.unparse(child.func) == "pytest.mark.usefixtures"
                and all(
                    isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                    for arg in child.args
                )
                and not child.keywords
            )
            for child in ast.walk(node.value)
        )
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
    ):
        return False
    if not any(
        isinstance(node, ast.FunctionDef) and node.name.startswith(("check_", "test_"))
        for node in tree.body
    ):
        return False
    if any(
        isinstance(node, ast.ClassDef)
        or isinstance(node, ast.Call)
        and ast.unparse(node.func)
        in {
            "sys.addaudithook",
            "pytest.skip",
            "pytest.xfail",
            "pytest.mark.skip",
            "pytest.mark.skipif",
            "pytest.mark.xfail",
        }
        or isinstance(node, (ast.Global, ast.Nonlocal))
        for node in ast.walk(tree)
    ):
        return False
    runners = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "support.pytest_cli"
        for alias in node.names
        if alias.name == "run"
    }
    if any(
        isinstance(node, ast.ImportFrom)
        and any(
            (alias.asname or alias.name).startswith(("check_", "test_"))
            for alias in node.names
        )
        for node in tree.body
    ):
        return False
    main = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        ),
        None,
    )
    entry = tree.body[-1] if tree.body else None
    if any(
        not isinstance(
            node,
            (
                ast.Import,
                ast.ImportFrom,
                ast.FunctionDef,
                ast.ClassDef,
                ast.Assign,
                ast.AnnAssign,
            ),
        )
        and not (
            isinstance(node, ast.If)
            and (node is entry or ast.unparse(node.test) == "not __debug__")
        )
        and not (
            isinstance(node, ast.Expr)
            and (
                isinstance(node.value, ast.Constant)
                or isinstance(node.value, ast.Call)
                and ast.unparse(node.value.func) == "sys.path.insert"
            )
        )
        for node in tree.body
    ):
        return False
    if (
        not isinstance(entry, ast.If)
        or ast.unparse(entry.test) != "__name__ == '__main__'"
        or entry.orelse
        or any(
            not isinstance(node, ast.ImportFrom) or node.module != "support.pytest_cli"
            for node in entry.body[:-1]
        )
    ):
        return False
    statement = entry.body[-1]
    if (
        not isinstance(statement, ast.Raise)
        or not isinstance(statement.exc, ast.Call)
        or ast.unparse(statement.exc.func) != "SystemExit"
        or len(statement.exc.args) != 1
    ):
        return False
    call = statement.exc.args[0]
    if (
        isinstance(call, ast.Call)
        and ast.unparse(call.func) == "main"
        and not call.args
        and not call.keywords
        and main is not None
        and len(main.body) == 1
        and isinstance(main.body[0], ast.Return)
    ):
        call = main.body[0].value
    return (
        isinstance(call, ast.Call)
        and ast.unparse(call.func) in runners
        and len(call.args) == 1
        and ast.unparse(call.args[0]) == "__file__"
        and all(keyword.arg == "message" for keyword in call.keywords)
        and not shared_state_writes(tree)
    )


def unit_commands(paths):
    """Partition the existing complete selection; no second suite registry."""
    grouped, isolated = [], []
    for path in paths:
        (grouped if groupable(path) else isolated).append(str(path))
    split = (len(grouped) + 1) // 2 if len(grouped) > 2 else len(grouped)
    return [
        [sys.executable, str(Path(__file__).resolve()), "--group", *group]
        if len(group) > 1
        else [sys.executable, *group]
        for group in (grouped[:split], grouped[split:])
        if group
    ] + [[sys.executable, path] for path in isolated]


class GroupDiagnostics(Diagnostics):
    def __init__(self, paths):
        self.expected = {}
        for path in paths:
            path = Path(path).resolve()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            self.expected[path] = {
                node.name
                for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.name.startswith(("check_", "test_"))
            }
        self.generated = Counter()
        self.collected = Counter()
        self.executed = Counter()
        self.passed = Counter()
        self.invalid = False

    def pytest_configure(self, config):
        config.blueprint_ut_group = True

    def pytest_sessionstart(self, session):
        self.collection_path = sys.path[:]

    def pytest_itemcollected(self, item):
        self.generated[item.nodeid] += 1

    def pytest_deselected(self, items):
        for item in items:
            self.invalid = True
            print(f"UT group deselected node: {item.nodeid}", file=sys.stderr)

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_finish(self, session):
        sys.path[:] = self.collection_path
        found = {path: set() for path in self.expected}
        for item in session.items:
            path = Path(item.path).resolve()
            if path not in found:
                self.invalid = True
                print(f"UT group unknown node: {item.nodeid}", file=sys.stderr)
                continue
            found[path].add(item.originalname or item.name)
            self.collected[item.nodeid] += 1
        for node in sorted(self.generated.keys() | self.collected.keys()):
            if self.generated[node] != 1 or self.collected[node] != 1:
                self.invalid = True
                print(
                    f"UT group collection mismatch: {node}: generated={self.generated[node]}, selected={self.collected[node]}",
                    file=sys.stderr,
                )
        duplicates = [node for node, count in self.collected.items() if count != 1]
        if duplicates:
            print(f"UT group duplicate nodes: {duplicates}", file=sys.stderr)
        if (
            found != self.expected
            or not self.collected
            or any(count != 1 for count in self.collected.values())
        ):
            self.invalid = True
            for path, names in self.expected.items():
                if found[path] != names:
                    print(
                        f"UT group collection mismatch: {path}: missing={sorted(names - found[path])}; unexpected={sorted(found[path] - names)}",
                        file=sys.stderr,
                    )

    def pytest_runtest_logreport(self, report):
        super().pytest_runtest_logreport(report)
        if report.skipped or report.failed or hasattr(report, "wasxfail"):
            self.invalid = True
            print(
                f"UT group unsuccessful node: {report.nodeid} ({report.when})",
                file=sys.stderr,
            )
        if report.when == "call":
            self.executed[report.nodeid] += 1
            if report.passed:
                self.passed[report.nodeid] += 1

    def pytest_sessionfinish(self, session, exitstatus):
        incomplete = sorted(
            node
            for node in self.generated.keys()
            | self.collected.keys()
            | self.executed.keys()
            | self.passed.keys()
            if not (
                self.generated[node]
                == self.collected[node]
                == self.executed[node]
                == self.passed[node]
                == 1
            )
        )
        if incomplete:
            print(f"UT group incomplete cases: {incomplete}", file=sys.stderr)
        if not exitstatus and (self.invalid or incomplete):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


def run_group(paths):
    resolved = [str(Path(path).resolve()) for path in paths]
    if (
        not resolved
        or len(set(resolved)) != len(resolved)
        or not all(groupable(path) for path in resolved)
    ):
        raise ValueError("UT group requires unique compatible suites")
    return int(pytest.main([*resolved, "-q"], plugins=[GroupDiagnostics(resolved)]))


def run(path, checks=(), message=None):
    path = str(Path(path).resolve())
    targets = [f"{path}::{name}" for name in checks] or [path]
    result = pytest.main([*targets, "-s", "-p", "no:terminal"], plugins=[Diagnostics()])
    if result == 0 and message is not None:
        print(message)
    return int(result != 0)


if __name__ == "__main__":
    if sys.argv[1:2] != ["--group"]:
        raise SystemExit("expected --group <UT suites>")
    raise SystemExit(run_group(sys.argv[2:]))
