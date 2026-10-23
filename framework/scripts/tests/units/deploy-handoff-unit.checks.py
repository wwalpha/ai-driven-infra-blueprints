"""Problem policy/evidence checks, without AWS, real consumer inputs or Git mutation."""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from cloudformation_inputs import Blocked
from deploy import failures, handoff
from deploy import retry_policy as policy
from deploy.controller import create_runtime
from deploy.recovery import cleanup_unexecuted
from deploy_handoff import main
from support.model_sources import allocate_fixture, write_model
from task_contract_core import selected_task, set_status, task_digest
from utils.aws.client import AwsError
from utils.aws_mappings import definition_root
from utils.file_operations import sha
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.json_format import fingerprint as fingerprint

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


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


def _lambda_check_effective_inputs_and_safe_events_effective_129(artifact, parameters, template, tmp_path, units, /):
    return handoff.effective(tmp_path, units, lambda u: (template, parameters), lambda us: [template, parameters, artifact])


def check_effective_inputs_and_safe_events(tmp_path):
    template, parameters, artifact = [tmp_path / p for p in ('template.yaml', 'parameters.json', 'script.py')]
    template.write_text('Resources: {R: {Type: AWS::EC2::VPC, Properties: {CidrBlock: 10.0.0.0/16}}}\n')
    parameters.write_text('[]')
    artifact.write_text('approved')
    units = [{'name': 'Stack'}]
    effective = _bind_framework_callback(_lambda_check_effective_inputs_and_safe_events_effective_129, artifact, parameters, template, tmp_path, units)
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
    text = '## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n- Authorized delete/replacement: `none`\n'
    suspended = set_status(text, 'suspend') + '\n## Suspension reason\n\n    awaiting child\n'
    assert task_digest(text) == task_digest(suspended) == task_digest(set_status(suspended, 'running'))
    assert task_digest(text) == task_digest(text.replace('`none`', '`change-set`'))
    assert task_digest(text) != task_digest(text + '\n## Other\nchanged\n')


def _callback_check_signed_ledger_rejects_rollback_and_recovers_interrupted(actual_replace, path, /, source, target):
    result = actual_replace(source, target)
    if Path(target) == path:
        raise OSError('injected after real session replacement')
    return result


