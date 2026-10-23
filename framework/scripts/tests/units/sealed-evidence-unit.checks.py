"""Legacy sealed bytes, trust boundaries, and independent workflow ownership."""

import ast
import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import worktree_state
from support.pytest_cli import run
from utils import sealed_evidence as evidence
from utils.json_format import document_sha256

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

LEGACY = '{"payload":{"z":"日本語","a":[1,true,null,{"x":1.25}]},"signature":"8570b820b830d60c2b83fbe8e475134c501a35f92985281d4061de4a3f171be4"}\n'


def check_legacy_bytes(tmp_path):
    value = {'z': '日本語', 'a': [1, True, None, {'x': 1.25}]}
    file = tmp_path / 'legacy.json'
    file.write_text(LEGACY, encoding='utf-8')
    with patch.object(evidence, 'seal_key', return_value=bytes(range(32))):
        assert evidence.read_sealed(tmp_path, file) == value
        assert evidence.sealed(tmp_path, value) == LEGACY
        evidence.write_sealed(tmp_path, file, value)
        assert file.read_bytes() == LEGACY.encode('utf-8')
    # Original digest expression; ordering and non-ASCII serialization remain exact.
    for item in (value, None, {}, [], '/fixed/root', '/fixed/home', {'b': 1, 'a': 2}):
        old = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        assert document_sha256(item) == old


@pytest.mark.parametrize('problem', ['payload', 'key', 'missing', 'extra', 'signature', 'null', 'list', 'invalid'])
def check_rejected_envelopes(tmp_path, problem):
    file = tmp_path / 'receipt.json'
    envelope = json.loads(LEGACY)
    key = bytes(range(32))
    if problem == 'payload':
        envelope['payload']['z'] = 'tampered'
    elif problem == 'key':
        key = b'x' * 32
    elif problem == 'missing':
        del envelope['signature']
    elif problem == 'extra':
        envelope['extra'] = True
    elif problem == 'signature':
        envelope['signature'] = 1
    elif problem == 'null':
        envelope = None
    elif problem == 'list':
        envelope = []
    file.write_text('{' if problem == 'invalid' else json.dumps(envelope), encoding='utf-8')
    with patch.object(evidence, 'seal_key', return_value=key), pytest.raises(ValueError):
        evidence.read_sealed(tmp_path, file)


def check_store_and_key(tmp_path):
    with patch.object(evidence.tempfile, 'gettempdir', return_value=str(tmp_path)), patch.object(evidence.Path, 'home', return_value=Path('/fixed/home')):
        root = Path('/fixed/root')
        store = evidence.evidence_store(root)
        assert store == tmp_path / 'blueprint-import-f658928b4bb1be1b' / '6eed197c06336b46e5d3929894a319660ead27bb44c141a805f932c03d7efeab'
        other = evidence.evidence_store(tmp_path / 'other', create=False)
        assert other != store and not other.exists()
        key = evidence.seal_key(root)
        assert len(key) == 32 and evidence.seal_key(root) == key
        assert evidence.seal_key(tmp_path / 'other') != key
        if os.name != 'nt':
            assert store.stat().st_mode & 0o077 == 0
            assert (store / 'seal.key').stat().st_mode & 0o077 == 0
        (store / 'seal.key').write_bytes(b'bad')
        with pytest.raises(ValueError, match='invalid local evidence seal'):
            evidence.seal_key(root)


