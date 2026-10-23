"""Durable, sealed offline handoff records. This module never launches an LLM or Git."""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from types import SimpleNamespace

import copy
import hashlib
import json
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

import cloudformation_inputs as _imports_cloudformation_inputs
import model.sources as _imports_model_sources
import project_targets as _imports_project_targets
import task_contract_core as _imports_task_contract
import utils.aws_mappings as _imports_utils_aws_mappings
from cloudformation_inputs import Blocked
from task_contract_core import safe_path, task_path
from task_contract_core import task_digest as task_digest
from utils.cloudformation_format import decode
from utils.file_operations import atomic_files as atomic_files
from utils.file_operations import sha as sha
from utils.json_format import fingerprint
from utils.sealed_evidence import evidence_store, read_sealed, write_sealed
from worktree_task import bind_deploy_workflow as register_workflow

import deploy.change_sets as _imports_deploy_change_sets
import deploy.inputs as _imports_deploy_inputs
import deploy.session as _imports_deploy_session
from deploy import failures, retry_policy
from deploy.typing import InputPaths, Manifest, PathsFor, Session, StackUnit
from utils.type_contracts import JsonObject
from utils.type_contracts import JsonValue as JsonValue

# Timing and obsolete measurement metadata are historical, never execution authority.
HISTORICAL = {'metrics', 'skillStartedAt', 'firstExecuteAcceptedAt', 'within120Seconds',
              'skillToFirstExecuteSeconds', 'validationStatus', 'validationDigest', 'validationError', 'validationErrors',
              'workflowBinding'}
_verified = {}


def protected(session: Session) -> JsonObject:
    return {key: value for key, value in session.items() if key not in HISTORICAL}


def binding_path(root: Path, task_file: str) -> Path:
    return evidence_store(root) / ('deploy-workflow-' + fingerprint([str(root), task_file]) + '.json')


