#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.import_model_fixtures import *

def check_null_parameter():
    from model_parameter_inputs import check_value, schema
    check_value(schema({'type':'null','description':'null','required':True,'format':'literal'}),None,'null')
    check(resolve('<<Node>>',{'Node':None},structured=True) is None,'null node remains JSON null')



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
