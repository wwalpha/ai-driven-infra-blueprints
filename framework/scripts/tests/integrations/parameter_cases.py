"""Explicit environment properties retain identities, policy types and reference meanings."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pytest
from support.model_sources import write_model
from support.it_workspace import populate
from model.sources import FileReads, list_models, load_model, design_source_digest
from model.operations import CandidateReads
from model.format import parse, patch as patch_properties, serialize
from model.references import declarations
from model.files import trace_model
from model.projection import document_sha256
ROOT = Path(__file__).resolve().parents[4]


def check(root, alias, service):
    populate('input_templates', root)
    path = root / 'model/preview' / alias / (service + '.properties')
    other = root / 'model/prod' / alias / (service + '.properties')
    before, other_before = load_model(path), load_model(other)
    original = {p: p.read_bytes() for p in (root / 'model').rglob('*') if p.is_file()}
    assert before.authoritative and not before.warnings
    assert not (root / 'model/templates').exists() and not (root / 'model/parameters').exists()
    fixed = {key: value for key, value in before.authoritative.items() if key.startswith('desired.resource.')}
    digest = design_source_digest(path)
    for key in before.authoritative:
        trace = trace_model(path, key)
        file = Path(trace['file'])
        assert file in before.files and trace['key'] == key and trace['value'] == before.authoritative[key]
        assert file.read_text().splitlines()[trace['line'] - 1].startswith(key + '=')
    assert all(not key.endswith('.artifactSha256') for key in before.authoritative)
    assert all(not key.startswith('observed.') or key.endswith('.value') for key in before.authoritative)

    def proposed(changes, dependencies=None):
        values = {**before.authoritative, **changes}
        values = {key: value for key, value in values.items() if value is not None}
        text = serialize(values)
        result = load_model(before.scope, CandidateReads(FileReads(), {path: text, **(dependencies or {})}))
        assert {key: value for key, value in result.authoritative.items() if key.startswith('desired.resource.')} == fixed
        assert load_model(other).authoritative == other_before.authoritative
        assert all(p.read_bytes() == raw for p, raw in original.items())
        return result

    # Initial values/order survive a serializer round trip and a byte-local no-op.
    assert load_model(before.scope, CandidateReads(FileReads(), {path: serialize(before.authoritative)})).authoritative == before.authoritative
    assert patch_properties(parse(path.read_text()), {}) == path.read_text()
    comment, = [key for key in before.authoritative if key.endswith('.comment') and key.startswith('desired.row.')][:1]
    result = proposed({comment: '更新確認 ' + before.authoritative[comment]})
    assert result.authoritative[comment].startswith('更新確認 ')
    with pytest.raises(ValueError, match='unknown Model field'):
        proposed({'desired.resource.017.unknown': 'bad'})
    required = next(key for key in before.authoritative if key.startswith('desired.row.') and key.endswith('.value'))
    with pytest.raises(ValueError, match='Row requires'):
        proposed({required: None})
    with pytest.raises(ValueError, match='duplicate'):
        load_model(before.scope, CandidateReads(FileReads(), {path: path.read_text() + required + '=duplicate\n'}))

    if service == 'codecommit':
        key = next(key.removesuffix('.property') + '.value' for key, raw in before.authoritative.items() if raw == 'CodeCommit.Repository.RepositoryDescription')
        changed = proposed({key: ' 001 \\ " '})
        assert changed.authoritative[key] == ' 001 \\ " '
    elif service == 'security-hub':
        assert any(value == '`SECURITY_CONTROL`' for value in before.authoritative.values())
        assert any(value == '`true`' for value in before.authoritative.values())
    elif service == 'datazone':
        assert len([key for key in before.authoritative if key.endswith('.resourceType')]) == 6
        assert set(fixed) == {key for key in proposed({}).authoritative if key.startswith('desired.resource.')}
    elif service == 'athena':
        producer = path.with_name('s3.properties')
        assert producer in before.dependencies
        spec, = declarations(before.authoritative).values()
        assert spec['producerId'] == '001' and spec['format'] == 'name' and spec['property'] == 'S3.Bucket.BucketName'
        changed_producer = producer.read_text().replace('fixture-bucket-001-one', 'fixture-bucket-001-two')
        stale = proposed({}, {producer: changed_producer})
        assert stale.authoritative == before.authoritative and stale.warnings
        assert stale.dependencies[producer] != before.dependencies[producer]
        assert design_source_digest(path) == digest
        key = spec['consumerKey']
        after = proposed({key: before.authoritative[key].replace('-one', '-two'), 'desired.reference.result.text': 'fixture-bucket-001-two'}, {producer: changed_producer})
        assert not after.warnings and after.authoritative[key] != before.authoritative[key]
        for invalid in (changed_producer.replace('S3.Bucket', 'IAM.Role'), changed_producer.replace('BucketName', 'Other')):
            preserved = proposed({}, {producer: invalid})
            assert preserved.authoritative == before.authoritative and preserved.warnings
        missing = proposed({}, {producer: None})
        assert missing.authoritative == before.authoritative and missing.warnings
    elif service == 'sqs':
        key, = [key for key in before.authoritative if key.endswith('.document')]
        document = json.loads(before.authoritative[key])
        statement = document['Statement'][0]
        assert isinstance(document['Statement'], list) and statement['Action'] == 'sqs:SendMessage'
        assert statement['Resource']['Fn::GetAtt'] == ['HulftRetrievalDetectDlq', 'Arn']
        assert any(raw == '[017](#fixture-sqs-017)' for raw in before.authoritative.values())
        assert statement['Condition']['StringEquals']['aws:SourceAccount'] == '123456789012'
        checksum = key.removesuffix('.document') + '.artifactSha256'
        assert before.values[checksum] == document_sha256(document) and checksum not in before.authoritative
        spec, = declarations(before.authoritative).values()
        assert spec['producerKind'] == 'context' and spec['contextProperty'] == 'executionAccountId'
        assert spec['pointer'] == '/Statement/0/Condition/StringEquals/aws:SourceAccount'
        project = root / 'project.json'
        topology = json.loads(project.read_text())
        topology['targets'][0]['awsExecutionAccountId'] = '999999999999'
        stale = proposed({}, {project: json.dumps(topology)})
        assert stale.authoritative == before.authoritative and stale.warnings
        assert stale.values[checksum] == before.values[checksum]
        changed_document = json.loads(before.authoritative[key])
        changed_document['Statement'][0]['Condition']['StringEquals']['aws:SourceAccount'] = '999999999999'
        after = proposed({key: json.dumps(changed_document), 'desired.reference.account.text': '999999999999'}, {project: json.dumps(topology)})
        assert not after.warnings and after.values[checksum] != before.values[checksum]
        changed_document['Statement'][0]['Action'] = ['sqs:SendMessage', 'sqs:GetQueueUrl']
        after = proposed({key: json.dumps(changed_document), 'desired.reference.account.text': '999999999999'}, {project: json.dumps(topology)})
        assert json.loads(after.authoritative[key])['Statement'][0]['Action'] == ['sqs:SendMessage', 'sqs:GetQueueUrl']
    assert load_model(path).authoritative == before.authoritative and design_source_digest(path) == digest
    assert all(p.read_bytes() == raw for p, raw in original.items())


def run(service):
    from support.it_fixture_bundle import source
    with patch(__name__ + '.ROOT', source('input_templates')):
        aliases = sorted({scope.target for scope in list_models(ROOT) if scope.service == service})
        assert aliases, 'no explicit service fixture cases'
        for alias in aliases:
            with TemporaryDirectory(prefix=service + '-properties-') as directory, patch.dict(os.environ, {'BLUEPRINT_TASK_FILE': ''}):
                check(Path(directory), alias, service)
