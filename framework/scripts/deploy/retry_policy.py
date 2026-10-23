"""Pure repair decisions. Static validation and file changes are never AWS progress."""

import uuid

MAX_PROBLEM_CYCLES = 3
DEFAULT_BUDGET = 20


def related(workflow, identity):
    problem = workflow['problems'][identity]
    cause = problem.get('causeId', identity)
    return [p for key, p in workflow['problems'].items() if p.get('causeId', key) == cause]


def attempts_for(workflow, identity):
    ids = {a for p in related(workflow, identity) for a in p['attempts']}
    return [a for key, a in workflow['attempts'].items() if key in ids]


def decision(workflow, problem_ids):
    if workflow.get('status') in {'CLOSED', 'COMPLETE'}:
        return 'WAITING_HUMAN'
    if workflow.get('legacyUncertain'):
        return 'WAITING_HUMAN'
    if workflow.get('reserved', 0) >= workflow.get('budget', DEFAULT_BUDGET):
        return 'WAITING_HUMAN'
    for identity in problem_ids:
        problem = workflow['problems'][identity]
        attempts = attempts_for(workflow, identity)
        if len(attempts) >= MAX_PROBLEM_CYCLES:
            return 'WAITING_HUMAN'
        if any(p.get('regression') or p.get('noProgress') for p in related(workflow, identity)):
            return 'STOPPED'
        if not problem.get('observations'):
            return 'NEEDS_DIAGNOSIS'
    return 'REPAIR_ALLOWED' if problem_ids else 'NEEDS_DIAGNOSIS'


def observe(workflow, identity, observation, progress=()):
    problem = workflow['problems'].setdefault(identity, {'observations': [], 'attempts': []})
    history = problem['observations']
    if any(item['execution'] == observation['execution'] for item in history):
        return  # A poll is not a second execution.
    if problem.get('resolvedByExecution'):
        problem.setdefault('resolutions', []).append({'execution': problem.pop('resolvedByExecution'), 'revision': problem.pop('resolvedRevision')})
    observed_progress = set(progress)
    prior = {value for p in related(workflow, identity) for value in p.get('progress', [])}
    targeted = attempts_for(workflow, identity)
    prior_history = any(p['observations'] for p in related(workflow, identity))
    if prior_history and targeted:
        last_attempt = targeted[-1]
        if last_attempt.get('acceptedRevision') is not None and observation['revision'] >= last_attempt['acceptedRevision']:
            problem['noProgress'] = problem.get('noProgress', False) or not bool(observed_progress - prior)
            if any(p.get('absentAfterRepair') for p in related(workflow, identity)):
                problem['regression'] = True
    problem['progress'] = sorted(prior | observed_progress)
    history.append(observation)
    problem.pop('absentAfterRepair', None)


def reserve(workflow, request_id, problem_ids):
    existing = [item for item in workflow['attempts'].values() if item['requestId'] == request_id]
    if existing:
        if existing[0]['problemIds'] != sorted(problem_ids):
            raise ValueError('request retry changed problem set')
        return existing[0]
    result = decision(workflow, problem_ids)
    if result != 'REPAIR_ALLOWED':
        raise ValueError('repair policy: ' + result)
    identity = uuid.uuid4().hex
    attempt = {'attemptId': identity, 'requestId': request_id, 'problemIds': sorted(problem_ids),
               'stage': 'RESERVED', 'staticFailures': 0}
    workflow['attempts'][identity] = attempt
    workflow['reserved'] = workflow.get('reserved', 0) + 1
    for problem in problem_ids:
        workflow['problems'][problem]['attempts'].append(identity)
    return attempt
