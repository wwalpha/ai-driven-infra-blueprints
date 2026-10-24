#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import aws_mapping_compare as _imports_aws_mapping_compare
import support.check_model_aws_fixtures as _retained_fixture_offline_network
from aws_mapping import Identity
from support.check_model_aws_fixtures import (
    ACCOUNT,
    PATCHES,
    REPRESENTATIVES,
    STACK_MODEL,
    TARGET,
    ExitStack,
    FakeResource,
    Offline,
    Path,
    SimpleNamespace,
    Stubber,
    acquired,
    boto3,
    check,
    copy,
    expect,
    io,
    json,
    m,
    model_text,
    os,
    patch,
    pytest,
    redirect_stderr,
    redirect_stdout,
    remove_tokens,
    run,
    set_path,
    shape_value,
    sys,
    write_model,
)
from support.it_case_receipt import it_case

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

offline_network = _retained_fixture_offline_network.offline_network

_CALLBACK_DEFAULT = object()



@it_case
def service_checks(root):
    # Every supported field is extracted from a real botocore-validated SDK
    # response after executing the service's fetch adapter. These are not stubs
    # that simply echo comparator mappings. Unknown SDK paths fail here.
    type_count, field_count = 0, 0
    for service in m.SERVICES:
        module = m.service_module(service)
        if service == 'cloudformation-stacks':
            continue
        comparison = _imports_aws_mapping_compare.comparison
        mapping, definitions = comparison(m.ROOT, service)
        for kind in sorted(mapping.adapter_resource_types):
            relevant = {prop: item.field for prop, item in definitions.items()
                        if prop.startswith(kind + '.') and item.field.classification == 'supported'
                        and mapping.getters.get(item.field.getter, {}).get('kind') == 'adapter'}
            relevant.update(getattr(module, 'MODEL_FIELDS', {}))
            relevant = {key: field for key, field in relevant.items() if key.startswith(kind + '.')}
            if not relevant:  # Inline types still must have their actual getter exercised below.
                raise AssertionError('resource type without acquisition: ' + kind)
            owner = {'S3.BucketPolicy': 'S3.Bucket', 'EC2.SubnetRouteTableAssociation': 'EC2.Subnet'}.get(kind, kind)
            ctx = Offline(root)
            ctx.egress = False
            ctx.verify()
            resource = FakeResource(ctx, service, owner)
            for prop, field in relevant.items():
                value = m.select(ctx.fetch(resource, field.getter), field.path)
                check(acquired(value), 'unreadable mapping ' + prop + ' -> ' + field.path)
                field_count += 1
            identity = mapping.identities.get(kind)
            if identity is not None:
                response = ctx.fetch(resource, identity.getter)
                for path in (identity.id_path, identity.arn_path):
                    if path is not None:
                        check(acquired(m.select(response, path)), 'unreadable identity ' + kind + ' -> ' + path)
                getter, id_path, arn_path, name_property = identity.getter, identity.id_path, identity.arn_path, identity.name_property
                for mode in ('id', 'arn', 'name'):
                    start = len(ctx.trace)
                    if mode == 'name' and name_property:
                        ctx.fetch(resource, getter)
                        expected = resource.value(name_property, 'string')
                    elif (path := arn_path if mode == 'arn' else id_path):
                        expected = m.select(ctx.fetch(resource, getter), path)
                    else:
                        expect(m.Unresolved, lambda *, mode=mode, resource=resource: m.Resource.identity(resource, mode))
                        continue
                    expected_trace = ctx.trace[start:]
                    start = len(ctx.trace)
                    check(m.Resource.identity(resource, mode) == expected, kind + ': Registry ' + mode)
                    check(ctx.trace[start:] == expected_trace, kind + ': identity API trace/cache unchanged')
            ctx.finish()
            type_count += 1
        kind, prop, expected = REPRESENTATIVES[service]
        for state in ('match', 'difference', 'missing', 'failed'):
            ctx = Offline(root)
            ctx.egress = False
            ctx.verified = True
            ctx.fault = state if state in {'missing', 'failed'} else None
            different = not expected if type(expected) is bool else expected + 1 if type(expected) is int else 'deliberately different'
            resource = FakeResource(ctx, service, kind, kind + '.' + prop, expected if state != 'difference' else different)
            results = m.compare_resource(ctx, resource)
            wanted = {'missing': 'resource_missing', 'failed': 'acquisition_failed'}.get(state, state)
            check(any(item['status'] == wanted for item in results), service + ': ' + state + ': ' + repr(results))
            ctx.finish()
    print(f'Service acquisition/field extraction: {type_count} resource types, {field_count} supported mappings, 27 × 4 comparison cases')


def _callback_cli_checks_execute(responses, /, command, **kwargs):
    check(command[0] == 'aws' and isinstance(command, list), 'CLI uses argument list without a shell')
    check(command[command.index('--region') + 1] == TARGET['awsRegion'], 'configured CLI region')
    check(command[command.index('--profile') + 1] == 'configured', 'configured CLI profile')
    check('--output' in command and command[command.index('--output') + 1] == 'json' and '--query' not in command,
          'complete JSON response without output filtering')
    check('--no-cli-pager' in command and kwargs['env']['AWS_CLI_AUTO_PROMPT'] == 'off', 'no interactive CLI prompt or pager')
    check(kwargs['encoding'] == 'utf-8', 'CLI JSON decoded as UTF-8')
    inputs = json.loads(command[command.index('--cli-input-json') + 1])
    if command[2] in {'get-bucket-location', 'get-bucket-versioning'}:
        check(inputs == {'Bucket': 'fixture', 'ExpectedBucketOwner': ACCOUNT}, 'structured CLI inputs preserve owner safeguard')
    check(('--no-paginate' not in command) == (command[2] == 'list-buckets'), 'collections use CLI automatic pagination')
    return SimpleNamespace(returncode=0, stdout=json.dumps(responses[tuple(command[1:3])]), stderr='')


