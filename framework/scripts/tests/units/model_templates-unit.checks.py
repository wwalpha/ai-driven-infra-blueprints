#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.model_templates_fixtures import *

def check_template_syntax(root):
    template = common_shape_template(root)
    original=template.read_text(encoding='utf-8')
    for malformed in (original.replace('/Statement/1','/Statement/-1'),
                      original.replace('/Statement/1','/Statement/01'),
                      original.replace('/Statement/1','/Statement/~2'),
                      original.replace('"pointer":"/Value"','"pointer":null'),
                      original.replace('# choice: desired.row.config.value', '# choice: desired.row.config.value {"parameter":"AlternateAnchor","value":"other"}\n# choice: desired.row.config.value'),
                      original.replace('desired.resource.bucket.logicalId HasLogicalId','desired.resource.bucket.unknown HasLogicalId'),
                      original.replace('HasLogicalId boolean','HasLogicalId string')):
        template.write_text(malformed,encoding='utf-8')
        rejected(lambda:templates.parse_template(template))



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
