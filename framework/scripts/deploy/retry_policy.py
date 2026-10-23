"""Pure repair decisions. Static validation and file changes are never AWS progress."""
MAX_PROBLEM_CYCLES = 3
DEFAULT_BUDGET = 20


def decision(workflow, problem_ids):
    if workflow.get('legacyUncertain'):
        return 'WAITING_HUMAN'
    if workflow.get('reserved', 0) >= workflow.get('budget', DEFAULT_BUDGET):
        return 'WAITING_HUMAN'
    for identity in problem_ids:
        problem = workflow['problems'][identity]
        attempts = problem.get('attempts', [])
        if len(attempts) >= MAX_PROBLEM_CYCLES:
            return 'WAITING_HUMAN'
        if problem.get('regression') or problem.get('noProgress'):
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
    prior = set(problem.get('progress', []))
    targeted = problem['attempts']
    if history and targeted:
        last_attempt = workflow['attempts'][targeted[-1]]
        if last_attempt.get('acceptedRevision') is not None and observation['revision'] >= last_attempt['acceptedRevision']:
            problem['noProgress'] = not bool(observed_progress - prior)
            if problem.get('absentAfterRepair'):
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
    import uuid
    identity = uuid.uuid4().hex
    attempt = {'attemptId': identity, 'requestId': request_id, 'problemIds': sorted(problem_ids),
               'stage': 'RESERVED', 'staticFailures': 0}
    workflow['attempts'][identity] = attempt
    workflow['reserved'] = workflow.get('reserved', 0) + 1
    for problem in problem_ids:
        workflow['problems'][problem]['attempts'].append(identity)
    return attempt
