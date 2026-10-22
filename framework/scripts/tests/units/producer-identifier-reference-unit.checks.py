#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.producer_identifier_reference_fixtures import *
from model.validation import validate_json_settings, check_model_inputs as model_findings
from unittest.mock import patch
import pytest


def check_json_settings():
    path = Path('/synthetic/model/preview/team/vpc-endpoint.properties')
    key = 'desired.row.008-001.document'
    values = resource('008', 'EC2.VPCEndpoint', 'consumer', [('PolicyDocument', '[policy](vpc-endpoint/policy.json)')])
    link = '[vpc](vpc.md#vpc-one)'
    for body, pointer in [
        ({'Condition': {'StringEquals': {'aws:SourceVpc': link}}}, '/Condition/StringEquals/aws:SourceVpc'),
        ({'Resource': {'$resource': link, '$attribute': 'Arn'}}, '/Resource/$resource'),
        ({'Description': 'prefix ' + link + ' suffix'}, '/Description'),
        ({'a/b~c': [link]}, '/a~1b~0c/0'),
        ({'PolicyText': json.dumps({'Resource': link})}, '/PolicyText'),
    ]:
        bad = {**values, key: json.dumps(body)}
        for field in ('document', 'value'):
            candidate = bad if field == 'document' else {**values, key.replace('.document', '.value'): '`' + json.dumps(body) + '`'}
            with pytest.raises(ValueError) as error:
                validate_json_settings(candidate, path)
            assert all(text in str(error.value) for text in
                       (str(path), 'EC2_VPCEndpoint_008', 'EC2.VPCEndpoint.PolicyDocument', pointer))
    good = {**values, key: json.dumps({'Condition': {'StringEquals': {'aws:SourceVpc': 'vpc-0123456789abcdef0'}},
        'URL': 'https://example.com/vpc.md#guide', 'Text': '[guide](https://example.com/guide#section)',
        'Artifact': '[policy](vpc-endpoint/policy.json)', 'Literal': 'ordinary [brackets] and $resource text'})}
    good.update(reference('vpc', key, 'vpc-0123456789abcdef0', 'vpc', '001', 'EC2.VPC',
        mode='identifier', prop='EC2.VPC.VpcId', pointer='/Condition/StringEquals/aws:SourceVpc'))
    before = dict(good)
    with patch('model.identity.Resolver.operand', side_effect=AssertionError('physical literals must not resolve')):
        validate_json_settings(good, path)
        assert declarations(good)['vpc']['format'] == 'identifier'
    assert good == before
    validate_json_settings(values, path)  # The artifact link is outside the JSON body.
    validate_json_settings({**values, key.replace('.document', '.value'): link}, path)


def check_json_boundaries(tmp_path):
    from model.operations import validate_candidates, prepare_edit
    from model.sources import SourceWriteContext
    from types import SimpleNamespace
    from model.render import generate_files, generate_markdown, render_validated_model
    setup(tmp_path, ['vpc-endpoint'], ['EC2.VPCEndpoint'])
    path = tmp_path / 'model/preview/team/vpc-endpoint.properties'
    view = tmp_path / 'docs/designs/preview/team/vpc-endpoint.md'
    values = resource('008', 'EC2.VPCEndpoint', 'consumer', [('PolicyDocument', '[policy](vpc-endpoint/policy.json)')])
    values['desired.row.008-001.document'] = json.dumps({'Resource': '[missing](vpc.md#missing)'})
    write_model(path, values)
    before = path.read_bytes()
    findings = model_findings(path, values, tmp_path)
    assert any('JSON setting contains' in error for error in findings.errors), findings.errors
    for render in (generate_files, generate_markdown, render_validated_model):
        with pytest.raises(ValueError, match='JSON setting contains'):
            render(view, values, tmp_path)
    with pytest.raises(ValueError, match='JSON setting contains'):
        validate_candidates(tmp_path, {path.relative_to(tmp_path)}, {}, {('preview', 'team', 'vpc-endpoint')})
    for action in ('edit', 'import'):
        reads = FileReads()
        context = SourceWriteContext._authorized(tmp_path, reads, SimpleNamespace(action=action),
            lambda changes: None, frozenset({path}))
        snapshot = load_model(path, reads)
        with pytest.raises(ValueError, match='JSON setting contains'):
            prepare_edit(snapshot, {path: serialize(values)}, context)
    assert path.read_bytes() == before and not view.exists()

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
