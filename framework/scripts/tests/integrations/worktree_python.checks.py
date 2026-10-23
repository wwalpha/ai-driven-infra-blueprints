#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Event
from types import SimpleNamespace as _CallbackState

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils.function_wrapper import BoundCallback as _bind_framework_callback

from support.it_case_receipt import it_case
from support.worktree_python_fixtures import (
    Path,
    blocked,
    checks,
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


@it_case
def check_output_decoding():
    for encoding in ("cp932", "utf-8"):
        stdout = "セットアップ出力\n".encode(encoding)
        for stderr in (b"", "エラー詳細\n".encode(encoding)):
            for returncode in (0, 7):
                code = (f"import os; os.write(1, {stdout!r}); os.write(2, {stderr!r}); "
                        f"raise SystemExit({returncode})")
                command = [sys.executable, "-I", "-c", code]
                if returncode:
                    try:
                        py.run(command, Path.cwd())
                    except ValueError as error:
                        assert "Python setup command failed (7)" in str(error), str(error)
                        assert str(error).endswith((stderr or stdout).decode("utf-8", errors="replace")), str(error)
                    else:
                        raise AssertionError("nonzero child exit must fail setup")
                else:
                    assert py.run(command, Path.cwd()) == stdout.decode("utf-8", errors="replace").strip()
    print("Real CP932/UTF-8 stdout/stderr and zero/nonzero child exits: PASS")


def requirements(root):
    req = root / py.REQUIREMENTS
    req.parent.mkdir(parents=True)
    req.write_text("", encoding="utf-8")
    (root / ".gitignore").write_text((root / ".gitignore").read_text() + ".venv/\n")
    checks.git(root, "add", ".")
    checks.git(root, "commit", "-qm", "requirements")


def fake_run(command, root, env=None):
    if "venv" in command:
        directory = Path(command[-1])
        (directory / "pyvenv.cfg").write_text("home = fixture\n")
        py.python_path(directory).parent.mkdir(exist_ok=True)
        py.python_path(directory).touch()
    return ""


def _callback_check_setup_failing(_state_check_setup_77, /, command, where, env=None):
    if _state_check_setup_77.stage in command:
        raise ValueError("fixture " + _state_check_setup_77.stage + " failed")
    return fake_run(command, where, env)


def _callback_check_setup_mkdir(_state_check_setup_77, /, path, *args, **kwargs):
    if path.name == "python-env.setup-lock":
        raise PermissionError("fixture permission denied")
    return _state_check_setup_77.original_mkdir(path, *args, **kwargs)


@it_case
def check_setup():
    _state_check_setup_77 = _CallbackState()
    with checks.fixture() as root:
        requirements(root)
        with patch.object(py, "probe"), patch.object(py, "verify") as verify, \
                patch.object(py, "run", side_effect=fake_run) as commands:
            states = [wt.create(root, name) for name in ("one", "two", "three")]
            directory = root / ".worktrees/.blueprint/python-env"
            assert [s["python_setup"]["installed"] for s in states] == [True, False, False]
            assert verify.call_count == 1
            assert sum("install" in c.args[0] for c in commands.call_args_list) == 1
            target = Path(states[0]["worktree"])
            for state in states:
                assert state["python_setup"]["kind"] == "shared"
                assert py.runtime(Path(state["worktree"]))[0] == py.python_path(directory)
                assert not (Path(state["worktree"]) / ".venv").exists()
            path = wt.load(target, "one")[2]
            saved = path.read_bytes()
            path.unlink()
            blocked(lambda: py.runtime(target), "state missing")
            path.write_bytes(saved)
            (target / py.REQUIREMENTS).write_text("missing==0.0.0\n")
            with patch.object(py, "run", side_effect=AssertionError("reuse ran a subprocess")):
                assert not wt.setup(root, "one")["python_setup"]["installed"]
                py.runtime(target)
            assert verify.call_count == 1
            for error in (AttributeError("unexpected setup error"), KeyboardInterrupt()):
                with patch.object(py, "setup", side_effect=error):
                    blocked(lambda: wt.setup(root, "one"), type(error).__name__)
                assert wt.load(root, "one")[3]["python_setup"]["status"] == "failed"
                blocked(lambda: py.runtime(target), "failed")
                wt.setup(root, "one")
            _, _, path, record = wt.load(root, "one")
            for field in ("interpreter", "bin"):
                original = record["python_setup"][field]
                record["python_setup"][field] = "foreign"
                wt.save(path, record)
                blocked(lambda: py.runtime(target), "registration mismatch")
                record["python_setup"][field] = original
            for kind in (None, "global", "venv", "unknown"):
                record["python_setup"]["kind"] = kind
                wt.save(path, record)
                blocked(lambda: py.runtime(target), "kind is missing or unsupported")
                assert wt.setup(root, "one")["python_setup"]["kind"] == "shared"
            blocked(lambda: wt.create(root, "one"), "collision")
            py.python_path(directory).unlink()
            blocked(lambda: py.runtime(target), "executable missing")
            blocked(lambda: wt.setup(root, "one"), "executable missing")
            assert directory.is_dir() and target.is_dir()
    # All initial failure stages retain Task/branch and resume only through setup.
    for _state_check_setup_77.stage in ("venv", "install", "verify", "permission"):
        with checks.fixture() as root:
            requirements(root)
            failing = _bind_framework_callback(_callback_check_setup_failing, _state_check_setup_77)
            mkdir = _bind_framework_callback(_callback_check_setup_mkdir, _state_check_setup_77)
            _state_check_setup_77.original_mkdir = Path.mkdir
            permission = patch.object(Path, "mkdir", mkdir) if _state_check_setup_77.stage == "permission" else nullcontext()
            with patch.object(py, "run", side_effect=failing), patch.object(py, "probe"), \
                    patch.object(py, "verify", side_effect=ValueError("fixture verify failed") if _state_check_setup_77.stage == "verify" else None), permission:
                blocked(lambda: wt.create(root, "failed"), "write denied" if _state_check_setup_77.stage == "permission" else "failed")
            _, _, _, retained = wt.load(root, "failed")
            assert retained["python_setup"]["status"] == "failed"
            assert Path(retained["worktree"]).is_dir() and wt.branch_exists(root, retained["branch"])
            directory = py.shared_directory(root)
            assert not (directory / ".blueprint-ready").exists()
            with patch.object(py, "run", side_effect=fake_run), patch.object(py, "probe"), patch.object(py, "verify"):
                assert wt.setup(root, "failed")["python_setup"]["installed"]
    print("Shared first/reuse setup, strict runtime registration, failure retention/recovery and permissions: PASS")


@it_case
def check_real_global():
    # Ordinary checkouts keep their existing wrapper behavior.
    with checks.fixture() as root:
        assert py.runtime(root) is None
        spec = spec_from_file_location("python_wrapper", Path(py.__file__).with_name("run-python.py"))
        wrapper = module_from_spec(spec)
        spec.loader.exec_module(wrapper)
        with patch.object(wrapper.worktree_python, "runtime", return_value=None) as runtime, \
                patch.object(wrapper.os, "execvpe") as execute, patch.object(wrapper.sys, "platform", "linux"), patch.object(wrapper.sys, "argv", ["wrapper", "-c", "pass"]):
            wrapper.main()
            assert execute.call_args.args[1][0] == sys.executable
            runtime.assert_called_once_with(Path.cwd().resolve())
    print("Ordinary checkout wrapper retains launcher behavior: PASS")


def _callback_check_venv_fallback_timed_setup(actual_setup, setup_times, /, *args):
    begin = time.monotonic()
    result = actual_setup(*args)
    setup_times.append(time.monotonic() - begin)
    return result


@it_case
def check_venv_fallback():
    with checks.fixture() as root:
        requirements(root)
        with patch.object(py, "IMPORTS", []), patch.dict(py.os.environ, {"PIP_NO_INDEX": "1"}), \
                patch.object(py, "run", wraps=py.run) as commands, patch.object(py, "verify", wraps=py.verify) as verification:
            times = []
            setup_times = []
            actual_setup = py.setup
            timed_setup = _bind_framework_callback(_callback_check_venv_fallback_timed_setup, actual_setup, setup_times)
            states = []
            with patch.object(py, "setup", side_effect=timed_setup):
                for name in ("first", "second", "third"):
                    begin = time.monotonic()
                    states.append(wt.create(root, name))
                    times.append(time.monotonic() - begin)
            directory = py.shared_directory(root)
            assert [s["python_setup"]["installed"] for s in states] == [True, False, False]
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
            print("Offline empty-requirements Create timings (total/setup/git+state seconds): " +
                  str([(round(t, 3), round(s, 3), round(t-s, 3)) for t, s in zip(times, setup_times, strict=False)]))
    print("Real fixed-path venv, one install, wrapper/CLI, shared survival after cleanup: PASS")


def _callback_check_parallel_fallback_run(_state_check_parallel_fallback_218, installing, /, command, target, env=None):
    assert not (_state_check_parallel_fallback_218.root / ".worktrees/.blueprint/lifecycle.lock").exists()
    if "install" in command:
        installing.set()
        assert _state_check_parallel_fallback_218.release.wait(timeout=10)
    return fake_run(command, target, env)


@it_case
def check_parallel_fallback():
    _state_check_parallel_fallback_218 = _CallbackState()
    with checks.fixture() as _state_check_parallel_fallback_218.root:
        requirements(_state_check_parallel_fallback_218.root)
        installing, _state_check_parallel_fallback_218.release = Event(), Event()
        run = _bind_framework_callback(_callback_check_parallel_fallback_run, _state_check_parallel_fallback_218, installing)
        with patch.object(py, "probe"), patch.object(py, "verify"), patch.object(py, "run", side_effect=run) as commands:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(wt.create, _state_check_parallel_fallback_218.root, "parallel-a")
                assert installing.wait(timeout=10)
                second = pool.submit(wt.create, _state_check_parallel_fallback_218.root, "parallel-b")
                try:
                    # The other Create can finish Git/state while installation is blocked.
                    deadline = time.monotonic() + 10
                    state_path = _state_check_parallel_fallback_218.root / ".worktrees/.blueprint/tasks/parallel-b.json"
                    while not state_path.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    assert state_path.exists()
                    assert not second.done()
                finally:
                    _state_check_parallel_fallback_218.release.set()
                states = [first.result(), second.result()]
            assert states[0]["python_setup"]["interpreter"] == states[1]["python_setup"]["interpreter"]
            assert [s["python_setup"]["installed"] for s in states] == [True, False]
            assert sum("install" in call.args[0] for call in commands.call_args_list) == 1
            lock = wt.load(_state_check_parallel_fallback_218.root, "parallel-a")[2].with_suffix(".setup-lock")
            lock.mkdir()
            blocked(lambda: wt.setup(_state_check_parallel_fallback_218.root, "parallel-a"), "Python setup busy")
            assert lock.is_dir()
            lock.rmdir()  # Fixture-owned simulated lock.
            directory = py.shared_directory(_state_check_parallel_fallback_218.root)
            (directory / ".blueprint-ready").unlink()
            lock = directory.with_name("python-env.setup-lock")
            lock.mkdir()
            with patch.object(py.time, "monotonic", side_effect=[0, 301]):
                blocked(lambda: wt.setup(_state_check_parallel_fallback_218.root, "parallel-a"), "shared Python setup lock busy")
            assert lock.is_dir()
            lock.rmdir()  # Fixture-owned simulated lock.
    # Exercise the same filesystem mutex in independent Python processes.
    with checks.fixture() as _state_check_parallel_fallback_218.root:
        requirements(_state_check_parallel_fallback_218.root)
        waiting, _state_check_parallel_fallback_218.release = _state_check_parallel_fallback_218.root.parent / "installing", _state_check_parallel_fallback_218.root.parent / "release"
        child = """import sys,time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import worktree_task as wt
import worktree_python as py
py.IMPORTS = []
original = py.run
def run(command, root, env=None):
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
        first = subprocess.Popen([*args, "process-a", str(waiting), str(_state_check_parallel_fallback_218.release)], cwd=_state_check_parallel_fallback_218.root, env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        second = None
        try:
            deadline = time.monotonic() + 20
            while not waiting.exists() and time.monotonic() < deadline and first.poll() is None:
                time.sleep(0.01)
            assert waiting.exists()
            second = subprocess.Popen([*args, "process-b", str(waiting), str(_state_check_parallel_fallback_218.release)], cwd=_state_check_parallel_fallback_218.root, env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            deadline = time.monotonic() + 10
            path = _state_check_parallel_fallback_218.root / ".worktrees/.blueprint/tasks/process-b.json"
            while not path.exists() and time.monotonic() < deadline and second.poll() is None:
                time.sleep(0.01)
            assert path.exists() and second.poll() is None
            _state_check_parallel_fallback_218.release.touch()
            out_a, err_a = first.communicate(timeout=30)
            out_b, err_b = second.communicate(timeout=30)
            assert first.returncode == second.returncode == 0, err_a + err_b
            states = [json.loads(out_a), json.loads(out_b)]
            assert [state["python_setup"]["installed"] for state in states] == [True, False]
            assert states[0]["python_setup"]["interpreter"] == states[1]["python_setup"]["interpreter"]
        finally:
            _state_check_parallel_fallback_218.release.touch()
            for process in (first, second):
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=10)
    print("Concurrent Create serializes one install without Git lock; retained setup locks protected: PASS")


@it_case
def check_symlink_safety():
    with checks.fixture() as root:
        requirements(root)
        external = root.parent / "external"
        external.mkdir()
        (external / "keep").write_text("keep")
        shared = py.shared_directory(root)
        shared.parent.mkdir(parents=True)
        shared.symlink_to(external, target_is_directory=True)
        blocked(lambda: py.setup(root, {}), "symlink")
        shared.unlink()
        shared.mkdir()
        (shared / ".blueprint-ready").write_text(str(shared))
        blocked(lambda: py.setup(root, {}), "unknown shared Python directory")
        assert (shared / ".blueprint-ready").exists()
        # Fixture explicitly owns this directory; add its ownership and exercise redirects.
        (shared / ".blueprint-owner").write_text(str(shared))
        for name in (".blueprint-owner", ".blueprint-ready", "pyvenv.cfg", py.python_path(shared).parent.name):
            path = shared / name
            if path.exists():
                path.unlink()
            path.symlink_to(external, target_is_directory=True)
            blocked(lambda: py.setup(root, {}), "symlink")
            path.unlink()
            if name.startswith(".blueprint-"):
                path.write_text(str(shared))
        assert (external / "keep").read_text() == "keep"
    print("Legacy/shared symlinks and unknown directories retained without external deletion: PASS")


if __name__ == "__main__":
    check_output_decoding()
    check_setup()
    check_real_global()
    check_venv_fallback()
    check_parallel_fallback()
    check_symlink_safety()
