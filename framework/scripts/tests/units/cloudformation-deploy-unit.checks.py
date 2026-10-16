#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.cloudformation_deploy_fixtures import *

def check_scheduler():
    # Cases 1 and 4: order barrier, including an early A completion.
    scoped = units(10, 20, 30)
    state, fake = states(scoped), Fake()
    assert finish(scoped, 3, state, fake) == "COMPLETE"
    assert starts(fake) == ["A", "B", "C"]
    for previous, following in (("A", "B"), ("B", "C")):
        assert fake.events.index(("poll", previous, "CREATE_COMPLETE")) < next(i for i, e in enumerate(fake.events) if e[:2] == ("start", following))
    scoped = units(10, 10, 20)
    state, fake = states(scoped), Fake({"B": ["CREATE_IN_PROGRESS"] * 3 + ["CREATE_COMPLETE"]})
    assert scheduler.run_group(scoped, 2, state, fake, sleep=lambda _: None) == "GROUP_COMPLETE"
    assert starts(fake) == ["A", "B"]
    assert state["C"]["status"] == "NOT_STARTED"
    assert finish(scoped, 2, state, fake) == "COMPLETE"
    assert fake.events.index(("poll", "B", "CREATE_COMPLETE")) < next(i for i, e in enumerate(fake.events) if e[:2] == ("start", "C"))
    # Cases 2 and 3: slot reuse before B finishes, no template deduplication.
    scoped = units(10, 10, 10)
    state, fake = states(scoped), Fake({"A": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"],
                                        "B": ["CREATE_IN_PROGRESS"] * 4 + ["CREATE_COMPLETE"]})
    assert finish(scoped, 2, state, fake) == "COMPLETE"
    assert fake.peak == 2 and starts(fake) == ["A", "B", "C"]
    assert next(i for i, e in enumerate(fake.events) if e[:2] == ("start", "C")) < fake.events.index(("poll", "B", "CREATE_COMPLETE"))
    assert state["A"]["changeSetId"] != state["B"]["changeSetId"]
    assert ("prepare", "A", "app.yaml", "a.json") in fake.events
    assert ("prepare", "B", "app.yaml", "b.json") in fake.events
    # Case 5: detect failure while B runs, drain B, keep C/D unstarted.
    scoped = units(10, 10, 10, 20)
    state, fake = states(scoped), Fake({"A": ["CREATE_IN_PROGRESS", "ROLLBACK_IN_PROGRESS", "ROLLBACK_COMPLETE"],
                                        "B": ["CREATE_IN_PROGRESS"] * 3 + ["CREATE_COMPLETE"]})
    assert finish(scoped, 2, state, fake) == "STOPPED"
    assert [s["status"] for s in state.values()] == ["FAILED", "SUCCESS", "NOT_STARTED", "NOT_STARTED"]
    assert starts(fake) == ["A", "B"] and not fake.running
    assert scheduler.run_group(scoped, 2, state, fake) == "STOPPED"
    # Restart after a failure was saved but another execution was still running.
    state = states(scoped)
    state["A"]["status"], state["B"]["status"] = "FAILED", "RUNNING"
    fake = Fake({"B": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]})
    fake.running = {"B"}
    assert finish(scoped, 2, state, fake) == "STOPPED"
    assert state["B"]["status"] == "SUCCESS" and not fake.running and not starts(fake)
    # A blocker during B preparation stops queueing and drains A.
    state, fake = states(scoped), Fake({"A": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]}, blocked={"B"})
    assert finish(scoped, 2, state, fake) == "STOPPED"
    assert [s["status"] for s in state.values()] == ["READY", "BLOCKED", "NOT_STARTED", "NOT_STARTED"]
    assert starts(fake) == [] and not fake.running
    # Read errors stop queueing but do not claim terminal failure.
    state, fake = states(scoped), Fake({"A": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]})
    poll, failed = fake.poll, [False]
    def transient(unit, state):
        if not failed[0]:
            failed[0] = True
            raise M.Blocked("read access temporarily unavailable")
        return poll(unit, state)
    fake.poll = transient
    assert finish(scoped, 2, state, fake) == "STOPPED"
    assert starts(fake) == ["A", "B"] and state["A"]["status"] == "SUCCESS"


    # Intent persistence failure cannot reach execute; submission loss drains without retrying.
    selected = units(10, 10)
    for boundary in ('intent', 'submitted', 'response'):
        state, fake, trace = states(selected), Fake(), []
        execute = fake.execute
        def save():
            trace.append(('save', state['A']['status'], state['A'].get('clientToken')))
            if state['A']['status'] == 'RUNNING' and (boundary == 'intent' or
                    boundary == 'response' and starts(fake)):
                raise OSError('injected persistence failure')
        def submit(unit, snapshot):
            assert trace[-1] == ('save', 'RUNNING', snapshot['clientToken'])
            execute(unit, snapshot)
            if boundary == 'submitted':
                raise TimeoutError('injected uncertain submission')
        fake.execute = submit
        try:
            result = scheduler.run_group(selected, 1, state, fake, save, sleep=lambda _: None)
            assert boundary == 'submitted' and result == 'STOPPED'
        except OSError:
            assert boundary != 'submitted'
        assert trace and state['A'].get('clientToken')
        assert starts(fake) == ([] if boundary == 'intent' else ['A'])
        assert state['B']['status'] == 'NOT_STARTED'
        if boundary != 'intent':
            token = state['A']['clientToken']
            assert scheduler.run_group(selected, 1, state, fake, sleep=lambda _: None, drain_only=True) == 'STOPPED'
            assert state['A']['status'] == 'SUCCESS' and state['A']['clientToken'] == token
            assert starts(fake) == ['A']
    # Worker writes are reflected only by the controller, including error snapshots.
    from deployment.scheduler import read_parallel
    state = states(selected)
    def read(unit, snapshot):
        snapshot['readEvidence'] = unit['name']
        assert 'readEvidence' not in state[unit['name']]
        raise M.Blocked('injected read loss')
    results = read_parallel(selected, state, read, 2)
    assert len(results) == 2 and all(error and snapshot['readEvidence'] == unit['name']
                                  for unit, snapshot, _, error in results)
    assert all('readEvidence' not in item for item in state.values())


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
