#!/usr/bin/env python3
"""Contract checks for validation guidance and conditional read routing."""

import re
import sys
from pathlib import Path

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from utils.markdown_format import markdown_sections, rule_readings

ROOT = Path(__file__).resolve().parents[4]
RULE = ROOT / "framework/rules/loop-engineering.md"
TEXT = RULE.read_text(encoding="utf-8")


def section(name):
    anchor = re.sub(r"[^\w -]", "", name.lower()).replace(" ", "-")
    return markdown_sections(TEXT)[anchor]


def readings(text):
    return rule_readings(ROOT, RULE, text)


def require_anchors(text, path, anchors):
    found = readings(text).get(path.resolve())
    assert found and set(anchors) <= set(found["sections"]), (path, anchors, found)


def check_routes_and_selection():
    local = section("Local loop")
    policy = section("Validation policy")
    regression = section("Framework regression")
    execution = section("Local loop execution")
    change = section("Change Validation and Full Model Validation")
    windows = section("Windows full regression input guard")
    for anchor in (
        "validation-policy",
        "local-loop-execution",
        "change-validation-and-full-model-validation",
        "framework-regression",
        "windows-full-regression-input-guard",
    ):
        assert f"(loop-engineering.md#{anchor})" in local
    assert "(loop-engineering.md#local-loop)" in policy
    assert "its conditional mandatory reads" in policy
    assert (
        "If a loop is required" in local
        and "If classification, OS or execution form is uncertain" in local
    )
    assert (
        "the OS is Windows and the run uses `full` or `--all`" in regression
        and "otherwise stop" in regression
    )
    assert "## Windows full regression" not in regression
    for phrase in (
        "Markdown, Skill or Prompt text only",
        "no local loop or regression",
        "Individual service properties or parts",
        "Individual module with proven bounded impact",
        "Shared Framework logic",
        "Validation infrastructure or execution control",
        "Unknown impact",
        "Stop for missing dependency evidence",
    ):
        assert phrase in policy
    for phrase in (
        "--mode task --write",
        "--staged --write",
        "start no subsequent UT or Git checks",
        "Without `--write`",
        "Blocking failure at any layer is FAIL",
    ):
        assert phrase in execution
    for phrase in (
        "Change Validation only",
        "--model-validation full",
        "Full Model validation with `--write` is rejected",
        "old Model validity is not a save prerequisite",
    ):
        assert phrase.lower() in " ".join(change.lower().split())
    for phrase in (
        "human password input",
        "do not start validation processes or report PASS",
        "Agents must not register/retrieve actual passwords or bypass guards",
    ):
        assert phrase in windows
    for phrase in (
        "--mode local",
        "Repository-wide IaC checks remain enabled",
        "delete/replacement checks",
    ):
        assert phrase in regression


def check_representative_routes():
    local = section("Local loop")
    policy = section("Validation policy")
    regression = section("Framework regression")
    rule = RULE.resolve()
    task = (ROOT / "framework/rules/task-contract.md").resolve()
    require_anchors(
        local,
        task,
        {"task-transition", "acceptance-contract", "selection-and-publication"},
    )
    require_anchors(
        local,
        rule,
        {
            "validation-policy",
            "local-loop-execution",
            "change-validation-and-full-model-validation",
            "framework-regression",
            "windows-full-regression-input-guard",
        },
    )
    require_anchors(policy, rule, {"local-loop"})
    require_anchors(regression, rule, {"windows-full-regression-input-guard"})
    assert "If a loop is required" in local
    assert "for Model changes" in local
    assert "If Framework regression applies" in local
    assert "When the OS is Windows and the run uses `full` or `--all`" in local
    assert "When the OS is Windows and the run uses `full` or `--all`" in regression
    assert "If classification, OS or execution form is uncertain" in local
    assert "otherwise stop" in regression
    condition = "When the OS is Windows and the run uses `full` or `--all`, read"
    for text in (local, regression):
        assert condition in text
        damaged = text.replace(condition, "For Windows Full or `--all`, read")
        with pytest.raises(AssertionError):
            assert condition in damaged
    for parent in (local, policy, regression):
        assert "human password input" not in parent
    # Direct callers must still reach the entry from actual Markdown links.
    for relative, heading, expected in (
        (
            ".agents/skills/worktree/SKILL.md",
            "read-before-execution",
            {"local-loop", "validation-policy", "framework-regression"},
        ),
        (
            "framework/prompts/codex/03_implement.md",
            "read-before-changing-files",
            {"local-loop"},
        ),
        ("framework/prompts/codex/04_deploy.md", "read-before-changing-files", set()),
    ):
        source = ROOT / relative
        source_text = source.read_text(encoding="utf-8")
        # Deploy has a different heading and still refers directly to these sections.
        entry = markdown_sections(source_text).get(heading, source_text)
        actual = rule_readings(ROOT, source, entry).get(rule)
        assert actual and expected <= set(actual["sections"]), relative
    # Removal of any required entry link must be detected, and broken anchors rejected.
    for anchor in (
        "local-loop-execution",
        "change-validation-and-full-model-validation",
        "framework-regression",
        "windows-full-regression-input-guard",
    ):
        damaged = local.replace(f"loop-engineering.md#{anchor}", "loop-engineering.md")
        with pytest.raises(AssertionError):
            require_anchors(damaged, rule, {anchor})
    with pytest.raises(ValueError, match="missing rule section"):
        readings(
            local.replace(
                "loop-engineering.md#local-loop-execution",
                "loop-engineering.md#missing-section",
            )
        )
    for anchor in (
        "task-transition",
        "acceptance-contract",
        "selection-and-publication",
    ):
        damaged = local.replace(f"task-contract.md#{anchor}", "task-contract.md")
        with pytest.raises(AssertionError):
            require_anchors(damaged, task, {anchor})


def check_incoming_anchors():
    # Check all tracked-style documentation sources, including hidden Skills and Copilot.
    targets = {
        "local-loop",
        "validation-policy",
        "change-validation-and-full-model-validation",
        "local-loop-execution",
        "framework-regression",
        "windows-full-regression-input-guard",
    }
    headings = set()
    for title in re.findall(r"^#{1,6} +(.+?)\s*$", TEXT, re.M):
        headings.add(re.sub(r"[^\w -]", "", title.lower()).replace(" ", "-"))
    assert targets <= headings
    sources = [ROOT / "AGENTS.md", ROOT / "README.md"]
    for directory in (ROOT / ".agents", ROOT / ".github", ROOT / "framework"):
        sources.extend(directory.rglob("*.md"))
    seen = set()
    for path in sources:
        for anchor in re.findall(
            r"loop-engineering\.md#([a-z0-9-]+)", path.read_text(encoding="utf-8")
        ):
            assert anchor in headings, (path, anchor)
            seen.add(anchor)
    assert {
        "local-loop",
        "validation-policy",
        "framework-regression",
        "windows-full-regression-input-guard",
    } <= seen


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
