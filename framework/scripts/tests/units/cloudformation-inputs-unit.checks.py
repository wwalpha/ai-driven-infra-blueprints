"""Pure CloudFormation input evaluation; no AWS or repository Model."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import Mock

import pytest
from support.cloudformation_inputs_fixtures import condition_document
from utils.cloudformation.inputs import (
    Blocked,
    checked_parameters,
    condition_active,
    load_template_inputs,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_parameters():
    # Strict comparison typing has a separate contract from permissive deployment inputs.
    for kind, default, expected in [('String', 'abc', 'abc'), ('Number', '7', 7),
        ('Number', '9007199254740993', 9007199254740993), ('Number', '0.5', 0.5),
        ('CommaDelimitedList', 'a, b', ['a', 'b']), ('List<Number>', '1, 2.5', [1, 2.5])]:
        document = {'Parameters': {'Extra': {'Type': kind, 'Default': default}}}
        assert checked_parameters(document, [])['Extra'] == expected
        assert checked_parameters(document, [{'ParameterKey': 'Extra', 'ParameterValue': default}])['Extra'] == expected
    for definition, reason in [
        ({'Type': 'String', 'Default': 'bad', 'AllowedValues': ['dev', 'stg']}, 'AllowedValues'),
        ({'Type': 'String', 'Default': 'prefix-good-suffix', 'AllowedPattern': 'good'}, 'AllowedPattern'),
        ({'Type': 'String', 'Default': 'a', 'MinLength': 2}, 'MinLength'),
        ({'Type': 'String', 'Default': 'abcd', 'MaxLength': 3}, 'MaxLength'),
        ({'Type': 'Number', 'Default': '1', 'MinValue': 2}, 'MinValue'),
        ({'Type': 'Number', 'Default': '3', 'MaxValue': 2}, 'MaxValue'),
        ({'Type': 'Number', 'Default': 'NaN'}, 'Number'), ({'Type': 'Number', 'Default': True}, 'Number'),
        ({'Type': 'String', 'Default': []}, 'String'), ({'Type': 'String'}, 'required parameter'),
        ({'Type': 'CommaDelimitedList', 'Default': 'a,bad', 'AllowedValues': ['a']}, 'AllowedValues'),
        ({'Type': 'CommaDelimitedList', 'Default': 'a,1', 'AllowedPattern': '[a-z]+'}, 'AllowedPattern')]:
        with pytest.raises(ValueError, match=reason):
            checked_parameters({'Parameters': {'Extra': definition}}, [])
    for text, reason in [('[]', 'required parameter'),
        ('[{"ParameterKey":"Unknown","ParameterValue":"x"}]', 'undeclared'),
        ('[{"ParameterKey":"Name","ParameterValue":7}]', 'explicit'),
        ('[{"ParameterKey":"Name","ParameterValue":"a"},{"ParameterKey":"Name","ParameterValue":"b"}]', 'duplicate'),
        ('[{"ParameterKey":"Name","ParameterValue":"a","ParameterValue":"b"}]', 'duplicate')]:
        parameter_file = Mock()
        parameter_file.read_text.return_value = text
        with pytest.raises(ValueError, match=reason):
            load_template_inputs(None, parameter_file, strict_parameters=True, document={'Parameters': {'Name': {'Type': 'String'}}})
    parameter_file = Mock()
    parameter_file.read_text.return_value = '[]'
    assert load_template_inputs(None, parameter_file, document={'Parameters': {'Extra': {'Type': 'Number', 'Default': '7'}}})[1] == {'Extra': '7'}


def check_conditions():
    for condition in ('IsEnabled', 'Combined', 'Branch', 'SubOff'):
        assert condition_active(condition_document, {'Enable': 'false', 'Other': 'yes'}, {}, {'Condition': condition}) is False
    for condition in ('IsEnabled', 'Combined'):
        assert condition_active(condition_document, {'Enable': 'true', 'Other': 'yes'}, {}, {'Condition': condition}) is True
    for expression, reason in [({'Condition': 'Missing'}, 'unresolved'), ({'Condition': 'Broken'}, 'cyclic'),
                               ('false', 'non-boolean'), ({'Fn::Equals': [{'Ref': 'Unknown'}, 'x']}, 'unsupported')]:
        with pytest.raises(Blocked, match=reason):
            condition_active({'Conditions': {'Broken': expression}}, {}, {}, {'Condition': 'Broken'})


@pytest.mark.parametrize('first', [
    'utils.aws.client', 'comparison.inputs', 'deploy.controller',
    'model.importing.references', 'validation.framework_contracts',
])
def check_import_order_and_blocked_identity(first, tmp_path):
    scripts = Path(__file__).resolve().parents[2]
    code = f"""
import importlib, sys
sys.path.insert(0, {str(scripts)!r})
importlib.import_module({first!r})
from utils.cloudformation.inputs import Blocked
for name in ('utils.aws.client', 'comparison.resource', 'deploy.controller',
             'model.adapters.observed', 'iac_evaluation'):
    assert importlib.import_module(name).Blocked is Blocked, name
assert 'cloudformation_inputs' not in sys.modules
assert 'cloudformation_schema' not in sys.modules
assert 'utils.cloudformation_format' not in sys.modules
"""
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd=tmp_path,
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__, message='CloudFormation inputs: PASS'))
