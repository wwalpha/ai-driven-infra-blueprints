#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from support.it_case_receipt import it_case
from support.worktree_python_fixtures import (
    Path,
    blocked,
    checks,
    fake_run,
    json,
    patch,
    py,
    sys,
    wt,
)
from support.worktree_python_fixtures import (
    spec as spec,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def requirements(root):
    req = root / py.REQUIREMENTS
    req.parent.mkdir(parents=True)
    req.write_text("", encoding="utf-8")
    (root / ".gitignore").write_text((root / ".gitignore").read_text() + ".venv/\n")
    checks.git(root, "add", ".")
    checks.git(root, "commit", "-qm", "requirements")


def _callback_check_setup_failing(command, where, env=None):
    if "install" in command:
        raise ValueError("fixture install failed")
    return fake_run(command, where, env)


@it_case
def check_setup():
    with checks.fixture() as root:
        requirements(root)
        with patch.object(py, "run", side_effect=_callback_check_setup_failing), patch.object(py, "probe"), patch.object(py, "verify"):
            blocked(lambda: wt.create(root, "failed"), "fixture install failed")
        _, _, _, retained = wt.load(root, "failed")
        assert retained["python_setup"]["status"] == "failed"
        assert Path(retained["worktree"]).is_dir() and wt.branch_exists(root, retained["branch"])
        directory = py.shared_directory(root)
        assert (directory / ".blueprint-owner").exists() and not (directory / ".blueprint-ready").exists()
        with patch.object(py, "run", side_effect=fake_run), patch.object(py, "probe"), patch.object(py, "verify"):
            assert wt.setup(root, "failed")["python_setup"]["installed"]
        assert wt.load(root, "failed")[3]["python_setup"]["status"] == "ready"
        assert py.runtime(Path(retained["worktree"]))[0] == py.python_path(directory)


@it_case
def check_venv_fallback():
    with checks.fixture() as root:
        requirements(root)
        with patch.object(py, "IMPORTS", []), patch.dict(py.os.environ, {"PIP_NO_INDEX": "1"}), \
                patch.object(py, "run", wraps=py.run) as commands, patch.object(py, "verify", wraps=py.verify) as verification:
            states = [wt.create(root, name) for name in ("first", "second")]
            directory = py.shared_directory(root)
            assert [s["python_setup"]["installed"] for s in states] == [True, False]
            assert len({s["python_setup"]["interpreter"] for s in states}) == 1
            assert sum("install" in c.args[0] for c in commands.call_args_list) == 1
            assert verification.call_count == 1
            target = Path(states[0]["worktree"])
            wrapper = Path(py.__file__).with_name("run-python.py")
            code = "import sys,os,json; print(json.dumps([sys.executable,sys.prefix,os.environ['VIRTUAL_ENV'],os.environ['PATH'].split(os.pathsep)[0]]))"
            for arguments in (["-c", code], ["--command", "python", "-c", code]):
                result = subprocess.run([sys.executable, "-B", str(wrapper), *arguments], cwd=target,
                                        capture_output=True, text=True)
                assert result.returncode == 0, result.stderr + result.stdout
                executable, prefix, virtual, first_bin = json.loads(result.stdout)
                assert Path(executable) == py.python_path(directory)
                assert Path(prefix) == Path(virtual) == directory
                assert Path(first_bin) == py.python_path(directory).parent
            wt.tasks.start(target, states[0]["task_file"], checks.contract("first", [py.REQUIREMENTS]))
            wt.tasks.complete(target, states[0]["task_file"])
            assert wt.finalize(root, "first")["cleaned"]
            assert directory.is_dir() and py.shared_ready(directory)
            assert py.runtime(Path(states[1]["worktree"]))[0] == py.python_path(directory)
    print("Real fixed-path venv, one install, wrapper/CLI, shared survival after cleanup: PASS")


@it_case
def check_parallel_fallback():
    with checks.fixture() as root:
        requirements(root)
        waiting, release = root.parent / "installing", root.parent / "release"
        child = """import sys,time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import worktree_task as wt
import worktree_python as py
py.IMPORTS = []
original = py.run
original_sleep = py.time.sleep
def sleep(seconds):
    if sys.argv[2] == 'process-b' and seconds == 0.1:
        Path(sys.argv[3]).with_name('contending').touch()
    original_sleep(seconds)
py.time.sleep = sleep
def run(command, root, env=None):
    assert not (Path.cwd() / '.worktrees/.blueprint/lifecycle.lock').exists()
    if 'install' in command and sys.argv[2] == 'process-a':
        Path(sys.argv[3]).touch()
        deadline = time.monotonic() + 20
        while not Path(sys.argv[4]).exists():
            if time.monotonic() > deadline: raise ValueError('test release timed out')
            time.sleep(0.01)
    return original(command, root, env)
py.run = run
state = wt.create(Path.cwd(), sys.argv[2])
import json
print(json.dumps(state))
"""
        env = {**py.os.environ, "PIP_NO_INDEX": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        args = [sys.executable, "-B", "-c", child, str(Path(py.__file__).parent)]
        first = subprocess.Popen([*args, "process-a", str(waiting), str(release)], cwd=root, env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        second = None
        try:
            deadline = time.monotonic() + 20
            while not waiting.exists() and time.monotonic() < deadline and first.poll() is None:
                time.sleep(0.01)
            assert waiting.exists()
            second = subprocess.Popen([*args, "process-b", str(waiting), str(release)], cwd=root, env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            deadline = time.monotonic() + 10
            path = root / ".worktrees/.blueprint/tasks/process-b.json"
            contending = waiting.with_name("contending")
            while not contending.exists() and time.monotonic() < deadline and second.poll() is None:
                time.sleep(0.01)
            assert contending.exists() and path.exists() and second.poll() is None
            release.touch()
            out_a, err_a = first.communicate(timeout=30)
            out_b, err_b = second.communicate(timeout=30)
            assert first.returncode == second.returncode == 0, err_a + err_b
            states = [json.loads(out_a), json.loads(out_b)]
            assert [state["python_setup"]["installed"] for state in states] == [True, False]
            assert states[0]["python_setup"]["interpreter"] == states[1]["python_setup"]["interpreter"]
        finally:
            release.touch()
            for process in (first, second):
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=10)
    print("Independent Create processes serialize one install: PASS")


@it_case
def check_symlink_safety():
    with checks.fixture() as root:
        external = root.parent / "external"
        external.mkdir()
        marker = external / "keep"
        marker.write_bytes(b"external data")
        shared = py.shared_directory(root)
        shared.parent.mkdir(parents=True)
        shared.symlink_to(external, target_is_directory=True)
        blocked(lambda: py.setup(root, {}), "symlink")
        assert shared.is_symlink() and marker.read_bytes() == b"external data"
        assert sorted(path.name for path in external.iterdir()) == ["keep"]


if __name__ == "__main__":
    check_setup()
    check_venv_fallback()
    check_parallel_fallback()
    check_symlink_safety()
