"""Explicit reference authorities and immutable definition inputs for offline tests."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from model.sources import load_model, source_inputs, design_source_digest, FileReads
from model.references import declarations, usages
from model.impact import affected
from model.files import read_model, trace_model
from model.format import serialize
from support.model_sources import write_model


def setup(root, services, kinds, environments=('preview',)):
    from support.import_model_fixtures import project_fixture
    root.mkdir(exist_ok=True)
    project_fixture(root)
    (root / 'project.json').write_text(json.dumps({'targets': [
        {'environment': env, 'alias': 'team', 'awsAccountId': '111111111111',
         'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'} for env in environments]}) + '\n', encoding='utf-8')


def reference(identity, key, text, service, rid, kind, *, mode='name', prop=None, pointer=None,
              environment='preview', label='none'):
    fields = {'consumerKey': key, 'text': text, 'occurrence': '1', 'producerKind': 'resource',
              'producerScope': environment + '/team/' + service, 'producerLogicalId': kind.replace('.', '_') + '_' + rid,
              'resourceType': kind, 'format': mode, 'labelPolicy': label}
    if prop is not None:
        fields['property'] = prop
    if pointer is not None:
        fields['pointer'] = pointer
    return {'desired.reference.' + identity + '.' + name: value for name, value in fields.items()}


def resource(rid, kind, anchor, rows):
    from support.import_model_fixtures import resource_values
    return resource_values(rid, kind, anchor, 'IMPORT', rows)


def dependency_hashes(path):
    return {str(file): None if raw is None else hashlib.sha256(raw).hexdigest()
            for file, raw in load_model(path, FileReads()).dependencies.items()}


def warning(path, phrase):
    snapshot = load_model(path, FileReads())
    assert any(phrase in item['message'] for item in snapshot.warnings), snapshot.warnings
    return snapshot


def rejected(function, phrase):
    try:
        function()
    except (ValueError, OSError, TypeError) as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError('invalid reference metadata accepted: ' + phrase)
