"""Explicit reference authorities and immutable definition inputs for offline tests."""
import copy as copy
import hashlib
import json
import shutil as shutil
import tempfile as tempfile
from pathlib import Path as Path

from model.files import read_model as read_model
from model.files import trace_model as trace_model
from model.format import serialize as serialize
from model.impact import affected as affected
from model.references import declarations as declarations
from model.references import usages as usages
from model.sources import design_source_digest as design_source_digest
from model.sources import load_model as load_model
from model.sources import source_inputs as source_inputs
from support.import_model_fixtures import project_fixture, resource_values
from support.model_sources import write_model as write_model
from utils.source_reads import FileReads as FileReads


def setup(root, services, kinds, environments=('preview',)):
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