def check_signed_ledger_rejects_rollback_and_recovers(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    path = tmp_path / 'state.json'
    session = {'repository': str(root), 'taskFile': 'tasks/deploy.md', 'states': {'Stack': {'status': 'NOT_STARTED'}}}
    handoff.bind(root, path, session)
    handoff.save(path, session)
    old = path.read_bytes()
    session['workflow']['reserved'] = 1
    actual_replace = Path.replace
    interrupted = _bind_framework_callback(_callback_check_signed_ledger_rejects_rollback_and_recovers_interrupted, actual_replace, path)
    with patch.object(Path, 'replace', autospec=True, side_effect=interrupted), pytest.raises(OSError, match='injected after real session replacement'):
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


def diagnosis_fixture(tmp_path, peer=False):
    root = tmp_path
    (root / 'project.json').write_text(json.dumps({'projectName':'fixture','targets':[{'environment':'dev','awsAccountId':'123456789012','awsRegion':'ap-northeast-1','iacEngine':'cloudformation'}]}))
    template = root / 'infra/template.yaml'
    template.parent.mkdir()
    template.write_text('Resources: {Item: {Type: AWS::EC2::VPC, Properties: {CidrBlock: wrong, EnableDnsSupport: true}}}')
    if peer:
        template.write_text(template.read_text().replace('Resources: {', 'Resources: {Item2: {Type: AWS::EC2::VPC, Properties: {CidrBlock: wrong}}, '))
    model = root / 'model/dev/123456789012/ec2.properties'
    values = {'desired.resource.001.resourceType': 'EC2.VPC', 'desired.resource.001.cfn-logicalId': 'Stack-Item',
                       'desired.row.001-001.property': 'EC2.VPC.CidrBlock', 'desired.row.001-001.value': '10.0.0.0/16', 'desired.row.001-001.comment':'承認済アドレス',
                       'desired.row.001-002.property': 'EC2.VPC.EnableDnsSupport', 'desired.row.001-002.value': 'true', 'desired.row.001-002.comment':'承認済DNS'}
    if peer:
        values.update({'desired.resource.002.resourceType':'EC2.VPC', 'desired.resource.002.cfn-logicalId':'Stack-Item2',
                       'desired.row.002-001.property':'EC2.VPC.CidrBlock', 'desired.row.002-001.value':'10.0.0.0/16',
                       'desired.row.002-001.comment':'承認済アドレス'})
    values.update(allocate_fixture(values, ['001', '002'] if peer else ['001']))
    write_model(model, values)
    relative, model_relative = template.relative_to(root).as_posix(), model.relative_to(root).as_posix()
    state = {'status': 'FAILED', 'stackStatus': 'ROLLBACK_COMPLETE', 'failureEvents': [
        {'resourcePath': 'Item', 'ResourceType': 'AWS::EC2::VPC', 'ResourceStatus': 'CREATE_FAILED', 'code': 'InvalidRequest', 'properties':['CidrBlock']}]}
    session = {'inputRevision': 0, 'logicalTarget': ['dev','account','region'], 'modelInputManifest': {model_relative: sha(model)},
               'states': {'Stack': state}, 'unitInputPaths': {'Stack': [relative]},
               'failureObservations': [{'observationId': 'one', 'stack': 'Stack', 'execution': 'token-one', 'revision': 0,
                                        'inputManifest': {relative: sha(template)}, 'awsState': state}]}
    handoff.workflow(session)['latestObservations'] = ['one']
    problem = {'relation': 'NEW', 'relatedProblemIds': [],
               'reason': 'The failed CidrBlock differs from the approved Model row in the referenced template.',
               'evidenceRefs': [{'observationId': 'one', 'revision': 0, 'eventIndices': [0]}], 'observationId': 'one', 'eventIndices': [0], 'resourcePath': 'Item', 'resourceType': 'AWS::EC2::VPC',
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
        entry.update(constraint='new-claim-only', relatedProblemIds=[first])
    elif defect == 'wrong-property-proof':
        entry.update(property='EnableDnsSupport', relatedProblemIds=[first])
    elif defect == 'wrong-sha':
        entry['inputRefs'][0]['sha256'] = 'bad'
    elif defect == 'wrong-event':
        entry['resourcePath'] = 'Other'
    else:
        session['failureObservations'][0]['awsState']['failureEvents'].append({'resourcePath':'Unknown', 'ResourceType':'Custom::Unknown', 'ResourceStatus':'DELETE_FAILED'})
    if defect == 'same-constraint-proof':
        assert handoff.diagnose(tmp_path, session, {'revision': 0, 'problems': [entry]}) == 'NEEDS_DIAGNOSIS'
    else:
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
    other.update(property='EnableDnsSupport', constraint='boolean', relatedProblemIds=[first])
    other['inputRefs'][0]['pointer'] = '/Resources/Item/Properties/EnableDnsSupport'
    other['modelRefs'][0]['key'] = 'desired.row.001-002.value'
    assert handoff.diagnose(tmp_path, session, {'revision': 0, 'problems': [other]}) == 'NEEDS_DIAGNOSIS'
    session['failureObservations'][0]['awsState']['failureEvents'][0]['properties'] = ['EnableDnsSupport']
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
    problem['evidenceRefs'][0]['eventIndices'] = []
    if allowed:
        assert handoff.diagnose(tmp_path,session,{'revision':0,'problems':[problem]}) == 'REPAIR_ALLOWED'
    else:
        with pytest.raises(Blocked):
            handoff.diagnose(tmp_path,session,{'revision':0,'problems':[problem]})
    assert state['status'] == 'BLOCKED' and 'stackStatus' not in state


def _callback_check_unexecuted_shell_recovery_aws(calls, change, defect, stack, /, operation, **arguments):
    calls.append((operation,arguments))
    assert arguments['StackName'] == 'original'
    if operation == 'describe_stacks':
        if defect == 'interrupted':
            raise AwsError('cloudformation',operation,'ValidationError',stack_absent=True)
        return {'Stacks':[stack]}
    if operation == 'describe_change_set':
        return change
    if operation == 'list_stack_resources':
        if defect == 'read':
            raise AwsError('cloudformation',operation,'AccessDenied')
        return {'StackResourceSummaries':[{}] if defect == 'resources' else []}
    assert operation == 'delete_stack'


@pytest.mark.parametrize('defect', ['none','origin','identity','protected','parent','status','change-stack','executed','change-status','resources','read','interrupted'])
def check_unexecuted_shell_recovery(defect):
    proof = {'stackId':'original','changeSetId':'change','operationType':'CREATE','absentBeforeCreate':True}
    state = {'status':'NOT_STARTED','stackId':'original','preExecutionRecovery':proof}
    stack = {'StackId':'original','StackStatus':'REVIEW_IN_PROGRESS'}
    change = {'StackId':'original','ChangeSetId':'change','Status':'FAILED','ExecutionStatus':'UNAVAILABLE'}
    if defect == 'origin':
        proof['absentBeforeCreate'] = False
    if defect == 'identity':
        stack['StackId'] = 'reused'
    if defect == 'protected':
        stack['EnableTerminationProtection'] = True
    if defect == 'parent':
        stack['ParentId'] = 'parent'
    if defect == 'status':
        stack['StackStatus'] = 'CREATE_COMPLETE'
    if defect == 'change-stack':
        change['StackId'] = 'other'
    if defect == 'executed':
        change['ExecutionStatus'] = 'EXECUTE_COMPLETE'
    if defect == 'change-status':
        change['Status'] = 'CREATE_COMPLETE'
    if defect == 'interrupted':
        state.update(cleanupStatus='DELETE_INTENT',cleanupStackId='original')
    calls, saves, waits = [], [], []
    aws = _bind_framework_callback(_callback_check_unexecuted_shell_recovery_aws, calls, change, defect, stack)
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
    session, problem = diagnosis_fixture(tmp_path)
    relative = 'framework/materials/cloudformation-schema/ap-northeast-1/aws-ec2-vpc.json'
    digest = sha(definition_root(tmp_path) / relative)
    refs = [{'path':relative,'sha256':digest,'pointer':'/properties/CidrBlock' + suffix} for suffix in ('','/type')]
    if defect != 'missing-previous':
        problem['constraintRefs'] = copy.deepcopy(refs)
    handoff.diagnose(tmp_path,session,{'revision':0,'problems':[problem]})
    original = session['workflow']['currentProblemIds'][0]
    entry = copy.deepcopy(problem)
    entry.update(constraint='same-proofs-new-name',relatedProblemIds=[original],constraintRefs=list(reversed(refs)))
    if defect == 'metadata':
        entry['constraintRefs'][0]['note'] = 'not a new constraint'
    assert handoff.diagnose(tmp_path,session,{'revision':0,'problems':[entry]}) == 'NEEDS_DIAGNOSIS'
    assert list(session['workflow']['problems']) == [original]


def _callback_check_bootstrap_history_preserves_distinct_safe_failure_aws(identifier, /, operation, **arguments):
    if operation == 'describe_stacks':
        return {'Stacks':[{'StackStatus':'ROLLBACK_COMPLETE'}]}
    assert operation == 'describe_stack_events', 'non-secret failure must not PUT or clean a shell'
    return {'StackEvents':[
        {'StackId':'original','ResourceType':'AWS::CloudFormation::Stack','ClientRequestToken':'one','ResourceStatus':'ROLLBACK_COMPLETE'},
        {'LogicalResourceId':'Item','ResourceType':'AWS::EC2::VPC','ClientRequestToken':'one','ResourceStatus':'CREATE_FAILED',
         'EventId':identifier[0], 'ResourceStatusReason':'invalid CidrBlock DUMMY_PRIVATE (HandlerErrorCode: InvalidRequest)'}]}


def check_bootstrap_history_preserves_distinct_safe_failure(tmp_path):
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
    aws = _bind_framework_callback(_callback_check_bootstrap_history_preserves_distinct_safe_failure_aws, identifier)
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


def next_diagnosis(session, entry, *, relation='SAME', related=None, properties=None, code=None):
    """A distinct AWS execution, with immutable previous observation evidence."""
    previous = session['failureObservations'][-1]
    observation = copy.deepcopy(previous)
    observation.update(observationId='obs-' + str(len(session['failureObservations'])),
                       execution='exec-' + str(len(session['failureObservations'])), revision=session['inputRevision'] + 1)
    if properties is not None:
        observation['awsState']['failureEvents'][0]['properties'] = properties
    if code is not None:
        observation['awsState']['failureEvents'][0]['code'] = code
    session['failureObservations'].append(observation)
    session['inputRevision'] = observation['revision']
    session['workflow']['latestObservations'] = [observation['observationId']]
    candidate = copy.deepcopy(entry)
    candidate.update(relation=relation, relatedProblemIds=related or session['workflow']['currentProblemIds'],
                     observationId=observation['observationId'],
                     reason='Compare this distinct AWS execution with the cited prior failure and approved input/Model locations.')
    candidate['evidenceRefs'].append({'observationId':observation['observationId'], 'revision':observation['revision'], 'eventIndices':[0]})
    return candidate


@pytest.mark.parametrize('difference', ['schema-pointer', 'label', 'request-and-prose', 'invalid-value'])
def check_v5_relabel_does_not_buy_new_attempt(tmp_path, difference):
    session, entry = diagnosis_fixture(tmp_path)
    schema = 'framework/materials/cloudformation-schema/ap-northeast-1/aws-ec2-vpc.json'
    entry['constraintRefs'] = [{'path':schema, 'sha256':sha(definition_root(tmp_path) / schema), 'pointer':'/properties/CidrBlock/type'}]
    handoff.diagnose(tmp_path,session,{'revision':0,'problems':[entry]})
    identity = session['workflow']['currentProblemIds'][0]
    attempted(session['workflow'],identity,revision=1)
    new = next_diagnosis(session,entry,relation='NEW')
    new['constraint'] = 'different-name'
    if difference == 'schema-pointer':
        new['constraintRefs'][0]['pointer'] = '/properties/CidrBlock'
    elif difference == 'request-and-prose':
        session['failureObservations'][-1]['awsState']['failureEvents'][0].update(RequestId='new', reasonDigest='new-prose')
        session['taskFile'] = 'tasks/another.md'
    elif difference == 'invalid-value':
        path = tmp_path / new['inputRefs'][0]['path']
        path.write_text(path.read_text().replace('wrong','still-invalid'))
        digest = sha(path)
        new['inputRefs'][0]['sha256'] = digest
        session['failureObservations'][-1]['inputManifest'][new['inputRefs'][0]['path']] = digest
    assert handoff.diagnose(tmp_path,session,{'revision':1,'problems':[new]}) == 'NEEDS_DIAGNOSIS'
    assert list(session['workflow']['problems']) == [identity] and session['workflow']['reserved'] == 1
    new.update(relation='SAME')
    assert handoff.diagnose(tmp_path,session,{'revision':1,'problems':[new]}) == 'STOPPED'
    assert session['workflow']['currentProblemIds'] == [identity]
    # Rewriting the diagnosis and duplicate polling never erase a spent attempt/stop.
    new['constraint'] = 'yet-another-name'
    assert handoff.diagnose(tmp_path,session,{'revision':1,'problems':[new]}) == 'STOPPED'
    assert len(session['workflow']['problems'][identity]['observations']) == 2


@pytest.mark.parametrize('missing', ['relation','relatedProblemIds','reason','evidenceRefs','prior-reference','prior-comparison','boilerplate'])
def check_relation_contract_and_atomic_rejection(tmp_path, missing):
    session, entry = diagnosis_fixture(tmp_path)
    handoff.diagnose(tmp_path,session,{'revision':0,'problems':[entry]})
    new = next_diagnosis(session,entry,relation='NEW',code='AnotherCode')
    if missing == 'prior-reference':
        new['evidenceRefs'] = new['evidenceRefs'][-1:]
    elif missing == 'boilerplate':
        new['reason'] = 'different cause'
    elif missing == 'prior-comparison':
        new['relatedProblemIds'] = []
    else:
        new.pop(missing)
    before = copy.deepcopy(session)
    with pytest.raises(Blocked):
        handoff.diagnose(tmp_path,session,{'revision':1,'problems':[new]})
    assert session == before


@pytest.mark.parametrize('repairable', [True, False])
def check_unknown_is_durable_and_never_issues_request(tmp_path, repairable):
    session, entry = diagnosis_fixture(tmp_path)
    if not repairable:
        session['failureObservations'][0]['awsState']['failure'] = {'classification':'NEEDS_HUMAN'}
    entry.update(relation='UNKNOWN', reason='The available event does not distinguish the input defect from the runtime constraint; read-only evidence is required.')
    for key in ('cause','constraint','property'):
        entry.pop(key)
    assert handoff.diagnose(tmp_path,session,{'revision':0,'problems':[entry]}) == 'NEEDS_DIAGNOSIS'
    path = tmp_path / 'session.json'
    handoff.save(path,session)
    restored = json.loads(path.read_text())
    assert restored['workflow']['diagnoses'][0]['problems'][0]['relation'] == 'UNKNOWN'
    assert not restored['workflow']['problems']
    with pytest.raises(ValueError,match='NEEDS_DIAGNOSIS'):
        handoff.issue_request(tmp_path,path,restored,[],[],[])


@pytest.mark.parametrize('target', ['Item/Child', 'Item2'])
def check_same_cause_across_resource_targets_shares_attempt_limit(tmp_path, target):
    session, entry = diagnosis_fixture(tmp_path, peer=target == 'Item2')
    handoff.diagnose(tmp_path,session,{'revision':0,'problems':[entry]})
    original = session['workflow']['currentProblemIds'][0]
    attempted(session['workflow'],original,revision=1)
    new = next_diagnosis(session,entry)
    new['resourcePath'] = target
    session['failureObservations'][-1]['awsState']['failureEvents'][0]['resourcePath'] = target
    if target == 'Item2':
        new['inputRefs'][0]['pointer'] = '/Resources/Item2/Properties/CidrBlock'
        new['modelRefs'][0]['key'] = 'desired.row.002-001.value'
    assert handoff.diagnose(tmp_path,session,{'revision':1,'problems':[new]}) == 'STOPPED'
    other = session['workflow']['currentProblemIds'][0]
    assert other != original
    assert session['workflow']['problems'][other]['causeId'] == original
    assert len(policy.attempts_for(session['workflow'],other)) == 1
    assert session['workflow']['problems'][original]['attempts']


def check_new_code_is_evidence_not_python_cause_inference(tmp_path):
    session, entry = diagnosis_fixture(tmp_path)
    handoff.diagnose(tmp_path,session,{'revision':0,'problems':[entry]})
    original = session['workflow']['currentProblemIds'][0]
    attempted(session['workflow'],original,revision=1)
    new = next_diagnosis(session,entry,relation='NEW',code='DifferentConstraint')
    new['constraint'] = 'second-constraint'
    new['reason'] = 'The current AWS operation reports a different constraint code after the first constraint was corrected; compare both cited executions.'
    assert handoff.diagnose(tmp_path,session,{'revision':1,'problems':[new]}) == 'REPAIR_ALLOWED'
    second = session['workflow']['currentProblemIds'][0]
    assert second != original
    attempted(session['workflow'],second,revision=2)
    again = next_diagnosis(session,entry,related=[original],code='InvalidRequest')
    assert handoff.diagnose(tmp_path,session,{'revision':2,'problems':[again]}) == 'STOPPED'
    assert session['workflow']['currentProblemIds'] == [original]
    # SAME cannot transfer an already known signature to a different cause either.
    again['relatedProblemIds'] = [second]
    again['evidenceRefs'].extend(new['evidenceRefs'])
    assert handoff.diagnose(tmp_path,session,{'revision':2,'problems':[again]}) == 'NEEDS_DIAGNOSIS'
    assert session['workflow']['reserved'] == 2


@pytest.mark.parametrize('history', ['problem', 'budget-extension'])
def check_v5_signed_history_migrates_without_reset(tmp_path, history):
    root = tmp_path / 'repository'
    root.mkdir()
    session, entry = diagnosis_fixture(root)
    handoff.diagnose(root,session,{'revision':0,'problems':[entry]})
    identity = session['workflow']['currentProblemIds'][0]
    attempted(session['workflow'],identity,revision=1)
    session.update(repository=str(root),taskFile='tasks/deploy.md')
    path = tmp_path / 'session.json'
    handoff.bind(root,path,session)
    # Simulate sealed v5 histories, including an unverifiable extension before repairs.
    cycles = 1
    if history == 'budget-extension':
        session['workflow'].update(problems={}, attempts={}, reserved=0, budget=40,
                                   budgetExtensions=[{'cycles':20, 'authorizationDigest':'unverified'}])
        cycles = 0
    session['workflow'].pop('diagnosisVersion')
    handoff.save(path,session)
    session = json.loads(path.read_text())
    handoff.restore(root,path,session)
    retained = copy.deepcopy(session['workflow']['attempts'])
    handoff.workflow(session)
    assert session['workflow']['legacyUncertain'] and session['workflow']['reserved'] == cycles
    assert session['workflow']['attempts'] == retained
    assert policy.decision(session['workflow'],[identity]) == 'WAITING_HUMAN'
    handoff.save(path,session)
    path.unlink()
    restored = handoff.recover_session(root,path,'tasks/deploy.md')
    assert restored['workflow']['legacyUncertain'] and restored['workflow']['reserved'] == cycles


def check_budget_text_is_not_human_authority(tmp_path):
    root = tmp_path / 'repository'
    root.mkdir()
    task = root / 'tasks/deploy.md'
    task.parent.mkdir()
    task.write_text('## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n'
                    '## Modified files\n- `tasks/deploy.md`\n## Allowed paths\n- `tasks/deploy.md`\n')
    session = {'repository':str(root),'taskFile':'tasks/deploy.md','taskDigest':task_digest(task.read_text()),
               'states':{'Stack':{'status':'NOT_STARTED'}}}
    path = tmp_path / 'state.json'
    handoff.bind(root,path,session)
    session['workflow']['reserved'] = 20
    handoff.save(path,session)
    assert main(['budget','--repository-root',str(root),'--state',str(path),'--additional-cycles','20',
                 '--authorization','LLMが作った文字列']) == 2
    restored = json.loads(path.read_text())
    assert restored['workflow']['budget'] == restored['workflow']['reserved'] == 20
    assert restored['workflow']['status'] == 'WAITING_HUMAN'
    assert not restored['workflow'].get('budgetExtensions')
    assert main(['close','--repository-root',str(root),'--state',str(path),'--authorization','stop']) == 0
    assert main(['budget','--repository-root',str(root),'--state',str(path),'--additional-cycles','20',
                 '--authorization','another self-issued string']) == 2
    assert json.loads(path.read_text())['workflow']['status'] == 'CLOSED'



@pytest.mark.parametrize('progress', ['nested', 'peer', 'static'])
def check_only_observed_target_progress_counts(tmp_path, progress):
    session, entry = diagnosis_fixture(tmp_path)
    handoff.diagnose(tmp_path,session,{'revision':0,'problems':[entry]})
    identity = session['workflow']['currentProblemIds'][0]
    attempted(session['workflow'],identity,revision=1)
    new = next_diagnosis(session,entry)
    state = session['failureObservations'][-1]['awsState']
    state['successEvents'] = [{'resourcePath':'Item/Child' if progress == 'nested' else 'Peer', 'ResourceStatus':'CREATE_COMPLETE'}]
    state['staticValidation'] = 'PASS'
    expected = 'REPAIR_ALLOWED' if progress == 'nested' else 'STOPPED'
    assert handoff.diagnose(tmp_path,session,{'revision':1,'problems':[new]}) == expected

@pytest.mark.parametrize('targeted', [True, False])
def check_common_cause_progress_requires_repaired_target_success(tmp_path, targeted):
    session, entry = diagnosis_fixture(tmp_path, peer=True)
    handoff.diagnose(tmp_path,session,{'revision':0,'problems':[entry]})
    identity = session['workflow']['currentProblemIds'][0]
    attempt = attempted(session['workflow'],identity,revision=1)
    attempt['expectation'] = [{'stack':'Stack','resourcePath':'Item','operation':'CREATE','status':'CREATE_COMPLETE'}]
    new = next_diagnosis(session,entry)
    new['resourcePath'] = 'Item2'
    new['inputRefs'][0]['pointer'] = '/Resources/Item2/Properties/CidrBlock'
    new['modelRefs'][0]['key'] = 'desired.row.002-001.value'
    session['failureObservations'][-1]['awsState']['failureEvents'][0]['resourcePath'] = 'Item2'
    session['states']['Stack'].update(clientToken='actual-new-execution', successEvents=[
        {'resourcePath':'Item' if targeted else 'UnrelatedPeer', 'ResourceStatus':'CREATE_COMPLETE'}])
    handoff.record_outcomes(session)
    assert bool(session['workflow']['problems'][identity].get('resolvedByExecution')) == targeted
    assert handoff.diagnose(tmp_path,session,{'revision':1,'problems':[new]}) == ('REPAIR_ALLOWED' if targeted else 'STOPPED')


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
