"""One primary-owned Python environment for every managed worktree."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REQUIREMENTS = "framework/scripts/requirements.txt"
# WeasyPrint loads native PDF libraries; check them only during PDF export.
IMPORTS = "yaml boto3 botocore pytest cfnlint pypdf".split()


def python_path(directory=None):
    if directory is None:
        return Path(sys._base_executable).resolve()
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def environment(directory=None):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV")}
    env["PATH"] = str(python_path(directory).parent) + os.pathsep + env.get("PATH", "")
    if directory is not None:
        env["VIRTUAL_ENV"] = str(directory)
    return env


def run(command, root, env=None):
    result = subprocess.run(list(map(str, command)), cwd=root, env=env,
                            capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise ValueError(f"Python setup command failed ({result.returncode}): {' '.join(map(str, command))}\n"
                         + (result.stderr or result.stdout)[-6000:])
    return result.stdout.strip()


def venv_directory(root):
    directory = root / ".venv"
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise ValueError("unexpected .venv structure; retain it for review")
    if directory.exists() and not (directory / "pyvenv.cfg").is_file():
        raise ValueError(".venv has no Python environment configuration; retain it for review")
    return directory


def probe(root, directory):
    code = ("import json,sys; from pathlib import Path; "
            "cfg=dict((k.strip().lower(),v.strip().lower()) for k,_,v in "
            "(l.partition('=') for l in Path(sys.prefix,'pyvenv.cfg').read_text(encoding='utf-8').splitlines())); "
            "print(json.dumps({'prefix':sys.prefix,'version':sys.version,"
            "'isolated':cfg.get('include-system-site-packages')=='false'}))")
    data = json.loads(run([python_path(directory), "-I", "-c", code], root, environment(directory)))
    if Path(data["prefix"]).resolve() != directory or not data["isolated"]:
        raise ValueError("venv interpreter is not isolated at its registered location")
    return data["version"]


def verify(root, directory):
    env = environment(directory)
    run([python_path(directory), "-I", "-m", "pip", "check"], root, env)
    # Initial completion requires working imports and requested versions.
    code = ("import importlib,importlib.metadata as m; from pathlib import Path; "
            f"[importlib.import_module(n) for n in {IMPORTS!r}]; "
            f"lines=Path({str(root / REQUIREMENTS)!r}).read_text(encoding='utf-8').splitlines(); "
            "pairs=[l.strip().split('==') for l in lines if l.strip() and not l.lstrip().startswith('#')]; "
            "bad=[n for n,v in pairs if m.version(n)!=v]; "
            "\nif bad: raise ValueError('requirement versions differ: '+str(bad))")
    run([python_path(directory), "-I", "-c", code], root, env)


def shared_directory(root):
    import worktree_task as wt
    _, _, primary = wt.repository(root)
    return wt.metadata_directory(primary) / "python-env"


def shared_ready(directory):
    # Markers alone cannot claim a redirected or previously unknown directory.
    owner = directory / ".blueprint-owner"
    complete = directory / ".blueprint-ready"
    for path in (directory, owner, complete, directory / "pyvenv.cfg", python_path(directory).parent):
        if path.is_symlink():
            raise ValueError(f"unexpected shared Python symlink; retain for review: {path}")
    if not directory.exists():
        return False
    if not directory.is_dir() or not owner.is_file() or owner.read_text(encoding="utf-8") != str(directory):
        raise ValueError(f"unknown shared Python directory; retain for review: {directory}")
    if not complete.exists():
        return False
    if not complete.is_file() or complete.read_text(encoding="utf-8") != str(directory):
        raise ValueError("invalid shared Python completion marker; explicit maintenance required")
    if not python_path(directory).is_file():
        raise ValueError("shared Python executable missing; explicit maintenance required")
    if not (directory / "pyvenv.cfg").is_file():
        raise ValueError("shared Python configuration missing; explicit maintenance required")
    return True


def setup(root, previous):
    directory = shared_directory(root)
    # Inspect legacy artifacts without adopting, modifying or deleting them.
    venv_directory(root)
    def result(installed):
        return {"status": "ready", "kind": "shared", "interpreter": str(python_path(directory)),
                "bin": str(python_path(directory).parent), "installed": installed}
    lock = directory.with_name("python-env.setup-lock")
    # A competing builder may be between mkdir and its ownership record.
    if (directory / ".blueprint-ready").exists() or not lock.exists():
        if shared_ready(directory):
            return result(False)
    deadline = time.monotonic() + 300
    while True:
        if lock.is_symlink():
            raise ValueError(f"unexpected shared setup lock symlink; retain for review: {lock}")
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ValueError(f"shared Python setup lock busy; retain lock for review, then rerun setup: {lock}") from None
            time.sleep(0.1)
        except PermissionError as error:
            raise PermissionError(f"shared Python directory write denied: {lock}: {error}") from error
    try:
        if shared_ready(directory):
            return result(False)
        if not directory.exists():
            try:
                directory.mkdir()
                (directory / ".blueprint-owner").write_text(str(directory), encoding="utf-8")
            except PermissionError as error:
                raise PermissionError(f"shared Python directory write denied: {directory}: {error}") from error
        # A failed initial setup retains its ownership record and resumes in place.
        if not (directory / "pyvenv.cfg").is_file() or not python_path(directory).is_file():
            try:
                run([python_path(), "-I", "-m", "venv", str(directory)], root, environment())
            except (OSError, ValueError) as error:
                raise ValueError(f"shared Python environment creation failed; partial environment retained; rerun setup: {error}") from error
        try:
            run([python_path(directory), "-I", "-m", "pip", "install", "--disable-pip-version-check",
                 "-r", str(root / REQUIREMENTS)], root, environment(directory))
        except (OSError, ValueError) as error:
            raise ValueError(f"shared Python pip install failed; incomplete environment retained; rerun setup: {error}") from error
        probe(root, directory)
        verify(root, directory)
        (directory / ".blueprint-ready").write_text(str(directory), encoding="utf-8")
        return result(True)
    finally:
        lock.rmdir()


def remove(root):
    directory = venv_directory(root)
    if directory.exists():
        shutil.rmtree(directory)  # rmtree never follows directory symlinks within the environment.


def runtime(root):
    """Resolve ready lifecycle metadata afresh; no shell activation or saved PATH needed."""
    import worktree_task as wt
    _, _, primary = wt.repository(root)
    path = wt.metadata_directory(primary) / "tasks" / f"{root.name}.json"
    if not path.is_file():
        if root.parent == primary / ".worktrees":
            raise ValueError("managed worktree Python state missing; rerun worktree setup")
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if Path(state["worktree"]) != root:
        if root.parent == primary / ".worktrees":
            raise ValueError("managed worktree Python registration mismatch")
        return None
    _, _, _, state = wt.load(root, root.name)
    setup_state = state.get("python_setup", {})
    if setup_state.get("status") != "ready":
        raise ValueError(f"Python setup is missing or failed; run worktree_task.py setup --task-id {state['task_id']}")
    if setup_state.get("kind") != "shared":
        raise ValueError(f"Python setup kind is missing or unsupported; run worktree_task.py setup --task-id {state['task_id']}")
    directory = shared_directory(root)
    interpreter = python_path(directory)
    if setup_state.get("interpreter") != str(interpreter) or setup_state.get("bin") != str(interpreter.parent):
        raise ValueError("shared Python registration mismatch; rerun worktree setup")
    if not shared_ready(directory):
        raise ValueError("shared Python partially built or missing completion marker; rerun worktree setup")
    return interpreter, environment(directory)
