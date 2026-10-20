#!/usr/bin/env python3
"""Model input and generated Markdown agree on limited Route53 expressions."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import pytest
from support.model_design_fixtures import model, ROOT
from support.validator import schema_validator
from model_design import check_model_inputs as _check_model_inputs, markdown_for


@pytest.mark.usefixtures('catalog_display_fixture')
def check_route53_import_expression_validation(tmp_path):
    path = tmp_path / 'docs/designs/dev/123456789012/route53.md'
    path.parent.mkdir(parents=True)
    (path.parent / 'vpc-endpoint.md').write_text('# 接続先\n', encoding='utf-8')
    source = tmp_path / 'model/dev/123456789012/route53.properties'
    expression = 'Fn::ImportValue: QuickSightWebsiteInterfaceEndpointHostedZoneId${Suffix}'
    values = model('route53', 'Route53.RecordSet', 'test.example.com', [
        ('Name', '`test.example.com`', 'レコード名'), ('Type', '`A`', '種別'),
        ('AliasTarget.DNSName', '`test.example.com`', '接続先'),
        ('AliasTarget.HostedZoneId', 'Z123', 'ゾーンID'),
        ('AliasTarget.EvaluateTargetHealth', 'true', 'ヘルス評価'),
    ])
    document = markdown_for(path, values, tmp_path, definitions_root=ROOT)
    validator = schema_validator(tmp_path)
    catalog = validator.catalog_design_properties()
    for field, value, valid in (
        ('AliasTarget.HostedZoneId', 'Z' * 44, True),
        ('AliasTarget.HostedZoneId', 'Z' * 45, False),
        ('AliasTarget.HostedZoneId', expression, True),
        ('AliasTarget.HostedZoneId', '`' + expression + '`', True),
        ('AliasTarget.HostedZoneId', f'[{expression}](vpc-endpoint.md)', True),
        ('AliasTarget.HostedZoneId', '[Z123](vpc-endpoint.md#endpoint)', True),
        ('AliasTarget.HostedZoneId', f'[{expression}](missing.md)', False),
        ('AliasTarget.HostedZoneId', f'[{expression}](../vpc-endpoint.md)', False),
        ('AliasTarget.HostedZoneId', '[Z123](vpc-endpoint.md)', False),
        ('AliasTarget.HostedZoneId', expression.replace('ImportValue', 'Unknown'), False),
        ('AliasTarget.HostedZoneId', expression.replace('${Suffix}', '${Other}'), False),
        ('AliasTarget.HostedZoneId', expression + 'extra', False),
        ('AliasTarget.DNSName', expression, False),
        ('AliasTarget.DNSName', f'[{expression}](vpc-endpoint.md)', False),
        ('AliasTarget.EvaluateTargetHealth', 'yes', False),
    ):
        selected = dict(values)
        row = {'AliasTarget.HostedZoneId': '004', 'AliasTarget.DNSName': '003',
               'AliasTarget.EvaluateTargetHealth': '005', 'Type': '002'}[field]
        key = f'desired.row.001-{row}.value'
        selected[key] = value
        inputs = _check_model_inputs(source, selected, tmp_path, definitions_root=ROOT)
        errors = [error for error in inputs.errors if 'provider schema violation' in error or 'ImportValue' in error]
        assert bool(errors) != valid, (field, value, inputs.errors)
        # Render accepted values; inject rejected values into an otherwise valid View.
        shown = markdown_for(path, selected, tmp_path, definitions_root=ROOT) if valid else document.replace(
            '| ' + field + ' | ' + values[key] + ' |', '| ' + field + ' | ' + value + ' |')
        path.write_text(shown, encoding='utf-8')
        validator = schema_validator(tmp_path)
        validator.design_sources = {path: selected}
        validator.check_design_tables({}, *catalog, paths=[path])
        errors = [error for error in validator.findings.errors if 'provider schema violation' in error or 'invalid Model expression' in error]
        assert bool(errors) != valid, (field, value, validator.findings.errors)


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
