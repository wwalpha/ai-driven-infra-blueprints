"""Build a manual-copy inventory from committed Framework blobs; never copy a consumer."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOTS = ('framework', '.agents', 'AGENTS.md', 'README.md', '.github/workflows/framework-it.yml')


def _git(root, *arguments, data=None):
    result = subprocess.run(['git', *arguments], cwd=root, input=data, capture_output=True)
    if result.returncode:
        raise ValueError('distribution Git read failed: ' + result.stderr.decode('utf-8').strip())
    return result.stdout


def _inventory(root, revision):
    if not isinstance(revision, str) or re.fullmatch('[0-9a-f]{40}', revision) is None:
        raise ValueError('distribution requires a full fixed commit hash')
    actual = _git(root, 'rev-parse', '--verify', revision + '^{commit}').decode('ascii').strip()
    if actual != revision:
        raise ValueError('distribution revision is not the fixed commit')
    entries = {}
    for entry in _git(root, 'ls-tree', '-r', '-z', revision, '--', *ROOTS).split(b'\0'):
        if not entry:
            continue
        metadata, raw_path = entry.split(b'\t', 1)
        mode, kind, blob = metadata.decode('ascii').split()
        path = raw_path.decode('utf-8')
        if kind != 'blob' or mode not in {'100644', '100755'} or any(part in {'.', '..'} for part in Path(path).parts):
            raise ValueError('unsupported distribution file type/path: ' + path)
        entries[path] = {'blob': blob, 'mode': mode}
    blobs = sorted({entry['blob'] for entry in entries.values()})
    stream = _git(root, 'cat-file', '--batch', data=''.join(blob + '\n' for blob in blobs).encode('ascii'))
    hashes, offset = {}, 0
    for blob in blobs:
        end = stream.index(b'\n', offset)
        actual, kind, length = stream[offset:end].decode('ascii').split()
        size = int(length)
        start = end + 1
        content = stream[start:start + size]
        if actual != blob or kind != 'blob' or len(content) != size or stream[start + size:start + size + 1] != b'\n':
            raise ValueError('distribution blob framing differs from the fixed revision')
        hashes[blob] = {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': size}
        offset = start + size + 1
    if offset != len(stream):
        raise ValueError('distribution contains unexpected blob data')
    return {path: {'revision': revision, 'gitMode': entry['mode'], **hashes[entry['blob']]}
            for path, entry in sorted(entries.items())}


def distribution_manifest(root, baseline, revision, destination):
    root, destination = Path(root).resolve(), Path(destination).absolute()
    if destination.resolve().is_relative_to(root) or destination.exists() or any(
            path.is_symlink() for path in (destination, *destination.parents)):
        raise ValueError('distribution manifest requires a new external non-symlink destination')
    before, after = _inventory(root, baseline), _inventory(root, revision)
    required = {'AGENTS.md', 'README.md', 'framework/scripts/model/cli.py', 'framework/scripts/requirements.txt',
                'framework/scripts/tests/run_it.py', 'framework/scripts/tests/CASES.md'}
    if not required <= after.keys() or not any(path.startswith('framework/scripts/tests/support/') for path in after):
        raise ValueError('distribution revision lacks the matching runtime/tests/support/dependencies')
    changes = []
    for path in sorted(before.keys() | after.keys()):
        old, new = before.get(path), after.get(path)
        if old is not None and new is not None and (old['sha256'], old['gitMode']) == (new['sha256'], new['gitMode']):
            continue
        changes.append({'path': path, 'action': 'add' if old is None else 'delete' if new is None else 'overwrite',
                        'before': old, 'after': new})
    result = {'manifestVersion': 1, 'modelFormat': 2, 'baselineRevision': baseline, 'frameworkRevision': revision,
              'changes': changes, 'files': [{'path': path, **record} for path, record in after.items()],
              'copyPerformed': False}
    from sync_files import atomic_files
    atomic_files({destination: json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + '\n'},
                 staging_directory=destination.parent)
    return result
