#!/usr/bin/env python3
"""Explicit properties authority, runtime derivation and raw input safety."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
from unittest.mock import patch
from support.it_case_receipt import module_complete
from support.producer_identifier_reference_fixtures import *
from model.sources import model_paths, publication_lock, _publish_transaction
from model.format import parse, patch as patch_properties

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory).resolve()
    setup(root, ['s3'], ['S3.Bucket'], ('preview', 'release', 'prod'))
    path = root / 'model/preview/team/example.properties'
    values = {'desired.service.example.serviceId': 'example', 'desired.resource.017.resourceType': 'S3.Bucket',
              'desired.resource.017.anchor': 's3-fixed', 'desired.resource.017.cfn-logicalId': 'fixed-stack-FixedBucket',
              'desired.row.017-023.property': 'S3.Bucket.BucketName', 'desired.row.017-023.value': '`fixed-name`',
              'desired.row.017-023.comment': '合成設定'}
    assert model_paths(root) == []
    assert not path.exists(), 'registered targets never create Model files'
    write_model(path, values)
    assert model_paths(root) == [path] and model_paths(root, 'prod') == []
    for _ in range(2):
        raw = path.read_bytes()
        assert load_model(path).authoritative == values and path.read_bytes() == raw
    raw = path.read_bytes()
    path.unlink()
    assert model_paths(root) == []
    rejected(lambda: load_model(path), 'example.properties')
    path.write_bytes(raw)
    for text, phrase in [(raw.decode().replace('# model-format: 2', '# model-format: 99'), 'unsupported Model format'),
                         (raw.decode() + 'desired.extra=unknown\n', 'invalid Model key'),
                         (raw.decode() + 'desired.row.017-023.value=duplicate\n', 'duplicate')]:
        path.write_text(text)
        rejected(lambda: load_model(path), phrase)
    path.write_bytes(raw)
    old, dependencies = design_source_digest(path), dependency_hashes(path)
    path.write_bytes(raw + b'# changed input\n')
    assert design_source_digest(path) == old and dependency_hashes(path) != dependencies
    assert affected(root, [path.relative_to(root)]) == {('preview', 'team', 'example')}
    path.write_bytes(raw)
    other = root / 'model/release/team/example.properties'
    write_model(other, values)
    assert set(model_paths(root)) == {path, other}
    assert affected(root, [path.relative_to(root)]) == {('preview', 'team', 'example')}
    assert load_model(other).authoritative == values and design_source_digest(path) == old
    legacy = root / 'model/parameters'
    legacy.mkdir()
    (legacy / 'parameters.json').write_text('{}')
    rejected(lambda: load_model(path), 'legacy')
    (legacy / 'parameters.json').unlink(); legacy.rmdir()
    with patch.object(Path, 'read_bytes', side_effect=PermissionError('denied')):
        rejected(lambda: load_model(path), 'denied')
print('Runtime Models: PASS (discovery; no auto-generation; fixed identity; read idempotence; missing/corrupt/legacy rejection; raw snapshot invalidation; independent environments)')

module_complete(__file__)