@it_case
def cli_checks(root):
    directory = root / 'model/dev' / ACCOUNT
    directory.mkdir(parents=True)
    path = directory / 's3.properties'
    write_model(path, model_text('S3.Bucket', [('S3.Bucket.BucketName', '`fixture`'),
                                             ('S3.Bucket.VersioningConfiguration.Status', '`Enabled`')]))
    items = [(dict(TARGET, awsProfile='configured'), path)]
    responses = {
        ('sts', 'get-caller-identity'): {'Account': ACCOUNT, 'Arn': 'arn:aws:iam::' + ACCOUNT + ':user/offline'},
        ('s3api', 'list-buckets'): {'Buckets': [{'Name': 'fixture'}]},
        ('s3api', 'get-bucket-versioning'): {'Status': 'Enabled'},
        ('s3api', 'get-bucket-location'): {'LocationConstraint': TARGET['awsRegion']},
    }

    execute = _bind_framework_callback(_callback_cli_checks_execute, responses)

    with patch.object(m.subprocess, 'run', side_effect=execute) as process, \
            patch.object(boto3, 'Session', side_effect=AssertionError('default comparison must use CLI')):
        report = m.run(root, items)
        check(report['status'] == 'matched' and report['counts'] == {'match': 2}, 'default CLI comparison retains matches')
        check(process.call_count == 4, 'one STS check and cached selected-service retrieval')
        responses[('s3api', 'get-bucket-versioning')] = {'Status': 'Suspended'}
        check(m.run(root, items)['exitCode'] == 1, 'CLI difference remains exit 1')
        responses[('sts', 'get-caller-identity')] = {'Account': '999999999999'}
        process.reset_mock()
        check(m.run(root, items)['exitCode'] == 2 and process.call_count == 1, 'account mismatch stops before service CLI calls')
        process.reset_mock()
        expect(ValueError, lambda: m.run(root, items, profile='wrong'))
        check(not process.called, 'profile conflict stops before CLI invocation')

    for fault, reason in [(FileNotFoundError('secret'), 'FileNotFoundError'),
                          (SimpleNamespace(returncode=255, stdout='', stderr='secret credential failure'), 'AwsCliError'),
                          (SimpleNamespace(returncode=0, stdout='invalid secret', stderr=''), 'JSONDecodeError'),
                          (SimpleNamespace(returncode=0, stdout='[]', stderr=''), 'ValueError')]:
        with patch.object(m.subprocess, 'run', side_effect=fault if isinstance(fault, Exception) else None,
                          return_value=fault) as process:
            report = m.run(root, items)
            check(report['exitCode'] == 2 and report['results'][0]['reason'] == reason, 'CLI failures remain incomplete')
            check('secret' not in json.dumps(report) and process.call_count == 1, 'CLI error details hidden and no fallback')

    for code, expected in [('NoSuchBucket', 'resource_missing'), ('AccessDenied', 'acquisition_failed')]:
        ctx = m.Context(root, items[0][0])
        ctx.verified = True
        error = SimpleNamespace(returncode=254, stdout='', stderr=f'An error occurred ({code}) when calling the GetBucketVersioning operation: secret')
        with patch.object(m.subprocess, 'run', return_value=error) as process:
            for _ in range(2):
                with pytest.raises(m.AcquisitionError) as caught:
                    ctx.call('s3', 'get_bucket_versioning', Bucket='fixture')
                check(caught.value.status == expected and caught.value.code == code, 'CLI AWS error classification retained')
                check('secret' not in str(caught.value), 'CLI error message redacted')
            check(process.call_count == 1, 'failed CLI request cached')

    ctx = m.Context(root, TARGET)
    with patch.object(m.subprocess, 'run') as process:
        expect(ValueError, lambda: ctx.call('s3', 'list_buckets'))
        ctx.verified = True
        expect(ValueError, lambda: ctx.call('secretsmanager', 'get_secret_value', SecretId='fixture'))
        expect(ValueError, lambda: ctx.call('s3', 'delete_bucket', Bucket='fixture'))
        expect(ValueError, lambda: ctx.pages('s3', 'delete_bucket', Bucket='fixture'))
        check(not process.called, 'unverified, secret and mutating CLI calls blocked')
    merged = {'ResourceRecordSets': [{'Name': 'first'}, {'Name': 'second'}]}
    with patch.object(m.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(merged), stderr='')) as process:
        check(ctx.pages('route53', 'list_resource_record_sets', HostedZoneId='fixture') == merged, 'CLI merged pagination response preserved')
        check(ctx.pages('route53', 'list_resource_record_sets', HostedZoneId='fixture') == merged and process.call_count == 1, 'CLI pagination cached')
        check('--no-paginate' not in process.call_args.args[0] and '--max-items' not in process.call_args.args[0], 'CLI owns service-specific pagination tokens')
    with patch.object(m.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='{}', stderr='')) as process:
        ctx.call('logs', 'describe_log_groups', logGroupNamePrefix='日本語')
        check(json.loads(process.call_args.args[0][process.call_args.args[0].index('--cli-input-json') + 1]) == {'logGroupNamePrefix': '日本語'}, 'Unicode CLI input preserved')
        check('--profile' not in process.call_args.args[0], 'unconfigured profile uses CLI credential chain')
    ctx = m.Context(root, TARGET)
    ctx.verified = True
    with patch.object(m.subprocess, 'run', return_value=SimpleNamespace(returncode=254, stdout=json.dumps(merged), stderr='An error occurred (AccessDenied) when calling the ListResourceRecordSets operation: later page')):
        expect(m.AcquisitionError, lambda: ctx.pages('route53', 'list_resource_record_sets', HostedZoneId='fixture'))


@pytest.mark.parametrize('service,operation,cli_service', [
    ('config', 'describe_configuration_recorders', 'configservice'),
    ('config', 'describe_delivery_channels', 'configservice'),
    ('s3', 'list_buckets', 's3api'),
    ('logs', 'describe_log_groups', 'logs'),
])
@pytest.mark.parametrize('paginate', [False, True])
def check_cli_service_names(tmp_path, service, operation, cli_service, paginate):
    ctx = m.Context(tmp_path, TARGET)
    ctx.verified = True
    with patch.object(m.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='{}', stderr='')) as process:
        (ctx.pages if paginate else ctx.call)(service, operation)
    command = process.call_args.args[0]
    assert command[:3] == ['aws', cli_service, operation.replace('_', '-')]
    assert ('--no-paginate' not in command) == paginate




