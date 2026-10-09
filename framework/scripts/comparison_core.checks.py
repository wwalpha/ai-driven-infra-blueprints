"""Pure comparison contracts; explicit expected values, no AWS or project."""
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from comparison_rows import put_row

for rows, expected in [
    ([('A', 1), ('B.C', None)], {'A': 1, 'B': {'C': None}}),
    ([('A[].K', 'a'), ('A[].V', 1), ('A[].K', 'a'), ('A[].V', 2)], {'A': [{'K': 'a', 'V': 1}, {'K': 'a', 'V': 2}]}),
    ([('A[2].K', 'b'), ('A[1].K', 'a')], {'A': [{'K': 'a'}, {'K': 'b'}]}),
    ([('A[]', [1, 1]), ('A[]', 2), ('B', 1), ('B', [2, 2])], {'A': [1, 1, 2], 'B': [1, 2, 2]}),
    # Existing nested boundary behavior is recorded here, not a specification fix.
    ([('A[].B[].K', 'a'), ('A[].B[].K', 'b')], {'A': [{'B': [{'K': 'a'}, {'K': 'b'}]}]}),
]:
    tree = {}
    for path, value in rows:
        put_row(tree, path, value)
    assert tree == expected, (rows, tree)
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

# Fresh processes forbid acquisition/CLI/file-read paths, rather than merely observing no network.
import subprocess
import sys
from pathlib import Path
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
'''
for order in [('comparison_rows', 'iac_values', 'iac_evaluation'), ('iac_evaluation', 'iac_values', 'comparison_rows')]:
    subprocess.run([sys.executable, '-B', '-c', code, str(Path(__file__).parent), *order], check=True)
print('Comparison core checks: PASS (rows/typed values/uncertainty/masking/fresh import identity)')
