#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.model_parameter_inputs_fixtures import *

def check_yaml_schema():
    from model_parameter_inputs import values_for
    rejected(lambda: values_for({}, {'AvailabilityZone2': 'b', 'AvailabilityZone1': 'a'}, 'service'), "unknown parameter: service: ['AvailabilityZone1', 'AvailabilityZone2']")
    rejected(lambda: values_for({}, [], 'service'), 'expected an object')
    assert yaml_read('value: on\ndate: 2026-10-11\nnumber: 001\nboolean: true\n')=={'value':'on','date':'2026-10-11','number':'001','boolean':True}
    for text in ['a: 1\na: 2','a: {b: 1, b: 2}','a: !!python/object:bad {}','a: &x {b: 1}\nc: {<<: *x}']:rejected(lambda:yaml_read(text),'YAML')
    rejected(lambda:schema({'type':'integer','description':'test','required':True,'constraints':{'minimum':'x'}}),'numeric constraint')



def check_embedded_parameter_type():
    rejected(lambda:t.resolve('x<<Flag>>',{'Flag':True}),'non-string parameter embedded')



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