def _batch_checks_cli(arguments):
    stdout, stderr = (io.StringIO(), io.StringIO())
    with patch.object(sys, 'argv', ['check-model-aws.py', *arguments]), redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            code = m.main()
        except SystemExit as error:
            code = error.code
    return (code, json.loads(stdout.getvalue()) if stdout.getvalue() else None, stderr.getvalue())


def _callback_batch_checks_compare_session_factory_client(api_calls, fault, real_client, requests, stack, stubbers, /, service, **client_kwargs):
    result = real_client(service, **client_kwargs)
    stub = stack.enter_context(Stubber(result))
    stubbers.append(stub)
    api_calls.append((service, stack.enter_context(patch.object(result, '_make_api_call', wraps=result._make_api_call))))
    for operation, inputs in requests[service]:
        if service == 'kms' and fault:
            stub.add_client_error(operation, 'NotFoundException' if fault == 'missing' else 'AccessDeniedException', expected_params=inputs)
            continue
        response = remove_tokens(shape_value(result.meta.service_model.operation_model(result.meta.method_to_api_mapping[operation]).output_shape))
        for path, value in PATCHES.get((service, operation), {}).items():
            set_path(response, path, copy.deepcopy(value))
        if service == 's3' and operation == 'get_bucket_location':
            response['LocationConstraint'] = TARGET['awsRegion']
        if service == 's3' and operation == 'get_bucket_versioning':
            response['Status'] = 'Enabled'
        stub.add_response(operation, response, expected_params=inputs)
    return result


def _callback_batch_checks_compare_session_factory(api_calls, fault, requests, session_class, stack, stubbers, /, **kwargs):
    session = session_class(aws_access_key_id='offline', aws_secret_access_key='offline', region_name=kwargs['region_name'])
    real_client = session.client

    client = _bind_framework_callback(_callback_batch_checks_compare_session_factory_client, api_calls, fault, real_client, requests, stack, stubbers)

    stack.enter_context(patch.object(session, 'client', side_effect=client))
    return session


def _callback_batch_checks_compare_294(base_args, cli, requests, root, selected, session_class, _default_fault, _default_direct, _default_items, /, services, fault=_CALLBACK_DEFAULT, direct=_CALLBACK_DEFAULT, items=_CALLBACK_DEFAULT):
    if fault is _CALLBACK_DEFAULT:
        fault = _default_fault
    if direct is _CALLBACK_DEFAULT:
        direct = _default_direct
    if items is _CALLBACK_DEFAULT:
        items = _default_items
    with ExitStack() as stack:
        api_calls, stubbers = [], []

        session_factory = _bind_framework_callback(_callback_batch_checks_compare_session_factory, api_calls, fault, requests, session_class, stack, stubbers)

        factory = stack.enter_context(patch.object(boto3, 'Session', side_effect=session_factory))
        contexts = stack.enter_context(patch.object(m, 'Context', wraps=m.Context))
        if direct:
            report = m.run(root, items if items is not None else m.inventory(root, selected, services), session_factory=factory)
            code = report['exitCode']
        else:
            actual_run = m.run
            with patch.object(m, 'run', side_effect=lambda root, items, profile: actual_run(root, items, profile, session_factory=factory)):
                code, report, _ = cli([*base_args, *(arg for service in services for arg in ('--service', service))])
        for stub in stubbers:
            stub.assert_no_pending_responses()
        target_count = len({(target['environment'], target['directory']) for target, _ in items}) if items is not None else 1
        check(factory.call_count == contexts.call_count == target_count, 'Session factory and real Context initialized once per target')
        check(sum(call.call_count for service, call in api_calls if service == 'sts') == target_count, 'STS get_caller_identity called once per target')
        expected_apis = {service: len(requests[service]) * target_count for service in {'sts', *services}}
        actual_apis = {service: sum(call.call_count for name, call in api_calls if name == service) for service, _ in api_calls}
        check(actual_apis == expected_apis, 'only selected service API requests, no extra or repeated SDK calls')
        return code, report