def write_session(path: Path, session: Session) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(session, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def save(path: Path, session: Session) -> None:
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


def restore(root: Path, path: Path, session: Session) -> None:
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


def recover_session(root: Path, path: Path, task_file: str) -> Session:
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
def locked(path: Path) -> Iterator[None]:
    lock = path.with_name(path.name + '.handoff-lock')
    try:
        lock.mkdir()
    except FileExistsError:
        raise Blocked('handoff busy/interrupted; retain lock and review: ' + str(lock)) from None
    try:
        yield
    finally:
        lock.rmdir()


def external(root: Path, path: str | Path) -> Path:
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or path.resolve().is_relative_to(root.resolve()):
        raise Blocked('handoff evidence must be an absolute external file')
    return path.resolve()


def workflow(session: Session) -> JsonObject:
    if 'workflow' not in session:
        session['workflow'] = {'workflowId': uuid.uuid4().hex, 'budget': retry_policy.DEFAULT_BUDGET,
                               'reserved': 0, 'problems': {}, 'attempts': {}, 'accepted': [], 'diagnosisVersion': 1}
    # v5 stored label fingerprints, which cannot prove common-cause identity.
    current = session['workflow']
    if current.get('diagnosisVersion') not in {None, 1}:
        raise Blocked('unsupported workflow diagnosis version; retain history for explicit migration')
    if current.get('diagnosisVersion') != 1:
        if current['problems'] or current['attempts'] or current.get('reserved') or current.get('budgetExtensions'):
            current['legacyUncertain'] = True
            current['status'] = 'WAITING_HUMAN'
        current['diagnosisVersion'] = 1
    session.setdefault('inputRevision', 0)
    return session['workflow']


def bind(root: Path, path: Path, session: Session) -> None:
    """One unfinished workflow per Task; replacing/deleting its session is not a reset."""
    current = workflow(session)
    if not current['attempts'] and not current.get('reserved') and not current.get('budgetExtensions'):
        current['budget'] = session.get('repairBudget', retry_policy.DEFAULT_BUDGET)
    record_path = binding_path(root, session['taskFile'])
    value = {'workflowId': current['workflowId'], 'session': str(path), 'taskFile': session['taskFile']}
    if record_path.exists():
        record = read_sealed(root, record_path)
        if any(record.get(key) != val for key, val in value.items()):
            raise Blocked('Task already owns another deploy workflow; inherit the original session/history')
        if id(session) not in _verified:
            restore(root, path, session)
    else:
        record = value | {'sequence': 0, 'state': protected(session)}
        write_sealed(root, record_path, record)
        _verified[id(session)] = (str(path), 0)
    session['workflowBinding'] = str(record_path)
    contract = (root / session['taskFile']).read_text(encoding='utf-8') if (root / session['taskFile']).is_file() else ''
    register_workflow(root, path, session, record_path,
        activate='- External IaC repair: `allowed`' in contract.splitlines() or bool(current['attempts']) or current['reserved'] > 0)


def effective(root: Path, units: Iterable[StackUnit], paths_for: PathsFor, input_paths: InputPaths) -> dict[str, str]:
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


def record_stop(session: Session, units: Iterable[StackUnit]) -> None:
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
        load_model = _imports_model_sources.load_model
        if reference.get('key') not in load_model(path).authoritative:
            raise Blocked('diagnosis Model key does not exist')
    else:
        if reference.get('pointer') != '':
            raise Blocked('artifact diagnosis must reference the whole exact source')


def diagnose(root: Path, session: Session, diagnosis: JsonObject) -> str:
    """Publish a complete diagnosis atomically, without partially rewriting histories."""
    candidate = copy.deepcopy(session)
    result = _diagnose(root, candidate, diagnosis)
    session.clear()
    session.update(candidate)
    return result


def _relation(current, observations, entry):
    relation = entry.get('relation')
    related = entry.get('relatedProblemIds')
    reason = entry.get('reason')
    if relation not in {'SAME', 'NEW', 'UNKNOWN'} or not isinstance(related, list) or len(related) != len(set(related)):
        raise Blocked('diagnosis requires SAME/NEW/UNKNOWN and relatedProblemIds')
    if set(related) - current['problems'].keys() or relation == 'SAME' and not related:
        raise Blocked('diagnosis must reference known related problems')
    if not isinstance(reason, str) or len(reason.strip()) < 32:
        raise Blocked('diagnosis requires a concrete comparison reason, not a label')
    refs = entry.get('evidenceRefs')
    if not isinstance(refs, list) or not refs:
        raise Blocked('diagnosis requires current/prior observation evidenceRefs')
    cited = set()
    for ref in refs:
        observation = observations.get(ref.get('observationId'))
        if not observation or ref.get('revision') != observation['revision']:
            raise Blocked('diagnosis observation reference revision changed')
        indices = ref.get('eventIndices')
        events = observation['awsState'].get('failureEvents', [])
        if not isinstance(indices, list) or (events and not indices) or any(type(i) is not int or not 0 <= i < len(events) for i in indices):
            raise Blocked('diagnosis observation event reference missing')
        cited.update((ref['observationId'], i) for i in indices or [None])
    needed = {(entry['observationId'], i) for i in entry.get('eventIndices', []) or [None]}
    for identity in related:
        evidence = current['problems'][identity]['evidence']
        needed.update((evidence['observationId'], i) for i in evidence.get('eventIndices', []) or [None])
    if not needed <= cited:
        raise Blocked('diagnosis must compare cited current and related historical failures')
    return relation, related


def _lambda__diagnose_target_389(value):
    return tuple((value[k] for k in ('target', 'stack', 'resourcePath', 'resourceType', 'operation')))


def _diagnose(root, session, diagnosis):
    """Check evidence membership/revisions. The LLM retains semantic responsibility."""
    current = workflow(session)
    if session.get('observedError') or any(s['status'] == 'RUNNING' or s.get('pollError') for s in session['states'].values()):
        raise Blocked('drain/observe and publish successful peers before diagnosis')
    if diagnosis.get('revision') != session['inputRevision'] or not diagnosis.get('problems'):
        raise Blocked('diagnosis revision/problem set missing')
    if session.get('pendingRequest') or current.get('status') in {'CLOSED', 'COMPLETE'}:
        raise Blocked('finish the pending request or retain the closed workflow')
    observations = {o['observationId']: o for o in session.get('failureObservations', [])}
    active = set(current.get('latestObservations', []))
    identified, covered = set(), set()
    uncertain = False
    previous_ids = set(current['problems'])
    for entry in diagnosis['problems']:
        observation = observations.get(entry.get('observationId'))
        if not observation or observation['observationId'] not in active:
            raise Blocked('failure is not an evidenced repair candidate')
        state = observation['awsState']
        events = state.get('failureEvents', [])
        indices = entry.get('eventIndices', [])
        if events and (not indices or any(type(i) is not int or not 0 <= i < len(events) for i in indices)):
            raise Blocked('missing failure event reference')
        relation, related_ids = _relation(current, observations, entry)
        if relation == 'UNKNOWN':
            for key, manifest in (('inputRefs', observation['inputManifest']), ('modelRefs', session['modelInputManifest'])):
                for ref in entry.get(key, []):
                    _reference(root, manifest, ref)
            covered.update((observation['observationId'], i) for i in indices)
            uncertain = True
            continue
        if not failures.repairable(observation):
            raise Blocked('failure is not an evidenced repair candidate')
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
            load_model = _imports_model_sources.load_model
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
        definition_root = _imports_utils_aws_mappings.definition_root
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
        signatures = failures.structured(observation, indices)
        replay = next((key for key, p in current['problems'].items() if entry in p.get('diagnoses', [])), None)
        if relation == 'SAME':
            causes = {current['problems'][key].get('causeId', key) for key in related_ids}
            if len(causes) != 1:
                raise Blocked('SAME cannot merge independently counted causes; Human review required')
            cause_id = causes.pop()
            known_causes = {p.get('causeId', key) for key, p in current['problems'].items()
                            if signatures & set(p.get('failureSignatures', []))}
            if known_causes - {cause_id}:
                uncertain = True
                continue
            target = _lambda__diagnose_target_389
            problem_id = next((key for key, p in current['problems'].items()
                               if p.get('causeId', key) == cause_id and target(p['identity']) == target(identity)), None)
            problem_id = problem_id or uuid.uuid4().hex
        elif replay:
            problem_id = replay
            cause_id = current['problems'][problem_id]['causeId']
        else:
            if not previous_ids <= set(related_ids):
                raise Blocked('NEW must compare all retained prior problems, including other resources')
            known = {signature for p in current['problems'].values() for signature in p.get('failureSignatures', [])}
            if signatures & known or current.get('legacyUncertain'):
                # Reference existence is never proof of semantic difference.
                uncertain = True
                continue
            problem_id = cause_id = uuid.uuid4().hex
        problem = current['problems'].setdefault(problem_id, {'identity': identity, 'causeId': cause_id,
                                                            'observations': [], 'attempts': []})
        problem['evidence'] = copy.deepcopy(entry)
        if entry not in problem.setdefault('diagnoses', []):
            problem['diagnoses'].append(copy.deepcopy(entry))
        problem['failureSignatures'] = sorted(set(problem.get('failureSignatures', [])) | signatures)
        # Only nested successes or verified repaired targets of this cause are progress.
        progress = [fingerprint([observation['stack'], e.get('resourcePath'), e.get('ResourceStatus')]) for e in state.get('successEvents', [])
                    if str(e.get('resourcePath', '')).startswith(identity['resourcePath'] + '/')]
        for peer in retry_policy.related(current, problem_id):
            if peer is not problem and peer.get('resolvedByExecution') and peer.get('resolvedRevision') == observation['revision']:
                target = peer['identity']
                progress.append(fingerprint([target['stack'], target['resourcePath'], target['operation'], 'VERIFIED_TARGET']))
        retry_policy.observe(current, problem_id, {'execution': observation['execution'], 'revision': observation['revision'],
                                                  'observationId': observation['observationId']}, progress)
        identified.add(problem_id)
    expected = {(oid, i) for oid in active for i, event in enumerate(observations[oid]['awsState'].get('failureEvents', []))}
    if covered != expected:
        raise Blocked('unexplained rollback/delete/peer failures require diagnosis')
    # Absence is not success. It is nevertheless a regression if a targeted problem returns later.
    for key, problem in current['problems'].items():
        if not uncertain and key not in identified and problem['attempts'] and not any(
                current['problems'][p].get('causeId', p) == problem.get('causeId', key) for p in identified):
            attempt = current['attempts'][problem['attempts'][-1]]
            if attempt.get('acceptedRevision', float('inf')) <= session['inputRevision']:
                problem['absentAfterRepair'] = True
    current['currentProblemIds'] = sorted(identified)
    if diagnosis not in current.setdefault('diagnoses', []):
        current['diagnoses'].append(copy.deepcopy(diagnosis))
    current['status'] = ('WAITING_HUMAN' if current.get('legacyUncertain') else
                         'NEEDS_DIAGNOSIS' if uncertain else retry_policy.decision(current, identified))
    return current['status']


def issue_request(
    root: Path,
    path: Path,
    session: Session,
    problem_ids: Sequence[str],
    allowed_paths: Sequence[str],
    expectation: list[JsonObject],
) -> JsonObject:
    current = workflow(session)
    if current.get('status') in {'NEEDS_DIAGNOSIS', 'WAITING_HUMAN', 'STOPPED', 'CLOSED', 'COMPLETE'}:
        raise ValueError('repair policy: ' + current['status'])
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


def verify_inputs(
    root: Path,
    session: Session,
    child_paths: Iterable[str] = (),
    contract_file: str | None = None,
) -> Manifest:
    load_target = _imports_project_targets.load_target
    selected_task = _imports_task_contract.selected_task

    deployment_input_paths = _imports_deploy_inputs.deployment_input_paths
    load_units = _imports_deploy_inputs.load_units
    design_digest = _imports_deploy_session.design_digest
    execution_digest = _imports_deploy_session.execution_digest
    model_input_manifest = _imports_deploy_session.model_input_manifest
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


def dependencies(backend: SimpleNamespace, units: Iterable[StackUnit]) -> dict[str, list[str]]:

    condition_active = _imports_cloudformation_inputs.condition_active
    resolve_value = _imports_cloudformation_inputs.resolve_value

    import_names = _imports_deploy_change_sets.import_names
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


def record_outcomes(session: Session) -> None:
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
