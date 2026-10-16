"""Responsibility boundaries: dispatch, mutable gates, callbacks and import safety."""

from support.it_case_receipt import it_case


from contextlib import ExitStack, redirect_stdout


import io


import os


from pathlib import Path


import subprocess


import sys


from unittest.mock import patch


from support.validator import MODULE, SCRIPT, project, write, load


from validation_cache import PassCache


@it_case
def check_module_inputs():
    names = ('findings', 'scenario', 'cloudformation', 'iac', 'terraform', 'design', 'design_tables', 'design_links',
             'project', 'task', 'framework_contracts')
    command = '''from pathlib import Path
from unittest.mock import patch
import importlib
with patch.object(Path, 'rglob', side_effect=AssertionError('repository scan')), \\
     patch.object(Path, 'glob', side_effect=AssertionError('repository scan')), \\
     patch.object(Path, 'iterdir', side_effect=AssertionError('repository scan')), \\
     patch('subprocess.run', side_effect=AssertionError('process launched')):
    for name in %r:
        importlib.import_module('validation.' + name)
''' % (names,)
    completed = subprocess.run([sys.executable, '-B', '-c', command], cwd=SCRIPT.parent,
                               env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True)
    assert completed.returncode == 0 and not completed.stdout and not completed.stderr, completed.stderr

