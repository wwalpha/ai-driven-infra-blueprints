#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.worktree_python_fixtures import *

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


@it_case
def check_setup():
    with checks.fixture() as root:
        req = root / py.REQUIREMENTS
        req.parent.mkdir(parents=True)
        req.write_text("", encoding="utf-8")
        (root / ".gitignore").write_text((root / ".gitignore").read_text() + ".venv/\n")
        checks.git(root, "add", ".")
        checks.git(root, "commit", "-qm", "requirements")
        with patch.object(py, "probe_global"), patch.object(py, "verify") as verify, \
                patch.object(py, "run", side_effect=AssertionError("unexpected install or process")):
            first = wt.create(root, "one")
            second = wt.create(root, "two")
            target = Path(first["worktree"])
            for state in (first, second):
                assert state["python_setup"]["kind"] == "global"
                assert not state["python_setup"]["installed"]
                assert state["python_setup"]["interpreter"] == str(py.python_path())
                assert py.runtime(Path(state["worktree"]))[0] == py.python_path()
            path = root / ".worktrees/.blueprint/tasks/one.json"
            assert wt.load(Path(second["worktree"]), "one")[2] == path
            old = root / ".git/blueprint-worktree-tasks/one.json"
            old.parent.mkdir()
            old.write_text("invalid old state", encoding="utf-8")
            saved = path.read_bytes()
            path.unlink()
            assert py.runtime(target) is None
            path.write_bytes(saved)
            assert py.runtime(target)[0] == py.python_path()
            assert not wt.setup(root, "one")["python_setup"]["installed"]
            req = target / py.REQUIREMENTS
            req.write_text("# changed\n")
            blocked(lambda: py.runtime(target), "stale")
            assert not wt.setup(root, "one")["python_setup"]["installed"]
            verify.side_effect = ValueError("missing import")
            blocked(lambda: wt.setup(root, "one"), "unexpected install or process")
            assert not (target / ".venv").exists(), "failed process startup must not leave an empty venv"
            assert wt.load(root, "one")[3]["python_setup"]["status"] == "failed"
            blocked(lambda: py.runtime(target), "failed")
            blocked(lambda: wt.create(root, "one"), "collision")
            assert target.is_dir()
            verify.side_effect = None
            wt.setup(root, "one")
            verify.side_effect = ValueError("packages changed")
            blocked(lambda: py.runtime(target), "packages changed")
            verify.side_effect = None
            def change(*args):
                req.write_text(req.read_text() + "# concurrent change\n")
            verify.side_effect = change
            blocked(lambda: wt.setup(root, "one"), "changed during setup")
            verify.side_effect = None
            wt.setup(root, "one")
            for error in (AttributeError("unexpected setup error"), KeyboardInterrupt()):
                with patch.object(py, "setup", side_effect=error):
                    blocked(lambda: wt.setup(root, "one"), type(error).__name__)
                _, _, path, retained = wt.load(root, "one")
                assert retained["python_setup"]["status"] == "failed"
                assert path == root / ".worktrees/.blueprint/tasks/one.json"
                wt.setup(root, "one")
            _, _, path, record = wt.load(root, "one")
            record["python_setup"]["interpreter"] = "foreign"
            wt.save(path, record)
            blocked(lambda: py.runtime(target), "registration mismatch")
            wt.setup(root, "one")
            _, _, path, record = wt.load(root, "one")
            for kind in (None, "shared", "unknown"):
                if kind is None:
                    record["python_setup"].pop("kind")
                else:
                    record["python_setup"]["kind"] = kind
                wt.save(path, record)
                blocked(lambda: py.runtime(target), "kind is missing or unsupported")
            wt.setup(root, "one")
            wt.tasks.start(target, first["task_file"], checks.contract("one", [py.REQUIREMENTS]))
            wt.tasks.complete(target, first["task_file"])
            assert wt.finalize(root, "one")["cleaned"]
            assert py.python_path().is_file()
            assert py.runtime(Path(second["worktree"]))[0] == py.python_path()
    print("Global setup without creation/install, failure retention, unsupported kinds rejected and cleanup: PASS")