@it_case
def batch_checks(root):
    directory = root / 'model/dev' / ACCOUNT
    directory.mkdir(parents=True)
    (root / 'project.json').write_text(json.dumps({'targets': [TARGET, dict(TARGET, environment='stg')]}), encoding='utf-8')
    s3 = directory / 's3.properties'
    s3_rows = [('S3.Bucket.BucketName', '`fixture`'), ('S3.Bucket.VersioningConfiguration.Status', '`Enabled`')]
    write_model(s3, model_text('S3.Bucket', s3_rows))
    write_model(directory / 'iam.properties', model_text('IAM.Role', [('IAM.Role.RoleName', '`fixture`')]))
    # An unrelated entrance must never be compared or included in scoped coverage.
    write_model(directory / 'athena.properties', model_text('Athena.WorkGroup', [('Athena.WorkGroup.Name', '`fixture`')]))
    selected = m.targets(root, 'dev', ACCOUNT)
    base_args = ['--root', str(root), '--environment', 'dev', '--target', ACCOUNT]

    cli = _batch_checks_cli

    session_class = boto3.Session
    requests = {
        'sts': [('get_caller_identity', {})],
        's3': [('list_buckets', {}), ('get_bucket_location', {'Bucket': 'fixture', 'ExpectedBucketOwner': ACCOUNT}),
               ('get_bucket_versioning', {'Bucket': 'fixture', 'ExpectedBucketOwner': ACCOUNT})],
        'iam': [('get_role', {'RoleName': 'fixture'})],
        'kms': [('describe_key', {'KeyId': 'fixture'})],
    }

    compare = _bind_framework_callback(_callback_batch_checks_compare_294, base_args, cli, requests, root, selected, session_class, None, False, None)

    single = compare(['s3'])
    check(single == compare(['s3'], direct=True), 'single-service CLI preserves existing run result exactly')
    check(single[0] == 0 and single[1]['counts'] == {'match': 2}, 'single service remains matched')
    check(single == compare(['s3', 's3']), 'duplicate CLI services do not duplicate results or API calls')
    iam = compare(['iam'])
    code, batch = compare(['s3', 'iam'])
    expected = m.summarize(iam[1]['results'] + single[1]['results'])
    check(code == 0 and batch == expected, 'batch results equal standalone results, preserving JSON and counts')
    check({item['service'] for item in batch['results']} == {'s3', 'iam'}, 'batch compares both requested services only')
    compare(['s3', 'iam'], direct=True)
    batch_items = m.inventory(root, selected, ['s3', 'iam'])
    stg_items = []
    for target, path in batch_items:
        stg = root / 'model/stg' / target['directory'] / path.name
        stg.parent.mkdir(parents=True, exist_ok=True)
        stg.write_bytes(path.read_bytes())
        stg_items.append((dict(target, environment='stg'), stg))
    compare(['s3', 'iam'], direct=True, items=batch_items + stg_items)

    with patch.object(boto3, 'Session', side_effect=AssertionError('offline coverage must not create a session')) as factory, \
            patch.object(m.subprocess, 'run', side_effect=AssertionError('offline coverage must not invoke AWS CLI')) as process:
        code, report, _ = cli([*base_args, '--service', 's3', '--service', 'iam', '--coverage'])
        check(code == 0 and report['services'] == ['iam', 's3'] and report['modelCount'] == 2, 'batch coverage selects requested services only')
        check({item['service'] for item in report['mappings']} == {'s3', 'iam'} and report['keyCount'] == 3, 'unselected service excluded from coverage mappings')
        code, duplicate, _ = cli([*base_args, '--service', 's3', '--service', 'iam', '--service', 's3', '--coverage'])
        check(code == 0 and duplicate == report, 'coverage deduplicates requested services')
        check(not factory.called, 'coverage never creates an SDK session')
        check(not process.called, 'coverage never invokes AWS CLI')

    expect(ValueError, lambda: m.inventory(root, selected, ['s3', 'iam', 'kms']))
    expect(ValueError, lambda: m.inventory(root, selected, ['kms']))
    with patch.object(m, 'run') as run, patch.object(m, 'coverage') as coverage:
        for flags in ([], ['--coverage']):
            code, report, _ = cli([*base_args, '--service', 's3', '--service', 'iam', '--service', 'kms', *flags])
            check(code == 2 and report == {'status': 'incomplete', 'reason': 'service entrance models are missing for target: kms'}, 'missing batch service fails closed in existing error schema')
        check(not run.called and not coverage.called, 'missing service rejected before comparison or coverage')
    with patch.object(m, 'targets') as targets:
        for flags in ([], ['--all', '--service', 's3'], ['--all', '--environment', 'dev'],
                      ['--all', '--target', ACCOUNT], ['--environment', 'dev', '--target', ACCOUNT],
                      ['--service', 's3'], ['--environment', 'dev', '--service', 's3'],
                      ['--target', ACCOUNT, '--service', 's3']):
            code, report, error = cli(['--root', str(root), *flags])
            check(code == 2 and report is None and 'use --all alone' in error, 'invalid selector rejected: ' + repr(flags))
        check(not targets.called, 'invalid selectors rejected before inventory')
    with patch.object(m, 'run', return_value=single[1]) as run:
        code, _, _ = cli(['--root', str(root), '--all'])
        check(code == 0 and {path.stem for _, path in run.call_args.args[1]} == {'s3', 'iam', 'athena'}, 'explicit --all remains available')

    write_model(directory / 'kms.properties', model_text('KMS.Key', [('KMS.Key.KeyId', '`fixture`'), ('KMS.Key.Description', '`fixture`')]))
    s3_rows[1] = ('S3.Bucket.VersioningConfiguration.Status', '`Suspended`')
    write_model(s3, model_text('S3.Bucket', s3_rows))
    for fault, wanted_code, wanted_status in ((None, 1, 'identifier'), ('missing', 1, 'resource_missing'), ('failed', 2, 'acquisition_failed')):
        code, report = compare(['s3', 'iam', 'kms'], fault=fault)
        statuses = {(item['service'], item['status']) for item in report['results']}
        check(code == wanted_code and ('s3', 'difference') in statuses and ('iam', 'match') in statuses and ('kms', wanted_status) in statuses,
              'batch exit precedence retains successful comparisons and S3 differences: ' + str(fault))
        check(set(report) == {'status', 'exitCode', 'counts', 'results'}, 'batch does not add a JSON wrapper')


def _callback_common_checks_bad_factory(calls, /, **kw):
    calls.append(kw)
    raise RuntimeError('secret credential failure')


