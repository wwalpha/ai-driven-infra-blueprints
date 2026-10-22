#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.deploy_preparation_fixtures import *

def check_workflow_contract():
    from utils.markdown_format import read_declaration, declared_readings
    prompt = ROOT / 'framework/prompts/codex/04_deploy.md'
    declaration = read_declaration(prompt.read_text(encoding='utf-8'))
    assert set(declaration) == {'startup', 's3', 'approval', 'repair', 'resume', 'success', 'terraform'}
    for stage in declaration:
        assert declared_readings(ROOT, prompt, [stage])
    assert sum(len(v['text']) for v in declared_readings(ROOT, prompt, ['startup', 's3']).values()) <= 20000
    skill = (ROOT / '.agents/skills/deploy/SKILL.md').read_text()
    assert '#normal-startup' in skill and '#read' in skill and 'in full' not in skill


def check_dependencies_and_timing():
    with patch.object(M.importlib, "import_module", side_effect=ImportError), patch.object(M.shutil, "which", return_value=None):
        try:
            M.environment(ROOT)
        except ValueError as error:
            assert all(name in str(error) for name in ("boto3", "botocore", "PyYAML", "git"))
        else:
            raise AssertionError("missing dependencies accepted")
    with patch.object(M.importlib, "import_module"), patch.object(M.importlib.metadata, "version", return_value="different.patch"), patch.object(M.shutil, "which", return_value="tool"), patch.object(subprocess, "run") as run:
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
