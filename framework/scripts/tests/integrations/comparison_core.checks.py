#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import module_complete

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
import comparison as iac
import comparison.inputs as inputs
spec = importlib.util.spec_from_file_location('comparison.alternate_inputs', Path(sys.argv[1]) / 'comparison/inputs.py')
alternate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alternate)
assert alternate.Expression is inputs.Expression is values.Expression
assert alternate.ResourceReference is inputs.ResourceReference is values.ResourceReference
assert alternate.Blocked is inputs.Blocked is evaluation.Blocked
from script_loader import module
import issues.runner as scan
from deploy import s3_delivery as delivery
aws = module('model/adapters/aws.py', 'model.adapters.aws')
from deploy import controller as deploy
from deploy import repair
assert delivery.module('model/adapters/aws.py', 'model.adapters.aws') is aws
assert aws.Unresolved is rows.Unresolved and aws.put_row is repair.put_row is rows.put_row
assert repair.same is values.same and scan.Comparison is iac.Comparison
assert deploy.Blocked is inputs.Blocked
import model.render as model_design, model.core as model_core
from model.adapters import observed
assert not hasattr(model_design, 'cfn_resource_identity')
assert inputs.cfn_resource_identity is observed.cfn_resource_identity is repair.cfn_resource_identity is model_core.cfn_resource_identity is values.cfn_resource_identity
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

module_complete(__file__)