@pytest.mark.parametrize('kind', ['receipt', 'key', 'directory'])
def check_symlink_rejection(tmp_path, kind):
    with patch.object(evidence.tempfile, 'gettempdir', return_value=str(tmp_path)):
        root = tmp_path / 'root'
        store = evidence.evidence_store(root)
        file = store / 'receipt.json'
        target = tmp_path / 'target'
        target.write_text(LEGACY, encoding='utf-8')
        if kind == 'receipt':
            file.symlink_to(target)
            with pytest.raises(ValueError, match='symlink'):
                evidence.read_sealed(root, file)
            with pytest.raises(ValueError, match='symlink'):
                evidence.write_sealed(root, file, {})
            assert target.read_text(encoding='utf-8') == LEGACY
        elif kind == 'key':
            (store / 'seal.key').symlink_to(target)
            with pytest.raises(ValueError, match='unsafe'):
                evidence.seal_key(root)
        else:
            store.rmdir()
            directory = tmp_path / 'redirect'
            directory.mkdir()
            store.symlink_to(directory, target_is_directory=True)
            with pytest.raises(ValueError, match='unsafe'):
                evidence.evidence_store(root)


def check_private_permissions(tmp_path):
    if os.name == 'nt':
        return
    with patch.object(evidence.tempfile, 'gettempdir', return_value=str(tmp_path)):
        store = evidence.evidence_store(tmp_path)
        evidence.seal_key(tmp_path)
        key = store / 'seal.key'
        key.chmod(0o644)
        with pytest.raises(ValueError, match='unsafe'):
            evidence.seal_key(tmp_path)
        key.chmod(0o600)
        store.chmod(0o755)
        with pytest.raises(ValueError, match='private'):
            evidence.evidence_store(tmp_path)
        store.chmod(0o700)
        with patch.object(evidence.os, 'getuid', return_value=os.getuid() + 1):
            with pytest.raises(ValueError, match='private'):
                evidence.evidence_store(tmp_path)


def check_atomic_failure(tmp_path):
    file = tmp_path / 'receipt.json'
    file.write_text(LEGACY, encoding='utf-8')
    with patch.object(evidence, 'seal_key', return_value=bytes(range(32))), patch('utils.file_operations.os.replace', side_effect=OSError('failed')):
        with pytest.raises(OSError, match='failed'):
            evidence.write_sealed(tmp_path, file, {'new': True})
    assert file.read_text(encoding='utf-8') == LEGACY
    assert list(tmp_path.iterdir()) == [file]


@pytest.mark.parametrize('problem', ['none', 'task', 'root', 'merged', 'owner'])
def check_ownership(tmp_path, problem):
    name = 'tasks/example.md'
    state = {'task_file': name, 'worktree': str(tmp_path), 'merged': None}
    owner = tmp_path
    if problem == 'task':
        state['task_file'] = 'tasks/other.md'
    elif problem == 'root':
        state['worktree'] = str(tmp_path / 'other')
    elif problem == 'merged':
        state['merged'] = 'commit'
    elif problem == 'owner':
        owner = tmp_path / 'other'
    with patch.object(worktree_state, 'load', return_value=(None, None, None, state)), patch.object(worktree_state, 'task_worktree', return_value=owner):
        if problem == 'none':
            assert worktree_state.managed_task_state(tmp_path, name) is state
        else:
            with pytest.raises(ValueError):
                worktree_state.managed_task_state(tmp_path, name)


def check_dependency_boundaries():
    scripts = Path(__file__).resolve().parents[2]
    paths = [(file, ('import_guard',)) for file in (scripts / 'deploy').glob('*.py')]
    paths += [(scripts / 'utils/sealed_evidence.py', ('import_guard', 'model', 'deploy', 'worktree', 'task_contract')),
              (scripts / 'worktree_state.py', ('import_guard', 'model', 'deploy'))]
    for file, forbidden in paths:
        tree = ast.parse(file.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
            assert not any(name.startswith(prefix) for name in names for prefix in forbidden), file
    for file in (scripts / 'import_guard.py', scripts / 'utils/import_evidence.py'):
        tree = ast.parse(file.read_text(encoding='utf-8'))
        assert not any(isinstance(node, ast.FunctionDef) and node.name in {'seal_key', 'sealed', 'read_sealed', 'write_sealed', 'managed_task_state'} for node in ast.walk(tree))


if __name__ == '__main__':
    raise SystemExit(run(__file__))
