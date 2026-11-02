"""Standard-library-only checks for the Python structure gate."""

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
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
            with redirect_stdout(io.StringIO()) as output:
                result = STRUCTURE.main([directory])
            self.assertEqual(result, 1)
            self.assertIn(f"{source}:2: function-import", output.getvalue())
            source.write_text("import os\n", encoding="utf-8")
            self.assertEqual(STRUCTURE.main([directory]), 0)


if __name__ == "__main__":
    unittest.main()
