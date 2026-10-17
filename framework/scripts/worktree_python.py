"""Prefer verified global Python, otherwise use the worktree-local venv."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REQUIREMENTS = "framework/scripts/requirements.txt"
# WeasyPrint loads native PDF libraries; check them only during PDF export.
IMPORTS = "yaml pystache boto3 botocore pytest cfnlint pypdf".split()


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


def signature(root):
    return {"requirements_sha256": hashlib.sha256((root / REQUIREMENTS).read_bytes()).hexdigest(),
            "python_version": sys.version, "base_python": str(Path(sys._base_executable).resolve())}


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
    # Check imports and requested versions: missing/broken packages invalidate cached success.
    code = ("import importlib,importlib.metadata as m; from pathlib import Path; "
            f"[importlib.import_module(n) for n in {IMPORTS!r}]; "
            f"lines=Path({str(root / REQUIREMENTS)!r}).read_text(encoding='utf-8').splitlines(); "
            "pairs=[l.strip().split('==') for l in lines if l.strip() and not l.lstrip().startswith('#')]; "
            "bad=[n for n,v in pairs if m.version(n)!=v]; "
            "\nif bad: raise ValueError('requirement versions differ: '+str(bad))")
    run([python_path(directory), "-I", "-c", code], root, env)


def probe_global(root):
    code = ("import json,sys; print(json.dumps({'version':sys.version,"
            "'global':sys.prefix==sys.base_prefix,'executable':sys.executable}))")
    data = json.loads(run([python_path(), "-I", "-c", code], root, environment()))
    if (not data["global"] or data["version"] != sys.version
            or Path(data["executable"]).resolve() != python_path()):
        raise ValueError("global Python interpreter changed; rerun worktree setup")


def setup(root, previous):
    directory = venv_directory(root)
    desired = signature(root)
    probe_global(root)
    try:
        verify(root, None)
    except (OSError, ValueError):
        pass
    else:
        if signature(root) != desired:
            raise ValueError("requirements/Python changed during setup; retry")
        return {"status": "ready", **desired, "kind": "global", "interpreter": str(python_path()),
                "bin": str(python_path().parent), "installed": False}
    installed = False
    current = None
    if (directory / "pyvenv.cfg").is_file() and python_path(directory).exists():
        try:
            current = probe(root, directory)
        except (OSError, ValueError):
            pass
    if current != sys.version:
        remove(root)
        run([python_path(), "-I", "-m", "venv", str(directory)], root)
    reusable = (current == sys.version and previous.get("status") == "ready"
                and all(previous.get(k) == v for k, v in desired.items()))
    if reusable:
        try:
            verify(root, directory)
        except (OSError, ValueError):
            reusable = False
    if not reusable:
        run([python_path(directory), "-I", "-m", "pip", "install", "--disable-pip-version-check",
             "-r", str(root / REQUIREMENTS)], root, environment(directory))
        installed = True
        if probe(root, directory) != sys.version:
            raise ValueError("venv Python version does not match setup interpreter")
        verify(root, directory)
    if signature(root) != desired:
        raise ValueError("requirements/Python changed during setup; retry")
    return {"status": "ready", **desired, "kind": "venv", "interpreter": str(python_path(directory)),
            "bin": str(python_path(directory).parent), "installed": installed}


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
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if Path(state["worktree"]) != root:
        return None
    _, _, _, state = wt.load(root, root.name)
    setup_state = state.get("python_setup", {})
    desired = signature(root)
    if setup_state.get("status") != "ready" or any(setup_state.get(k) != v for k, v in desired.items()):
        raise ValueError(f"Python setup is missing, failed or stale; run worktree_task.py setup --task-id {state['task_id']}")
    kind = setup_state.get("kind")
    if kind not in ("global", "venv"):
        raise ValueError(f"Python setup kind is missing or unsupported; run worktree_task.py setup --task-id {state['task_id']}")
    directory = None if kind == "global" else venv_directory(root)
    interpreter = python_path(directory)
    if setup_state.get("interpreter") != str(interpreter) or setup_state.get("bin") != str(interpreter.parent):
        raise ValueError(f"{kind} Python registration mismatch; rerun worktree setup")
    if kind == "global":
        probe_global(root)
        verify(root, None)  # Global packages can change outside the worktree.
    elif probe(root, directory) != setup_state["python_version"]:
        raise ValueError("Python interpreter changed; rerun worktree setup")
    return interpreter, environment(directory)
