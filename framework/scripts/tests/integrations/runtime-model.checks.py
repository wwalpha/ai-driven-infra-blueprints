#!/usr/bin/env python3
"""Runtime-only discovery, required authorities and input invalidation."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

import copy
import tempfile
from unittest.mock import patch
from model_files import load_model
from model_templates import model_paths, source_paths, create_service, affected, design_source_digest, json_text
from support.model_sources import write_model, snapshot_model

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def rejected(call):
    try:
        call()
    except (ValueError, OSError):
        return
    raise AssertionError('invalid runtime authority accepted')


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory).resolve()
    path = root/'model/preview/team/example.properties'
    values = {'desired.service.example.serviceId':'example',
              'desired.resource.017.resourceType':'S3.Bucket',
              'desired.resource.017.anchor':'s3-fixed',
              'desired.resource.017.cfn-logicalId':'fixed-stack-FixedBucket',
              'desired.row.017-023.property':'S3.Bucket.BucketName',
              'desired.row.017-023.value':'`fixed-name`'}
    write_model(path, values)
    _, template, source = source_paths(path)
    assert model_paths(root)==[path] and model_paths(root,'prod')==[]
    assert not path.exists() and not list(root.rglob('source.json'))
    for _ in range(2):
        before = snapshot_model(path)
        create_service(path)
        assert snapshot_model(path)==before and load_model(path).values==values
        assert not path.exists() and not list(root.rglob('source.json'))
    for file in (template,source/'parameters.yaml',source/'bindings.json'):
        data=file.read_bytes();file.unlink()
        assert model_paths(root)==[path]
        rejected(lambda:load_model(path));file.write_bytes(data)
    binding_path=source/'bindings.json';data=binding_path.read_bytes()
    binding=__import__('json').loads(data);bad=copy.deepcopy(binding)
    bad['instances']['fixture']['definition']='Unknown'
    binding_path.write_text(json_text(bad));rejected(lambda:load_model(path));binding_path.write_bytes(data)
    yaml=source/'parameters.yaml';data=yaml.read_bytes()
    for text in ('instances: [','instances: {}\nunknown: true\n','instances: null\n'):
        yaml.write_text(text);rejected(lambda:load_model(path))
    yaml.write_bytes(data)
    (source/'parameters.json').write_text('{}');rejected(lambda:load_model(path));(source/'parameters.json').unlink()
    old=design_source_digest(path)
    yaml.write_bytes(data+b'# changed input\n')
    assert design_source_digest(path)!=old and affected(root,[yaml.relative_to(root)])=={('preview','team','example')}
    yaml.write_bytes(data)
    other=root/'model/release/team/example.properties';write_model(other,values)
    assert set(model_paths(root))=={path,other}
    assert affected(root,[template.relative_to(root)])=={('preview','team','example'),('release','team','example')}
    assert load_model(other).values==values and design_source_digest(path)!=old
    with patch.object(Path,'read_bytes',side_effect=PermissionError('denied')):
        rejected(lambda:load_model(path))
    assert not path.exists() and not other.exists() and not list(root.rglob('source.json'))
print('Runtime Models: PASS (source discovery; binding-only resources; fixed identities; creation/rerun; missing/corrupt/unknown rejection; input invalidation; no projection/stamp)')
