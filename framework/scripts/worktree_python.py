"""One primary-owned Python environment for every managed worktree."""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import worktree_state as wt

REQUIREMENTS = "framework/scripts/requirements.txt"
APPLIED = ".blueprint-requirements-sha256"
UNVERIFIED = "pending verification"
# WeasyPrint loads native PDF libraries; check them only during PDF export.
IMPORTS = "yaml boto3 botocore pytest pypdf".split()


def python_path(directory=None):
    if directory is None:
        return Path(sys._base_executable).resolve()
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def environment(directory=None):
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV")
    }
    env["PATH"] = str(python_path(directory).parent) + os.pathsep + env.get("PATH", "")
    if directory is not None:
        env["VIRTUAL_ENV"] = str(directory)
    return env


def run(command, root, env=None):
    result = subprocess.run(
        list(map(str, command)),
        cwd=root,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise ValueError(
            f"Python setup command failed ({result.returncode}): {' '.join(map(str, command))}\n"
            + (result.stderr or result.stdout)[-6000:]
        )
    return result.stdout.strip()


def probe(root, directory):
    code = (
        "import json,sys; from pathlib import Path; "
        "cfg=dict((k.strip().lower(),v.strip().lower()) for k,_,v in "
        "(l.partition('=') for l in Path(sys.prefix,'pyvenv.cfg').read_text(encoding='utf-8').splitlines())); "
        "print(json.dumps({'prefix':sys.prefix,'version':sys.version,"
        "'isolated':cfg.get('include-system-site-packages')=='false'}))"
    )
    data = json.loads(
        run([python_path(directory), "-I", "-c", code], root, environment(directory))
    )
    if Path(data["prefix"]).resolve() != directory or not data["isolated"]:
        raise ValueError("venv interpreter is not isolated at its registered location")
    return data["version"]


def verify(root, directory):
    env = environment(directory)
    run([python_path(directory), "-I", "-m", "pip", "check"], root, env)
    # Installation requires working imports and requested versions.
    code = (
        "import importlib,importlib.metadata as m; from pathlib import Path; "
        f"[importlib.import_module(n) for n in {IMPORTS!r}]; "
        f"lines=Path({str(root / REQUIREMENTS)!r}).read_text(encoding='utf-8').splitlines(); "
        "pairs=[l.strip().split('==') for l in lines if l.strip() and not l.lstrip().startswith('#')]; "
        "bad=[n for n,v in pairs if m.version(n)!=v]; "
        "\nif bad: raise ValueError('requirement versions differ: '+str(bad))"
    )
    run([python_path(directory), "-I", "-c", code], root, env)


def shared_directory(root):
    _, _, primary = wt.repository(root)
    return wt.metadata_directory(primary) / "python-env"


def shared_ready(directory):
    # Markers alone cannot claim a redirected or previously unknown directory.
    owner = directory / ".blueprint-owner"
    complete = directory / ".blueprint-ready"
    for path in (
        directory,
        owner,
        complete,
        directory / APPLIED,
        directory / (APPLIED + ".tmp"),
        directory / "pyvenv.cfg",
        python_path(directory).parent,
    ):
        if path.is_symlink():
            raise ValueError(
                f"unexpected shared Python symlink; retain for review: {path}"
            )
    if not directory.exists():
        return False
    if (
        not directory.is_dir()
        or not owner.is_file()
        or owner.read_text(encoding="utf-8") != str(directory)
    ):
        raise ValueError(
            f"unknown shared Python directory; retain for review: {directory}"
        )
    if not complete.exists():
        return False
    if not complete.is_file() or complete.read_text(encoding="utf-8") != str(directory):
        raise ValueError(
            "invalid shared Python completion marker; explicit maintenance required"
        )
    if not python_path(directory).is_file():
        raise ValueError(
            "shared Python executable missing; explicit maintenance required"
        )
    if not (directory / "pyvenv.cfg").is_file():
        raise ValueError(
            "shared Python configuration missing; explicit maintenance required"
        )
    return True


def setup_result(directory, installed):
    return {
        "status": "ready",
        "kind": "shared",
        "interpreter": str(python_path(directory)),
        "bin": str(python_path(directory).parent),
        "installed": installed,
    }


def requirement_pins(content):
    pins = {}
    for line in content.decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;#]+)", line)
        if not match:
            raise ValueError(f"shared Python requires exact name==version pins: {line}")
        name, version = match.groups()
        name = re.sub(r"[-_.]+", "-", name).lower()
        if name in pins:
            raise ValueError(f"duplicate shared Python requirement: {name}")
        pins[name] = version
    return pins


def requirements_snapshot(root, primary):
    canonical = (primary / REQUIREMENTS).read_bytes()
    local = (root / REQUIREMENTS).read_bytes()
    if local != canonical:
        pins = requirement_pins(canonical)
        conflicts = [
            f"{name}: worktree requires {version}, primary requires {pins.get(name, 'absent')}"
            for name, version in requirement_pins(local).items()
            if pins.get(name) != version
        ]
        if conflicts:
            raise ValueError(
                f"shared Python requirements conflict with {primary / REQUIREMENTS}; "
                "update/reconcile this worktree before execution: "
                + "; ".join(conflicts)
            )
    return primary, canonical, local


def applied(directory, content):
    marker = directory / APPLIED
    return (
        marker.is_file()
        and marker.read_text(encoding="utf-8") == hashlib.sha256(content).hexdigest()
    )


def requirement_differences(root, directory, content):
    code = (
        "import importlib.metadata as m,json\n"
        "versions={}\n"
        f"for name in {list(requirement_pins(content))!r}:\n"
        " try: versions[name]=m.version(name)\n"
        " except m.PackageNotFoundError: versions[name]=None\n"
        "print(json.dumps(versions))"
    )
    versions = json.loads(
        run([python_path(directory), "-I", "-c", code], root, environment(directory))
    )
    return [
        f"{name}: required {version}, installed {versions.get(name) or 'missing'}"
        for name, version in requirement_pins(content).items()
        if versions.get(name) != version
    ]


def setup(root, previous):
    directory = shared_directory(root)
    primary = directory.parents[2]
    lock = directory.with_name("python-env.setup-lock")
    # A competing builder may be between mkdir and its ownership record.
    if not lock.exists() and not lock.is_symlink():
        if shared_ready(directory):
            if applied(directory, requirements_snapshot(root, primary)[1]):
                return setup_result(directory, False)
    deadline = time.monotonic() + 300
    while True:
        if lock.is_symlink():
            raise ValueError(
                f"unexpected shared setup lock symlink; retain for review: {lock}"
            )
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ValueError(
                    f"shared Python setup lock busy; retain lock for review, then rerun setup: {lock}"
                ) from None
            time.sleep(0.1)
        except PermissionError as error:
            raise PermissionError(
                f"shared Python directory write denied: {lock}: {error}"
            ) from error
    try:
        ready = shared_ready(directory)
        snapshot = requirements_snapshot(root, primary)
        primary, content, _ = snapshot
        if ready and applied(directory, content):
            return setup_result(directory, False)
        if not directory.exists():
            try:
                directory.mkdir()
                (directory / ".blueprint-owner").write_text(
                    str(directory), encoding="utf-8"
                )
            except PermissionError as error:
                raise PermissionError(
                    f"shared Python directory write denied: {directory}: {error}"
                ) from error
        # A failed initial setup retains its ownership record and resumes in place.
        if (
            not (directory / "pyvenv.cfg").is_file()
            or not python_path(directory).is_file()
        ):
            try:
                run(
                    [python_path(), "-I", "-m", "venv", str(directory)],
                    root,
                    environment(),
                )
            except (OSError, ValueError) as error:
                raise ValueError(
                    f"shared Python environment creation failed; partial environment retained; rerun setup: {error}"
                ) from error
        differences = (
            requirement_differences(primary, directory, content) if ready else []
        )
        installed = not ready or bool(differences)
        marker = directory / APPLIED
        unverified = (
            marker.is_file() and marker.read_text(encoding="utf-8") == UNVERIFIED
        )
        if installed:
            # A partial pip update invalidates even the previously applied hash.
            marker.write_text(UNVERIFIED, encoding="utf-8")
            try:
                run(
                    [
                        python_path(directory),
                        "-I",
                        "-m",
                        "pip",
                        "install",
                        "--disable-pip-version-check",
                        "-r",
                        str(primary / REQUIREMENTS),
                    ],
                    primary,
                    environment(directory),
                )
                if not ready:
                    probe(primary, directory)
                verify(primary, directory)
            except (OSError, ValueError) as error:
                raise ValueError(
                    "shared Python dependency synchronization failed; environment retained; "
                    f"retry execution/setup; {'; '.join(differences)}: {error}"
                ) from error
        elif unverified:
            verify(primary, directory)
        if (primary / REQUIREMENTS).read_bytes() != content or (
            root / REQUIREMENTS
        ).read_bytes() != snapshot[2]:
            raise ValueError(
                "shared Python requirements changed during synchronization; retry"
            )
        temporary = directory / (APPLIED + ".tmp")
        temporary.write_text(hashlib.sha256(content).hexdigest(), encoding="utf-8")
        temporary.replace(directory / APPLIED)
        (directory / ".blueprint-ready").write_text(str(directory), encoding="utf-8")
        return setup_result(directory, installed)
    finally:
        lock.rmdir()


def runtime(root):
    """Resolve ready lifecycle metadata afresh; no shell activation or saved PATH needed."""
    _, _, primary = wt.repository(root)
    path = wt.metadata_directory(primary) / "tasks" / f"{root.name}.json"
    if not path.is_file():
        if root.parent == primary / ".worktrees":
            raise ValueError(
                "managed worktree Python state missing; rerun worktree setup"
            )
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if Path(state["worktree"]) != root:
        if root.parent == primary / ".worktrees":
            raise ValueError("managed worktree Python registration mismatch")
        return None
    _, _, _, state = wt.load(root, root.name)
    setup_state = state.get("python_setup", {})
    if setup_state.get("status") != "ready":
        raise ValueError(
            f"Python setup is missing or failed; run worktree_task.py setup --task-id {state['task_id']}"
        )
    if setup_state.get("kind") != "shared":
        raise ValueError(
            f"Python setup kind is missing or unsupported; run worktree_task.py setup --task-id {state['task_id']}"
        )
    directory = shared_directory(root)
    interpreter = python_path(directory)
    if setup_state.get("interpreter") != str(interpreter) or setup_state.get(
        "bin"
    ) != str(interpreter.parent):
        raise ValueError("shared Python registration mismatch; rerun worktree setup")
    if not shared_ready(directory):
        raise ValueError(
            "shared Python partially built or missing completion marker; rerun worktree setup"
        )
    lock = directory.with_name("python-env.setup-lock")
    if (
        lock.exists()
        or lock.is_symlink()
        or not applied(directory, requirements_snapshot(root, primary)[1])
    ):
        setup(root, setup_state)
    return interpreter, environment(directory)
