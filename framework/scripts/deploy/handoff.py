"""Durable, sealed offline handoff records. This module never launches an LLM or Git."""
import copy
import hashlib
import json
import re
import uuid
from contextlib import contextmanager
from pathlib import Path
from cloudformation_inputs import Blocked
from deploy import failures, retry_policy
from deploy.contracts import task_digest, sha
from import_guard import evidence_store, read_sealed, write_sealed
from task_contract import task_path, safe_path
from utils.file_operations import atomic_files
from utils.json_format import fingerprint
from utils.cloudformation_format import decode


# Timing and obsolete measurement metadata are historical, never execution authority.
HISTORICAL = {'metrics', 'skillStartedAt', 'firstExecuteAcceptedAt', 'within120Seconds',
              'skillToFirstExecuteSeconds', 'validationStatus', 'validationDigest', 'validationError', 'validationErrors',
              'workflowBinding'}
_verified = {}


def protected(session):
    return {key: value for key, value in session.items() if key not in HISTORICAL}


def binding_path(root, task_file):
    return evidence_store(root) / ('deploy-workflow-' + fingerprint([str(root), task_file]) + '.json')


def write_session(path, session):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(session, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def save(path, session):
    if not session.get('workflowBinding'):
        # Pure scheduler fixtures and explicitly unmigrated legacy sessions have no ledger.
        write_session(path, session)
        return
    root = Path(session['repository'])
    proof = binding_path(root, session['taskFile'])
    record = read_sealed(root, proof)
    if _verified.get(id(session)) != (str(path), record['sequence']):
        raise Blocked('session was not verified at the current ledger revision')
    after = protected(session)
    pending = {'before': fingerprint(record['state']), 'state': after, 'sequence': record['sequence'] + 1,
               'session': str(path), 'workflowId': session['workflow']['workflowId']}
    intent = proof.with_name(proof.name + '.intent')
    if intent.exists():
        raise Blocked('recover the signed session save intent before another publication')
    write_sealed(root, intent, pending)
    write_session(path, session)
    record.update(state=after, sequence=pending['sequence'])
    write_sealed(root, proof, record)
    intent.unlink()
    _verified[id(session)] = (str(path), record['sequence'])


def restore(root, path, session):
    """Verify a saved revision or finish its sealed write intent; reject stale copies."""
    proof = binding_path(root, session['taskFile'])
    if not proof.exists():
        if session.get('workflowBinding'):
            raise Blocked('workflow ledger missing; never reset history')
        return  # New/explicitly migrating v3 only; normal v4 callers bind before saving.
    record = read_sealed(root, proof)
    identity = {'session': str(path), 'taskFile': session['taskFile'], 'workflowId': session.get('workflow', {}).get('workflowId')}
    if any(record.get(key) != value for key, value in identity.items()):
        raise Blocked('Task already owns another deploy workflow; inherit its state')
    intent = proof.with_name(proof.name + '.intent')
    if intent.exists():
        pending = read_sealed(root, intent)
        before, after, actual = pending['before'], fingerprint(pending['state']), fingerprint(protected(session))
        if (pending['session'] != str(path) or pending['workflowId'] != record['workflowId'] or
                actual not in {before, after} or fingerprint(record['state']) not in {before, after} or
                record['sequence'] not in {pending['sequence'] - 1, pending['sequence']}):
            raise Blocked('session save intent does not match known before/after revisions')
        retained = {key: value for key, value in session.items() if key in HISTORICAL}
        session.clear()
        session.update(retained | pending['state'])
        write_session(path, session)
        record.update(state=pending['state'], sequence=pending['sequence'])
        write_sealed(root, proof, record)
        intent.unlink()
    if fingerprint(protected(session)) != fingerprint(record['state']):
        raise Blocked('saved session differs from signed workflow ledger; no history/hash reset')
    session['workflowBinding'] = str(proof)
    _verified[id(session)] = (str(path), record['sequence'])


def recover_session(root, path, task_file):
    proof = binding_path(root, task_file)
    record = read_sealed(root, proof)
    if record['session'] != str(path) or record['taskFile'] != task_file:
        raise Blocked('recovery must retain the original session/Task path')
    session = copy.deepcopy(record['state'])
    session['workflowBinding'] = str(proof)
    write_session(path, session)
    restore(root, path, session)
    return session


@contextmanager
def locked(path):
    lock = path.with_name(path.name + '.handoff-lock')
    try:
        lock.mkdir()
    except FileExistsError:
        raise Blocked('handoff busy/interrupted; retain lock and review: ' + str(lock)) from None
    try:
        yield
    finally:
        lock.rmdir()


def external(root, path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or path.resolve().is_relative_to(root.resolve()):
        raise Blocked('handoff evidence must be an absolute external file')
    return path.resolve()


def workflow(session):
    if 'workflow' not in session:
        session['workflow'] = {'workflowId': uuid.uuid4().hex, 'budget': retry_policy.DEFAULT_BUDGET,
                               'reserved': 0, 'problems': {}, 'attempts': {}, 'accepted': []}
    session.setdefault('inputRevision', 0)
    return session['workflow']


def bind(root, path, session):
    """One unfinished workflow per Task; replacing/deleting its session is not a reset."""
    current = workflow(session)
    if not current['attempts'] and not current.get('budgetExtensions'):
        current['budget'] = session.get('repairBudget', retry_policy.DEFAULT_BUDGET)
    record_path = binding_path(root, session['taskFile'])
    value = {'workflowId': current['workflowId'], 'session': str(path), 'taskFile': session['taskFile']}
    if record_path.exists():
        record = read_sealed(root, record_path)
        if any(record.get(key) != val for key, val in value.items()):
            raise Blocked('Task already owns another deploy workflow; inherit/explicitly close it first')
        if id(session) not in _verified:
            restore(root, path, session)
    else:
        record = value | {'sequence': 0, 'state': protected(session)}
        write_sealed(root, record_path, record)
        _verified[id(session)] = (str(path), 0)
    session['workflowBinding'] = str(record_path)
    from worktree_task import bind_deploy_workflow
    contract = (root / session['taskFile']).read_text(encoding='utf-8') if (root / session['taskFile']).is_file() else ''
    bind_deploy_workflow(root, path, session, record_path,
        activate='- External IaC repair: `allowed`' in contract.splitlines() or bool(current['attempts']) or current['reserved'] > 0)


def effective(root, units, paths_for, input_paths):
    """Existing CFn decoder, JSON parameters and artifact hashes; no intrinsic evaluation."""
    result = {}
    for unit in units:
        template, parameters = paths_for(unit)
        raw = template.read_bytes()
        document, errors = decode(raw)
        try:
            # The decoder can emit date scalars. Preserve their type deterministically.
            template_hash = hashlib.sha256(json.dumps(document, sort_keys=True, default=str).encode()).hexdigest() if not errors else sha(template)
            values = json.loads(parameters.read_text(encoding='utf-8'))
            if isinstance(values, list):
                values = sorted(values, key=lambda item: item.get('ParameterKey', ''))
            parameter_hash = fingerprint(values)
        except (ValueError, TypeError, AttributeError):
            template_hash, parameter_hash = sha(template), sha(parameters)
        artifacts = [(p.relative_to(root).as_posix(), sha(p)) for p in input_paths([unit]) if p not in {template, parameters}]
        result[unit['name']] = fingerprint([template_hash, parameter_hash, artifacts])
    return result


def record_stop(session, units):
    current = workflow(session)
    observed = []
    for unit in units:
        state = session['states'][unit['name']]
        record = failures.capture(session, unit, state)
        if record:
            observed.append(record['observationId'])
    if observed:
        current['status'] = 'NEEDS_DIAGNOSIS'
        current['latestObservations'] = observed


def _reference(root, manifest, reference):
    path = safe_path(root, reference['path'])
    if manifest.get(reference['path']) != reference.get('sha256') or sha(path) != reference['sha256']:
        raise Blocked('diagnosis reference revision changed')
    if path.suffix in {'.yaml', '.yml', '.json'}:
        document, errors = decode(path.read_bytes())
        if errors:
            if reference.get('pointer') != '':
                raise Blocked('unparseable input requires an exact whole-input reference')
            return
        value = document
        pointer = reference['pointer']
        if pointer and not pointer.startswith('/'):
            raise Blocked('invalid diagnosis JSON pointer')
        try:
            for part in pointer.split('/')[1:] if pointer else []:
                key = part.replace('~1', '/').replace('~0', '~')
                value = value[int(key)] if isinstance(value, list) else value[key]
        except (KeyError, IndexError, ValueError, TypeError):
            raise Blocked('diagnosis input location does not exist') from None
    elif path.suffix == '.properties':
        from model.sources import load_model
        if reference.get('key') not in load_model(path).authoritative:
            raise Blocked('diagnosis Model key does not exist')
    else:
        if reference.get('pointer') != '':
            raise Blocked('artifact diagnosis must reference the whole exact source')


def diagnose(root, session, diagnosis):
    """Check evidence membership/revisions. The LLM retains semantic responsibility."""
    current = workflow(session)
    if session.get('observedError') or any(s['status'] == 'RUNNING' or s.get('pollError') for s in session['states'].values()):
        raise Blocked('drain/observe and publish successful peers before diagnosis')
    if diagnosis.get('revision') != session['inputRevision'] or not diagnosis.get('problems'):
        raise Blocked('diagnosis revision/problem set missing')
    observations = {o['observationId']: o for o in session.get('failureObservations', [])}
    active = set(current.get('latestObservations', []))
    identified, covered = set(), set()
    for entry in diagnosis['problems']:
        observation = observations.get(entry.get('observationId'))
        if not observation or observation['observationId'] not in active or not failures.repairable(observation):
            raise Blocked('failure is not an evidenced repair candidate')
        state = observation['awsState']
        events = state.get('failureEvents', [])
        indices = entry.get('eventIndices', [])
        if events and (not indices or any(type(i) is not int or not 0 <= i < len(events) for i in indices)):
            raise Blocked('missing failure event reference')
        identity = {key: entry.get(key) for key in ('resourcePath', 'resourceType', 'operation', 'property', 'constraint', 'cause')}
        if any(v in {'unknown', 'UNSET', 'none', 'unconfirmed'} for v in identity.values()):
            raise Blocked('unconfirmed problem identity; NEEDS_DIAGNOSIS')
        if any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_.:/\[\]-]{1,240}', v) for v in identity.values()):
            raise Blocked('ambiguous problem identity; NEEDS_DIAGNOSIS')
        if identity['cause'] not in {'IAC_PROPERTY', 'IAC_SYNTAX', 'IAC_PARAMETER', 'IAC_ARTIFACT', 'IAC_PERMISSION'}:
            raise Blocked('design/scope/unknown cause requires Human diagnosis')
        for index in indices:
            event = events[index]
            if identity['operation'] != event.get('ResourceStatus', '').split('_', 1)[0]:
                raise Blocked('problem operation differs from failed event')
            if event.get('resourcePath', event.get('LogicalResourceId')) != identity['resourcePath'] or event.get('ResourceType') != identity['resourceType']:
                raise Blocked('problem target differs from event')
            covered.add((observation['observationId'], index))
        if not events and identity['operation'] != (state.get('failure', {}).get('operation') or 'decode_input'):
            raise Blocked('problem operation differs from unexecuted failure stage')
        refs = entry.get('inputRefs', [])
        models = entry.get('modelRefs', [])
        if not refs or not models:
            raise Blocked('diagnosis requires failed-input and approved-design locations')
        if any(ref['path'] not in session['unitInputPaths'][observation['stack']] for ref in refs):
            raise Blocked('diagnosis input belongs to another Stack')
        for ref in refs:
            _reference(root, observation['inputManifest'], ref)
        model_properties = set()
        for ref in models:
            _reference(root, session['modelInputManifest'], ref)
            from model.sources import load_model
            authority = load_model(root / ref['path']).authoritative
            owners = [key.split('.')[2] for key, value in authority.items() if key.startswith('desired.resource.') and
                      key.endswith('.cfn-logicalId') and value == observation['stack'] + '-' + identity['resourcePath'].split('/')[0]]
            resource_ref = any(ref['key'].startswith('desired.row.' + owner + '-') or ref['key'].startswith('desired.resource.' + owner + '.') for owner in owners)
            stack_ref = not events and identity['resourceType'] == 'AWS::CloudFormation::Stack' and any(key.startswith('desired.stack.') and key.endswith('.name') and value == observation['stack'] and ref['key'].startswith(key.removesuffix('.name') + '.') for key, value in authority.items())
            if not resource_ref and not stack_ref:
                raise Blocked('Model evidence does not belong to the failed resource/Stack')
            if resource_ref and ref['key'].startswith('desired.row.'):
                model_properties.add(authority.get(ref['key'].rsplit('.', 1)[0] + '.property'))
        if identity['cause'] == 'IAC_PROPERTY':
            model_property = '.'.join(identity['resourceType'].split('::')[1:]) + '.' + identity['property']
            property_pointer = '/Resources/' + identity['resourcePath'].split('/')[0] + '/Properties/' + identity['property'].replace('.', '/')
            if model_property not in model_properties or not any(ref.get('pointer') == property_pointer or
                    ref.get('pointer', '').startswith(property_pointer + '/') for ref in refs):
                raise Blocked('claimed Property differs from referenced input/Model property')
        constraint_refs = entry.get('constraintRefs', [])
        from utils.aws_mappings import definition_root
        for ref in constraint_refs:
            path = safe_path(definition_root(root), ref['path'])
            if not ref['path'].startswith('framework/materials/cloudformation-schema/'):
                raise Blocked('constraint reference must be a pinned provider schema')
            _reference(definition_root(root), {ref['path']: sha(path)}, ref)
            if json.loads(path.read_text()).get('typeName') != identity['resourceType']:
                raise Blocked('constraint schema type differs from the failed resource')
            prefix = '/properties/' + identity['property'].split('.')[0]
            if identity['cause'] == 'IAC_PROPERTY' and not (ref['pointer'] == prefix or ref['pointer'].startswith(prefix + '/')):
                raise Blocked('constraint schema reference does not target the claimed Property')
        if events and not any('/Resources/' + identity['resourcePath'].split('/')[0] in ref.get('pointer', '')
                              or ref['path'].endswith('.json') for ref in refs):
            raise Blocked('diagnosis input does not reference the failed resource')
        identity.update(target=session['logicalTarget'], stack=observation['stack'])
        problem_id = fingerprint(identity)
        related = {key for key, problem in current['problems'].items() if key != problem_id and
                   problem.get('identity', {}).get('stack') == identity['stack'] and
                   problem.get('identity', {}).get('resourcePath') == identity['resourcePath']}
        is_new = problem_id not in current['problems']
        if is_new and related and not related <= set(entry.get('distinctFrom', [])):
            raise Blocked('different constraint/cause requires explicit prior-problem evidence')
        for previous_id in related if is_new else ():
            previous = current['problems'][previous_id]
            if previous['identity']['property'] != identity['property']:
                mentioned = {prop for i in indices for prop in events[i].get('properties', [])}
                if identity['property'].split('.')[0] not in mentioned and not constraint_refs:
                    raise Blocked('different Property lacks corresponding event/schema evidence; NEEDS_DIAGNOSIS')
            if previous['identity']['property'] == identity['property']:
                old = previous['evidence']
                old_codes = {e.get('code') for e in observations[old['observationId']]['awsState'].get('failureEvents', [])}
                new_codes = {events[i].get('code') for i in indices}
                reference_keys = lambda refs: {(ref['path'], ref['sha256'], ref['pointer']) for ref in refs}
                previous_refs = reference_keys(old.get('constraintRefs', []))
                distinct_refs = bool(previous_refs and constraint_refs and reference_keys(constraint_refs) != previous_refs)
                if not distinct_refs and new_codes <= old_codes:
                    raise Blocked('different constraint needs distinct confirmed schema/event-code evidence')
        problem = current['problems'].setdefault(problem_id, {'identity': identity, 'observations': [], 'attempts': []})
        problem['evidence'] = copy.deepcopy(entry)
        # Progress requires newly successful resources *within* this failure path.
        progress = [fingerprint([e.get('resourcePath'), e.get('ResourceStatus')]) for e in state.get('successEvents', [])
                    if str(e.get('resourcePath', '')).startswith(identity['resourcePath'] + '/')]
        retry_policy.observe(current, problem_id, {'execution': observation['execution'], 'revision': observation['revision'],
                                                  'observationId': observation['observationId']}, progress)
        identified.add(problem_id)
    expected = {(oid, i) for oid in active for i, event in enumerate(observations[oid]['awsState'].get('failureEvents', []))}
    if covered != expected:
        raise Blocked('unexplained rollback/delete/peer failures require diagnosis')
    # Absence is not success. It is nevertheless a regression if a targeted problem returns later.
    for key, problem in current['problems'].items():
        if key not in identified and problem['attempts']:
            attempt = current['attempts'][problem['attempts'][-1]]
            if attempt.get('acceptedRevision', float('inf')) <= session['inputRevision']:
                problem['absentAfterRepair'] = True
    current['currentProblemIds'] = sorted(identified)
    current['status'] = retry_policy.decision(current, identified)
    return current['status']


def issue_request(root, path, session, problem_ids, allowed_paths, expectation):
    current = workflow(session)
    contract = task_path(root).read_text(encoding='utf-8')
    if '- External IaC repair: `allowed`' not in contract.splitlines():
        raise Blocked('external repair loop needs explicit original Task authorization')
    if session.get('pendingRequest'):
        pending = session['pendingRequest']
        if set(pending['problemIds']) != set(problem_ids) or pending['allowedPaths'] != sorted(allowed_paths) or pending['expectation'] != expectation:
            raise Blocked('another request is already pending')
        return pending
    if set(problem_ids) - set(current.get('currentProblemIds', [])):
        raise Blocked('request problems are not the current diagnosed failures')
    if len(allowed_paths) != len(set(allowed_paths)):
        raise Blocked('repair paths must be unique')
    if not allowed_paths or set(allowed_paths) - session['infraManifest'].keys():
        raise Blocked('repair paths must be exact declared execution inputs')
    problem_stacks = {current['problems'][p]['identity']['stack'] for p in problem_ids}
    related_inputs = {p for name in problem_stacks for p in session['unitInputPaths'][name]}
    if set(allowed_paths) - related_inputs:
        raise Blocked('repair paths do not belong to the target problem Stacks')
    for relative in allowed_paths:
        safe_path(root, relative)
        if not relative.startswith('infra/'):
            raise Blocked('repair can only edit authorized IaC inputs')
    expected_targets = {(current['problems'][p]['identity']['stack'], current['problems'][p]['identity']['resourcePath'],
                         current['problems'][p]['identity']['operation']) for p in problem_ids}
    if not expectation or {(e['stack'], e['resourcePath'], e['operation']) for e in expectation} != expected_targets:
        raise Blocked('expected observations must cover exactly the repaired problem operations')
    request_id = uuid.uuid4().hex
    attempt = retry_policy.reserve(current, request_id, problem_ids)
    attempt['expectation'] = copy.deepcopy(expectation)
    pending = {'expectation': copy.deepcopy(expectation), 'target': session['target'], 'environment': session['environment'],
               'deploymentScope': sorted(session['states']),
               'workflowId': current['workflowId'], 'requestId': request_id, 'attemptId': attempt['attemptId'],
               'session': str(path), 'repository': str(root), 'taskFile': session['taskFile'], 'taskDigest': session['taskDigest'],
               'inputDigest': session['inputDigest'], 'revision': session['inputRevision'],
               'problemIds': sorted(problem_ids), 'allowedPaths': sorted(allowed_paths),
               'infraManifest': copy.deepcopy(session['infraManifest']), 'modelInputManifest': copy.deepcopy(session['modelInputManifest']),
               'designDigest': session['designDigest'], 'executionDigest': session['executionDigest'],
               'observations': copy.deepcopy([o for o in session['failureObservations'] if o['observationId'] in current['latestObservations']]),
               'validationScope': session['validationScope']}
    session['pendingRequest'] = pending
    current['status'] = 'REQUESTED'
    save(path, session)  # Reservation and intent precede any task switch, including interruption.
    return pending


def verify_inputs(root, session, child_paths=(), contract_file=None):
    from deploy.session import design_digest, model_input_manifest, execution_digest
    from deploy.inputs import deployment_input_paths, load_units
    from project_targets import load_target
    from task_contract import selected_task
    environment, directory, target = session['environment'], session['directory'], session['target']
    current = load_target(root, environment, target['awsAccountId'], target.get('alias'))
    if current != target:
        raise Blocked('project target changed during handoff')
    with selected_task(root, contract_file or session['taskFile']):
        if design_digest(root, environment, directory, contract_file=contract_file or session['taskFile']) != session['designDigest'] or model_input_manifest(root, environment, directory) != session['modelInputManifest']:
            raise Blocked('approved design/Model dependency inputs changed during handoff')
        _, units = load_units(root, environment, directory, list(session['states']))
        actual = {p.relative_to(root).as_posix(): sha(p) for p in deployment_input_paths(root, environment, directory, target, units)}
    allowed = set(child_paths)
    if actual.keys() != session['infraManifest'].keys() or any(actual[p] != digest for p, digest in session['infraManifest'].items() if p not in allowed):
        raise Blocked('unrecorded IaC changes during handoff')
    if execution_digest(root, target, sha, session['unitDigests']) != session['executionDigest']:
        raise Blocked('execution definitions changed; repair-result cannot migrate them')
    return actual


def dependencies(backend, units):
    from deploy.change_sets import import_names
    from cloudformation_inputs import condition_active, resolve_value
    producers, imports = {}, {}
    for unit in units:
        document, parameters = backend.templates[unit['name']]
        pseudo = {'AWS::StackName': unit['name'], 'AWS::Region': backend.target['awsRegion'],
                  'AWS::AccountId': backend.target.get('awsExecutionAccountId', backend.target['awsAccountId'])}
        try:
            imports[unit['name']] = import_names(document, parameters, pseudo)
            for output in document.get('Outputs', {}).values():
                if 'Export' in output and condition_active(document, parameters, pseudo, output):
                    name = resolve_value(output['Export']['Name'], parameters, pseudo, conditions=document.get('Conditions', {}))
                    if name in producers and producers[name] != unit['name']:
                        raise Blocked('declared Export has multiple producers')
                    producers[name] = unit['name']
        except Blocked:
            # Keep uncertainty explicit; the normal fresh AWS boundary still rejects it.
            imports[unit['name']] = None
    result = {unit['name']: [] for unit in units}
    for consumer, names in imports.items():
        if names is None:
            result.setdefault('__unresolved__', []).append(consumer)
            continue
        for name in names:
            if name in producers and consumer != producers[name]:
                result[producers[name]].append(consumer)
    return {name: sorted(set(values)) for name, values in result.items()}


def record_outcomes(session):
    current = workflow(session)
    for attempt in current['attempts'].values():
        if attempt.get('acceptedRevision') is None or attempt['acceptedRevision'] > session.get('inputRevision', 0):
            continue
        expectation = attempt.get('expectation', [])
        for problem_id in attempt['problemIds']:
            problem = current['problems'][problem_id]
            identity = problem['identity']
            expected = [item for item in expectation if item['stack'] == identity['stack'] and item['resourcePath'] == identity['resourcePath']]
            state = session['states'][identity['stack']]
            if expected and all((item['operation'] in state.get('successfulPreparationOperations', {}) if item['status'] == 'SUCCEEDED' else any(event.get('resourcePath') == item['resourcePath'] and event.get('ResourceStatus') == item['status'] for event in state.get('successEvents', []))) for item in expected):
                problem['resolvedByExecution'] = state.get('clientToken')
                problem['resolvedRevision'] = session['inputRevision']

    if all(state['status'] == 'SUCCESS' and state.get('observedSynced') for state in session['states'].values()):
        unresolved = {problem for attempt in current['attempts'].values() if attempt.get('acceptedRevision') is not None
                      for problem in attempt['problemIds'] if not current['problems'][problem].get('resolvedByExecution')}
        current['status'] = 'NEEDS_DIAGNOSIS' if unresolved else 'COMPLETE'
        if unresolved:
            session['repairOutcomeUnverified'] = sorted(unresolved)
        else:
            session.pop('repairOutcomeUnverified', None)
