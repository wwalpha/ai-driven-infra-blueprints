#!/usr/bin/env python3
"""Markdown section boundaries used by static document validation."""

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


pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == "__main__":
    raise SystemExit(run(__file__))
