#!/usr/bin/env python3
"""Limited Model expression syntax, links and unchanged literal constraints."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import pytest
from model_references import is_import_expression
from cloudformation_schema import CloudFormationSchemaCatalog


def check_limited_import_expression(tmp_path):
    prop = 'Route53.RecordSet.AliasTarget.HostedZoneId'
    expression = 'Fn::ImportValue: QuickSightWebsiteInterfaceEndpointHostedZoneId${Suffix}'
    design = tmp_path / 'route53.md'
    (tmp_path / 'vpc-endpoint.md').write_text('# 接続先\n', encoding='utf-8')
    link = f'[{expression}](vpc-endpoint.md)'
    for value in (expression, '`' + expression + '`', link):
        assert is_import_expression(prop, value, design)
    for value in ('Z123', 'Z' * 45, '[Z123](vpc-endpoint.md#endpoint)'):
        assert not is_import_expression(prop, value, design)
    for value in (
        expression.replace('ImportValue', 'Unknown'),
        expression.replace('QuickSightWebsiteInterfaceEndpointHostedZoneId', ''),
        expression.replace('QuickSightWebsite', 'Quick SightWebsite'),
        expression.replace('QuickSight', 'quickSight'),
        expression.replace('${Suffix}', ''), expression + '${Suffix}',
        expression + 'Extra', 'prefix ' + expression, ' ' + expression,
        expression.replace('${Suffix}', '${Other}'), expression[:-1],
        'Fn::ImportValue: Fn::Sub: Export${Suffix}', 'Ref: Export', '!ImportValue Export',
        link[:-1], link + 'extra', '`' + link + '`', '[Z123](vpc-endpoint.md)',
        f'[{expression}](vpc-endpoint.md#endpoint)',
        f'[{expression}](missing.md)', f'[{expression}](../vpc-endpoint.md)',
        f'[{expression}](/vpc-endpoint.md)', f'[{expression}](https://example.com/vpc-endpoint.md)',
        f'[{expression}](vpc-endpoint.md?query)',
    ):
        with pytest.raises(ValueError):
            is_import_expression(prop, value, design)
    for other in ('Route53.RecordSet.HostedZoneId', 'Route53.RecordSet.AliasTarget.DNSName'):
        for value in (expression, link):
            with pytest.raises(ValueError):
                is_import_expression(other, value, design)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'target.md').write_text('# 外部\n', encoding='utf-8')
    (tmp_path / 'escape.md').symlink_to(outside / 'target.md')
    with pytest.raises(ValueError):
        is_import_expression(prop, f'[{expression}](escape.md)', design)

    catalog = CloudFormationSchemaCatalog(Path(__file__).resolve().parents[4])
    assert not catalog.literal_errors('Route53.RecordSet', 'AliasTarget.HostedZoneId', 'Z' * 44)
    assert catalog.literal_errors('Route53.RecordSet', 'AliasTarget.HostedZoneId', 'Z' * 45)
    assert not catalog.literal_errors('Route53.RecordSet', 'AliasTarget.EvaluateTargetHealth', 'true')
    assert catalog.literal_errors('Route53.RecordSet', 'AliasTarget.EvaluateTargetHealth', 'yes')
    assert catalog.literal_errors('Route53.RecordSet', 'Weight', 'not-a-number')


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