@it_case
def common_checks(root):
    directory = root / 'model/dev' / ACCOUNT
    directory.mkdir(parents=True)
    (root / 'project.json').write_text(json.dumps({'targets': [TARGET]}), encoding='utf-8')
    check(m.targets(root, 'dev', ACCOUNT)[0]['directory'] == ACCOUNT, 'existing target resolver')
    expect(ValueError, lambda: m.targets(root, 'dev', 'unknown'))
    text = model_text('Athena.WorkGroup', [('Athena.WorkGroup.Name', '`fixture`'), ('Athena.WorkGroup.State', '`ENABLED`')])
    path = directory / 'athena.properties'
    write_model(path, text)
    data = path.read_text()
    parts = path.with_suffix('')
    parts.mkdir()
    (parts / 'part-001.properties').write_text('# model-format: 2\ndesired.note.001.text=Standalone annotation\n')
    (parts / 'part-002.properties').write_text(data)
    path.write_text('# model-format: 2\n# model-index: 2\n# part: athena/part-001.properties\n# part: athena/part-002.properties\n')
    ctx = Offline(root)
    ctx.egress = False
    ctx.verify()
    model = ctx.model(path)
    check(len(model.resources) == 1 and model.locations['desired.row.001-002.value']['file'].endswith('part-002.properties'), 'split projection and source')
    check(all(item['status'] == 'match' for item in m.compare_resource(ctx, model.resources[0])), 'desired typed model comparison')
    check(ctx.request_count == 2, 'one shared SDK response for two selected keys')
    check(all(item['apis'] for item in m.compare_resource(ctx, model.resources[0])), 'cached responses retain API evidence')
    resource = model.resources[0]
    resource.rows.append(('001-003', {'property': 'Athena.WorkGroup.Unknown', 'value': 'false', 'comment': 'fixture'}))
    model.locations['desired.row.001-003.value'] = {'file': str(path), 'line': 1}
    expect(ValueError, lambda: m.compare_resource(ctx, resource))  # Missing Mapping is a validation error.
    resource.rows.pop()
    resource.rows[1][1]['value'] = 'UNSET'
    check(any(item['status'] == 'design_unresolved' for item in m.compare_resource(ctx, resource)), 'unresolved desired is not equality')
    resource.rows[1][1]['value'] = '`ENABLED`'
    failed = Offline(root, 'failed')
    failed.egress = False
    failed.verified = True
    failures = m.compare_resource(failed, failed.model(path).resources[0])
    check(len(failures) == 1 and len(failures[0]['affectedKeys']) == 2, 'one failure with affected-key scope')
    ctx.finish()
    expect(ValueError, lambda: ctx.call('s3', 'delete_bucket', Bucket='fixture'))
    expect(ValueError, lambda: ctx.call('secretsmanager', 'get_secret_value', SecretId='fixture'))
    unverified = Offline(root)
    expect(ValueError, lambda: unverified.call('s3', 'list_buckets'))
    bad = dict(TARGET, awsAccountId='999999999999')
    ctx2 = Offline(root, target=bad)
    expect(m.IdentityError, ctx2.verify)
    check(not ctx2.verified and set(ctx2.clients) == {'sts'}, 'account mismatch stops all service APIs')
    split = Offline(root, target=dict(TARGET, awsAccountId='999999999999', awsExecutionAccountId=ACCOUNT))
    split.verify()
    check(split.verified and split.target['awsAccountId'] == '999999999999', 'execution account verification preserves resource account')
    split_resource = split.model(path).resources[0]
    check(split_resource.resolve_json({'Fn::Sub': 'account-${AWS::AccountId}'}, None) == 'account-' + ACCOUNT,
          'live CFN pseudo account uses verified execution account')
    check(split_resource.resolve_json({'Ref': 'AWS::AccountId'}) == ACCOUNT,
          'live CFN Ref pseudo account uses verified execution account')
    split.finish()
    wrong_execution = Offline(root, target=dict(TARGET, awsExecutionAccountId='999999999999'))
    expect(m.IdentityError, wrong_execution.verify)
    check(not wrong_execution.verified and set(wrong_execution.clients) == {'sts'}, 'execution mismatch stops all service APIs')
    # Implicit API account contexts use execution IDs; explicit model values stay untouched.
    execution = '999999999999'
    api_ctx = SimpleNamespace(target=dict(TARGET, awsExecutionAccountId=execution))
    resource_stub = SimpleNamespace(kind='SQS.Queue', value=lambda key: 'fixture', current=lambda key: None)
    with patch.object(api_ctx, 'call', create=True, return_value={'QueueUrl': 'url'}) as call:
        m.service_module('sqs').fetch(api_ctx, resource_stub, 'base')
        check(call.call_args_list[0].kwargs['QueueOwnerAWSAccountId'] == execution, 'SQS implicit owner is execution account')
    with patch.object(api_ctx, 'call', create=True, return_value={}) as call:
        m.service_module('s3').fetch(api_ctx, resource_stub, 'versioning')
        check(call.call_args.kwargs['ExpectedBucketOwner'] == execution, 'S3 implicit owner is execution account')
        check(m.service_module('macie').fetch(api_ctx, resource_stub, 'session')['AwsAccountId'] == execution,
              'Macie session actual account is execution account')
    resource_stub.kind = 'Glue.Catalog'
    with patch.object(api_ctx, 'pages', create=True, return_value={'CatalogList': [{'Name': 'fixture'}]}) as pages:
        m.service_module('glue').fetch(api_ctx, resource_stub, 'base')
        check(pages.call_args.kwargs['ParentCatalogId'] == execution, 'Glue implicit parent catalog is execution account')
    calls = []
    expect(ValueError, lambda: m.run(root, [(dict(TARGET, awsProfile='confirmed'), path)], profile='wrong', session_factory=lambda **kw: calls.append(kw)))
    check(not calls, 'profile conflict rejected before session creation')
    bad_factory = _bind_framework_callback(_callback_common_checks_bad_factory, calls)
    m.run(root, [(dict(TARGET, awsProfile='confirmed'), path)], session_factory=bad_factory)
    check(len(calls) == 1 and calls[0]['profile_name'] == 'confirmed', 'no profile fallback')
    # Real paginator and two STS-free, credential-free pages, including a later-page failure.
    for fail in (False, True):
        session = boto3.Session(aws_access_key_id='offline', aws_secret_access_key='offline', region_name=TARGET['awsRegion'])
        page_ctx = m.Context(root, TARGET, session)
        page_ctx.verified = True
        client = page_ctx.client('logs')
        with Stubber(client) as stub:
            stub.add_response('describe_log_groups', {'logGroups': [{'logGroupName': 'first'}], 'nextToken': 'page-2'}, {})
            if fail:
                stub.add_client_error('describe_log_groups', 'AccessDeniedException', expected_params={'nextToken': 'page-2'})
                expect(m.AcquisitionError, lambda *, page_ctx=page_ctx: page_ctx.pages('logs', 'describe_log_groups'))
            else:
                stub.add_response('describe_log_groups', {'logGroups': [{'logGroupName': 'second'}]}, {'nextToken': 'page-2'})
                check(len(page_ctx.pages('logs', 'describe_log_groups')['logGroups']) == 2, 'all paginator pages')
            stub.assert_no_pending_responses()
    # Reference resolution reads the authoritative model and obtains ARN from SDK.
    role = directory / 'iam.properties'
    write_model(role, model_text('IAM.Role', [('IAM.Role.RoleName', '`fixture`')], anchor='iam-fixture'))
    check(resource.resolve_json('[fixture](iam.md#iam-fixture)', 'arn').startswith('arn:' ) is False, 'SDK synthetic ARN used, not constructed')
    expect(m.Unresolved, lambda: resource.reference('[missing](iam.md#missing)'))
    # Ordered arrays remain ordered; tags keep Key/Value pairs together.
    check(m.normalize(ctx, 'false', 'boolean') is False and m.normalize(ctx, '60', 'number') == 60, 'typed SDK string values')
    expect(m.Unresolved, lambda: m.normalize(ctx, 'FALSE', 'boolean'))
    check(m.normalize(ctx, 'alias/fixture', 'kms') == m.normalize(ctx, 'fixture', 'kms'), 'SDK-confirmed KMS alias/key identity')
    check(resource.resolve_json({'Fn::ImportValue': 'fixture-export'}) == 'confirmed-export-value', 'SDK-confirmed export in authoritative policy')
    check(resource.resolve_json({'Fn::Sub': '${AWS::AccountId}/${AWS::Region}/${AWS::Partition}'}) == ACCOUNT + '/ap-northeast-1/aws', 'verified pseudo-parameters')
    expect(m.Unresolved, lambda: resource.resolve_json({'Fn::ImportValue': 'missing-export'}))
    sample_row = {'property': 'GuardDuty.MalwareProtectionPlan.ProtectedResource.S3Bucket.ObjectPrefixes[]', 'value': '`["a/","b/"]`'}
    check(resource.parse(sample_row) == ['a/', 'b/'], 'terminal-array literal')
    check(resource.parse({'property': 'S3.Bucket.LifecycleConfiguration.Rules[].Prefix', 'value': '``'}) == '', 'explicit empty optional prefix')
    ctx.finish()
    # Stack presence/state and local metadata, without templates or parameters.
    stacks = directory / 'cloudformation-stacks.properties'
    write_model(stacks, STACK_MODEL)
    for fault in (None, 'missing', 'failed'):
        stack_ctx = Offline(root, fault)
        stack_ctx.egress = False
        stack_ctx.verified = True
        results = m.service_module('cloudformation-stacks').compare(stack_ctx, stack_ctx.model(stacks))
        check(results[0]['status'] == {None: 'match', 'missing': 'resource_missing', 'failed': 'acquisition_failed'}[fault], 'stack acquisition')
        check(sum(item['status'] == 'local_metadata' for item in results) == 4, 'stack local metadata')
        stack_ctx.finish()