@it_case
def check_real_global():
    with checks.fixture() as root:
        req = root / py.REQUIREMENTS
        req.parent.mkdir(parents=True)
        req.write_text("", encoding="utf-8")
        (root / ".gitignore").write_text((root / ".gitignore").read_text() + ".venv/\n")
        checks.git(root, "add", ".")
        checks.git(root, "commit", "-qm", "requirements")
        with patch.object(py, "IMPORTS", []), patch.object(py, "run", wraps=py.run) as commands, \
                patch.dict(py.os.environ, {"PIP_NO_INDEX": "1"}):
            state = wt.create(root, "real")
            target = Path(state["worktree"])
            interpreter, env = py.runtime(target)
            data = json.loads(py.run([interpreter, "-I", "-c",
                                     "import json,sys; print(json.dumps([sys.prefix,sys.base_prefix]))"], target, env))
            assert data[0] == data[1]
            assert not any("install" in call.args[0] or "venv" in call.args[0] for call in commands.call_args_list)
    print("Real offline global Python executes without venv creation or installation: PASS")


@it_case
def check_venv_fallback():
    with checks.fixture() as root:
        req = root / py.REQUIREMENTS
        req.parent.mkdir(parents=True)
        req.write_text("# 保持日数\n", encoding="utf-8")
        (root / ".gitignore").write_text((root / ".gitignore").read_text() + ".venv/\n")
        checks.git(root, "add", ".")
        checks.git(root, "commit", "-qm", "requirements")
        verify = py.verify
        def missing_global(target, directory):
            if directory is None:
                raise ValueError("global dependency missing or incompatible")
            return verify(target, directory)
        with patch.object(py, "IMPORTS", []), patch.object(py, "verify", side_effect=missing_global), \
                patch.dict(py.os.environ, {"PIP_NO_INDEX": "1"}), patch.object(py, "run", wraps=py.run) as commands:
            first = wt.create(root, "fallback")
            target = Path(first["worktree"])
            state = first["python_setup"]
            directory = target / ".venv"
            assert state["kind"] == "venv" and state["installed"]
            assert "environment" not in state
            assert py.runtime(target)[0] == py.python_path(directory)
            data = json.loads(py.run([py.python_path(directory), "-I", "-c",
                                     "import json,sys; print(json.dumps([sys.prefix,sys.base_prefix]))"], target))
            assert Path(data[0]).resolve() == directory and data[0] != data[1]
            assert not wt.setup(root, "fallback")["python_setup"]["installed"]
            second = wt.create(root, "reuse")
            second_directory = Path(second["worktree"]) / ".venv"
            assert second_directory != directory
            assert second["python_setup"]["installed"]
            assert py.runtime(Path(second["worktree"]))[0] == py.python_path(second_directory)
            installs = [call.args[0] for call in commands.call_args_list if "install" in call.args[0]]
            assert len(installs) == 2 and installs[0][0] == py.python_path(directory)
            assert installs[0][-2:] == ["-r", str(target / py.REQUIREMENTS)]
            _, _, path, record = wt.load(root, "fallback")
            for field in ("interpreter", "bin"):
                registered = record["python_setup"][field]
                record["python_setup"][field] = str(root / "shared" / field)
                wt.save(path, record)
                blocked(lambda: py.runtime(target), "venv Python registration mismatch")
                record["python_setup"][field] = registered
            wt.save(path, record)
            assert py.runtime(target)[0] == py.python_path(directory)
            broken = True
            def broken_cache(target, selected):
                nonlocal broken
                if selected == directory and broken:
                    broken = False
                    raise ValueError("worktree dependency is broken")
                return missing_global(target, selected)
            with patch.object(py, "verify", side_effect=broken_cache):
                repaired = wt.setup(root, "fallback")["python_setup"]
            assert repaired["installed"] and repaired["interpreter"] == str(py.python_path(directory))
            assert directory.is_dir()
            (target / py.REQUIREMENTS).write_text("missing-blueprint-dependency==0.0.0\n", encoding="utf-8")
            blocked(lambda: wt.setup(root, "fallback"), "Python setup command failed")
            failed = wt.load(root, "fallback")[3]
            assert failed["python_setup"]["status"] == "failed" and target.is_dir()
            assert directory.is_dir() and py.runtime(Path(second["worktree"]))[0] == py.python_path(second_directory)
            (target / py.REQUIREMENTS).write_bytes(req.read_bytes())
            assert wt.setup(root, "fallback")["python_setup"]["installed"]
        # Once global verification succeeds, prefer it over the already available venv.
        with patch.object(py, "verify"), patch.object(py, "run", side_effect=AssertionError("unexpected installation")), \
                patch.object(py, "probe_global"):
            assert wt.setup(root, "fallback")["python_setup"]["kind"] == "global"
        assert directory.is_dir()
        wt.tasks.start(target, first["task_file"], checks.contract("fallback", [py.REQUIREMENTS]))
        wt.tasks.complete(target, first["task_file"])
        assert wt.finalize(root, "fallback")["cleaned"]
        assert second_directory.is_dir()
    print("Real offline per-worktree venvs, strict registration, repair, retry and venv cleanup: PASS")


