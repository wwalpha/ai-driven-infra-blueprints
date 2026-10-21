#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.model_files_fixtures import *

def check_cfn_selector():
    from model.files import resource_keys
    import pytest
    text = 'desired.resource.007.resourceType=EC2.VPC\ndesired.resource.007.logicalId=EC2_VPC_001\ndesired.service.identity.lastAllocated={"EC2.VPC":1}\ndesired.resource.007.cfn-logicalId=cfn-stack-app-dev-network-Vpc\n'
    assert resource_keys(text, '007') == resource_keys(text, 'EC2_VPC_001')
    for selector in ('ec2-network', 'cfn-stack-app-dev-network-Vpc'):
        with pytest.raises(ValueError):
            resource_keys(text, selector)



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
