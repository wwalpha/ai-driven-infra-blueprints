#!/usr/bin/env python3
"""Real Policy CLI validates then publishes derived Markdown without changing JSON."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from support.policy_tables_fixtures import (
    SCRIPTS,
    iam_fixture,
    policy_cli,
    rendered_design,
    run,
    subprocess,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_iam(tmp_path):
    path, artifacts, _, _, text = iam_fixture(tmp_path)
    before = {file: file.read_bytes() for file in artifacts.iterdir()}
    rendered = rendered_design(path)
    # --write updates only derived Markdown and requires an explicit file.
    path.write_text(text, encoding="utf-8")
    check = policy_cli([str(path)])
    assert check.returncode == 1 and path.read_text(encoding="utf-8") == text
    assert b"policy tables are stale; regenerate with --write" in check.stderr
    write = subprocess.run([sys.executable, str(SCRIPTS / "policy_tables.py"), str(path), "--write"], capture_output=True)
    assert write.returncode == 0, write.stderr
    assert write.stdout == b"Policy tables: PASS\n" and write.stderr == b""
    assert path.read_text(encoding="utf-8") == rendered

    assert before == {file: file.read_bytes() for file in before}


if __name__ == '__main__':
    raise SystemExit(run(__file__))
