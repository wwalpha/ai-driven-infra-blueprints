#!/usr/bin/env python3
"""Markdown section boundaries used by static document validation."""

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from support.pytest_cli import run
from utils.markdown_format import markdown_sections, rule_readings

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_rule_section_boundaries():
    text = "# Rules\r\n\r\n## Required\r\nkeep\r\n```md\r\n## Required\r\n```\r\n### Child\r\nchild\r\n## Unrelated\r\nomit\r\n"
    text = text.replace(
        "## Required\r\nkeep", '<a id="explicit"></a>\r\n\r\n## Required\r\nkeep'
    )
    sections = markdown_sections(text)
    assert sections["explicit"] == sections["required"]
    assert "child" in sections["required"] and "omit" not in sections["required"]
    for ambiguous in (
        "## Duplicate\nsame\n## Duplicate\nsame\n",
        '<a id="shared"></a>\n## One\nfirst\n<a id="shared"></a>\n## Two\nsecond\n',
    ):
        try:
            markdown_sections(ambiguous)
        except ValueError as error:
            assert "ambiguous rule section" in str(error)
        else:
            raise AssertionError("duplicate heading/anchor accepted")
    assert "same" in markdown_sections('<a id="same"></a>\n## Same\nrule\n')
    # Required child exceptions and stop conditions remain inside the selected range.
    nested = (
        "## Required\nrule\n### Exception\nstop on missing input\n## Optional\nomit\n"
    )
    assert (
        markdown_sections(nested)["required"]
        == "## Required\nrule\n### Exception\nstop on missing input\n"
    )


@pytest.mark.parametrize("target", ["missing.md#required", "rules.md#missing"])
def check_broken_rule_reference_rejected(tmp_path, target):
    root = tmp_path
    rules = root / "framework/rules"
    rules.mkdir(parents=True)
    (rules / "rules.md").write_text("## Required\nbody\n")
    source = root / "framework/prompts/codex/04_deploy.md"
    source.parent.mkdir(parents=True)
    with pytest.raises((OSError, ValueError)):
        rule_readings(root, source, f"[rule](../../rules/{target})")



def check_direct_deploy_routes():
    root = Path(__file__).resolve().parents[4]
    skill = root / ".agents/skills/deploy/SKILL.md"
    text = skill.read_text(encoding="utf-8")
    sections = markdown_sections(text)
    # Executable SDK examples live at the entry, with fixed Task/target on every action.
    blocks = re.findall(r"```console\n(.*?)```", text, re.S)
    commands = [shlex.split(line) for block in blocks for line in block.splitlines()]
    actions = [argv for argv in commands if "--action" in argv]
    assert [argv[argv.index("--action") + 1] for argv in actions] == [
        "advance", "sync", "checkpoint", "status", "sync"
    ]
    for argv in actions:
        assert "BLUEPRINT_TASK_FILE=tasks/<task-id>.md" in argv
        assert all(flag in argv for flag in ("--environment", "--alias", "--stack"))
        assert "framework/scripts/run-python.py" in argv
    assert "--final" in actions[-1] and "--final" not in actions[2]
    assert "04_deploy.md" not in text
    assert "SDK is the default; CLI requires an explicit Human choice" in text
    assert "never search, inspect or read Framework Python source" in text
    assert "null/missing command means stop" in text
    # Each conditional route resolves to a real procedure, rather than a compatibility stub.
    runbook = root / "framework/prompts/codex/deploy/runbook.md"
    procedures = markdown_sections(runbook.read_text(encoding="utf-8"))
    links = re.findall(r"deploy/runbook.md#([a-z-]+)", text)
    assert set(links) <= procedures.keys()
    for anchor in (
        "cli-prepare", "observation-reads", "verify-and-finish", "terraform",
        "confirm-unapproved-deletereplacement", "unfinished-aws-operation-recovery",
        "correct-this-tasks-preparation-omissions", "external-iac-repair-handoff", "git-recovery",
    ):
        assert anchor in links
    assert "--action" not in sections["common-entry"]
    assert "no unconditional status-before-advance call" in sections["sdk-operations"]
    rule_readings(root, skill, text)


pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == "__main__":
    raise SystemExit(run(__file__))
