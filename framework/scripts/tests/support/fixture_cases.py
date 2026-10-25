"""Static YAML cases shared by test suites; no Model or runner behavior."""

import math
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path, PureWindowsPath

from utils.yaml_format import yaml_read

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(
        r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*", value
    )


def _value(value, ancestors=()):
    if type(value) in (dict, list):
        if id(value) in ancestors:
            raise ValueError("recursive fixture data")
        for child in value.values() if isinstance(value, dict) else value:
            _value(child, (*ancestors, id(value)))
    elif value is not None and (
        type(value) not in (str, bool, int, float)
        or isinstance(value, float)
        and not math.isfinite(value)
    ):
        raise ValueError("invalid fixture data")


def _relative(name):
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or "\x00" in name
        or ":" in name
        or PureWindowsPath(name).drive
        or name.startswith("/")
        or any(part in ("", ".", "..") for part in name.split("/"))
    ):
        raise ValueError(f"invalid fixture path: {name!r}")
    return Path(name)


def _section(section):
    if not isinstance(section, dict) or section.keys() - {"data", "files", "expected"}:
        raise ValueError("invalid fixture section")
    if "data" in section and not isinstance(section["data"], dict):
        raise ValueError("fixture data must be a mapping")
    _value(section)
    files = section.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("fixture files must be a mapping")
    for name, text in files.items():
        _relative(name)
        if not isinstance(text, str):
            raise ValueError("fixture file content must be text")


@lru_cache(maxsize=None)
def _suite(name):
    if not _identifier(name):
        raise ValueError(f"invalid fixture suite: {name!r}")
    suite = yaml_read((_FIXTURES / f"{name}.yaml").read_text(encoding="utf-8"))
    if (
        not isinstance(suite, dict)
        or suite.keys() - {"version", "base", "cases"}
        or type(suite.get("version")) is not int
        or suite["version"] != 1
        or not isinstance(suite.get("cases"), dict)
        or not suite["cases"]
    ):
        raise ValueError("invalid fixture schema/version")
    _section(suite.get("base", {}))
    for case_id, case in suite["cases"].items():
        if not _identifier(case_id):
            raise ValueError(f"invalid fixture case ID: {case_id!r}")
        _section(case)
    return suite


def load_suite(name):
    """Read/validate once per process; callers never receive the cached object."""
    return deepcopy(_suite(name))


def load_case(name, case_id):
    """Return independent values, merging data/files at their immediate keys only."""
    suite = _suite(name)
    if not isinstance(case_id, str) or case_id not in suite["cases"]:
        raise ValueError(f"unknown fixture case: {case_id!r} in {name}")
    case = suite["cases"][case_id]
    result = deepcopy(suite.get("base", {}))
    for key, value in case.items():
        if key in ("data", "files"):
            result.setdefault(key, {}).update(deepcopy(value))
        else:
            result[key] = deepcopy(value)
    return result


def materialize_files(root, files):
    """Validate all destinations before writing exact UTF-8 bytes below root."""
    _section({"files": files})
    root = Path(root)
    if root.is_symlink():
        raise ValueError(f"fixture workspace is a symlink: {root}")
    root = root.resolve()
    destinations = {}
    for name, text in files.items():
        path = root / _relative(name)
        for component in (path, *path.parents):
            if component == root:
                break
            if component.is_symlink():
                raise ValueError(f"fixture symlink path: {name}")
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"fixture path escapes workspace: {name}")
        if path.exists() and not path.is_file():
            raise ValueError(f"fixture destination is not a file: {name}")
        if (
            path in destinations
            or path.exists()
            and any(other.exists() and path.samefile(other) for other in destinations)
        ):
            raise ValueError(f"conflicting fixture paths: {name}")
        destinations[path] = text
    for path in destinations:
        if any(
            parent in destinations or parent.exists() and not parent.is_dir()
            for parent in path.parents
            if parent != root and parent.is_relative_to(root)
        ):
            raise ValueError(f"conflicting fixture paths: {path}")
    for path, text in destinations.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
