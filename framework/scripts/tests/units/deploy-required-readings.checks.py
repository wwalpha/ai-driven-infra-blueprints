#!/usr/bin/env python3
"""Markdown section boundaries used by static document validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from support.pytest_cli import run
from validation import framework_contracts
from validation.findings import Findings

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_deploy_skill_structure_uses_definition_root(tmp_path):
    root, definitions = tmp_path / "consumer", tmp_path / "definitions"
    root.mkdir()
    skill = definitions / ".agents/skills/deploy/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Deploy\n", encoding="utf-8")
    for present in (True, False):
        if not present:
            skill.unlink()
        findings = Findings(root)
        framework_contracts.check_structure(
            findings, root, definitions_root=definitions
        )
        missing = "required file missing: .agents/skills/deploy/SKILL.md"
        assert (missing in findings.errors) is not present


pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == "__main__":
    raise SystemExit(run(__file__))
