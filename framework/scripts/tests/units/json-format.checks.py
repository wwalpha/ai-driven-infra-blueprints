"""JSON contracts use fixed pre-refactor bytes, messages and digests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import math
import subprocess

import pytest
from utils.json_format import (
    canonical_json,
    document_sha256,
    fingerprint,
    json_text,
    policy_json,
    strict_json,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@pytest.mark.parametrize('reader', [strict_json, policy_json])
@pytest.mark.parametrize('raw, expected', [
    ('{"日本語":[true,false,null,2,-0.0,1.25],"empty":{}}',
     {'日本語': [True, False, None, 2, -0.0, 1.25], 'empty': {}}),
    ('[123456789012345678901234567890,"\\u65e5\\u672c",[]]',
     [123456789012345678901234567890, '日本', []]),
])
def check_parse(reader, raw, expected):
    assert reader(raw) == expected


@pytest.mark.parametrize('reader, label', [(strict_json, 'JSON'), (policy_json, 'policy JSON')])
@pytest.mark.parametrize('raw, message', [
    ('{"x":1,"x":2}', 'duplicate {label} key: x'),
    ('{"nested":[{"日本":1,"日本":2}]}', 'duplicate {label} key: 日本'),
    ('NaN', 'invalid JSON constant: NaN'),
    ('[Infinity]', 'invalid JSON constant: Infinity'),
    ('{"x":-Infinity}', 'invalid JSON constant: -Infinity'),
    ('{"x":}', 'Expecting value: line 1 column 6 (char 5)'),
])
def check_errors(reader, label, raw, message):
    with pytest.raises(ValueError) as error:
        reader(raw)
    assert str(error.value) == message.format(label=label)


@pytest.mark.parametrize('raw', ['1e999', '-1e999', '[1e999]'])
def check_model_overflow_only(raw):
    with pytest.raises(ValueError) as error:
        strict_json(raw)
    assert str(error.value) == 'nonfinite JSON number: ' + raw.strip('[]')
    value = policy_json(raw)
    assert math.isinf(value[0] if isinstance(value, list) else value)


def check_output_bytes_and_hashes():
    value = {'z': ['日本語', True, None], 'a': 1.0}
    assert json_text(value).encode('utf-8') == '{"z":["日本語",true,null],"a":1.0}'.encode('utf-8')
    assert canonical_json(value).encode('utf-8') == ('{\n  "a": 1.0,\n  "z": [\n    "日本語",\n    true,\n    null\n  ]\n}\n').encode('utf-8')
    assert document_sha256(value) == '39e63c66da6ddc3cd6e40fde0c98e3394095d21045500770a07ef0c24824c796'
    assert fingerprint(value) == '93d0eda33a52baf70abb1d83105d47c8657cfa4be82f89a3e5979f356d2f22a1'
    assert document_sha256(value) != fingerprint(value)
    assert document_sha256({'a': 1.0, 'z': value['z']}) == document_sha256(value)
    for number in (float('nan'), float('inf'), -float('inf')):
        with pytest.raises(ValueError, match='Out of range float values are not JSON compliant'):
            json_text(number)
    # Existing canonical/hash writers deliberately retain json.dumps allow_nan defaults.
    assert canonical_json(float('inf')) == 'Infinity\n'
    assert len(document_sha256(float('nan'))) == len(fingerprint(float('nan'))) == 64




@pytest.mark.parametrize('first', ['utils.aws_mappings', 'model.sources', 'model.adapters.aws', 'policy_tables'])
def check_isolated_imports_and_standalone_audit(first, tmp_path):
    scripts = Path(__file__).resolve().parents[2]
    code = f'''
import sys, importlib, json
sys.path.insert(0, {str(scripts)!r})
importlib.import_module({first!r})
for name in ('model.format', 'model.render', 'model.validation', 'model.importing.inventory',
             'utils.cloudformation.inputs', 'sync_runtime', 'utils.json_format'):
    importlib.import_module(name)
from model.audit import definitions
from pathlib import Path
source = definitions(Path({str(scripts / 'utils/json_format.py')!r}),
                     ['unique_object', 'invalid_constant', 'policy_json'])
namespace = {{'json': json}}
exec(source, namespace)
assert namespace['policy_json']('{{"日本語":1}}') == {{'日本語': 1}}
try:
    namespace['policy_json']('{{"x":1,"x":2}}')
except ValueError as error:
    assert str(error) == 'duplicate policy JSON key: x'
else:
    raise AssertionError('standalone parser accepted duplicate key')
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd=tmp_path,
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
