#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.issue_gate_fixtures import *

def check_inventory_parser(tmp_path):
    root = tmp_path
    scope = {("dev", "cde", "ec2")}
    scope = {("dev", "cde", "ec2")}
    assert not issue_errors(root, scope)
    path = root / "issues/dev/cde/issues.md"
    path.parent.mkdir(parents=True)
    original = "# 問題一覧\n\n## dev／cde\n\n### Amazon EC2\n\n1. 不正な設定。根拠: [ec2.properties:1](../../../model/dev/cde/ec2.properties)。\n\n```text\n1. 診断のcode例\n### fake\n```\n"
    path.write_text(original)
    assert len(issue_errors(root, scope)) == 1
    assert not issue_errors(root, {("prod", "cde", "ec2")})
    assert not issue_errors(root, {("dev", "non-cde", "ec2")})
    assert not issue_errors(root, {("dev", "cde", "s3")})
    assert not issue_errors(root, set())
    assert issue_errors(root, None)
    path.write_text("### Amazon EC2\n<!-- issue-service: ec2 -->\n\n1. 設定不足\n\n2. 参照不足\n")
    assert len(issue_errors(root, scope)) == 2
    path.write_text("### ec2\n\n1. 設定不足。参照先: [s3](../../../docs/designs/dev/cde/s3.md)。\n")
    assert issue_errors(root, scope)
    assert not issue_errors(root, {("dev", "cde", "s3")})  # Explicit ownership wins over references.
    path.write_text("### Unknown service\n\n1. 設定不足\n")
    assert "ambiguous" in issue_errors(root, {("dev", "cde", "s3")})[0]
    assert issue_errors(root, scope, remediation=scope)  # Unknown ownership cannot be waived.
    path.write_text("設定不足\n")
    assert issue_errors(root, scope)
    path.write_text("# 問題一覧\n\n未解決issueなし\n")
    assert not issue_errors(root, scope)
    path.write_text("")
    assert not issue_errors(root, scope)
    (path.parent / "diff.md").write_text("### ec2\n\n1. 環境間の差分\n")
    assert not issue_errors(root, scope)  # Differences never enter the unresolved issue inventory.
    for contents in ("### ec2\n1. 差分\n", "invalid inventory; 999 differences", ""):
        (path.parent / "iac-issues.md").write_text(contents)
        assert not issue_errors(root, scope)
    path.write_text(original)
    assert issue_errors(root, scope)


    assert not issue_errors(root, {("dev", "cde", "s3")})


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
