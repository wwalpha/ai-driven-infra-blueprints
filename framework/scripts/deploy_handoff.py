#!/usr/bin/env python3
"""Explicit supervising-LLM offline commands; never starts another Task or calls AWS."""
import argparse
import json
from pathlib import Path
from deploy import handoff
from cloudformation_inputs import Blocked
from deploy.contracts import task_digest
from task_contract import selected_task, task_path
from utils.json_format import fingerprint


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('diagnose', 'request', 'budget', 'migrate', 'close', 'recover-session'))
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--repository-root', type=Path, default=Path.cwd())
    parser.add_argument('--diagnosis', type=Path)
    parser.add_argument('--problem', action='append', default=[])
    parser.add_argument('--path', action='append', default=[])
    parser.add_argument('--expectation', type=Path, help='non-secret structured expected Resource/operation/status')
    parser.add_argument('--additional-cycles', type=int)
    parser.add_argument('--old-execution-digest')
    parser.add_argument('--new-execution-digest')
    parser.add_argument('--acknowledge-legacy-cycles', type=int)
    parser.add_argument('--authorization', help='explicit Human decision, without secrets')
    args = parser.parse_args(argv)
    root = args.repository_root.resolve()
    path = handoff.external(root, args.state)
    try:
        with handoff.locked(path):
            if args.command == 'recover-session':
                selected = task_path(root).relative_to(root).as_posix()
                session = handoff.recover_session(root, path, selected)
                print(json.dumps({'result': 'RECOVERED', 'workflowId': session['workflow']['workflowId']}))
                return 0
            session = json.loads(path.read_text(encoding='utf-8'))
            handoff.restore(root, path, session)
            if session['repository'] != str(root):
                raise Blocked('session belongs to a different parent Worktree')
            with selected_task(root, session['taskFile']):
                contract = task_path(root, required=True).read_text(encoding='utf-8')
                if args.command == 'migrate':
                    from deploy.resume import migrate
                    migrate(root, session, args)
                    handoff.bind(root, path, session)
                    value = {'result': 'MIGRATED', 'version': session['version']}
                else:
                    if task_digest(contract) != session['taskDigest']:
                        raise Blocked('original Task contract changed')
                    handoff.bind(root, path, session)
                    if args.command in {'diagnose', 'request'}:
                        handoff.verify_inputs(root, session)
                    if args.command == 'diagnose':
                        if not args.diagnosis:
                            raise Blocked('diagnose requires --diagnosis')
                        result = handoff.diagnose(root, session, json.loads(args.diagnosis.read_text(encoding='utf-8')))
                        value = {'result': result, 'problemIds': session['workflow'].get('currentProblemIds', [])}
                    elif args.command == 'request':
                        if not args.expectation:
                            raise Blocked('request requires a structured --expectation')
                        expectation = json.loads(args.expectation.read_text(encoding='utf-8'))
                        if not isinstance(expectation, list) or not expectation:
                            raise Blocked('expected redeploy observations missing')
                        for item in expectation:
                            if set(item) != {'stack', 'resourcePath', 'operation', 'status'} or item['stack'] not in session['states'] or item['status'] not in {'CREATE_COMPLETE', 'UPDATE_COMPLETE', 'IMPORT_COMPLETE', 'SUCCEEDED'}:
                                raise Blocked('expectation must identify the target operation success')
                        pending = handoff.issue_request(root, path, session, args.problem, args.path, expectation)
                        attempt = session['workflow']['attempts'][pending['attemptId']]
                        if attempt.get('expectation') not in (None, expectation):
                            raise Blocked('request retry changed expected result')
                        attempt['expectation'] = expectation
                        value = {'result': 'REQUESTED', 'requestId': pending['requestId'], 'attemptId': pending['attemptId'],
                                 'next': 'worktree_task.py repair-checkpoint --task-id ' + Path(session['taskFile']).stem + ' --state ' + str(path)}
                    elif args.command == 'budget':
                        if not args.authorization or not args.additional_cycles or args.additional_cycles <= 0:
                            raise Blocked('additional budget needs explicit Human authorization and a positive cycle count')
                        workflow = session['workflow']
                        workflow['budget'] += args.additional_cycles
                        workflow.setdefault('budgetExtensions', []).append({'cycles': args.additional_cycles, 'authorizationDigest': fingerprint(args.authorization)})
                        value = {'result': 'BUDGET_EXTENDED', 'budget': workflow['budget'], 'reserved': workflow['reserved']}
                    else:
                        if not args.authorization or any(s['status'] == 'RUNNING' or s.get('cleanupStatus') == 'DELETE_INTENT' or
                                s['status'] == 'SUCCESS' and not s.get('observedSynced') for s in session['states'].values()):
                            raise Blocked('explicit close requires drained, synchronized state')
                        pending = session.pop('pendingRequest', None)
                        if pending:
                            session['workflow']['attempts'][pending['attemptId']].update(stage='ABANDONED', closedRequest=pending)
                        session['workflow']['status'] = 'CLOSED'
                        # Keep binding and history. A new Task is required for a genuinely new workflow.
                        value = {'result': 'CLOSED', 'retained': str(path)}
            handoff.save(path, session)
        print(json.dumps(value, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, Blocked) as error:
        print('Deploy handoff: BLOCKED (' + str(error) + ')')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
