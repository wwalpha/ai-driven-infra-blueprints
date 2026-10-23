#!/usr/bin/env python3
"""Explicit properties authority, runtime derivation and raw input safety."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from unittest.mock import patch

from model.format import parse
from model.format import patch as patch_properties
from model.sources import _publish_transaction as _publish_transaction
from model.sources import model_paths as model_paths
from model.sources import publication_lock as publication_lock
from support.it_case_receipt import module_complete
from support.producer_identifier_reference_fixtures import (
    FileReads,
    Path,
    affected,
    load_model,
    rejected,
    serialize,
    setup,
    tempfile,
    trace_model,
    write_model,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory).resolve()
    setup(root, ['s3'], ['S3.Bucket'])
    path = root / 'model/preview/team/example.properties'
    desired = {'desired.resource.017.resourceType': 'S3.Bucket', 'desired.resource.017.logicalId': 'S3_Bucket_001', 'desired.service.identity.lastAllocated': '{"S3.Bucket":1}',
               'desired.row.017-023.property': 'S3.Bucket.BucketName', 'desired.row.017-023.value': '`desired-name`',
               'desired.row.017-023.comment': '観測値の説明'}
    write_model(path, desired)
    key = 'observed.row.017-023.value'
    assert load_model(path).authoritative == desired
    assert key not in load_model(path).values
    for value in ('false', '0', '', 'null', '`PENDING_DEPLOY`'):
        candidate = {**desired, key: value}
        text = serialize(candidate)
        reads = FileReads()
        reads.read(path)
        with publication_lock(root) as journal:
            reads.verify()
            _publish_transaction(root, {path: text}, (), journal)
        model = load_model(path)
        assert model.authoritative[key] == value and model.values[key] == value
        for field in ('property', 'comment'):
            metadata = key.removesuffix('value') + field
            source = 'desired.' + metadata.removeprefix('observed.')
            assert model.values[metadata] == desired[source] and metadata not in model.authoritative
            assert trace_model(path, metadata)['derivedFrom'] == source
        assert model.locations[key][0] == path
        for _ in range(2):
            before = path.read_bytes()
            with publication_lock(root) as journal:
                _publish_transaction(root, {path: text}, (), journal)
            assert path.read_bytes() == before
    original = path.read_bytes()
    for invalid in (False, 0, None):
        rejected(lambda *, invalid=invalid: serialize({**desired, key: invalid}), 'strings')
    for invalid in ({key: 'x', 'observed.row.017-023.property': 'wrong'}, {'observed.row.999-001.value': 'x'},
                    {'observed.row.017-023.state': 'unknown'}):
        path.write_text(serialize({**desired, **invalid}))
        try:
            load_model(path)
        except (ValueError, OSError):
            pass
        else:
            raise AssertionError('invalid observed metadata or owner accepted')
    path.write_text('# model-format: 2\n{')
    rejected(lambda: load_model(path), 'invalid')
    path.write_bytes(original)
    with patch.object(Path, 'read_bytes', side_effect=PermissionError('denied')):
        rejected(lambda: load_model(path), 'denied')
    marker = root / 'marker'
    marker.write_text('before')
    def interrupted(output):
        marker.write_text('partial')
        raise OSError('interrupted')
    with publication_lock(root) as journal, patch('sync_files.save_files', side_effect=interrupted):
        rejected(lambda: _publish_transaction(root, {marker: 'after'}, {path}, journal), 'interrupted')
    assert path.read_bytes() == original and marker.read_text() == 'before'
    for _ in range(2):
        with publication_lock(root) as journal:
            _publish_transaction(root, {path: serialize(desired)}, (), journal)
        assert load_model(path).authoritative == desired and key not in load_model(path).values
    reads = FileReads()
    reads.read(path)
    external = path.read_bytes() + b'# concurrent observed edit\n'
    path.write_bytes(external)
    rejected(reads.verify, 'input changed')
    assert path.read_bytes() == external
    for key in ('desired.resource.017.resourceType', 'desired.resource.017.logicalId', 'desired.row.017-023.property'):
        path.write_text(serialize({name: value for name, value in desired.items() if name != key}))
        try:
            load_model(path)
        except ValueError:
            pass
        else:
            raise AssertionError('missing fixed owner/field accepted: ' + key)
    path.write_text(serialize(desired))
    assert load_model(path).authoritative == desired
print('Compact sources: PASS (false/zero/empty/null/missing observed; derived metadata; fixed owner; malformed/I/O rejection; atomic rollback; raw snapshot; idempotence)')

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory).resolve()
    setup(root, ['s3'], ['S3.Bucket'], ('preview', 'release', 'independent'))
    values = {'desired.resource.017.resourceType': 'S3.Bucket', 'desired.resource.017.logicalId': 'S3_Bucket_001', 'desired.service.identity.lastAllocated': '{"S3.Bucket":1}',
              'desired.row.017-023.property': 'S3.Bucket.BucketName', 'desired.row.017-023.value': '`fixed-name`',
              'desired.row.017-023.comment': '環境に明示した説明'}
    paths = [root / 'model' / env / 'team/shared.properties' for env in ('preview', 'release', 'independent')]
    for path in paths:
        write_model(path, values)
    before = {path: path.read_bytes() for path in paths}
    explicit = paths[0]
    explicit.write_text(patch_properties(parse(explicit.read_text()), {'desired.row.017-023.comment': 'この環境だけ変更'}))
    for path in paths:
        after = load_model(path).authoritative
        assert after['desired.resource.017.logicalId'] == values['desired.resource.017.logicalId'] and set(after) == set(values)
        assert (path.read_bytes() != before[path]) == (path == explicit)
    assert affected(root, [explicit.relative_to(root)]) == {('preview', 'team', 'shared')}
print('Explicit environment sources: PASS (no shared expansion; fixed identity/keys retained; only explicitly edited environment changes)')

module_complete(__file__)
