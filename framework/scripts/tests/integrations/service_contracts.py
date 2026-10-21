"""Service-value, native type and projection contracts over explicit properties."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import pytest
from support.it_case_receipt import it_case
from model.sources import FileReads, list_models, load_model
from model.operations import CandidateReads
from model.format import serialize
from model.core import entries, literal, resource_row_index
from model.projection import document_sha256
from model.importing.cli import property_schema
from model.importing.sources import typed_row
from model.references import declarations
from service_rows import pipeline_rows, pipeline_display_rows
from design_catalog import DesignSchemaCatalog
from validation_cache import input_scope
ROOT = Path(__file__).resolve().parents[4]


def cases(service):
    scopes = [scope for scope in list_models(ROOT) if scope.service == service]
    assert scopes, 'no service contract cases: ' + service
    for scope in scopes:
        yield load_model(scope)


def candidate(before, changes):
    values = {**before.authoritative, **changes}
    values = {key: value for key, value in values.items() if value is not None}
    output = {before.scope.path: serialize(values)}
    after = load_model(before.scope, CandidateReads(FileReads(), output))
    assert {key for key in before.authoritative.keys() | after.authoritative.keys()
            if before.authoritative.get(key) != after.authoritative.get(key)} == {
                key for key in changes if before.authoritative.get(key) != changes[key]}
    assert all(path.read_bytes() == text.encode('utf-8') for path, text in before.files.items())
    return after


def property_key(snapshot, prop):
    keys = [key.removesuffix('.property') + '.value' for key, value in snapshot.authoritative.items() if key.endswith('.property') and value == prop]
    assert len(keys) == 1, (prop, keys)
    return keys[0]


def native_edit(before, prop, value):
    key = property_key(before, prop)
    row = {'property': prop}
    raw = '`' + json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '`' if not isinstance(value, str) else '`' + value + '`'
    assert type(typed_row(row, raw, property_schema(prop))) is type(value)
    kind = '.'.join(prop.split('.')[:2])
    assert not DesignSchemaCatalog(Path(__file__).resolve().parents[4]).literal_errors(kind, prop[len(kind) + 1:], literal(raw))
    return candidate(before, {key: raw})


def invalid_fields(before, prop):
    # Retired parameter grammar is replaced by canonical key/Row/type trust boundaries.
    key = property_key(before, prop)
    with pytest.raises(ValueError, match='unknown Model field'):
        candidate(before, {'desired.resource.001.unknown': '1'})
    with pytest.raises(ValueError, match='Row requires'):
        candidate(before, {key: None})
    expected = property_schema(prop).get('type')
    if expected == 'string':
        assert typed_row({'property': prop}, '001', property_schema(prop)) == '001'
        with pytest.raises(ValueError, match='duplicate'):
            candidate(before, {key.removesuffix('.value') + '.document': '{"x":1,"x":2}'})
    else:
        kind = '.'.join(prop.split('.')[:2])
        assert DesignSchemaCatalog(Path(__file__).resolve().parents[4]).literal_errors(kind, prop[len(kind) + 1:], 'not-a-number')


@it_case
def check_kms():
    for before in cases('kms'):
        after = native_edit(before, 'KMS.Key.PendingWindowInDays', 20)
        assert after.authoritative[property_key(before, 'KMS.Key.PendingWindowInDays')] == '`20`'
        key = property_key(before, 'KMS.Alias.AliasName')
        renamed = candidate(before, {key: '`alias/log-acceptance`'})
        assert renamed.authoritative[key].endswith('-acceptance`')
        assert {key: raw for key, raw in renamed.authoritative.items() if key.startswith('desired.resource.')} == {
            key: raw for key, raw in before.authoritative.items() if key.startswith('desired.resource.')}
        invalid_fields(before, 'KMS.Key.Enabled')


@it_case
def check_security_group():
    for before in cases('security-group'):
        prop = 'EC2.SecurityGroup.SecurityGroupIngress[].FromPort'
        previous = typed_row({'property': prop}, before.authoritative[property_key(before, prop)], property_schema(prop))
        assert type(previous) is int
        assert native_edit(before, prop, previous + 1).authoritative[property_key(before, prop)] == '`444`'
        invalid_fields(before, prop)


@it_case
def check_route53():
    for before in cases('route53'):
        values = before.authoritative
        for rid, rows in resource_row_index(values).items():
            row, = [(row_id, spec) for row_id, spec in rows if spec['property'] == 'Route53.RecordSet.TTL']
            key = 'desired.row.' + row[0] + '.value'
            assert typed_row(row[1], row[1]['value'], property_schema('Route53.RecordSet.TTL')) == '60'
            assert candidate(before, {key: '`61`'}).authoritative[key] == '`61`'
        names = {key.removesuffix('.property') + '.value': raw for key, raw in values.items() if raw == 'Route53.RecordSet.Name'}
        changes = {key: values[key].replace('fixture.', 'fixturex.') for key in names}
        renamed = candidate(before, changes)
        assert len(changes) == 2 and all(renamed.authoritative[key] == values[key] for key in values if key.endswith('.anchor'))
        # Duplicate TTL Properties belong to distinct fixed Resources, and remain typed separately.
        assert all(literal(values[key.removesuffix('.property') + '.value']) == '60' for key, raw in values.items() if raw == 'Route53.RecordSet.TTL')


@it_case
def check_iam():
    objects = 0
    for before in cases('iam'):
        key, = [key for key in before.authoritative if key.endswith('.document')]
        document = json.loads(before.authoritative[key])
        assert isinstance(document['Statement'], (dict, list))
        objects += isinstance(document['Statement'], dict)
        updated = json.loads(before.authoritative[key])
        updated['Statement']['Principal']['AWS'] = '123456789012'
        after = candidate(before, {key: json.dumps(updated)})
        hash_key = key.removesuffix('.document') + '.artifactSha256'
        assert after.values[hash_key] == document_sha256(updated) and after.values[hash_key] != before.values[hash_key]
        assert hash_key not in after.authoritative
        invalid_fields(before, 'IAM.Role.RoleName')
    assert objects > 0


@it_case
def check_s3():
    trails = 0
    for before in cases('s3'):
        prop = 'S3.Bucket.LifecycleConfiguration.Rules[].ExpirationInDays'
        assert native_edit(before, prop, 31).authoritative[property_key(before, prop)] == '`31`'
        invalid_fields(before, prop)
        trail = before.scope.path.with_name('cloudtrail.properties')
        assert load_model(trail).authoritative
        trails += 1
    assert trails == len(list(cases('cloudtrail'))) and trails > 0


@it_case
def check_glue():
    jobs = 0
    for before in cases('glue'):
        assert before.authoritative[property_key(before, 'Glue.Job.Timeout')] == '`30`'
        key = property_key(before, 'Glue.Job.SecurityConfiguration')
        name = property_key(before, 'Glue.SecurityConfiguration.Name')
        logical = before.authoritative['desired.resource.002.logicalId']
        from model.identity import address
        after = candidate(before, {key: address(before.scope, dict(entries(before.authoritative, 'desired.resource.'))['002'], consumer_scope=before.scope), name: '`glsc-a1b2c3`'})
        assert after.authoritative['desired.resource.002.logicalId'] == logical
        raw = after.authoritative[property_key(before, 'Glue.Job.DefaultArguments')]
        arguments = json.loads(literal(raw))
        assert isinstance(arguments, dict) and all(isinstance(value, str) for value in arguments.values())
        jobs += 1
    assert jobs > 0


@it_case
def check_cloudwatch_logs():
    groups, producers = 0, set()
    for before in cases('cloudwatch-logs'):
        producers.update(spec['producerScope'].split('/')[-1] for spec in declarations(before.authoritative).values())
        groups += len(resource_row_index(before.authoritative))
        assert before.authoritative[property_key(before, 'Logs.LogGroup.DeletionProtectionEnabled')] == '`false`'
        assert before.authoritative[property_key(before, 'Logs.LogGroup.RetentionInDays')] == '`30`'
        assert not before.warnings
        # Producer edits diagnose a mismatch; they never regenerate the saved consumer.
        producer = before.scope.path.with_name('lambda.properties')
        original = producer.read_bytes()
        try:
            producer.write_bytes(original.replace(b'value=`fixture`', b'value=`changed`'))
            after = load_model(before.scope, FileReads())
            assert after.authoritative == before.authoritative and after.warnings
        finally:
            producer.write_bytes(original)
    assert groups > 0 and {'lambda', 'glue', 'iam', 'codebuild', 'mwaa', 'cloudtrail'} <= producers


@it_case
def check_lambda():
    functions = permissions = 0
    for before in cases('lambda'):
        for rid, rows in resource_row_index(before.authoritative).items():
            kind = before.authoritative['desired.resource.' + rid + '.resourceType']
            functions += kind == 'Lambda.Function'
            permissions += kind == 'Lambda.Permission'
            for _, row in rows:
                if row['property'] == 'Lambda.Function.Architectures':
                    assert json.loads(literal(row['value'])) == ['x86_64']
                if row['property'] == 'Lambda.Permission.Principal':
                    assert literal(row['value']) in ('s3.amazonaws.com', 'events.amazonaws.com')
        assert native_edit(before, 'Lambda.Function.MemorySize', 129).authoritative[property_key(before, 'Lambda.Function.MemorySize')] == '`129`'
    assert functions > 0 and permissions > 0


@it_case
def check_eventbridge():
    rules = schedules = 0
    for before in cases('eventbridge'):
        for rid, rows in resource_row_index(before.authoritative).items():
            kind = before.authoritative['desired.resource.' + rid + '.resourceType']
            rules += kind == 'Events.Rule'
            schedules += kind == 'Scheduler.Schedule'
            for row_id, row in rows:
                if row['property'] == 'Events.Rule.EventPattern':
                    doc = json.loads(before.authoritative['desired.row.' + row_id + '.document'])
                    assert doc['detail']['eventName'] == ['GetObject']
                    assert isinstance(doc['detail']['userIdentity']['userName'], list)
                    assert isinstance(doc['detail']['requestParameters']['bucketName'], list)
                elif row['property'].endswith('.ScheduleExpressionTimezone'):
                    assert literal(row['value']) == 'Asia/Tokyo'
                elif row['property'].endswith('.ScheduleExpression'):
                    assert literal(row['value']).startswith('cron(')
                elif row['property'].endswith('.State'):
                    assert literal(row['value']) in ('ENABLED', 'DISABLED')
        for name, value in [('MaximumEventAgeInSeconds', 3600), ('MaximumRetryAttempts', 3)]:
            rows = [row for owned in resource_row_index(before.authoritative).values() for _, row in owned if row['property'].endswith('.RetryPolicy.' + name)]
            assert rows and all(row['value'] == f'`{value}`' for row in rows)
        assert not before.warnings
    assert rules > 0 and schedules > 0


@it_case
def check_codepipeline():
    pipelines = configurations = 0
    for before in cases('codepipeline'):
        for rows in resource_row_index(before.authoritative).values():
            pipelines += 1
            formal = [[row_id, row['property'].removeprefix('CodePipeline.Pipeline.'), row['value'], row['comment']] for row_id, row in rows]
            restored = pipeline_display_rows(pipeline_rows(formal))
            assert [(row[1].removeprefix('CodePipeline.Pipeline.'), row[2]) for row in restored] == [(row[1], row[2]) for row in formal]
            for row_id, row in rows:
                if row['property'].endswith('.Configuration'):
                    document = json.loads(literal(row['value']))
                    assert all(type(value) is str for value in document.values())
                    key = 'desired.row.' + row_id + '.value'
                    after = candidate(before, {key: '`' + json.dumps({**document, 'BranchName': document['BranchName'] + '-probe'}) + '`'})
                    assert json.loads(literal(after.authoritative[key])) == {**document, 'BranchName': document['BranchName'] + '-probe'}
                    configurations += 1
    assert pipelines > 0 and configurations > 0


@it_case
def check_responsibilities():
    services = {'config', 'data-firehose', 'guardduty', 'macie', 'quicksight', 'codebuild', 'ec2', 'mwaa', 'cloudformation-stacks', 'transit-gateway'}
    for service in sorted(services):
        for before in cases(service):
            assert before.authoritative and before.locations
            assert not any(key.endswith('.artifactSha256') for key in before.authoritative)
            assert ROOT / 'project.json' in before.dependencies
            if service == 'cloudformation-stacks':
                after = candidate(before, {'desired.deployment.maxConcurrentStacks': '3'})
                assert after.authoritative['desired.stack.fixture.placementName'] == 'fixture'
                assert after.values['desired.deployment.maxConcurrentStacks'] == '3'
                with pytest.raises(ValueError):
                    candidate(before, {'desired.deployment.maxConcurrentStacks': '0'})
            else:
                key, = [key for key in before.authoritative if key.endswith('.value')]
                after = candidate(before, {key: '`changed`'})
                assert all(after.authoritative[key] == raw for key, raw in before.authoritative.items() if key.startswith(('desired.resource.', 'observed.')))
            for key, raw in before.authoritative.items():
                if key.endswith('.document'):
                    assert before.values[key.removesuffix('.document') + '.artifactSha256'] == document_sha256(json.loads(raw))


@it_case
@input_scope
def check():
    from support.service_fixtures import typed_services
    with TemporaryDirectory(prefix='typed-services-') as directory:
        root = Path(directory)
        typed_services(root)
        with patch(__name__ + '.ROOT', root):
            check_fixtures()


@it_case
def check_fixtures():
    check_responsibilities()
    check_kms()
    check_security_group()
    check_route53()
    check_iam()
    check_s3()
    check_glue()
    check_cloudwatch_logs()
    check_lambda()
    check_eventbridge()
    check_codepipeline()
