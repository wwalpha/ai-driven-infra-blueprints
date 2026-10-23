"""Safe structured failure evidence; cause diagnosis belongs to the supervising LLM."""
from __future__ import annotations

from utils.type_contracts import JsonValue as JsonValue

from collections.abc import Iterable
from deploy.typing import AwsResponse, Session, StackState, StackUnit
from deploy.typing import AwsValue as AwsValue
from utils.type_contracts import JsonObject
import copy
import re

from utils.json_format import fingerprint

from deploy.guards import secret_value_missing

# A transport failure, approval wait or guard failure never becomes an IaC failure.
AUTH_CODES = {'AccessDenied', 'AccessDeniedException', 'UnauthorizedOperation', 'ExpiredToken',
              'ExpiredTokenException', 'InvalidClientTokenId', 'UnrecognizedClientException'}


def exception(state: StackState, error: Exception, stage: str) -> None:
    if hasattr(error, 'deploy_failure'):
        state['failure'] = copy.deepcopy(error.deploy_failure)
        return
    code = getattr(error, 'code', None)
    service = getattr(error, 'deploy_service', None)
    operation = getattr(error, 'deploy_operation', None)
    classification = ('AUTHORIZATION' if code in AUTH_CODES else
                      'IAC_CANDIDATE' if service == 'cloudformation' and
                      operation in {'validate_template', 'create_change_set'} and code in {'ValidationError', 'ValidationException'} else
                      'INPUT_CANDIDATE' if stage == 'INPUT_DECODE' else
                      'SUBMISSION_UNKNOWN' if state.get('status') == 'RUNNING' else 'NEEDS_HUMAN')
    state['failure'] = {'stage': stage, 'service': service, 'operation': operation, 'code': code,
                        'classification': classification, 'executionState': 'UNKNOWN' if state.get('status') == 'RUNNING' else 'NOT_EXECUTED'}


def event(event: AwsResponse, document: AwsResponse) -> JsonObject:
    logical = event.get('LogicalResourceId')
    reason = event.get('ResourceStatusReason') or ''
    # Keep names only when confirmed by the authored template. Never persist raw AWS prose.
    properties = document.get('Resources', {}).get(logical, {}).get('Properties', {})
    mentioned = [key for key in properties if re.search(r'(?<![A-Za-z0-9_])' + re.escape(key) + r'(?![A-Za-z0-9_])', reason)]
    handler = re.search(r'HandlerErrorCode:\s*([A-Za-z][A-Za-z0-9]+)', reason)
    result = {key: event.get(key) for key in ('LogicalResourceId', 'ResourceType', 'ResourceStatus', 'EventId')}
    result.update(resourcePath=event.get('ResourcePath', logical), properties=sorted(mentioned),
                  code=handler.group(1) if handler else None, reasonDigest=fingerprint(reason))
    if secret_value_missing(reason):
        result['ResourceStatusReason'] = 'SECRET_CURRENT_VALUE_MISSING'
    else:
        result['ResourceStatusReason'] = 'STRUCTURED_RESOURCE_FAILURE'
    return result


def template_safety(document: AwsResponse) -> JsonObject:
    return {'Resources': {key: {field: value for field, value in resource.items()
                               if field in {'Type', 'DeletionPolicy', 'UpdateReplacePolicy'}}
                          for key, resource in document.get('Resources', {}).items()}}


def capture(session: Session, unit: StackUnit, state: StackState) -> JsonObject | None:
    if state.get('status') not in {'FAILED', 'BLOCKED'}:
        return None
    execution = state.get('clientToken') if state.get('executionEvidence') else state.get('preparationId')
    if not execution:
        return None
    observation = {'stack': unit['name'], 'execution': execution, 'revision': session.get('inputRevision', 0),
                   'inputManifest': copy.deepcopy(session.get('infraManifest', {})),
                   'unitDigest': session.get('unitDigests', {}).get(unit['name']),
                   'effectiveDigest': session.get('effectiveDigests', {}).get(unit['name']),
                   'awsState': {key: copy.deepcopy(state[key]) for key in
                                ('status', 'stackStatus', 'stackId', 'changeSetId', 'clientToken', 'executionEvidence',
                                 'operationStackId', 'operationType', 'absentBeforeCreate', 'preparationId', 'changeSetFailure', 'failureTemplateSafety', 'failure', 'failureEvents', 'successEvents') if key in state}}
    observation['observationId'] = fingerprint([unit['name'], execution])
    history = session.setdefault('failureObservations', [])
    existing = next((item for item in history if item['observationId'] == observation['observationId']), None)
    if existing:
        return existing
    history.append(observation)
    return observation


def repairable(observation: JsonObject) -> bool:
    state = observation['awsState']
    failure = state.get('failure', {})
    if failure.get('classification') in {'AUTHORIZATION', 'SUBMISSION_UNKNOWN', 'NEEDS_HUMAN', 'APPROVAL'}:
        return False
    if state['status'] == 'FAILED':
        return state.get('stackStatus') in {'ROLLBACK_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE'} and bool(state.get('failureEvents'))
    return (failure.get('classification') in {'IAC_CANDIDATE', 'INPUT_CANDIDATE'} and
            failure.get('executionState') == 'NOT_EXECUTED')


def structured(observation: JsonObject, indices: Iterable[int]) -> set[str]:
    """Observation identity only, never a root-cause classifier or prose fingerprint."""
    state = observation['awsState']
    events = state.get('failureEvents', [])
    if events:
        return {fingerprint([observation['stack'], event.get('resourcePath', event.get('LogicalResourceId')),
                             event.get('ResourceType'), event.get('ResourceStatus'), event.get('code'),
                             sorted(event.get('properties', []))]) for event in (events[i] for i in indices)}
    failure = state.get('failure', {})
    return {fingerprint([observation['stack'], *(failure.get(k) for k in ('stage', 'service', 'operation', 'code'))])}
