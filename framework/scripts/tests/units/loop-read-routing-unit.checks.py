#!/usr/bin/env python3
"""Contract checks for validation guidance and conditional read routing."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RULE = ROOT / "framework/rules/loop-engineering.md"
TEXT = RULE.read_text(encoding="utf-8")


def section(name):
    match = re.search(rf"^## {re.escape(name)}\s*$", TEXT, re.M)
    assert match, name
    end = re.search(r"^## ", TEXT[match.end() :], re.M)
    return (
        TEXT[match.start() : match.end() + end.start()]
        if end
        else TEXT[match.start() :]
    )


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
        assert f"(#{anchor})" in local
    for anchor in (
        "local-loop-execution",
        "change-validation-and-full-model-validation",
        "framework-regression",
        "windows-full-regression-input-guard",
    ):
        assert f"(#{anchor})" in policy
    assert (
        "If a loop is required" in local
        and "If classification, OS or execution form is uncertain" in local
    )
    assert "Windows Full or `--all`" in regression and "otherwise stop" in regression
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
        assert phrase in change
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
    # Expected decisions are independent of the documentation text and cover both OS paths.
    cases = (
        (False, False, False, False, {"Validation policy"}),
        (
            True,
            True,
            False,
            False,
            {
                "Validation policy",
                "Local loop",
                "Local loop execution",
                "Change Validation and Full Model Validation",
            },
        ),
        (
            True,
            False,
            False,
            False,
            {"Validation policy", "Local loop", "Local loop execution"},
        ),
        (
            True,
            False,
            True,
            False,
            {
                "Validation policy",
                "Local loop",
                "Local loop execution",
                "Framework regression",
            },
        ),
        (
            True,
            False,
            True,
            True,
            {
                "Validation policy",
                "Local loop",
                "Local loop execution",
                "Framework regression",
                "Windows full regression input guard",
            },
        ),
    )
    routes = {
        "Local loop": section("Local loop"),
        "Validation policy": section("Validation policy"),
        "Framework regression": section("Framework regression"),
    }
    anchors = {
        "Local loop": "local-loop",
        "Local loop execution": "local-loop-execution",
        "Change Validation and Full Model Validation": "change-validation-and-full-model-validation",
        "Framework regression": "framework-regression",
        "Windows full regression input guard": "windows-full-regression-input-guard",
    }
    for loop, model, regression, windows, expected in cases:
        selected = {"Validation policy"}
        if loop:
            selected.update(("Local loop", "Local loop execution"))
        if model:
            selected.add("Change Validation and Full Model Validation")
        if regression:
            selected.add("Framework regression")
        if regression and windows:
            selected.add("Windows full regression input guard")
        assert selected == expected
        for target in selected - {"Validation policy"}:
            assert any(f"(#{anchors[target]})" in text for text in routes.values()), (
                target
            )
            assert section(target)
        assert ("Local loop execution" in selected) == loop
        assert ("Windows full regression input guard" in selected) == (
            regression and windows
        )
    assert "otherwise stop" in routes["Validation policy"]
    assert "otherwise stop" in routes["Framework regression"]


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
