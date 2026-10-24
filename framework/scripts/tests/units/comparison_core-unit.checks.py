"""Pure comparison contracts; explicit expected values, no AWS or project."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from functools import partial
from unittest.mock import Mock

import pytest
from array_display import indexed_rows
from cloudformation_inputs import (
    Blocked,
    checked_parameters,
    condition_active,
    load_template_inputs,
)
from comparison.resource import inactive_evidence
from comparison.services.cloudtrail import cloudtrail_rows
from comparison_rows import Unresolved, put_row
from iac_evaluation import Evaluation
from iac_values import (
    Expression,
    ResourceReference,
    comparison_result,
    safe_value,
    same,
    selected_same,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

index_rows = partial(indexed_rows, root=Path(__file__).resolve().parents[4])

trail_kind = 'CloudTrail.Trail.'
trail_fields = [
    ('EventSelectors[].IncludeManagementEvents', '`true`'),
    ('EventSelectors[].ReadWriteType', '`All`'),
    ('EventSelectors[].DataResources[].Type', '`AWS::S3::Object`'),
    ('EventSelectors[].DataResources[].Values', '`["arn:aws:s3"]`'),
    ('EventSelectors[].IncludeManagementEvents', '`false`'),
    ('EventSelectors[].DataResources[].Type', '`AWS::Lambda::Function`'),
    ('EventSelectors[].DataResources[].Values', '[function](lambda.md#function)'),
    ('EventSelectors[].DataResources[].Type', '`AWS::Lambda::Function`'),
    ('EventSelectors[].DataResources[].Values', '[other](lambda.md#other)'),
]
trail_rows = [(f'001-{i:03d}', dict(property=trail_kind + prop, value=value))
              for i, (prop, value) in enumerate(trail_fields, 1)]
trail_paths = [
    'EventSelectors[1].IncludeManagementEvents', 'EventSelectors[1].ReadWriteType',
    'EventSelectors[1].DataResources[1].Type', 'EventSelectors[1].DataResources[1].Values',
    'EventSelectors[2].IncludeManagementEvents',
    'EventSelectors[2].DataResources[1].Type', 'EventSelectors[2].DataResources[1].Values',
    'EventSelectors[2].DataResources[2].Type', 'EventSelectors[2].DataResources[2].Values',
]
trail_expected = {rid: dict(row, property=trail_kind + prop)
                  for (rid, row), prop in zip(trail_rows, trail_paths, strict=False)}
for ordered in (trail_rows, trail_rows[::-1], trail_rows[::2] + trail_rows[1::2]):
    projected = dict(cloudtrail_rows(ordered, index_rows=index_rows))
    assert projected == trail_expected, projected
    assert all(row['property'] == trail_kind + prop for (_, row), (prop, _) in zip(trail_rows, trail_fields, strict=False))
for invalid in (trail_rows[:3], trail_rows + [(trail_rows[0][0], dict(trail_rows[0][1], value='`false`'))],
                [('unknown', trail_rows[0][1]), *trail_rows[1:]],
                [(trail_rows[0][0], dict(trail_rows[0][1], property=trail_kind + 'EventSelectors[1].IncludeManagementEvents')), *trail_rows[1:]]):
    try:
        cloudtrail_rows(invalid, index_rows=index_rows)
    except Unresolved as error:
        assert 'array membership unresolved' in str(error)
    else:
        raise AssertionError('unproven CloudTrail membership accepted')

for rows, expected in [
    ([('A', 1), ('B.C', None)], {'A': 1, 'B': {'C': None}}),
    ([('A[].K', 'a'), ('A[].V', 1), ('A[].K', 'a'), ('A[].V', 2)], {'A': [{'K': 'a', 'V': 1}, {'K': 'a', 'V': 2}]}),
    ([('A[2].K', 'b'), ('A[1].K', 'a')], {'A': [{'K': 'a'}, {'K': 'b'}]}),
    ([('A[]', [1, 1]), ('A[]', 2), ('B', 1), ('B', [2, 2])], {'A': [1, 1, 2], 'B': [1, 2, 2]}),
    ([('A[1].B[]', [1, 1]), ('A[2].B[]', [])], {'A': [{'B': [1, 1]}, {'B': []}]}),
    ([('A[2]', 'same'), ('A[1]', 'same')], {'A': ['same', 'same']}),
]:
    tree = {}
    for path, value in rows:
        put_row(tree, path, value)
    assert tree == expected, (rows, tree)
# Explicit indexes are membership, independent of catalog order and optional fields.
stages = [
    {'Name': 'same', 'Actions': [
        {'Name': 'a', 'InputArtifacts': [{'Name': 'same'}, {'Name': 'same'}], 'OutputArtifacts': []},
        {'Name': 'b', 'RunOrder': 2, 'OutputArtifacts': [{'Name': 'out'}]}]},
    {'Name': 'same', 'Actions': [{'Name': 'c', 'InputArtifacts': []}]},
]
rows = []
def flatten(value, path):
    if isinstance(value, dict):
        for key, child in value.items():
            flatten(child, path + '.' + key if path else key)
    elif isinstance(value, list) and value:
        for index, child in enumerate(value, 1):
            flatten(child, f'{path}[{index}]')
    else:
        rows.append((path, value))
flatten(stages, 'Stages')
for ordered in (rows, list(reversed(rows)), sorted(rows)):
    tree = {}
    for path, value in ordered:
        put_row(tree, path, value)
    assert tree == {'Stages': stages}, tree
for path in ('A[].B[].K', 'A[].B[1].K', 'A[1].B[].K', 'A[].B[]', 'A[0].K'):
    tree = {'Existing': 1}
    try:
        put_row(tree, path, 'same')
    except Unresolved as error:
        assert path in str(error)
        assert tree == {'Existing': 1}, 'unresolved rows must not partially mutate the tree'
    else:
        raise AssertionError('ambiguous membership accepted: ' + path)


for left, right in [(True, 1), (1, 1.0), ('1', 1), (None, ''), ({}, []), ([1, 2], [2, 1]), ([1, 1], [1])]:
    assert same(left, right) is False
assert same(None, None) is True and same({}, {}) is True and same([], []) is True
assert comparison_result([None, False]) is False and comparison_result([None, True]) is None
assert comparison_result([None, True], any_match=True) is True
assert selected_same({'a': 1}, {'a': 1, 'b': 2}) is True
ref = ResourceReference({'$resource': ['s3', '001'], '$attribute': 'Arn'})
assert same(ref, dict(ref)) is False and same(ref, ResourceReference(ref)) is True
expression = Expression('Join', ['', [ref, '/*']])
assert same(expression, safe_value(expression)) is False
assert safe_value({'Password': 'one', 'Arn': 'arn:aws:s3:::private'}) == {'Password': '<masked>', 'Arn': '<masked ARN/secret>'}


# Schemas prove types/bounds, never DNS values or array elements.
schemas = {
    'DnsEntries': {'type': 'array', 'minItems': 1, 'maxItems': 2},
    'DnsEntries[]': {'type': 'string'},
    'UnknownLength': {'type': 'array'},
    'UnknownType': {},
    'UnknownElement': {'type': 'array', 'minItems': 1},
    'UnknownElement[]': {},
    'Numbers': {'type': 'array', 'minItems': 1},
    'Numbers[]': {'type': 'integer'},
    'Name': {'type': 'string'},
}
resources = {'vpc-endpoint': {'001': {'resourceType': 'EC2.VPCEndpoint'}}}
def symbol(stack, logical, attribute):
    assert logical == 'Endpoint'
    return ResourceReference({'$resource': ['vpc-endpoint', '001'], '$attribute': attribute})
def forbidden(*args):
    raise AssertionError('unexpected import lookup')
evaluator = Evaluation({'stack': ({}, {}, {})}, resources, lambda kind, path: schemas[path], symbol, forbidden, True)
def evaluate(value):
    return evaluator.evaluate('stack', value)
def getatt(attribute):
    return {'Fn::GetAtt': ['Endpoint', attribute]}
def select(index, items):
    return {'Fn::Select': [index, items]}
def rejects(value, exception, reason):
    try:
        evaluate(value)
    except exception as error:
        assert reason in str(error), str(error)
    else:
        raise AssertionError((value, exception, reason))

first = select('0', getatt('DnsEntries'))
split = {'Fn::Split': [':', first]}
chain = select(0, split)
expected = Expression('Select', [0, Expression('Split', [':', Expression('Select', [0, symbol('stack', 'Endpoint', 'DnsEntries')])])])
assert same(evaluate(chain), expected)
assert same(evaluate(chain), evaluate(select('0', split)))
assert evaluator.string_operand(evaluate(first))
assert not same(evaluate(chain), safe_value(expected))
assert not same(evaluate(chain), evaluate(select(0, {'Fn::Split': [',', first]})))
assert evaluator.string_operand(evaluate(select(0, getatt('Numbers')))) is False
assert evaluate(select(1, ['a', 'b'])) == 'b'
assert evaluate(select(1, {'Fn::Split': [':', 'zone:dns']})) == 'dns'
assert evaluate({'Fn::Split': [':', '']}) == ['']
for value, reason in [
    (select(0, getatt('UnknownLength')), 'index 0, symbolic array minItems=0'),
    (select(1, getatt('DnsEntries')), 'index 1, symbolic array minItems=1'),
    (select(0, getatt('UnknownType')), 'array type is unproven'),
    (select(1, split), 'index 1, symbolic array minItems=1'),
    (select(getatt('Name'), ['a']), 'index is unproven'),
    ({'Fn::Split': [':', select(0, getatt('UnknownElement'))]}, 'string type is unproven'),
]:
    rejects(value, Blocked, reason)
for value in [select(2, getatt('DnsEntries')), select(0, getatt('Name')),
              select(True, ['a']), select(-1, ['a']), select(1.0, ['a']),
              select('x', ['a']), select(1, ['a']), select(0, []), select(0, [None]),
              select(0, {}), {'Fn::Select': [0]},
              {'Fn::Split': [':', getatt('DnsEntries')]},
              {'Fn::Split': [':', select(0, getatt('Numbers'))]},
              {'Fn::Split': ['', 'text']}, {'Fn::Split': [1, 'text']},
              {'Fn::Split': [':', None]}, {'Fn::Split': [':']},
              {'Fn::Join': ['', [select(0, getatt('Numbers'))]]}]:
    rejects(value, ValueError, 'invalid')
# AWS/deploy mode still refuses symbolic array/string evaluation.
evaluator.local_comparison = False
assert evaluate(select(1, {'Fn::Split': [':', 'zone:dns']})) == 'dns'
rejects(first, ValueError, 'invalid Select operands')
rejects({'Fn::Split': [':', getatt('Name')]}, ValueError, 'invalid Split operands')
print('Symbolic array evaluation: PASS (schema types/bounds, chains, concrete inputs, errors, deploy isolation)')

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

conditions = {'IsEnabled': {'Fn::Equals': [{'Ref': 'Enable'}, 'true']},
    'OtherEnabled': {'Fn::Equals': [{'Ref': 'Other'}, 'yes']},
    'Combined': {'Fn::And': [{'Condition': 'IsEnabled'}, {'Fn::Or': [{'Condition': 'OtherEnabled'}, {'Fn::Not': [{'Condition': 'IsEnabled'}]}]}]},
    'Branch': {'Fn::If': ['IsEnabled', {'Condition': 'Missing'}, False]},
    'SubOff': {'Fn::Equals': [{'Fn::Sub': '${Enable}'}, 'true']}}
condition_document = {'Parameters': {'Enable': {'Type': 'String', 'Default': 'false'}, 'Other': {'Type': 'String', 'Default': 'yes'}}, 'Conditions': conditions}
for condition in ('IsEnabled', 'Combined', 'Branch', 'SubOff'):
    assert condition_active(condition_document, {'Enable': 'false', 'Other': 'yes'}, {}, {'Condition': condition}) is False
for condition in ('IsEnabled', 'Combined'):
    assert condition_active(condition_document, {'Enable': 'true', 'Other': 'yes'}, {}, {'Condition': condition}) is True
for expression, reason in [({'Condition': 'Missing'}, 'unresolved'), ({'Condition': 'Broken'}, 'cyclic'),
                           ('false', 'non-boolean'), ({'Fn::Equals': [{'Ref': 'Unknown'}, 'x']}, 'unsupported')]:
    with pytest.raises(Blocked, match=reason):
        condition_active({'Conditions': {'Broken': expression}}, {}, {}, {'Condition': 'Broken'})

for condition, names in [('Combined', {'Enable', 'Other'}), ('Branch', {'Enable'}), ('SubOff', {'Enable'})]:
    location, cause = inactive_evidence('stack', 'Bucket', {'Condition': condition}, condition_document,
        {'Enable': 'false', 'Other': 'yes'}, {}, path='template.yaml', parameter_path='parameters.json',
        supplied=set(), stack_id='001', target={}, environment='dev', directory='team', marks={},
        source_lookup=Mock(), redact=lambda value, key: value)
    assert {item['name'] for item in cause['inputs']} == names
    assert all(item['source']['kind'] == 'template-default' for item in cause['inputs'])
    assert set(cause['conditions']) == ({'Combined', 'IsEnabled', 'OtherEnabled'} if condition == 'Combined' else {condition, 'IsEnabled'} if condition == 'Branch' else {condition})
for value, noecho, name in [('private', True, 'Confidential'), (8912, True, 'Numeric'), ('private', False, 'SecretToken')]:
    document = {'Parameters': {name: {'NoEcho': noecho}}, 'Conditions': {'Off': {'Fn::Equals': [{'Ref': name}, 'other']}}}
    for supplied in (set(), {name}):
        _, cause = inactive_evidence('stack', 'Bucket', {'Condition': 'Off'}, document, {name: value}, {},
            path='template.yaml', parameter_path='parameters.json', supplied=supplied, stack_id='001', target={},
            environment='dev', directory='team', marks={}, source_lookup=Mock(), redact=safe_value)
        assert cause['inputs'][0]['value'] in {'<masked sensitive parameter>', '<masked>'}
for name, source in [('AWS::Region', {'path': 'project.json', 'key': 'awsRegion'}),
                     ('AWS::StackName', {'path': 'stacks.properties', 'key': 'desired.stack.001.name'})]:
    document = {'Conditions': {'Off': {'Fn::Equals': [{'Ref': name}, 'other']}}}
    _, cause = inactive_evidence('stack', 'Bucket', {'Condition': 'Off'}, document, {}, {name: 'fixture'},
        path='template.yaml', parameter_path='parameters.json', supplied=set(), stack_id='001', target={},
        environment='dev', directory='team', marks={}, source_lookup=Mock(return_value=source), redact=safe_value)
    assert all(cause['inputs'][0]['source'][key] == value for key, value in source.items())
