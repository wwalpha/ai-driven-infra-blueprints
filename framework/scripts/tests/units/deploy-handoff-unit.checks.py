"""Problem policy/evidence checks, without AWS, real consumer inputs or Git mutation."""
import copy
import json
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
import pytest
from deploy import retry_policy as policy, failures, handoff
from cloudformation_inputs import Blocked
from deploy.contracts import task_digest, sha
from utils.json_format import fingerprint


def workflow(*problems, budget=20):
    return {'budget': budget, 'reserved': 0, 'attempts': {}, 'problems': {
        p: {'observations': [], 'attempts': []} for p in problems}}


def observed(w, *problems, execution, revision):
    for problem in problems:
        policy.observe(w, problem, {'execution': execution, 'revision': revision})


def attempted(w, *problems, revision):
    attempt = policy.reserve(w, 'request-' + str(w['reserved']), problems)
    attempt['acceptedRevision'] = revision
    return attempt


@pytest.mark.parametrize('sequence,expected', [
    (('A', 'A'), 'STOPPED'), (('A', 'B'), 'REPAIR_ALLOWED'),
    (('A', 'B', 'C'), 'REPAIR_ALLOWED'), (('A', 'B', 'A'), 'STOPPED')])
def check_problem_sequences(sequence, expected):
    w = workflow('A', 'B', 'C')
    for index, problem in enumerate(sequence):
        observed(w, problem, execution='execution-' + str(index), revision=index)
        if index:
            for prior in set(sequence[:index]) - {problem}:
                w['problems'][prior]['absentAfterRepair'] = True
        result = policy.decision(w, [problem])
        if index < len(sequence) - 1:
            assert result == 'REPAIR_ALLOWED'
            attempted(w, problem, revision=index + 1)
    assert result == expected


def check_unrepaired_peers_and_request_idempotency():
    w = workflow('A', 'B')
    observed(w, 'A', 'B', execution='one', revision=0)
    attempt = policy.reserve(w, 'request', ['A'])
    assert policy.reserve(w, 'request', ['A']) is attempt and w['reserved'] == 1
    attempt['acceptedRevision'] = 1
    observed(w, 'B', execution='two', revision=1)
    assert policy.decision(w, ['B']) == 'REPAIR_ALLOWED'
    assert not w['problems']['B']['attempts']
    with pytest.raises(ValueError):
        policy.reserve(w, 'request', ['B'])


def check_progress_limits_and_budget():
    w = workflow('A', budget=20)
    observed(w, 'A', execution='one', revision=0)
    for index in range(3):
        assert policy.decision(w, ['A']) == 'REPAIR_ALLOWED'
        attempted(w, 'A', revision=index + 1)
        policy.observe(w, 'A', {'execution': str(index), 'revision': index + 1}, ['nested-' + str(index)])
    assert policy.decision(w, ['A']) == 'WAITING_HUMAN'
    w = workflow('A', 'B', budget=1)
    observed(w, 'A', 'B', execution='one', revision=0)
    attempted(w, 'A', 'B', revision=1)
    assert w['reserved'] == 1 and all(len(w['problems'][p]['attempts']) == 1 for p in ('A', 'B'))
    assert policy.decision(w, ['B']) == 'WAITING_HUMAN'
    w['budget'] += 1
    assert policy.decision(w, ['B']) == 'REPAIR_ALLOWED'
    w['legacyUncertain'] = True
    assert policy.decision(w, ['B']) == 'WAITING_HUMAN'


def check_duplicate_poll_is_not_a_new_failure():
    w = workflow('A')
    observed(w, 'A', execution='one', revision=0)
    attempted(w, 'A', revision=1)
    observed(w, 'A', execution='one', revision=0)
    assert len(w['problems']['A']['observations']) == 1
    assert policy.decision(w, ['A']) == 'REPAIR_ALLOWED'
    observed(w, 'A', execution='two', revision=1)
    assert policy.decision(w, ['A']) == 'STOPPED'


@pytest.mark.parametrize('stage,code,service,operation,expected', [
    ('PREPARATION', 'ValidationError', 'cloudformation', 'validate_template', 'IAC_CANDIDATE'),
    ('PREPARATION', 'ValidationException', 'cloudformation', 'create_change_set', 'IAC_CANDIDATE'),
    ('PREPARATION', 'AccessDenied', 'cloudformation', 'create_change_set', 'AUTHORIZATION'),
    ('PREPARATION', 'ReadTimeoutError', 'cloudformation', 'create_change_set', 'NEEDS_HUMAN'),
    ('POLL', 'ValidationError', 'cloudformation', 'describe_stacks', 'NEEDS_HUMAN'),
    ('EXECUTE', 'ReadTimeoutError', 'cloudformation', 'execute_change_set', 'SUBMISSION_UNKNOWN')])
