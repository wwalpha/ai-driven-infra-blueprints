#!/usr/bin/env python3
"""Observed ownership and real generated journal recovery, without a Project/controller."""

import base64
import copy
import json
import sys
import tempfile
from functools import partial
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from deploy import observed_resume as M
from support.pytest_cli import run
from task_contract_core import selected_task

from model import sources

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def read_authority(source, *args):
    return {source: source.read_bytes()}


def verify_owner(actual, order, partial_bytes, root, plan, record):
    assert {root / p: (root / p).read_bytes() for p in partial_bytes} == {root / p: raw for p, raw in partial_bytes.items()}
    actual(root, plan, record)
    order.append('owner')


def restore_owned(actual, order, originals):
    assert order == ['owner']
    actual(originals)
    order.append('restored')


def check_generated_journal_recovery_uses_observed_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    root = tmp_path / 'repo'
    source = root / 'model/dev/team/service.properties'
    source.parent.mkdir(parents=True)
    old = b'# model-format: 2\ndesired.row.001-001.value=`desired`\nobserved.row.001-001.value=`old`\n'
    new = old.replace(b'`old`', b'`new`')
    source.write_bytes(new)
    view, artifact = 'docs/designs/dev/team/service.md', 'docs/designs/dev/team/service/policy.json'
    originals = {view: b'old design\n', artifact: b'{"old":true}\n'}
    outputs = {view: 'new design\n', artifact: '{"new":true}\n'}
    partial_bytes = {view: outputs[view].encode(), artifact: originals[artifact]}
    for relative, raw in partial_bytes.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    relative = source.relative_to(root).as_posix()
    task = root / 'tasks/deploy.md'
    task.parent.mkdir()
    listed = ''.join('- `' + p + '`\n' for p in ['tasks/deploy.md', relative, view, artifact])
    text = ('## Task contract\n- Task status: `running`\n- Task type: `infrastructure`\n'
            '- Infrastructure phase: `deploy`\n- AWS API execution: `allowed`\n- Deploy/apply: `allowed`\n'
            '- Target environment: `dev`\n- Target AWS account: `123456789012`\n- Deployment scope: `A`\n'
            '## Modified files\n' + listed + '## Allowed paths\n' + listed)
    task.write_text(text, encoding='utf-8')
    state = {'status': 'SUCCESS', 'stackId': 'stack', 'changeSetId': 'change', 'clientToken': 'token',
             'changeDigest': 'digest', 'executionEvidence': {'StackId': 'stack', 'ChangeSetId': 'change',
             'clientToken': 'token', 'changeDigest': 'digest', 'inputDigest': 'unit'}}
    session = {'repository': str(root), 'taskFile': 'tasks/deploy.md', 'taskDigest': M.task_digest(text),
               'inputDigest': 'inputs', 'executionDigest': 'execution', 'infraManifest': {},
               'unitDigests': {'A': 'unit'}, 'states': {'A': state}, 'modelInputManifest': M.manifest({relative: old})}
    with selected_task(root, 'tasks/deploy.md'):
        session['pendingObserved'] = {'identity': M._identity(root, session, {}, 'dev', 'team'),
            'evidence': M.evidence(session['states'], ['A']), 'beforeManifest': M.manifest({relative: old}),
            'afterManifest': M.manifest({relative: new}), 'outputs': {relative: new.decode()},
            'originals': {relative: base64.b64encode(old).decode()}, 'directories': ['model/dev/team'],
            'inventory': [relative], 'stage': 'MODEL_PUBLISHED', 'services': ['service'],
            'generated': {'groups': {view: [view, artifact]},
                'originals': {p: base64.b64encode(raw).decode() for p, raw in originals.items()},
                'outputs': outputs, 'stage': 'CANDIDATE'}}
        path = tmp_path / 'session.json'
        path.write_text(json.dumps(session), encoding='utf-8')
        saved = json.loads(path.read_text(encoding='utf-8'))
        plan, evidence = copy.deepcopy(saved['pendingObserved']), copy.deepcopy(saved['states']['A']['executionEvidence'])
        with sources.publication_lock(root) as journal:
            pass
        journal.write_text(json.dumps({'root': str(root), 'originals': plan['generated']['originals']}), encoding='utf-8')
        order = []
        verify = partial(verify_owner, M.verify_generated_journal, order, partial_bytes)
        restore = partial(restore_owned, sources.sync_files.restore_files, order)
        with patch.object(M, 'authority_snapshot', side_effect=partial(read_authority, source)), \
             patch.object(M, 'verify_generated_journal', side_effect=verify), \
             patch.object(sources.sync_files, 'restore_files', side_effect=restore):
            assert M.reconcile(root, saved, {}, 'dev', 'team') == 'MODEL_PUBLISHED'
        assert order == ['owner', 'restored'] and not journal.exists()
        assert {p: (root / p).read_bytes() for p in originals} == originals
        assert source.read_bytes() == new and saved['pendingObserved'] == plan
        assert saved['states']['A']['executionEvidence'] == evidence


if __name__ == '__main__':
    raise SystemExit(run(__file__))
