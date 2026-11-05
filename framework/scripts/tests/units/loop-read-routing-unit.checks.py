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
    for anchor in (
        "validation-policy",
        "local-loop-execution",
        "change-validation-and-full-model-validation",
        "framework-regression",
    ):
        assert f"(loop-engineering.md#{anchor})" in local
    assert "(loop-engineering.md#local-loop)" in policy
    assert "its conditional mandatory reads" in policy
    assert (
        "If a loop is required" in local
        and "If classification, OS or execution form is uncertain" in local
    )
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
        "--mode local",
        "Repository-wide IaC checks remain enabled",
        "delete/replacement checks",
    ):
        assert phrase in regression


def require_routing_contract(local, policy, regression):
    # Check the actual natural-language directive and its target together; a valid
    # link elsewhere in the section cannot rescue a negated or inverted directive.
    local = " ".join(local.split())
    policy = " ".join(policy.split())
    regression = " ".join(regression.split())
    directives = (
        (
            local,
            "If a loop is required, read [Local loop execution](loop-engineering.md#local-loop-execution)",
        ),
        (
            local,
            "for Model changes also read [Change Validation and Full Model Validation](loop-engineering.md#change-validation-and-full-model-validation)",
        ),
        (
            local,
            "If Framework regression applies, read [Framework regression](loop-engineering.md#framework-regression)",
        ),
        (
            policy,
            "When a loop is required, read [Local loop](loop-engineering.md#local-loop) and its conditional mandatory reads",
        ),
        (policy, "Unknown impact | Stop for missing dependency evidence"),
        (
            policy,
            "Markdown, Skill or Prompt text only | `git diff --check`, diff review and necessary reference/description checks; no local loop or regression",
        ),
    )
    for text, directive in directives:
        assert directive in text, directive
    assert "If classification, OS or execution form is uncertain" in local
    assert "if it cannot be resolved, stop" in local


def check_conditional_read_mutations():
    local = section("Local loop")
    policy = section("Validation policy")
    regression = section("Framework regression")
    require_routing_contract(local, policy, regression)
    # Exact reviewer reproductions preserve the links but invert their instructions.
    for before, after in (
        ("If a loop is required, read", "If a loop is required, do not read"),
        ("for Model changes also read", "for Model changes also do not read"),
        (
            "If Framework regression applies, read",
            "If Framework regression applies, do not read",
        ),
        ("If a loop is required, read", "If a loop is not required, read"),
        ("for Model changes also read", "for non-Model changes also read"),
        (
            "If Framework regression applies, read",
            "If Framework regression does not apply, read",
        ),
    ):
        assert before in local
        mutated = local.replace(before, after, 1)
        with pytest.raises(AssertionError):
            require_routing_contract(mutated, policy, regression)
    for before, after in (
        ("When a loop is required, read", "When a loop is not required, read"),
        (
            "Unknown impact | Stop for missing dependency evidence",
            "Unknown impact | Continue without evidence",
        ),
    ):
        assert before in policy
        with pytest.raises(AssertionError):
            require_routing_contract(
                local, policy.replace(before, after, 1), regression
            )


def check_representative_routes():
    local = section("Local loop")
    policy = section("Validation policy")
    regression = section("Framework regression")
    require_routing_contract(local, policy, regression)
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
        },
    )
    require_anchors(policy, rule, {"local-loop"})
    assert "If a loop is required" in local
    assert "for Model changes" in local
    assert "If Framework regression applies" in local
    assert "If classification, OS or execution form is uncertain" in local
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
    ):
        source = ROOT / relative
        source_text = source.read_text(encoding="utf-8")
        entry = markdown_sections(source_text).get(heading, source_text)
        actual = rule_readings(ROOT, source, entry).get(rule)
        assert actual and expected <= set(actual["sections"]), relative
    # Removal of any required entry link must be detected, and broken anchors rejected.
    for anchor in (
        "local-loop-execution",
        "change-validation-and-full-model-validation",
        "framework-regression",
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


def require_engine_entry(source, text):
    document = " ".join(text.split())
    directive = "When a loop is required, follow [Local loop](loop-engineering.md#local-loop) and its conditional reads"
    assert directive in document
    found = rule_readings(ROOT, source, text)[RULE.resolve()]
    assert set(found["sections"]) == {
        "validation-policy",
        "validation-scope",
        "infrastructure-task-completion",
        "local-loop",
    }, found["sections"]
    assert "human password input" not in found["text"]
    assert "retain the applicable phase-specific" in document


def check_engine_entry_routes():
    for engine in ("terraform", "cloudformation"):
        source = ROOT / f"framework/rules/{engine}.md"
        text = source.read_text(encoding="utf-8")
        require_engine_entry(source, text)
        for original, replacement in (
            (
                "When a loop is required, follow",
                "When a loop is required, do not follow",
            ),
            ("When a loop is required, follow", "When a loop is not required, follow"),
            ("loop-engineering.md#validation-scope", "loop-engineering.md"),
            (
                "loop-engineering.md#infrastructure-task-completion",
                "loop-engineering.md#missing-section",
            ),
        ):
            assert original in text
            with pytest.raises((AssertionError, ValueError)):
                require_engine_entry(source, text.replace(original, replacement, 1))


def check_incoming_anchors():
    # Check all tracked-style documentation sources, including hidden Skills and Copilot.
    targets = {
        "local-loop",
        "validation-policy",
        "change-validation-and-full-model-validation",
        "local-loop-execution",
        "framework-regression",
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
    } <= seen


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