def check_failure_classes(stage, code, service, operation, expected):
    error = ValueError('must not be persisted as diagnosis')
    error.code, error.deploy_service, error.deploy_operation = code, service, operation
    state = {'status': 'RUNNING' if stage == 'EXECUTE' else 'BLOCKED'}
    failures.exception(state, error, stage)
    assert state['failure']['classification'] == expected
    assert 'must not be persisted' not in json.dumps(state)
    assert failures.repairable({'awsState': state}) == (expected == 'IAC_CANDIDATE')


def check_effective_inputs_and_safe_events(tmp_path):
    template, parameters, artifact = [tmp_path / p for p in ('template.yaml', 'parameters.json', 'script.py')]
    template.write_text('Resources: {R: {Type: AWS::EC2::VPC, Properties: {CidrBlock: 10.0.0.0/16}}}\n')
    parameters.write_text('[]')
    artifact.write_text('approved')
    units = [{'name': 'Stack'}]
    effective = lambda: handoff.effective(tmp_path, units, lambda u: (template, parameters), lambda us: [template, parameters, artifact])
    first = effective()
    template.write_text(template.read_text() + '# formatting only\n')
    assert effective() == first
    parameters.write_text('[{"ParameterKey":"Name","ParameterValue":"sensitive"}]')
    assert effective() != first and 'sensitive' not in json.dumps(effective())
    second = effective()
    artifact.write_text('different')
    assert effective() != second
    event = {'LogicalResourceId': 'R', 'ResourceType': 'AWS::EC2::VPC', 'ResourceStatus': 'CREATE_FAILED',
             'ResourceStatusReason': 'CidrBlock rejected (HandlerErrorCode: InvalidRequest), RequestId 123, secret-value'}
    document = {'Resources': {'R': {'Properties': {'CidrBlock': '10.0.0.0/16'}}}}
    record = failures.event(event, document)
    assert record['properties'] == ['CidrBlock'] and record['code'] == 'InvalidRequest'
    assert not any(word in json.dumps(record) for word in ('secret-value', 'RequestId'))
    event['ResourceStatusReason'] = 'CidrBlock rejected (HandlerErrorCode: InvalidRequest), RequestId 999'
    later = failures.event(event, document)
    assert later['properties'] == record['properties'] and later['code'] == record['code']


def check_status_helpers_preserve_task_identity():
    from task_contract import set_status
    text = '## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n- Authorized delete/replacement: `none`\n'
    suspended = set_status(text, 'suspend') + '\n## Suspension reason\n\n    awaiting child\n'
    assert task_digest(text) == task_digest(suspended) == task_digest(set_status(suspended, 'running'))
    assert task_digest(text) == task_digest(text.replace('`none`', '`change-set`'))
    assert task_digest(text) != task_digest(text + '\n## Other\nchanged\n')


def check_signed_ledger_rejects_rollback_and_recovers(tmp_path):
    from unittest.mock import patch
    root = tmp_path / 'repo'
    root.mkdir()
    path = tmp_path / 'state.json'
    session = {'repository': str(root), 'taskFile': 'tasks/deploy.md', 'states': {'Stack': {'status': 'NOT_STARTED'}}}
    handoff.bind(root, path, session)
    handoff.save(path, session)
    old = path.read_bytes()
    session['workflow']['reserved'] = 1
    actual_replace = Path.replace
    def interrupted(source, target):
        result = actual_replace(source, target)
        if Path(target) == path:
            raise OSError('injected after real session replacement')
        return result
    with patch.object(Path, 'replace', interrupted), pytest.raises(OSError):
        handoff.save(path, session)
    recovered = json.loads(path.read_text())
    handoff.restore(root, path, recovered)
    assert recovered['workflow']['reserved'] == 1
    path.write_bytes(old)
    with pytest.raises((Blocked, ValueError), match='ledger'):
        handoff.restore(root, path, json.loads(path.read_text()))
    path.unlink()
    final = handoff.recover_session(root, path, 'tasks/deploy.md')
    assert final['workflow']['reserved'] == 1 and final['workflow']['workflowId'] == session['workflow']['workflowId']
    with pytest.raises((Blocked, ValueError), match='original session'):
        handoff.recover_session(root, tmp_path / 'new-state.json', 'tasks/deploy.md')


