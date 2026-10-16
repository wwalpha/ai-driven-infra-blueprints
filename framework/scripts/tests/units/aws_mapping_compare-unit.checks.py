#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.aws_mapping_compare_fixtures import *

def check_missing_catalog_field():
    # Catalog field deletion is rejected before STS/session construction.
    document = ROOT / 'framework/mappings/aws/config.yaml'
    import yaml
    candidate = yaml.safe_load(document.read_text(encoding='utf-8'))
    del candidate['resourceTypes']['Config.DeliveryChannel']['properties']['S3KeyPrefix']
    with patch('aws_mapping.yaml_read', return_value=candidate):
        assert outcome(lambda: Registry(ROOT, 'config'))[0] == 'error'



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