@it_case
def association_checks(root):
    directory = root / 'model/dev' / ACCOUNT
    directory.mkdir(parents=True, exist_ok=True)
    write_model(directory / 'cloudformation-stacks.properties', STACK_MODEL)
    # SDK responses and desired rows are authored separately. Moving a tag value
    # onto a different key must fail even when the multisets of values are equal.
    path = directory / 'ec2.properties'
    text = model_text('EC2.Instance', [('EC2.Instance.InstanceId', '[Instance](#fixture)'),
                      ('EC2.Instance.Tags[].Key', '`b`'), ('EC2.Instance.Tags[].Value', '`2`'),
                      ('EC2.Instance.Tags[].Key', '`a`'), ('EC2.Instance.Tags[].Value', '`1`')])
    text += 'observed.row.001-001.value=fixture\n'
    write_model(path, text)
    for wrong in (False, True):
        patches = copy.deepcopy(PATCHES)
        patches[('ec2', 'describe_instances')] = {'Reservations.Instances.Tags': [{'Key': 'a', 'Value': '2' if wrong else '1'}, {'Key': 'b', 'Value': '1' if wrong else '2'}]}
        with patch.dict(PATCHES, patches, clear=True):
            ctx = Offline(root)
            ctx.egress = False
            ctx.verified = True
            values = m.compare_resource(ctx, ctx.model(path).resources[0])
            check(any(v['status'] == 'difference' for v in values) == wrong, 'tag values belong to their keys')
            ctx.finish()
    pipeline = directory / 'codepipeline.properties'
    write_model(pipeline, model_text('CodePipeline.Pipeline', [
        ('CodePipeline.Pipeline.Name', '`fixture`'),
        ('CodePipeline.Pipeline.Stages[].Actions[].ActionTypeId.Category', '`Source`'),
        ('CodePipeline.Pipeline.Stages[].Actions[].Name', '`source`'),
        ('CodePipeline.Pipeline.Stages[].Name', '`first`'),
        ('CodePipeline.Pipeline.Stages[].Actions[].ActionTypeId.Category', '`Build`'),
        ('CodePipeline.Pipeline.Stages[].Actions[].Name', '`build-a`'),
        ('CodePipeline.Pipeline.Stages[].Actions[].ActionTypeId.Category', '`Build`'),
        ('CodePipeline.Pipeline.Stages[].Actions[].Name', '`build-b`'),
        ('CodePipeline.Pipeline.Stages[].Name', '`second`'),
    ]))
    stages = [{'name': 'first', 'actions': [{'name': 'source', 'actionTypeId': {'category': 'Source', 'owner': 'AWS', 'provider': 'CodeCommit', 'version': '1'}}]},
              {'name': 'second', 'actions': [{'name': 'build-a', 'actionTypeId': {'category': 'Build', 'owner': 'AWS', 'provider': 'CodeBuild', 'version': '1'}},
                                            {'name': 'build-b', 'actionTypeId': {'category': 'Build', 'owner': 'AWS', 'provider': 'CodeBuild', 'version': '1'}}]}]
    for reversed_order in (False, True):
        patches = copy.deepcopy(PATCHES)
        patches[('codepipeline', 'get_pipeline')]['pipeline.stages'] = list(reversed(stages)) if reversed_order else stages
        with patch.dict(PATCHES, patches, clear=True):
            ctx = Offline(root)
            ctx.verified = True
            ctx.egress = False
            values = m.compare_resource(ctx, ctx.model(pipeline).resources[0])
            stage_results = [v for v in values if '.Stages' in v['propertiesKey']]
            check(stage_results and all(v['status'] == 'design_unresolved' for v in stage_results), 'ambiguous stages never compared')
            check(all('element index' in v['reason'] for v in stage_results), 'specific membership reason')
            check(not any(v['status'] == 'difference' for v in values), 'no guessed Action difference')
            ctx.finish()
    trail = directory / 'cloudtrail.properties'
    write_model(trail, model_text('CloudTrail.Trail', [('CloudTrail.Trail.TrailName', '`fixture`'), ('CloudTrail.Trail.IsLogging', '`true`')]))
    ctx = Offline(root, {('cloudtrail', 'get_trail_status'): 'failed'})
    ctx.egress = False
    ctx.verified = True
    values = m.compare_resource(ctx, ctx.model(trail).resources[0])
    check({v['status'] for v in values} == {'match', 'acquisition_failed'}, 'partial acquisition preserves successful comparisons')
    ctx.finish()
    failure = next(v for v in values if v['status'] == 'acquisition_failed')
    report = m.summarize([dict(failure, environment='dev', target=ACCOUNT, service='cloudtrail'),
                          dict(failure, environment='dev', target=ACCOUNT, service='cloudtrail', resource='second')])
    check(len(report['results']) == 1 and len(report['results'][0]['affectedResources']) == 2, 'one shared failure retains all affected resources')
    imported = directory / 'mwaa.properties'
    write_model(imported, model_text('MWAA.Environment', [('MWAA.Environment.Name', '`fixture`')], metadata='desired.resource.001.resourceMode=IMPORT\n'))
    ctx = Offline(root)
    ctx.verified = True
    ctx.egress = False
    check(m.compare_resource(ctx, ctx.model(imported).resources[0])[0]['status'] == 'match', 'IMPORT is compared')
    ctx.finish()
    # Wrong key membership is a difference despite matching AliasName.
    alias = directory / 'kms.properties'
    write_model(alias, model_text('KMS.Key', [('KMS.Key.KeyId', '[Key](#key)')], number='001', anchor='key', allocation=False) +
                     model_text('KMS.Alias', [('KMS.Alias.AliasName', '`fixture`')], number='002', anchor='alias',
                                allocation=False, metadata='desired.resource.002.parentReference=[Key](#key)\n') +
                     'observed.row.001-001.value=fixture\ndesired.service.identity.lastAllocated={"KMS.Key":1,"KMS.Alias":2}\n')
    patches = copy.deepcopy(PATCHES)
    patches[('kms', 'list_aliases')]['Aliases.TargetKeyId'] = 'different-key'
    with patch.dict(PATCHES, patches, clear=True):
        ctx = Offline(root)
        ctx.verified = True
        ctx.egress = False
        values = m.compare_resource(ctx, ctx.model(alias).resources[1])
        check(any(v['status'] == 'difference' and 'parentReference' in v['propertiesKey'] for v in values), 'KMS alias parent membership')
        ctx.finish()
    # Stack state differs without touching stack templates.
    patches = copy.deepcopy(PATCHES)
    patches[('cloudformation', 'describe_stacks')]['Stacks.StackStatus'] = 'ROLLBACK_COMPLETE'
    with patch.dict(PATCHES, patches, clear=True):
        ctx = Offline(root)
        ctx.verified = True
        ctx.egress = False
        values = m.service_module('cloudformation-stacks').compare(ctx, ctx.model(directory / 'cloudformation-stacks.properties'))
        check(values[0]['status'] == 'difference', 'stack unhealthy state')
        ctx.finish()