def check_total_budget_is_not_three_global_failures():
    names = [str(i) for i in range(21)]
    w = workflow(*names)
    for index, name in enumerate(names[:20]):
        observed(w, name, execution=str(index), revision=index)
        attempted(w, name, revision=index + 1)
    observed(w, names[-1], execution='twenty-one', revision=20)
    assert w['reserved'] == 20 and policy.decision(w, [names[-1]]) == 'WAITING_HUMAN'
    w['budget'] += 1
    assert policy.decision(w, [names[-1]]) == 'REPAIR_ALLOWED'


def diagnosis_fixture(tmp_path):
    from support.model_sources import write_model, allocate_fixture
    root = tmp_path
    (root / 'project.json').write_text(json.dumps({'projectName':'fixture','targets':[{'environment':'dev','awsAccountId':'123456789012','awsRegion':'ap-northeast-1','iacEngine':'cloudformation'}]}))
    template = root / 'infra/template.yaml'
    template.parent.mkdir()
    template.write_text('Resources: {Item: {Type: AWS::EC2::VPC, Properties: {CidrBlock: wrong, EnableDnsSupport: true}}}')
    model = root / 'model/dev/123456789012/ec2.properties'
    values = {'desired.resource.001.resourceType': 'EC2.VPC', 'desired.resource.001.cfn-logicalId': 'Stack-Item',
                       'desired.row.001-001.property': 'EC2.VPC.CidrBlock', 'desired.row.001-001.value': '10.0.0.0/16', 'desired.row.001-001.comment':'承認済アドレス',
                       'desired.row.001-002.property': 'EC2.VPC.EnableDnsSupport', 'desired.row.001-002.value': 'true', 'desired.row.001-002.comment':'承認済DNS'}
    values.update(allocate_fixture(values, ['001']))
    write_model(model, values)
    relative, model_relative = template.relative_to(root).as_posix(), model.relative_to(root).as_posix()
    state = {'status': 'FAILED', 'stackStatus': 'ROLLBACK_COMPLETE', 'failureEvents': [
        {'resourcePath': 'Item', 'ResourceType': 'AWS::EC2::VPC', 'ResourceStatus': 'CREATE_FAILED', 'code': 'InvalidRequest', 'properties':['CidrBlock']}]}
    session = {'inputRevision': 0, 'logicalTarget': ['dev','account','region'], 'modelInputManifest': {model_relative: sha(model)},
               'states': {'Stack': state}, 'unitInputPaths': {'Stack': [relative]},
               'failureObservations': [{'observationId': 'one', 'stack': 'Stack', 'execution': 'token-one', 'revision': 0,
                                        'inputManifest': {relative: sha(template)}, 'awsState': state}]}
    handoff.workflow(session)['latestObservations'] = ['one']
    problem = {'observationId': 'one', 'eventIndices': [0], 'resourcePath': 'Item', 'resourceType': 'AWS::EC2::VPC',
               'operation': 'CREATE', 'property': 'CidrBlock', 'constraint': 'approved-cidr', 'cause': 'IAC_PROPERTY',
               'inputRefs': [{'path': relative, 'sha256': sha(template), 'pointer': '/Resources/Item/Properties/CidrBlock'}],
               'modelRefs': [{'path': model_relative, 'sha256': sha(model), 'key': 'desired.row.001-001.value'}]}
    return session, problem


@pytest.mark.parametrize('defect', ['unknown', 'same-constraint-proof', 'wrong-property-proof', 'wrong-sha', 'wrong-event', 'uncovered'])
def check_ambiguous_new_and_invalid_evidence_rejected(tmp_path, defect):
    session, problem = diagnosis_fixture(tmp_path)
    assert handoff.diagnose(tmp_path, session, {'revision': 0, 'problems': [problem]}) == 'REPAIR_ALLOWED'
    first = session['workflow']['currentProblemIds'][0]
    entry = copy.deepcopy(problem)
    if defect == 'unknown':
        entry['property'] = 'unknown'
    elif defect == 'same-constraint-proof':
        entry.update(constraint='new-claim-only', distinctFrom=[first])
    elif defect == 'wrong-property-proof':
        entry.update(property='EnableDnsSupport', distinctFrom=[first])
    elif defect == 'wrong-sha':
        entry['inputRefs'][0]['sha256'] = 'bad'
    elif defect == 'wrong-event':
        entry['resourcePath'] = 'Other'
    else:
        session['failureObservations'][0]['awsState']['failureEvents'].append({'resourcePath':'Unknown', 'ResourceType':'Custom::Unknown', 'ResourceStatus':'DELETE_FAILED'})
    with pytest.raises((Blocked, ValueError)):
        handoff.diagnose(tmp_path, session, {'revision': 0, 'problems': [entry]})


