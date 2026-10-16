"""Pure comparison contracts; explicit expected values, no AWS or project."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from comparison_rows import Unresolved, put_row

from comparison_rows import cloudtrail_rows

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
                  for (rid, row), prop in zip(trail_rows, trail_paths)}
for ordered in (trail_rows, trail_rows[::-1], trail_rows[::2] + trail_rows[1::2]):
    projected = dict(cloudtrail_rows(ordered, Path(__file__).resolve().parents[4]))
    assert projected == trail_expected, projected
    assert all(row['property'] == trail_kind + prop for (_, row), (prop, _) in zip(trail_rows, trail_fields))
for invalid in (trail_rows[:3], trail_rows + [(trail_rows[0][0], dict(trail_rows[0][1], value='`false`'))],
                [('unknown', trail_rows[0][1]), *trail_rows[1:]],
                [(trail_rows[0][0], dict(trail_rows[0][1], property=trail_kind + 'EventSelectors[1].IncludeManagementEvents')), *trail_rows[1:]]):
    try:
        cloudtrail_rows(invalid, Path(__file__).resolve().parents[4])
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

from iac_values import Expression, ResourceReference, comparison_result, same, selected_same, safe_value

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

from iac_evaluation import Evaluation
from cloudformation_inputs import Blocked

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

# Fresh processes forbid acquisition/CLI/file-read paths, rather than merely observing no network.
import subprocess
code = r'''
import argparse, importlib.abc, importlib.util, socket, subprocess, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
class NoAWS(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'boto3', 'botocore', 'model_aws_compare'}:
            raise AssertionError('AWS/credential import forbidden: ' + fullname)
sys.meta_path.insert(0, NoAWS())
with patch.object(Path, 'read_text', side_effect=AssertionError('input read')), \
     patch.object(Path, 'read_bytes', side_effect=AssertionError('input read')), \
     patch.object(Path, 'open', side_effect=AssertionError('input open')), \
     patch.object(Path, 'glob', side_effect=AssertionError('input discovery')), \
     patch.object(argparse.ArgumentParser, 'parse_args', side_effect=AssertionError('CLI execution')), \
     patch.object(socket, 'socket', side_effect=AssertionError('network')), \
     patch.object(subprocess, 'Popen', side_effect=AssertionError('process')):
    for name in sys.argv[2:]:
        __import__(name)
    import comparison_rows as rows, iac_values as values, iac_evaluation as evaluation
    tree = {}
    rows.put_row(tree, 'A[].V', 1)
    assert tree == {'A': [{'V': 1}]}
    assert values.same(1, True) is False
    def forbidden(*args): raise AssertionError('lookup on literal')
    evaluator = evaluation.Evaluation({'stack': ({}, {}, {})}, {}, forbidden, forbidden, forbidden, True)
    assert evaluator.evaluate('stack', {'Fn::Join': [',', ['a', 'b']]}) == 'a,b'

# Orchestrators may read the immutable layout at import, but never project inputs.
import issues_iac as iac
spec = importlib.util.spec_from_file_location('alternate_iac', Path(sys.argv[1]) / 'issues_iac.py')
alternate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alternate)
assert alternate.Expression is iac.Expression is values.Expression
assert alternate.ResourceReference is iac.ResourceReference is values.ResourceReference
assert alternate.Blocked is iac.Blocked is evaluation.Blocked
from script_loader import module
import issues_scan as scan, s3_delivery as delivery
aws = module('check-model-aws.py', 'model_aws_compare')
deploy = module('cloudformation-deploy.py', 'core_deploy')
from deployment import repair
assert delivery.module('check-model-aws.py', 'model_aws_compare') is aws
assert aws.Unresolved is rows.Unresolved and aws.put_row is repair.put_row is rows.put_row
assert repair.same is values.same and scan.Comparison is iac.Comparison
assert deploy.Blocked is iac.Blocked
import model_design, model_core, cloudformation_observed as observed
assert not hasattr(model_design, 'cfn_resource_identity')
assert iac.cfn_resource_identity is observed.cfn_resource_identity is repair.cfn_resource_identity is model_core.cfn_resource_identity is values.cfn_resource_identity
assert values.cfn_resource_identity('cfn-stack-app-dev-ism-DepartmentVpc') == ('cfn-stack-app-dev-ism', 'DepartmentVpc')
for invalid in ('missing', 'stack-lowercase', 'stack-Resource-with-hyphen'):
    try:
        values.cfn_resource_identity(invalid)
    except ValueError as error:
        assert 'invalid cfn-logicalId' in str(error)
    else:
        raise AssertionError('invalid CFn identity accepted')
'''
for order in [('comparison_rows', 'iac_values', 'iac_evaluation'), ('iac_evaluation', 'iac_values', 'comparison_rows')]:
    subprocess.run([sys.executable, '-B', '-c', code, str(Path(__file__).resolve().parents[2]), *order], check=True)
print('Comparison core checks: PASS (rows/typed values/uncertainty/masking/fresh import identity)')
