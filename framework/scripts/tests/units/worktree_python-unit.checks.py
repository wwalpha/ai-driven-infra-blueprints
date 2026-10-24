#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from contextlib import nullcontext
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from support.worktree_python_fixtures import (
    Path,
    blocked,
    fake_run,
    importlib,
    json,
    patch,
    py,
    sys,
    tempfile,
    wt,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_environment():
    scripts = Path(__file__).resolve().parents[2]
    for first, second in (('worktree_python', 'worktree_task'), ('worktree_task', 'worktree_python')):
        code = (f"import sys; sys.path.insert(0, {str(scripts)!r}); "
                f"import {first}; import {second}; import worktree_python, worktree_state; "
                "assert worktree_python.wt is worktree_state")
        result = py.subprocess.run([sys.executable, '-I', '-B', '-c', code],
                                   capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
    with patch.dict(py.os.environ, {"VIRTUAL_ENV": "foreign", "PYTHONHOME": "foreign", "PYTHONPATH": "foreign"}):
        env = py.environment()
        assert not any(name in env for name in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"))
        assert env["PATH"].split(py.os.pathsep)[0] == str(py.python_path().parent)







def _check_pdf_native_optional_import_module(name):
    if name == 'weasyprint':
        raise OSError("cannot load library 'libgobject-2.0-0': error 0x7e")


def _check_pdf_native_optional_run(command, root, env):
    if '-c' in command:
        exec(command[-1], {})
    return ''


def check_pdf_native_optional():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        requirements = root / py.REQUIREMENTS
        requirements.parent.mkdir(parents=True)
        requirements.write_text("PyYAML==6.0.3\nweasyprint==70.0\n", encoding="utf-8")
        import_module = _check_pdf_native_optional_import_module
        run = _check_pdf_native_optional_run
        with patch.object(py, "run", side_effect=run) as commands, \
                patch.object(importlib, "import_module", side_effect=import_module) as imports, \
                patch.object(importlib.metadata, "version", side_effect={"PyYAML": "6.0.3", "weasyprint": "70.0"}.__getitem__) as versions:
            py.verify(root, root / ".venv")
            assert commands.call_args_list[0].args[0][-2:] == ["pip", "check"]
            assert "weasyprint" not in [call.args[0] for call in imports.call_args_list]
            assert "weasyprint" in [call.args[0] for call in versions.call_args_list]
            imports.side_effect = ImportError("core dependency is broken")
            blocked(lambda: py.verify(root, root / ".venv"), "core dependency is broken")
            imports.side_effect = import_module
            versions.side_effect = lambda name: "wrong"
            blocked(lambda: py.verify(root, root / ".venv"), "requirement versions differ")
    print("Missing PDF native library allowed; core imports, pip check and pinned PDF version retained: PASS")


def check_windows_exit_propagation(tmp_path):
    spec = importlib.util.spec_from_file_location("python_wrapper", (Path(__file__).resolve().parents[2] / "run-python.py"))
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    for code in (0, 2, 7, 130):
        with patch.object(wrapper.worktree_python, "runtime", return_value=None), \
             patch.object(wrapper.sys, "platform", "win32"), \
             patch.object(wrapper.sys, "argv", ["run-python.py", "-c", f"raise SystemExit({code})"]), \
             patch.object(wrapper.os, "execvpe", side_effect=AssertionError("Windows must wait")):
            assert wrapper.main() == code


@pytest.mark.parametrize('encoding', ['cp932', 'utf-8'])
@pytest.mark.parametrize('stderr', [False, True])
@pytest.mark.parametrize('returncode', [0, 7])
def check_output_decoding(tmp_path, encoding, stderr, returncode):
    output = 'セットアップ出力\n'.encode(encoding).decode('utf-8', errors='replace')
    error = 'エラー詳細\n'.encode(encoding).decode('utf-8', errors='replace') if stderr else ''
    result = SimpleNamespace(returncode=returncode, stdout=output, stderr=error)
    with patch.object(py.subprocess, 'run', return_value=result) as run:
        if returncode:
            with pytest.raises(ValueError) as caught:
                py.run(['python', 'setup'], tmp_path)
            assert str(caught.value).endswith(error or output)
            assert 'command failed (7)' in str(caught.value)
        else:
            assert py.run(['python', 'setup'], tmp_path) == output.strip()
    assert run.call_args.kwargs == dict(cwd=tmp_path, env=None, capture_output=True, encoding='utf-8', errors='replace')


def check_wrapper_launcher():
    spec = importlib.util.spec_from_file_location('python_wrapper', Path(py.__file__).with_name('run-python.py'))
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    with patch.object(wrapper.worktree_python, 'runtime', return_value=None) as runtime, \
         patch.object(wrapper.os, 'execvpe') as execute, patch.object(wrapper.sys, 'platform', 'linux'), \
         patch.object(wrapper.sys, 'argv', ['wrapper', '-c', 'pass']):
        wrapper.main()
    assert execute.call_args.args[1] == [sys.executable, '-c', 'pass']
    runtime.assert_called_once_with(Path.cwd().resolve())


@pytest.mark.parametrize('field,value,message', [
    ('state', None, 'state missing'), ('status', None, 'missing or failed'), ('status', 'failed', 'missing or failed'),
    ('kind', None, 'unsupported'), ('kind', 'global', 'unsupported'), ('kind', 'venv', 'unsupported'),
    ('kind', 'unknown', 'unsupported'), ('interpreter', 'foreign', 'registration mismatch'),
    ('bin', 'foreign', 'registration mismatch'),
])
def check_runtime_registration(tmp_path, field, value, message):
    target = tmp_path / '.worktrees/example'
    directory = tmp_path / '.worktrees/.blueprint/python-env'
    state = dict(task_id='example', worktree=str(target), python_setup=py.setup_result(directory, False))
    path = directory.parent / 'tasks/example.json'
    path.parent.mkdir(parents=True)
    if field != 'state':
        state['python_setup'][field] = value
        path.write_text(json.dumps(state))
    with patch.object(py.wt, 'repository', return_value=(target, None, tmp_path)), \
         patch.object(py.wt, 'load', return_value=(tmp_path, None, path, state)), \
         patch.object(py, 'run', side_effect=AssertionError('runtime must not launch Python')):
        blocked(lambda: py.runtime(target), message)


def _setup_failure_run(stage, command, root, env=None):
    if stage in command:
        raise ValueError('fixture ' + stage + ' failed')
    return fake_run(command, root, env)


def _setup_failure_mkdir(original, stage, path, *args, **kwargs):
    if stage == 'permission' and path.name == 'python-env.setup-lock':
        raise PermissionError('fixture permission denied')
    return original(path, *args, **kwargs)


@pytest.mark.parametrize('stage', ['venv', 'install', 'verify', 'permission', 'exception', 'interrupt'])
def check_setup_failure_recovery(tmp_path, stage):
    target = tmp_path / '.worktrees/example'
    shared = tmp_path / '.worktrees/.blueprint/python-env'
    path = shared.parent / 'tasks/example.json'
    path.parent.mkdir(parents=True)
    state = dict(task_id='example', worktree=str(target), merged=None)
    failure = AttributeError('unexpected setup error') if stage == 'exception' else KeyboardInterrupt()
    mkdir = partial(_setup_failure_mkdir, Path.mkdir, stage)
    with patch.object(wt, 'load', return_value=(tmp_path, None, path, state)), \
         patch.object(wt, 'task_worktree', return_value=target), patch.object(wt, 'lifecycle_lock', return_value=nullcontext()), \
         patch.object(py, 'shared_directory', return_value=shared), patch.object(py, 'probe'), \
         patch.object(py, 'run', side_effect=partial(_setup_failure_run, stage)), \
         patch.object(py, 'verify', side_effect=ValueError('fixture verify failed') if stage == 'verify' else None), \
         patch.object(Path, 'mkdir', autospec=True, side_effect=mkdir):
        with patch.object(py, 'setup', side_effect=failure) if stage in {'exception', 'interrupt'} else nullcontext():
            blocked(lambda: wt.setup(tmp_path, 'example'), 'Python setup failed')
        assert json.loads(path.read_text())['python_setup']['status'] == 'failed'
        assert not (shared / '.blueprint-ready').exists()
    with patch.object(py, 'shared_directory', return_value=shared), patch.object(py, 'probe'), \
         patch.object(py, 'verify') as verify, patch.object(py, 'run', side_effect=fake_run) as commands:
        assert py.setup(target, {})['installed']
        count = commands.call_count
        assert not py.setup(target, {})['installed']
        assert commands.call_count == count
        assert verify.call_count == 1
        assert sum('install' in c.args[0] for c in commands.call_args_list) == 1


def check_setup_lock_timeout(tmp_path):
    shared = tmp_path / 'python-env'
    lock = shared.with_name('python-env.setup-lock')
    lock.mkdir()
    with patch.object(py, 'shared_directory', return_value=shared), \
         patch.object(py.time, 'monotonic', side_effect=[0, 301]), \
         patch.object(py.time, 'sleep', side_effect=AssertionError('timeout must not sleep')):
        blocked(lambda: py.setup(tmp_path, {}), 'shared Python setup lock busy')
    assert lock.is_dir() and not shared.exists()
    path = tmp_path / 'example.json'
    task_lock = path.with_suffix('.setup-lock')
    task_lock.mkdir()
    with patch.object(wt, 'load', return_value=(tmp_path, None, path, {})):
        blocked(lambda: wt.setup(tmp_path, 'example'), 'Python setup busy')
    assert task_lock.is_dir()


@pytest.mark.parametrize('name', ['directory', '.blueprint-owner', '.blueprint-ready', 'pyvenv.cfg', 'bin'])
def check_shared_symlinks(tmp_path, name):
    shared, external = tmp_path / 'python-env', tmp_path / 'external'
    shared.mkdir()
    external.mkdir()
    (shared / '.blueprint-owner').write_text(str(shared))
    (shared / '.blueprint-ready').write_text(str(shared))
    path = shared if name == 'directory' else shared / (py.python_path(shared).parent.name if name == 'bin' else name)
    if path == shared:
        for child in shared.iterdir():
            child.unlink()
        shared.rmdir()
    elif path.exists():
        path.unlink()
    path.symlink_to(external, target_is_directory=True)
    blocked(lambda: py.shared_ready(shared), 'symlink')
    assert path.is_symlink() and not list(external.iterdir())


@pytest.mark.parametrize('problem', ['unknown', 'executable', 'configuration', 'marker'])
def check_shared_completion(tmp_path, problem):
    shared = tmp_path / 'python-env'
    shared.mkdir()
    (shared / '.blueprint-ready').write_text(str(shared))
    if problem != 'unknown':
        (shared / '.blueprint-owner').write_text(str(shared))
    if problem in {'configuration', 'marker'}:
        py.python_path(shared).parent.mkdir()
        py.python_path(shared).touch()
    if problem == 'marker':
        (shared / '.blueprint-ready').write_text('foreign')
    expected = {'unknown': 'unknown shared', 'executable': 'executable missing', 'configuration': 'configuration missing', 'marker': 'invalid shared'}
    blocked(lambda: py.shared_ready(shared), expected[problem])
    assert shared.is_dir()


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