def check_distinct_property_and_request_id_stability(tmp_path):
    session, problem = diagnosis_fixture(tmp_path)
    handoff.diagnose(tmp_path, session, {'revision': 0, 'problems': [problem]})
    first = session['workflow']['currentProblemIds'][0]
    state = session['failureObservations'][0]['awsState']
    state['failureEvents'][0]['RequestId'] = 'different-only'
    handoff.diagnose(tmp_path, session, {'revision': 0, 'problems': [problem]})
    assert session['workflow']['currentProblemIds'] == [first]
    other = copy.deepcopy(problem)
    other.update(property='EnableDnsSupport', constraint='boolean', distinctFrom=[first])
    other['inputRefs'][0]['pointer'] = '/Resources/Item/Properties/EnableDnsSupport'
    other['modelRefs'][0]['key'] = 'desired.row.001-002.value'
    with pytest.raises(Blocked, match='corresponding event'):
        handoff.diagnose(tmp_path, session, {'revision': 0, 'problems': [other]})
    state['failureEvents'][0]['properties'] = ['EnableDnsSupport']
    assert handoff.diagnose(tmp_path, session, {'revision': 0, 'problems': [other]}) == 'REPAIR_ALLOWED'
    assert session['workflow']['currentProblemIds'] != [first]


@pytest.mark.parametrize('classification,allowed', [('IAC_CANDIDATE', True), ('INPUT_CANDIDATE', True),
    ('APPROVAL',False), ('AUTHORIZATION',False), ('SUBMISSION_UNKNOWN',False), ('NEEDS_HUMAN',False)])
def check_unexecuted_diagnosis_preserves_aws_state(tmp_path, classification, allowed):
    session, problem = diagnosis_fixture(tmp_path)
    state = session['failureObservations'][0]['awsState']
    state.clear()
    state.update(status='BLOCKED', failure={'classification':classification,'executionState':'NOT_EXECUTED','operation':'validate_template'}, failureEvents=[])
    problem.update(eventIndices=[], operation='validate_template')
    if allowed:
        assert handoff.diagnose(tmp_path,session,{'revision':0,'problems':[problem]}) == 'REPAIR_ALLOWED'
    else:
        with pytest.raises(Blocked):
            handoff.diagnose(tmp_path,session,{'revision':0,'problems':[problem]})
    assert state['status'] == 'BLOCKED' and 'stackStatus' not in state


@pytest.mark.parametrize('defect', ['none','origin','identity','protected','parent','status','change-stack','executed','change-status','resources','read','interrupted'])
def check_unexecuted_shell_recovery(defect):
    from deploy.recovery import cleanup_unexecuted
    from utils.aws.client import AwsError
    proof = {'stackId':'original','changeSetId':'change','operationType':'CREATE','absentBeforeCreate':True}
    state = {'status':'NOT_STARTED','stackId':'original','preExecutionRecovery':proof}
    stack = {'StackId':'original','StackStatus':'REVIEW_IN_PROGRESS'}
    change = {'StackId':'original','ChangeSetId':'change','Status':'FAILED','ExecutionStatus':'UNAVAILABLE'}
    if defect == 'origin': proof['absentBeforeCreate'] = False
    if defect == 'identity': stack['StackId'] = 'reused'
    if defect == 'protected': stack['EnableTerminationProtection'] = True
    if defect == 'parent': stack['ParentId'] = 'parent'
    if defect == 'status': stack['StackStatus'] = 'CREATE_COMPLETE'
    if defect == 'change-stack': change['StackId'] = 'other'
    if defect == 'executed': change['ExecutionStatus'] = 'EXECUTE_COMPLETE'
    if defect == 'change-status': change['Status'] = 'CREATE_COMPLETE'
    if defect == 'interrupted': state.update(cleanupStatus='DELETE_INTENT',cleanupStackId='original')
    calls, saves, waits = [], [], []
    def aws(operation, **arguments):
        calls.append((operation,arguments))
        assert arguments['StackName'] == 'original'
        if operation == 'describe_stacks':
            if defect == 'interrupted': raise AwsError('cloudformation',operation,'ValidationError',stack_absent=True)
            return {'Stacks':[stack]}
        if operation == 'describe_change_set': return change
        if operation == 'list_stack_resources':
            if defect == 'read': raise AwsError('cloudformation',operation,'AccessDenied')
            return {'StackResourceSummaries':[{}] if defect == 'resources' else []}
        assert operation == 'delete_stack'
    if defect in {'none','interrupted'}:
        cleanup_unexecuted(aws,lambda:saves.append(copy.deepcopy(state)),lambda s:waits.append(s['stackId']),state)
        assert state['status'] == 'NOT_STARTED' and 'stackStatus' not in state
        assert (waits == ['original']) == (defect == 'none')
    else:
        with pytest.raises(Blocked):
            cleanup_unexecuted(aws,lambda:saves.append(copy.deepcopy(state)),lambda s:waits.append(s['stackId']),state)
        assert not any(op == 'delete_stack' for op,_ in calls)
        assert not waits
    assert saves or defect not in {'none','interrupted'}


