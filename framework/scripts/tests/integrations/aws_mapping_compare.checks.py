#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from support.aws_mapping_compare_fixtures import (
    ROOT,
    Path,
    checks,
    comparison,
    input_scope,
    m,
    mapped_value,
    outcome,
    patch,
    socket,
    sys,
)
from support.it_case_receipt import it_case

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@it_case
@input_scope
def mapping_checks():
    # include=false remains in Compare, with real acquisition and typed transforms.
    cases = [
        ('config', 'Config.DeliveryChannel', 'S3KeyPrefix'),
        ('codebuild', 'CodeBuild.Project', 'Artifacts.ArtifactIdentifier'),
        ('data-firehose', 'KinesisFirehose.DeliveryStream', 'S3DestinationConfiguration.EncryptionConfiguration.NoEncryptionConfig'),
        ('glue', 'Glue.Connection', 'ConnectionInput.AuthenticationConfiguration.KmsKeyArn'),
        ('glue', 'Glue.Table', 'TableInput.Description'),
        ('lambda', 'Lambda.Function', 'Code.S3ObjectVersion'),
        ('macie', 'Macie.ClassificationJob', 'description'),
        ('s3', 'S3.Bucket', 'LifecycleConfiguration.Rules[].ExpiredObjectDeleteMarker'),
    ]
    for service, kind, suffix in cases:
        mapping, properties = comparison(ROOT, service)
        key = kind + '.' + suffix
        definition = properties[key]
        assert not definition.include and definition.field.classification == 'supported', key
        ctx = checks.Offline(ROOT)
        ctx.verified = True
        resource = checks.FakeResource(ctx, service, kind, key)
        _, actual = mapped_value(ctx, resource, mapping, definition, key)
        assert checks.acquired(actual), key
        resource.desired = actual[0] if '.Rules[].' in key else actual
        result = m.compare_resource(ctx, resource)
        assert len(result) == 1 and result[0]['status'] == 'match', (key, result)
        requests = ctx.request_count
        assert m.compare_resource(ctx, resource) == result
        assert ctx.request_count == requests, key + ': repeated API acquisition'
        ctx.finish()
    ctx = checks.Offline(ROOT)
    ctx.verified = True
    resource = checks.FakeResource(ctx, 'codebuild', 'CodeBuild.Project', 'CodeBuild.Project.Triggers.Webhook', True)
    assert m.compare_resource(ctx, resource)[0]['status'] == 'match'
    assert ctx.request_count == 1
    # A legacy field and a new SDK field share exactly the same raw API response.
    resource.rows[0][1]['property'] = 'CodeBuild.Project.Name'
    resource.desired = 'fixture'
    assert m.compare_resource(ctx, resource)[0]['status'] == 'match' and ctx.request_count == 1
    ctx.finish()
    blocked = checks.FakeResource(ctx, 's3', 'S3.Bucket', 'S3.Bucket.LifecycleConfiguration.Rules[].ExpirationDate')
    result = m.compare_resource(ctx, blocked)
    assert result[0]['status'] == 'sdk_unavailable' and not result[0]['apis']
    assert ctx.request_count == 1 and ('cloudcontrol', 'get_resource') not in ctx.allowed
    webhook = checks.FakeResource(ctx, 'codebuild', 'CodeBuild.Project', 'CodeBuild.Project.Triggers.Webhook', False)
    for response in ({'projects': [{}]}, {'projects': [{'webhook': None}]}):
        with patch.object(ctx, 'fetch', return_value=response):
            assert m.compare_resource(ctx, webhook)[0]['status'] == 'match'
    # Ambiguous resource collections are unresolved, never first-element selection.
    mapping, properties = comparison(ROOT, 'codebuild')
    resource = checks.FakeResource(ctx, 'codebuild', 'CodeBuild.Project')
    with patch.object(ctx, 'fetch', return_value={'projects': [{'name': 'a'}, {'name': 'b'}]}):
        assert outcome(lambda: mapped_value(ctx, resource, mapping, properties['CodeBuild.Project.Triggers.Webhook'],
                                           'CodeBuild.Project.Triggers.Webhook'))[0] == 'error'
    with patch('aws_mapping_compare.comparison', side_effect=ValueError('missing Mapping')), patch.object(m, 'Context') as context:
        assert outcome(lambda: m.run(ROOT, [(checks.TARGET, Path('/offline/config.properties'))]))[0] == 'error'
        assert not context.called
    print('P4 Mapping: PASS (include=false, transforms, SDK collections, shared cache, blocked APIs, missing definitions)')


if __name__ == '__main__':
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        mapping_checks()
