#!/usr/bin/env python3
"""Saved SecurityGroup properties → grouped renderer, preserving authoritative bytes."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from model.render import markdown_for
from model.sources import load_model
from support.fixture_cases import load_case
from support.it_case_receipt import it_case
from support.security_group_tables_fixtures import (
    GENERATED_MODEL,
    REPOSITORY,
    VALIDATOR,
    VPC_DESIGN,
    tempfile,
    write_model,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@it_case
def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (root / 'project.json').write_text(json.dumps({'targets': [{'environment': 'dev', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'}]}))
        path = root / 'docs/designs/dev/123456789012/security-group.md'
        path.parent.mkdir(parents=True)
        path.with_name('vpc.md').write_text(VPC_DESIGN, encoding='utf-8')
        source = root / 'model/dev/123456789012/security-group.properties'
        write_model(source, GENERATED_MODEL)
        validator = VALIDATOR.Validator(root)
        catalog = validator.catalog_design_properties()
        assert validator.model_service_metadata(source, catalog[0]) == (
            'security-group', ('EC2.SecurityGroup', 'EC2.SecurityGroupIngress', 'EC2.SecurityGroupEgress'))
        assert not validator.errors, validator.errors
        case = load_case('security_group_tables', 'plain')
        values = dict(load_model(source).values)
        values.update(case['data']['presentation'])
        for identity in range(1, 7):
            values[f'desired.resource.{identity:03}.cfn-logicalId'] = f'fixture-Resource{identity}'
        for number, scalar in zip((4, 5), case['data']['scalars'], strict=False):
            values[f'desired.row.006-{number:03}.value'] = scalar
        write_model(source, values)
        write_model(source.with_name('cloudformation-stacks.properties'), case['data']['stacks'])
        before = {file: file.read_bytes() for file in load_model(source).files}
        rendered = markdown_for(path, load_model(source).values, root, definitions_root=REPOSITORY)
        marker = next(line for line in rendered.splitlines() if line.startswith('<!-- security-group-tags:'))
        expected = [dict(zip(('Key', 'Value'), case['expected'], strict=False)), {'Key': 'Environment', 'Value': 'dev'}]
        assert json.loads(marker.removeprefix('<!-- security-group-tags: ').removesuffix(' -->')) == expected
        assert {file: file.read_bytes() for file in before} == before


if __name__ == '__main__':
    from support.model_sources import catalog_display
    with catalog_display():
        main()
