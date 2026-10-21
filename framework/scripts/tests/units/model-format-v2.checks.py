"""Synthetic format/discovery checks; never inspect the executing project's Models."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import json
import tempfile
import pytest
from model.format import FORMAT, INDEX, parse, patch, serialize, split
from model.sources import Scope, load_model, list_models
from model.references import declarations, diagnose


def check_scalar_spelling_and_patch():
    text = FORMAT + '\r\n# comment\r\na.value= 010 \\ " \r\nb.value=`true`\r\n'
    document = parse(text)
    assert document.values == {'a.value': ' 010 \\ " ', 'b.value': '`true`'}
    edited = patch(document, {'b.value': '`false`'})
    assert edited == text.replace('`true`', '`false`')
    for raw in ('`{{resolve:secretsmanager:secret:SecretString:token}}`', '`[Policy](iam/policy.json)`', '`[Role](iam.md#role)`'):
        assert parse(FORMAT + '\ndesired.row.007-001.value=' + raw + '\n').values['desired.row.007-001.value'] == raw
        from model.references import _json
        assert _json('desired.row.007-001.value', raw) == (raw, False)


def check_json_continuation_and_types():
    text = FORMAT + '\ndesired.row.007-003.document={\\\n  "a": [true, 10, null, "1"],\\\n  "b": "slash\\\\"} \ndesired.row.007-004.value=`[\\\n"first", "second"]`\n'
    values = parse(text).values
    assert json.loads(values['desired.row.007-003.document']) == {'a': [True, 10, None, '1'], 'b': 'slash\\'}
    assert json.loads(values['desired.row.007-004.value'][1:-1]) == ['first', 'second']


@pytest.mark.parametrize('body', [
    'a.document={"a":1,"a":2}', 'a.document={"x":NaN}', 'a.document={\\',
    'a.document={\\\n# comment\n}', 'a.document={\\ \n}',
    'a.document={"x":"broken\\\nstring"}', 'a.document={\n"a":1}',
    'a.document={"x":Infinity}', 'a.document={"x":1e999}', 'a.value=`[-1e999]`', 'a.value=`[1,]`', 'a=1\na=2'])
def check_invalid_properties(body):
    with pytest.raises(ValueError):
        parse(FORMAT + '\n' + body + '\n')


@pytest.mark.parametrize('header', ['', '# model-format: 1', '# model-format: 3', '# model-template: 1'])
def check_unsupported_version(header):
    with pytest.raises(ValueError):
        parse(header + '\na=1\n')


@pytest.mark.parametrize('version', [None, 1, 2, 3.0])
def check_deploy_rejects_legacy_session_format(version):
    from deployment.session import require_session_format
    from cloudformation_inputs import Blocked
    with pytest.raises(Blocked, match='format is incompatible'):
        require_session_format({'version': version, 'modelFormat': 2, 'snapshotVersion': 2, 'referenceMeaningVersion': 1})
    require_session_format({'version': 3, 'modelFormat': 2, 'snapshotVersion': 2, 'referenceMeaningVersion': 1})


def check_observed_insertion_is_local_without_reflow():
    text = FORMAT + '\r\n# original comment  \r\n' + (
        'desired.row.007-001.property=EC2.VPC.VpcId\r\n'
        'desired.row.007-001.value=[network](#network)\r\n'
        'desired.row.007-001.comment=日本語の説明\r\n'
        '# next Row must keep its exact original bytes  \r\n'
        'desired.row.007-002.property=EC2.VPC.Name\r\n'
        'desired.row.007-002.value= 010 \\ " \r\n')
    marker = 'desired.row.007-001.comment=日本語の説明\r\n'
    observed = 'observed.row.007-001.value=\r\n'
    updated = patch(parse(text), {'observed.row.007-001.value': ''})
    assert updated == text.replace(marker, marker + observed)
    assert patch(parse(updated), {'observed.row.007-001.value': None}) == text




def check_import_observation_foreign_reference_and_identity_spoof(tmp_path):
    import shutil
    from model.sources import load_model
    from model.observed import observed_outputs
    from model.format import serialize
    from support.model_v2_fixtures import format_fixture, FRAMEWORK
    scope, values = format_fixture(tmp_path)
    for name in ('materials', 'mappings', 'rules'):
        shutil.copytree(FRAMEWORK / 'framework' / name, tmp_path / 'framework' / name)
    values.update({'desired.resource.008.resourceType': 'EC2.Subnet',
                   'desired.resource.008.resourceMode': 'IMPORT', 'desired.resource.008.anchor': 'imported-subnet',
                   'desired.row.008-001.property': 'EC2.Subnet.VpcId',
                   'desired.row.008-001.value': '[Network](#network)', 'desired.row.008-001.comment': 'foreign VPC',
                   'observed.row.008-001.value': 'vpc-before',
                   'desired.row.008-002.property': 'EC2.Subnet.SubnetId',
                   'desired.row.008-002.value': '[Subnet](#imported-subnet)', 'desired.row.008-002.comment': 'own ID',
                   'observed.row.008-002.value': 'subnet-before'})
    scope.path.write_text(serialize(values))
    snapshot = load_model(scope)
    outputs = observed_outputs(scope.path, {**snapshot.values, 'observed.row.008-001.value': 'PENDING_DEPLOY'})
    assert outputs[scope.path] == patch(parse(scope.path.read_text()), {'observed.row.008-001.value': 'PENDING_DEPLOY'})
    assert 'observed.row.008-002.value=subnet-before' in outputs[scope.path]
    with pytest.raises(ValueError, match='IMPORT physical identity'):
        observed_outputs(scope.path, {**snapshot.values, 'observed.row.008-002.value': 'subnet-other'})
    # A forged foreign link cannot make a native primary identifier writable.
    values['desired.row.008-002.value'] = '[Network](#network)'
    scope.path.write_text(serialize(values))
    snapshot = load_model(scope)
    with pytest.raises(ValueError, match='IMPORT physical identity'):
        observed_outputs(scope.path, {**snapshot.values, 'observed.row.008-002.value': 'subnet-other'})


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
