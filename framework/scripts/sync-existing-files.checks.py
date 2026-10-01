#!/usr/bin/env python3
"""Focused check for shared assets, root entrypoints, and synchronization boundaries."""

from __future__ import annotations

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("sync-existing-files.py")
SPEC = importlib.util.spec_from_file_location("sync_existing_files", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def check_failure_safety() -> None:
    missing_target = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert missing_target.returncode != 0 and "--target" in missing_target.stderr
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "source"
        target = Path(directory) / "target"
        (source / "framework").mkdir(parents=True)
        (source / ".agents").mkdir()
        target.mkdir()
        target = target.resolve()
        for relative in ("framework/a.txt", "framework/b.txt", "AGENTS.md", "README.md"):
            (source / relative).write_text("original\n", encoding="utf-8")

        def run() -> int:
            with mock.patch.object(MODULE, "FRAMEWORK_ROOT", source / "framework"), mock.patch.object(
                MODULE, "REPOSITORY_ROOT", source
            ), mock.patch.object(sys, "argv", [str(SCRIPT), "--target", str(target)]), redirect_stdout(
                io.StringIO()
            ), redirect_stderr(io.StringIO()):
                return MODULE.main()

        assert run() == 0
        (target / "framework/b.txt").unlink()
        original = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
        (source / "framework/a.txt").write_text("updated\n", encoding="utf-8")
        (source / "README.md").write_text("updated\n", encoding="utf-8")
        copy2 = shutil.copy2
        failed = False

        def fail_once(src: Path, dst: Path, *args: object, **kwargs: object) -> str:
            nonlocal failed
            if Path(dst) == target / "README.md" and not failed:
                failed = True
                raise OSError("injected copy failure")
            return copy2(src, dst, *args, **kwargs)

        with mock.patch.object(MODULE.shutil, "copy2", side_effect=fail_once):
            result = run()
            assert result == 1, (result, failed)
        assert failed
        assert {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()} == original

        new_source = source / "framework/new.txt"
        new_source.write_text("new\n", encoding="utf-8")
        with mock.patch.object(Path, "is_symlink", lambda self: self == new_source):
            assert run() == 1
        assert not (target / "framework/new.txt").exists()


def main() -> None:
    check_failure_safety()
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        protected = ("project.json", "docs/keep.md", "infra/keep.yaml", "model/keep.properties", "tasks/active.md", "tests/keep.py")
        for relative in protected:
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("target-specific", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--target", str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert (target / "framework" / "scripts" / SCRIPT.name).is_file()
        skill = Path(__file__).resolve().parents[2] / ".agents/skills/initialize/SKILL.md"
        assert (target / ".agents/skills/initialize/SKILL.md").read_bytes() == skill.read_bytes()
        root = SCRIPT.resolve().parents[2]
        for name in ("AGENTS.md", "README.md"):
            assert (target / name).read_bytes() == (root / name).read_bytes()
            (target / name).write_text("outdated", encoding="utf-8")
        command = [sys.executable, str(SCRIPT), "--target", str(target)]
        preview = subprocess.run([*command, "--dry-run"], capture_output=True, text=True)
        assert preview.returncode == 0, preview.stderr
        assert "pending=2" in preview.stdout, preview.stdout
        for name in ("AGENTS.md", "README.md"):
            assert f"WOULD COPY: {name}" in preview.stdout
            assert (target / name).read_text(encoding="utf-8") == "outdated"
        updated = subprocess.run(command, capture_output=True, text=True)
        assert updated.returncode == 0, updated.stderr
        assert "copied=2 added=0 pending=0" in updated.stdout, updated.stdout
        for name in ("AGENTS.md", "README.md"):
            assert (target / name).read_bytes() == (root / name).read_bytes()
        repeated = subprocess.run([*command, "--dry-run"], capture_output=True, text=True)
        assert repeated.returncode == 0, repeated.stderr
        assert "pending=0" in repeated.stdout, repeated.stdout
        assert "scope=framework,.agents,AGENTS.md,README.md" in repeated.stdout
        assert "excluded=project.json,docs,infra,model,tasks,tests" in repeated.stdout
        for relative in protected:
            assert (target / relative).read_text(encoding="utf-8") == "target-specific"
            if "/" in relative:
                assert {path.relative_to(target).as_posix() for path in (target / relative.split("/")[0]).rglob("*") if path.is_file()} == {relative}
    print("sync-existing-files: PASS")


if __name__ == "__main__":
    main()
