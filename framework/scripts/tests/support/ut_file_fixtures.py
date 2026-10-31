"""Copy fixed UT files without changing their contents."""

import re
import shutil
from pathlib import Path


def _no_symlinks(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"symlink is not allowed: {part}")


def _files(test_file, case_id, kind):
    if not isinstance(case_id, str) or not re.fullmatch(
        r"[0-9]{2}_[a-z0-9]+(?:_[a-z0-9]+)*", case_id
    ):
        raise ValueError(f"invalid case ID: {case_id}")
    test = Path(test_file).absolute()
    if not test.name.endswith(".checks.py"):
        raise ValueError(f"invalid test file: {test}")
    root = (
        test.parent.parent
        / "fixtures"
        / "units"
        / test.name.removesuffix(".checks.py")
        / case_id
        / kind
    )
    _no_symlinks(root)
    if not root.is_dir():
        raise FileNotFoundError(f"fixture directory missing: {root}")
    files = []
    for path in sorted(root.rglob("*")):
        _no_symlinks(path)
        if path.is_file():
            files.append(path.relative_to(root))
        elif not path.is_dir():
            raise ValueError(f"invalid fixture path: {path}")
    return root, files


def load_workspace(test_file, case_id, workspace):
    root, files = _files(test_file, case_id, "input")
    workspace = Path(workspace).absolute()
    _no_symlinks(workspace)
    if not workspace.is_dir():
        raise ValueError(f"workspace is not a directory: {workspace}")
    for relative in files:
        target = workspace / relative
        _no_symlinks(target)
        if target.exists():
            raise FileExistsError(f"workspace file already exists: {relative}")
        for parent in target.parents:
            if parent == workspace:
                break
            if parent.exists() and not parent.is_dir():
                raise ValueError(f"workspace parent is not a directory: {parent}")
    for relative in files:
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output, (root / relative).open("rb") as source:
            shutil.copyfileobj(source, output)
    return workspace


def assert_expected_files(test_file, case_id, workspace):
    root, files = _files(test_file, case_id, "expected")
    workspace = Path(workspace).absolute()
    _no_symlinks(workspace)
    for relative in files:
        target = workspace / relative
        _no_symlinks(target)
        if not target.is_file():
            raise AssertionError(f"expected file missing: {relative}")
        if (root / relative).read_bytes() != target.read_bytes():
            raise AssertionError(f"file differs: {relative}")
