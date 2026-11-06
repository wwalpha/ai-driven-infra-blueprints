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
from validation import framework_contracts
from validation.findings import Findings

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
    source = root / "framework/prompts/codex/deployment-notes.md"
    source.parent.mkdir(parents=True)
    with pytest.raises((OSError, ValueError)):
        rule_readings(root, source, f"[rule](../../rules/{target})")


def check_direct_deploy_routes():
    root = Path(__file__).resolve().parents[4]
    skill = root / ".agents/skills/deploy/SKILL.md"
    text = skill.read_text(encoding="utf-8")
    sections = markdown_sections(text)
    runbook = root / "framework/prompts/codex/deploy/runbook.md"
    book = runbook.read_text(encoding="utf-8")
    # Startup exposes only advance; later exact commands have one conditional authority.
    startup = re.findall(r"```console\n(.*?)```", text, re.S)
    assert ["--action" in block for block in startup] == [False, True]
    blocks = startup + re.findall(r"```console\n(.*?)```", book, re.S)
    commands = [shlex.split(line) for block in blocks for line in block.splitlines()]
    actions = [argv for argv in commands if "--action" in argv]
    assert [argv[argv.index("--action") + 1] for argv in actions] == [
        "advance",
        "sync",
        "checkpoint",
        "status",
        "sync",
    ]
    for argv in actions:
        assert "BLUEPRINT_TASK_FILE=tasks/<task-id>.md" in argv
        assert all(flag in argv for flag in ("--environment", "--alias", "--stack"))
        assert "framework/scripts/cloudformation-deploy.py" in argv
        assert "framework/scripts/run-python.py" not in argv
    assert "--final" in actions[-1] and "--final" not in actions[2]
    assert "04_deploy.md" not in text
    assert "SDK is the default; CLI requires an explicit Human choice" in text
    assert "never search, inspect or read Framework Python source" in text
    assert "null/missing command means stop" in text
    # Each conditional route resolves to a real procedure, rather than a compatibility stub.
    procedures = markdown_sections(book)
    links = set(re.findall(r"deploy/runbook.md#([a-z-]+)", text))
    for entry in ("sdk-saves", "sdk-finish"):
        links.update(re.findall(r"\]\(#([a-z-]+)\)", procedures[entry]))
    for anchor in (
        "cli-prepare",
        "sdk-saves",
        "sdk-finish",
        "observation-reads",
        "verify-and-finish",
        "terraform",
        "confirm-unapproved-deletereplacement",
        "unfinished-aws-operation-recovery",
        "correct-this-tasks-preparation-omissions",
        "external-iac-repair-handoff",
    ):
        assert anchor in links, anchor
    # Independent CLI How remains reachable without SDK command/receipt dependencies.
    expected = {
        "cli-prepare": ("method-and-local-lifecycle", "preflight-and-fixed-snapshot"),
        "cli-delivery": (
            "order-dependencies-and-s3-delivery",
            "s3-deployment-artifacts",
        ),
        "cli-changeset": ("changeset-review-and-execution",),
        "cli-execute": ("changeset-review-and-execution",),
        "cli-observe-and-save": ("observations-validation-and-publication",),
        "cli-finish": ("observations-validation-and-publication",),
        "cli-recovery": ("interruption-and-independent-recovery",),
    }
    for anchor, required in expected.items():
        readings = rule_readings(root, runbook, procedures[anchor])
        actual = readings[root / "framework/rules/cloudformation.md"]["sections"]
        assert set(required) <= set(actual), anchor
        assert "cloudformation-deploy.py" not in procedures[anchor]
    assert "--action" not in sections["common-entry"]
    assert "no unconditional status-before-advance call" in sections["sdk-operations"]
    entry = sections["local-entry"]
    assert "calling repository root" in entry
    assert "unused Task ID" in entry
    assert "original Task" in entry
    assert (
        "Deploy Preparation, AWS execution, Observed / View synchronization, Validation and Task completion"
        in entry
    )
    assert "create --task-name <task-name>" in entry
    assert "returned six-digit-suffixed Task ID" in entry
    assert "does not create, set up, finalize or clean up a Worktree" in entry
    assert "automatically commit, merge, push or publish Git changes" in entry
    assert "deploy-start" not in text
    worktree = (root / ".agents/skills/worktree/SKILL.md").read_text(encoding="utf-8")
    optional = markdown_sections(worktree)["optional-deploy-use"]
    assert "does not require a Worktree" in optional
    assert "ordinary `create --task-name <task-name>`" in optional
    assert "returned Task ID and local root" in optional
    assert "deploy-start" not in worktree
    assert "Normal Deploy Stack checkpoints" not in worktree
    assert "## Explicit CloudFormation repair handoff" in worktree
    permission = markdown_sections(
        (root / ".agents/skills/worktree/SKILL.md").read_text(encoding="utf-8")
    )["sandbox-permission-approval-and-continuation"]
    assert "in the relevant checkout only" in permission
    assert "Python chooses and checks the Task ID under its lock" in permission
    assert "git worktree list" not in permission


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
