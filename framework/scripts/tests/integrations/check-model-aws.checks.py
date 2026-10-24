#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import aws_mapping_compare as _imports_aws_mapping_compare
import support.check_model_aws_fixtures as _retained_fixture_offline_network
from support.check_model_aws_fixtures import (
    ACCOUNT,
    PATCHES,
    STACK_MODEL,
    TARGET,
    ExitStack,
    Offline,
    Path,
    SimpleNamespace,
    Stubber,
    _batch_checks_cli,
    boto3,
    check,
    copy,
    expect,
    json,
    m,
    model_text,
    os,
    patch,
    pytest,
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
    iam = compare(['iam'])
    code, batch = compare(['s3', 'iam'])
    expected = m.summarize(iam[1]['results'] + single[1]['results'])
    check(code == 0 and batch == expected, 'batch results equal standalone results, preserving JSON and counts')
    check({item['service'] for item in batch['results']} == {'s3', 'iam'}, 'batch compares both requested services only')
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
        check(not factory.called, 'coverage never creates an SDK session')
        check(not process.called, 'coverage never invokes AWS CLI')

    write_model(directory / 'kms.properties', model_text('KMS.Key', [('KMS.Key.KeyId', '`fixture`'), ('KMS.Key.Description', '`fixture`')]))
    s3_rows[1] = ('S3.Bucket.VersioningConfiguration.Status', '`Suspended`')
    write_model(s3, model_text('S3.Bucket', s3_rows))
    for fault, wanted_code, wanted_status in ((None, 1, 'identifier'), ('missing', 1, 'resource_missing'), ('failed', 2, 'acquisition_failed')):
        code, report = compare(['s3', 'iam', 'kms'], fault=fault)
        statuses = {(item['service'], item['status']) for item in report['results']}
        check(code == wanted_code and ('s3', 'difference') in statuses and ('iam', 'match') in statuses and ('kms', wanted_status) in statuses,
              'batch exit precedence retains successful comparisons and S3 differences: ' + str(fault))
        check(set(report) == {'status', 'exitCode', 'counts', 'results'}, 'batch does not add a JSON wrapper')


@it_case
def common_checks(root):
    directory = root / 'model/dev' / ACCOUNT
    directory.mkdir(parents=True)
    (root / 'project.json').write_text(json.dumps({'targets': [TARGET]}), encoding='utf-8')
    check(m.targets(root, 'dev', ACCOUNT)[0]['directory'] == ACCOUNT, 'existing target resolver')
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
    check(m.normalize(ctx, 'alias/fixture', 'kms') == m.normalize(ctx, 'fixture', 'kms'), 'SDK-confirmed KMS alias/key identity')
    check(resource.resolve_json({'Fn::ImportValue': 'fixture-export'}) == 'confirmed-export-value', 'SDK-confirmed export in authoritative policy')
    check(resource.resolve_json({'Fn::Sub': '${AWS::AccountId}/${AWS::Region}/${AWS::Partition}'}) == ACCOUNT + '/ap-northeast-1/aws', 'verified pseudo-parameters')
    expect(m.Unresolved, lambda: resource.resolve_json({'Fn::ImportValue': 'missing-export'}))
    ctx.finish()


@it_case
def association_checks(root):
    directory = root / 'model/dev' / ACCOUNT
    directory.mkdir(parents=True, exist_ok=True)
    write_model(directory / 'cloudformation-stacks.properties', STACK_MODEL)
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


@it_case
def stack_checks(root):
    path = root / 'model/dev' / ACCOUNT / 'cloudformation-stacks.properties'
    path.parent.mkdir(parents=True)
    write_model(path, STACK_MODEL)
    with patch.object(m.subprocess, 'run', return_value=SimpleNamespace(returncode=0,
            stdout=json.dumps({'Stacks': [{'StackName': 'fixture', 'StackStatus': 'CREATE_COMPLETE'}]}), stderr='')):
        ctx = m.Context(root, TARGET, services=['cloudformation-stacks'])
        ctx.verified = True
        results = m.service_module('cloudformation-stacks').compare(ctx, ctx.model(path))
        check(results[0]['status'] == 'match' and len(results) == 5, 'CLI Stack Model integration')


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
    (common_checks, ""), (association_checks, ""),
    (batch_checks, "batch"), (cli_checks, "cli"), (stack_checks, "stacks"),
    (cfn_identity_checks, "cfn-identity"), (fixture_coverage, "coverage"),
], ids=["common", "associations", "batch", "cli", "stacks", "cfn-identity", "coverage"])
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