@it_case
def check_parallel_fallback():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    with checks.fixture() as root:
        req = root / py.REQUIREMENTS
        req.parent.mkdir(parents=True)
        req.write_text("", encoding="utf-8")
        checks.git(root, "add", ".")
        checks.git(root, "commit", "-qm", "requirements")
        installing_a, installing_b, release = Event(), Event(), Event()
        def verify(target, directory):
            if directory is None:
                raise ValueError("missing global dependency")
        def run(command, target, env=None):
            if "install" in command:
                (installing_a if target.name == "parallel-a" else installing_b).set()
                assert release.wait(timeout=10)
            return ""
        with patch.object(py, "probe_global"), patch.object(py, "verify", side_effect=verify), \
                patch.object(py, "probe", return_value=sys.version), patch.object(py, "run", side_effect=run) as commands:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(wt.create, root, "parallel-a")
                assert installing_a.wait(timeout=10)
                second = pool.submit(wt.create, root, "parallel-b")
                try:
                    assert installing_b.wait(timeout=10)
                finally:
                    release.set()
                states = [first.result(), second.result()]
            assert states[0]["python_setup"]["interpreter"] != states[1]["python_setup"]["interpreter"]
            assert all(state["python_setup"]["installed"] for state in states)
            assert sum("install" in call.args[0] for call in commands.call_args_list) == 2
            lock = wt.load(root, "parallel-a")[2].with_suffix(".setup-lock")
            assert lock == root / ".worktrees/.blueprint/tasks/parallel-a.setup-lock"
            lock.mkdir()
            blocked(lambda: wt.setup(root, "parallel-a"), "Python setup busy")
            assert lock.is_dir()
            lock.rmdir()  # The fixture owns this simulated retained lock.
    print("Concurrent worktrees install separately; retained per-task setup lock fails safely: PASS")


@it_case
def check_symlink_safety():
    with checks.fixture() as root:
        external = root.parent / "external"
        external.mkdir()
        (external / "keep").write_text("keep")
        directory = root / ".venv"
        directory.symlink_to(external, target_is_directory=True)
        blocked(lambda: py.remove(root), "unexpected")
        blocked(lambda: py.setup(root, {}), "unexpected")
        assert (external / "keep").exists()
        directory.unlink()
        directory.mkdir()
        blocked(lambda: py.remove(root), "no Python environment configuration")
        blocked(lambda: py.setup(root, {}), "no Python environment configuration")
        (directory / "pyvenv.cfg").write_text("home = fixture\n")
        (directory / "external").symlink_to(external, target_is_directory=True)
        py.remove(root)
        assert (external / "keep").exists()
    print("Unmanaged/symlink .venv and external deletion boundary: PASS")


if __name__ == "__main__":
    check_output_decoding()
    check_setup()
    check_real_global()
    check_venv_fallback()
    check_parallel_fallback()
    check_symlink_safety()

