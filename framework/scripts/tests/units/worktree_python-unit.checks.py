#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from support.worktree_python_fixtures import (
    Path,
    blocked,
    importlib,
    patch,
    py,
    sys,
    tempfile,
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


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
