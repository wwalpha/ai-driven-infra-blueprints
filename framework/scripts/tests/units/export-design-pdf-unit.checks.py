"""PDF input rejection and converter errors use small authored files and Fake processes."""

import subprocess
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from support.pytest_cli import run
from utils.script_loader import module

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

MODULE = module("export-design-pdf.py", "blueprint_export_design_pdf")


@pytest.mark.parametrize("failure", ["missing-link", "duplicate-anchor"])
def check_bundle_rejects_invalid_references(tmp_path, failure):
    check = TestCase()
    path = tmp_path / "docs/designs/dev/team/iam.md"
    path.parent.mkdir(parents=True)
    text = '# IAM\n<a id="role"></a>\n'
    text += "[Role](#missing)\n" if failure == "missing-link" else '<a id="role"></a>\n'
    path.write_text(text, encoding="utf-8")
    with pytest.raises(
        ValueError, match="missing PDF link target|duplicate design anchor"
    ):
        MODULE.bundle(tmp_path)
    check.assertEqual(path.read_text(encoding="utf-8"), text)


def check_native_dependency_failure_preserves_pdf(tmp_path):
    check = TestCase()
    output = tmp_path / "existing.pdf"
    output.write_bytes(b"existing PDF")
    missing = "cannot load library 'libgobject-2.0-0': error 0x7e"
    with (
        patch.object(MODULE, "bundle", return_value=("# Design\n", {})),
        patch.object(MODULE.shutil, "which", return_value="available"),
        patch.object(
            MODULE.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                ["weasyprint", "--info"], 1, "", missing
            ),
        ) as child,
    ):
        with pytest.raises(RuntimeError, match="README.md#pdf-dependencies") as error:
            MODULE.export(tmp_path, output)
    check.assertIn(missing, str(error.value))
    check.assertEqual(child.call_count, 1)
    check.assertEqual(child.call_args.args[0], ["weasyprint", "--info"])
    check.assertEqual(output.read_bytes(), b"existing PDF")


if __name__ == "__main__":
    raise SystemExit(run(__file__))
