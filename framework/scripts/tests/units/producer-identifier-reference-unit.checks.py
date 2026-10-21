#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.producer_identifier_reference_fixtures import *

def check_identifier_schema():
    key = 'desired.row.008-001.value'
    values = resource('008', 'EC2.VPCEndpoint', 'consumer', [('PolicyDocument', 'saved')])
    values.update(reference('fixed', key, 'saved', 'vpc', '001', 'EC2.VPC', mode='identifier', prop='EC2.VPC.VpcId'))
    assert declarations(values)['fixed']['format'] == 'identifier'
    for fields, phrase in [({'format': 'unknown'}, 'format/scope'),
                           ({'labelPolicy': 'fixed'}, 'non-link'),
                           ({'contextProperty': 'environment'}, 'forbidden'),
                           ({'producerScope': '../team/vpc'}, 'unsafe'),
                           ({'selector': 'first'}, 'fields')]:
        bad = {**values, **{'desired.reference.fixed.' + field: value for field, value in fields.items()}}
        rejected(lambda: declarations(bad), phrase)
    bad = {key: value for key, value in values.items() if key != 'desired.reference.fixed.property'}
    rejected(lambda: declarations(bad), 'missing or forbidden')


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