@pytest.mark.parametrize('defect', ['order','metadata','missing-previous'])
def check_constraint_identity_ignores_reference_order(tmp_path, defect):
    from utils.aws_mappings import definition_root
    session, problem = diagnosis_fixture(tmp_path)
    relative = 'framework/materials/cloudformation-schema/ap-northeast-1/aws-ec2-vpc.json'
    digest = sha(definition_root(tmp_path) / relative)
    refs = [{'path':relative,'sha256':digest,'pointer':'/properties/CidrBlock' + suffix} for suffix in ('','/type')]
    if defect != 'missing-previous': problem['constraintRefs'] = copy.deepcopy(refs)
    handoff.diagnose(tmp_path,session,{'revision':0,'problems':[problem]})
    original = session['workflow']['currentProblemIds'][0]
    entry = copy.deepcopy(problem)
    entry.update(constraint='same-proofs-new-name',distinctFrom=[original],constraintRefs=list(reversed(refs)))
    if defect == 'metadata': entry['constraintRefs'][0]['note'] = 'not a new constraint'
    with pytest.raises(Blocked,match='distinct confirmed'):
        handoff.diagnose(tmp_path,session,{'revision':0,'problems':[entry]})
    assert session['workflow']['currentProblemIds'] == [original]


def check_bootstrap_history_preserves_distinct_safe_failure(tmp_path):
    from deploy.controller import create_runtime
    from task_contract import selected_task
    session, problem = diagnosis_fixture(tmp_path)
    task = tmp_path / 'tasks/deploy.md'
    task.parent.mkdir()
    task.write_text('## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n'
        '- Runtime recovery: `allowed`\n## Modified files\n- `tasks/deploy.md`\n## Allowed paths\n- `tasks/deploy.md`\n')
    target = {'awsAccountId':'123456789012','awsRegion':'ap-northeast-1'}
    backend = create_runtime(tmp_path,'dev','123456789012',target)
    unit = {'name':'Stack'}
    document, errors = handoff.decode((tmp_path / 'infra/template.yaml').read_bytes())
    assert not errors
    backend.templates['Stack'] = (document,{})
    backend.session = session
    state = session['states']['Stack']
    state.update(clientToken='one', stackId='original', repairs=[{'classification':'RUNTIME_BOOTSTRAP','stage':'RETRY_READY'}])
    identifier = ['request-one']
    def aws(operation, **arguments):
        if operation == 'describe_stacks': return {'Stacks':[{'StackStatus':'ROLLBACK_COMPLETE'}]}
        assert operation == 'describe_stack_events', 'non-secret failure must not PUT or clean a shell'
        return {'StackEvents':[
            {'StackId':'original','ResourceType':'AWS::CloudFormation::Stack','ClientRequestToken':'one','ResourceStatus':'ROLLBACK_COMPLETE'},
            {'LogicalResourceId':'Item','ResourceType':'AWS::EC2::VPC','ClientRequestToken':'one','ResourceStatus':'CREATE_FAILED',
             'EventId':identifier[0], 'ResourceStatusReason':'invalid CidrBlock DUMMY_PRIVATE (HandlerErrorCode: InvalidRequest)'}]}
    backend.aws = aws
    with selected_task(tmp_path,'tasks/deploy.md'):
        assert backend.poll(unit,state) == 'ROLLBACK_COMPLETE'
        assert not backend.repair(unit,state)
        assert state['failureClassification'] == 'NEEDS_DIAGNOSIS'
    assert state['failureEvents'][0]['properties'] == ['CidrBlock']
    assert state['failureEvents'][0]['code'] == 'InvalidRequest'
    assert 'DUMMY_PRIVATE' not in json.dumps(state)
    assert handoff.diagnose(tmp_path,session,{'revision':0,'problems':[problem]}) == 'REPAIR_ALLOWED'
    original = session['workflow']['currentProblemIds']
    identifier[0] = 'different-request-only'
    backend.poll(unit,state)
    assert handoff.diagnose(tmp_path,session,{'revision':0,'problems':[problem]}) == 'REPAIR_ALLOWED'
    assert session['workflow']['currentProblemIds'] == original


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
