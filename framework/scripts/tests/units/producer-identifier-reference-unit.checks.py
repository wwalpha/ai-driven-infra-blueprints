#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.producer_identifier_reference_fixtures import *

def check_identifier_schema():
    ref = {'service':'vpc', 'resource':'001', 'resourceType':'EC2.VPC', 'format':'identifier', 'property':'EC2.VPC.VpcId'}
    for bad in [{k:v for k,v in ref.items() if k!='property'}, {**ref,'property':'EC2.VPC.Arn'}, {**ref,'property':'EC2.Subnet.SubnetId'}, {'instance':'main','resourceType':'EC2.VPC','format':'identifier','property':'EC2.VPC.VpcId'}]:
        rejected(lambda: reference_schema(bad), 'identifier' if 'service' in bad else 'invalid Model parameter format')
    rejected(lambda: schema({'type':'string','description':'bad','required':True,'format':'identifier','property':'EC2.VPC.VpcId'}), 'invalid Model parameter format')



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
