"""Standard-library-only checks for the Python structure gate."""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

CHECKER = Path(__file__).resolve().parents[2] / "python_structure.py"
SPEC = importlib.util.spec_from_file_location("python_structure", CHECKER)
STRUCTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STRUCTURE)


class StructureTests(unittest.TestCase):
    def test_module_imports_and_methods(self):
        self.assertEqual(
            STRUCTURE.violations(
                "import os\nclass Example:\n def method(self):\n  return 1\n"
            ),
            [],
        )

    def test_function_import_and_nested_definition(self):
        self.assertEqual(
            STRUCTURE.violations("def outer():\n import os\n def inner():\n  pass\n"),
            [(2, "function-import"), (3, "nested-function")],
        )

    def test_async_and_method_bodies(self):
        self.assertEqual(
            STRUCTURE.violations(
                "class Example:\n async def method(self):\n  from os import path\n"
                "  async def inner():\n   pass\n"
            ),
            [(3, "function-import"), (4, "nested-function")],
        )

    def test_cli_reports_location_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "example.py"
            source.write_text("def outer():\n import os\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", str(CHECKER), directory],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn(f"{source}:2: function-import", result.stdout)
            source.write_text("import os\n", encoding="utf-8")
            self.assertEqual(
                subprocess.run(
                    [sys.executable, "-B", str(CHECKER), directory], check=False
                ).returncode,
                0,
            )


if __name__ == "__main__":
    unittest.main()
