#!/usr/bin/env python3
"""Deploy Rules selection/snapshot parity without a runtime prompt dependency."""

import hashlib
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import preparation as M
from deploy import required_readings as readings
from support.deploy_preparation_fixtures import ROOT, STACKS, fixture
from utils.markdown_format import markdown_sections, rule_readings

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

# Archived reading route, not the current prompt; explicitly preserves even redundant anchors.
LEGACY_LINKS = """[task](../../rules/task-contract.md)
[policy](../../rules/detailed-design.md#policy-account-selection)
[stacks](../../rules/detailed-design.md#cloudformation-stack-detailed-design)
[authority](../../rules/model-information.md#model-authority)
[mode](../../rules/model-information.md#resource-management-mode)
[format](../../rules/model-information.md#properties-format)
[generation](../../rules/model-information.md#properties-first-updates-and-display-generation)
[deployment](../../rules/model-information.md#cloudformation-deployment-policy)
[CFn](../../rules/cloudformation.md) [TF](../../rules/terraform.md)
[observed](../../rules/observed-values.md)
[local](../../rules/loop-engineering.md#local-loop)
[scope](../../rules/loop-engineering.md#validation-scope)
[finish](../../rules/loop-engineering.md#infrastructure-task-completion)
[project](../../rules/project-configuration.md)
[repair](../../rules/cloudformation.md#controlled-deploy-repair)
"""


def check_workflow_contract():
    old = rule_readings(
        ROOT,
        ROOT / "framework/prompts/codex/04_deploy.md",
        LEGACY_LINKS,
        engine="cloudformation",
    )
    current = readings.required_readings(ROOT)
    assert len(current) == 7 and current.keys() == old.keys()
    for path, entry in current.items():
        assert entry == old[path]
        assert (
            hashlib.sha256(entry["text"].encode()).digest()
            == hashlib.sha256(old[path]["text"].encode()).digest()
        )
        assert (
            hashlib.sha256(entry["sourceText"].encode()).digest()
            == hashlib.sha256(path.read_bytes()).digest()
        )


def check_prompt_independent_snapshot_and_registration(tmp_path):
    root, definitions, run = (
        tmp_path / "repo",
        tmp_path / "definitions",
        tmp_path / "prepare",
    )
    fixture(root)
    for relative in [
        ".agents/skills/deploy/SKILL.md",
        *["framework/rules/" + name for name in readings.REQUIRED_READINGS],
    ]:
        path = definitions / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    prompt = definitions / "framework/prompts/codex/04_deploy.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# Unrelated heading\nNo rule links.\n")
    run.mkdir()
    args = SimpleNamespace(
        task_file="tasks/deploy-test.md",
        service=["ec2", "iam"],
        environment="dev",
        aws_account_id="123456789012",
        alias=None,
        stack=STACKS,
        profile=None,
        sequential=True,
    )
    timing = M.Timing(root)
    with (
        patch.object(
            M, "environment", return_value={"python": sys.executable, "tools": {}}
        ),
        patch.object(M, "definition_root", return_value=definitions),
        patch.object(readings, "definition_root", return_value=definitions),
    ):
        plan = M.prepare(root, args, run, timing)
        assert "framework/prompts/codex/04_deploy.md" not in plan["inputs"]
        assert (
            len(
                [
                    d
                    for d in plan["documents"]
                    if d["source"].startswith("framework/rules/")
                ]
            )
            == 7
        )
        for doc in plan["documents"]:
            if doc["source"].startswith("framework/rules/"):
                entry = readings.required_readings(root)[definitions / doc["source"]]
                assert (
                    "".join(Path(c).read_text() for c in doc["chunks"]) == entry["text"]
                )
                assert (
                    doc["sha256"]
                    == hashlib.sha256(entry["sourceText"].encode()).hexdigest()
                )
        plan.update(preparationSeconds=0)
        path = run / "preparation.json"
        path.write_text(json.dumps(plan))
        prompt.unlink()  # Even a missing prompt cannot select or invalidate execution Rules.
        task = root / args.task_file
        task.parent.mkdir()
        shutil.copyfile(plan["contract"], task)
        with patch.object(
            M.subprocess, "run", return_value=SimpleNamespace(returncode=0)
        ):
            assert M.register(root, path, timing)["registeredContractDigest"]
        rule = definitions / "framework/rules/detailed-design.md"
        rule.write_text(rule.read_text() + "\nUnselected section changed.\n")
        with pytest.raises(M.cli_guidance.InputChanged):
            M.register(root, path, timing)


def check_missing_rule_section_stops(tmp_path):
    for name in readings.REQUIRED_READINGS:
        path = tmp_path / "framework/rules" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "framework/rules" / name, path)
    path = tmp_path / "framework/rules/detailed-design.md"
    path.write_text(
        path.read_text().replace(
            "## Policy account selection", "## Renamed policy section"
        )
    )
    with (
        patch.object(readings, "definition_root", return_value=tmp_path),
        pytest.raises(ValueError, match="missing required Deploy rule section"),
    ):
        readings.required_readings(tmp_path)


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


pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