@it_case
def stack_checks(root):
    path = root / 'model/dev' / ACCOUNT / 'cloudformation-stacks.properties'
    path.parent.mkdir(parents=True)
    write_model(path, STACK_MODEL)
    adapter = m.service_module('cloudformation-stacks')
    cases = [({'Stacks': [{'StackName': 'fixture', 'StackStatus': state}]}, None, status)
             for state, status in [('CREATE_COMPLETE', 'match'), ('UPDATE_COMPLETE', 'match'),
                                   ('IMPORT_COMPLETE', 'match'), ('ROLLBACK_COMPLETE', 'difference')]]
    cases += [(payload, None, 'resource_missing') for payload in
              ({'Stacks': []}, {'Stacks': [{'StackName': 'other', 'StackStatus': 'CREATE_COMPLETE'}]},
               {'Stacks': [{'StackName': 'fixture'}, {'StackName': 'fixture'}]})]
    cases += [({}, message, status) for message, status in
              [('Stack with id fixture does not exist', 'resource_missing'),
               ('Invalid StackName', 'acquisition_failed')]]
    for payload, message, status in cases:
        response = SimpleNamespace(returncode=254 if message else 0, stdout=json.dumps(payload),
                                   stderr=('An error occurred (ValidationError) when calling the DescribeStacks operation: ' + message) if message else '')
        with patch.object(m.subprocess, 'run', return_value=response) as process:
            ctx = m.Context(root, TARGET, services=['cloudformation-stacks'])
            ctx.verified = True
            model = ctx.model(path)
            results = adapter.compare(ctx, model)
            check(results[0]['status'] == status, 'dedicated Stack state/name/error: ' + str((payload, message)))
            check(results[0]['apis'] == [{'api': 'cloudformation.describe_stacks', 'inputs': {'StackName': 'fixture'}}], 'Stack API trace')
            check(sum(item['status'] == 'local_metadata' for item in results) == 4, 'Stack local metadata preserved')
            check(adapter.compare(ctx, model) == results and process.call_count == 1, 'Stack response/error cache and classification')
            check(ctx.allowed == {('sts', 'get_caller_identity'), ('cloudformation', 'describe_stacks')}, 'Stack allowlist isolated')


@it_case
def cfn_identity_checks(root):
    directory = root / 'model/dev' / ACCOUNT
    directory.mkdir(parents=True)
    path = directory / 'vpc.properties'
    content = ''
    for index, department in enumerate(('ism', 'ced', 'sd'), 1):
        number = f'{index:03d}'
        content += model_text('EC2.VPC', [('EC2.VPC.VpcId', f'[{department}](#vpc-{department})')], number=number, anchor='vpc-' + department, allocation=False,
                              metadata=f'desired.resource.{number}.cfn-logicalId=cfn-stack-app-dev-{department}-DepartmentVpc\n')
        content += f'observed.row.{number}-001.value=vpc-{department}\n'
    content += 'desired.service.identity.lastAllocated={"EC2.VPC":3}\n'
    write_model(path, content)
    ctx = Offline(root)
    resources = ctx.model(path).resources
    with patch.object(ctx, 'fetch', side_effect=lambda resource, getter: {'VpcId': 'vpc-' + ('ism', 'ced', 'sd')[int(resource.number) - 1]}):
        for index, resource in enumerate(resources):
            department = ('ism', 'ced', 'sd')[index]
            check(resource.resolve_json({'Ref': 'DepartmentVpc'}) == 'vpc-' + department, 'CFn JSON Ref respects originating stack instance')
            expect(m.Unresolved, lambda *, resource=resource: resource.resolve_json({'Ref': 'Missing'}))
        resources[1].spec['cfn-logicalId'] = resources[0].spec['cfn-logicalId']
        expect(m.Unresolved, lambda: resources[0].resolve_json({'Ref': 'DepartmentVpc'}))
    ctx.finish()




