#!/usr/bin/env python3
"""Focused check for shared assets, root entrypoints, and synchronization boundaries."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("sync-existing-files.py")


def main() -> None:
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
