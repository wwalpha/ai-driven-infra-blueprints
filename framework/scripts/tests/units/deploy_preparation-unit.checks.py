#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.deploy_preparation_fixtures import *

def check_workflow_contract():
    prompt = (ROOT / "framework/prompts/codex/04_deploy.md").read_text(encoding="utf-8")
    reading = M.markdown_sections(prompt)["read-before-changing-files"]
    assert "docs/designs/<environment>/<target-directory>/<service-id>.md" not in reading
    for text in (prompt, *((ROOT / "framework/rules" / (engine + ".md")).read_text(encoding="utf-8") for engine in ("cloudformation", "terraform"))):
        assert all(value in text for value in ("authoritative model properties", "desired.row.*.document", "desired.resource.*", "observed.*", "existence verification", "hash", "local loop", "fallback", "stop"))
        assert "Read approved detailed designs and service models as input" not in text
    assert all(value in prompt for value in ("generatedViews", "inputs", "unread sections", "load_units()", "Do not newly reregister already registered tasks"))


def check_dependencies_and_timing():
    with patch.object(M.importlib, "import_module", side_effect=ImportError), patch.object(M.shutil, "which", return_value=None):
        try:
            M.environment(ROOT)
        except ValueError as error:
            assert all(name in str(error) for name in ("boto3", "botocore", "PyYAML", "cfn-lint", "aws", "git"))
        else:
            raise AssertionError("missing dependencies accepted")
    with patch.object(M.importlib, "import_module"), patch.object(M.importlib.metadata, "version", return_value="different.patch"), patch.object(M.shutil, "which", return_value="tool"), patch.object(M.subprocess, "run") as run:
        run.return_value.returncode = 0
        assert M.environment(ROOT)["versions"]["boto3"] == "different.patch"
        assert run.call_args.args[0] == [sys.executable, "-m", "pip", "check"]
        run.return_value.returncode = 1
        run.return_value.stdout, run.return_value.stderr = "conflicting dependency", ""
        try:
            M.environment(ROOT)
        except ValueError as error:
            assert "conflicting dependency" in str(error)
        else:
            raise AssertionError("pip check failure accepted")
    with tempfile.TemporaryDirectory() as directory:
        try:
            M.Timing(Path(directory), Path(directory) / "timing.jsonl")
        except ValueError:
            pass
        else:
            raise AssertionError("repository-local timing accepted")
        path = Path(directory) / "external.jsonl"
        timing = M.Timing(ROOT, path)
        try:
            with timing.phase("authenticationContext"):
                raise RuntimeError("credential failure")
        except RuntimeError:
            pass
        event = json.loads(path.read_text())
        assert event["result"] == "FAIL" and event["phase"] == "authenticationContext"


def check_rule_section_boundaries():
    text = "# Rules\r\n\r\n## Required\r\nkeep\r\n```md\r\n## Required\r\n```\r\n### Child\r\nchild\r\n## Unrelated\r\nomit\r\n"
    text = text.replace("## Required\r\nkeep", '<a id="explicit"></a>\r\n\r\n## Required\r\nkeep')
    sections = M.markdown_sections(text)
    assert sections["explicit"] == sections["required"]
    assert "child" in sections["required"] and "omit" not in sections["required"]
    for ambiguous in ("## Duplicate\nsame\n## Duplicate\nsame\n",
                      "<a id=\"shared\"></a>\n## One\nfirst\n<a id=\"shared\"></a>\n## Two\nsecond\n"):
        try:
            M.markdown_sections(ambiguous)
        except ValueError as error:
            assert "ambiguous rule section" in str(error)
        else:
            raise AssertionError("duplicate heading/anchor accepted")
    assert "same" in M.markdown_sections('<a id="same"></a>\n## Same\nrule\n')
    # Required child exceptions and stop conditions remain inside the selected range.
    nested = "## Required\nrule\n### Exception\nstop on missing input\n## Optional\nomit\n"
    assert M.markdown_sections(nested)["required"] == "## Required\nrule\n### Exception\nstop on missing input\n"


import pytest
pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