def _identity_registry_checks_forbidden(context, selected, getter):
    return context.call('ec2', 'terminate_instances', InstanceIds=['unconfirmed'])


@it_case
def identity_registry_checks(root):
    ctx = Offline(root)
    ctx.verified = True
    resource = FakeResource(ctx, 's3', 'S3.Bucket')
    # Registry is the authority even when its response path differs from legacy Python.
    definition = SimpleNamespace(identities={'S3.Bucket': Identity('base', 'CustomId', 'BucketArn', 'BucketName')})
    with patch.object(ctx, 'comparison', return_value=(definition, {})), patch.object(ctx, 'fetch', return_value={'CustomId': 'registry-id'}):
        check(m.Resource.identity(resource) == 'registry-id', 'Registry identity path is used directly')
        expect(m.Unresolved, lambda: m.Resource.identity(resource, 'arn'))
        with patch.object(ctx, 'fetch', return_value={'CustomId': None}):
            expect(m.Unresolved, lambda: m.Resource.identity(resource))
        with patch.object(ctx, 'fetch', side_effect=m.Unresolved('resource does not exist')), patch.object(resource, 'value') as selected_name:
            expect(m.Unresolved, lambda: m.Resource.identity(resource, 'name'))
            check(not selected_name.called, 'Name selection follows confirmed existence')
        definition.identities = {}
        expect(m.Unresolved, lambda: m.Resource.identity(resource))
    allowed = set(ctx.allowed)
    definition.identities = {'S3.Bucket': Identity('new-getter', 'Name', None, None)}
    forbidden = _identity_registry_checks_forbidden
    with patch.object(ctx, 'comparison', return_value=(definition, {})), patch.object(resource.module, 'fetch', side_effect=forbidden):
        expect(ValueError, lambda: m.Resource.identity(resource))
    check(ctx.allowed == allowed and not ctx.trace, 'new Mapping getter cannot grant or call an API')
    stack = FakeResource(ctx, 'cloudformation-stacks', 'CloudFormation.Stack')
    expect(m.Unresolved, lambda: m.Resource.identity(stack))


@it_case
def fixture_coverage(root):
    directory = root / 'model/dev' / ACCOUNT
    directory.mkdir(parents=True)
    (root / 'project.json').write_text(json.dumps({'targets': [TARGET]}))
    for service in m.SERVICES:
        _ = m.service_module(service)
        if service == 'cloudformation-stacks':
            text = 'desired.stack.001.name=cfn-stack-app-dev-fixture\ndesired.stack.001.template=fixture.yaml\ndesired.stack.001.parameters=fixture.json\ndesired.stack.001.deployOrder=10\n'
        else:
            comparison = _imports_aws_mapping_compare.comparison
            mapping, definitions = comparison(m.ROOT, service)
            text = ''
            allocation = {}
            for index, kind in enumerate(sorted(mapping.adapter_resource_types), 1):
                number = f'{index:03d}'
                text += model_text(kind, [(prop, '`fixture`') for prop, item in sorted(definitions.items()) if prop.startswith(kind + '.') and item.include], number=number, anchor='fixture-'+number, allocation=False)
                allocation[kind] = index
            text += 'desired.service.identity.lastAllocated=' + json.dumps(allocation) + '\n'
        write_model(directory / (service + '.properties'), text)
    report = m.coverage(root, m.inventory(root, m.targets(root, all_targets=True)))
    check(not report['problems'], 'fixture coverage: ' + repr(report['problems']))
    check(set(report['services']) == set(m.SERVICES), 'all current services mechanically enumerated with fixed logicalIds')
    check(sum(map(len, report['adapterResourceTypes'].values())) == 52, '52 actual adapter types')
    check(sum(len(types) for service, types in report['comparisonResourceTypes'].items()
              if service != 'cloudformation-stacks') == 78, '78 mapped comparison types, independent of include')
    check(report['comparisonResourceTypes']['cloudformation-stacks'] == ['CloudFormation.Stack'], 'dedicated Stack coverage')
    print(f"Offline model coverage: {report['modelCount']} models / {report['resourceTypeCount']} types / {report['keyCount']} keys")


@pytest.mark.parametrize("callback, subdirectory", [
    (service_checks, ""), (common_checks, ""), (association_checks, ""), (identity_registry_checks, ""),
    (batch_checks, "batch"), (cli_checks, "cli"), (stack_checks, "stacks"),
    (cfn_identity_checks, "cfn-identity"), (fixture_coverage, "coverage"),
], ids=["services", "common", "associations", "identity-registry", "batch", "cli", "stacks", "cfn-identity", "coverage"])
def check_domains(tmp_path, callback, subdirectory):
    root = tmp_path / subdirectory
    root.mkdir(exist_ok=True)
    (root / 'project.json').write_text(json.dumps({'projectName': 'synthetic', 'targets': [
        {key: value for key, value in TARGET.items() if key != 'directory'}]}) + '\n')
    callback(root)


def check_consumer_coverage():
    consumer = Path(os.environ['AWS_COMPARE_COVERAGE_ROOT']) if 'AWS_COMPARE_COVERAGE_ROOT' in os.environ else None
    # Explicit read-only consumer audit is optional; regression has no host-path dependency.
    if consumer is not None and consumer.is_dir():
        report = m.coverage(consumer, m.inventory(consumer, m.targets(consumer, all_targets=True)))
        check(not report['problems'], 'consumer coverage: ' + repr(report['problems']))
        check(set(report['services']) == set(m.SERVICES), 'all current services mechanically enumerated')
        print(f"Read-only model coverage: {report['modelCount']} models / {report['resourceTypeCount']} types / {report['keyCount']} keys")
    elif 'AWS_COMPARE_COVERAGE_ROOT' in os.environ:
        raise AssertionError('explicit coverage root is missing')
    print(f"AWS model comparison checks: PASS ({check.__globals__['COUNT']} assertions; no AWS connection)")


def main():
    return run(__file__)


if __name__ == "__main__":
    raise SystemExit(main())
