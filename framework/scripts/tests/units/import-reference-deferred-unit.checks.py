"""The shared exception/cause/category contract; callers test their own propagation."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from comparison.deferral import CATEGORIES, ImportReferenceDeferred, defer_import_reference, failure_category, validate_cause
from utils.cloudformation.inputs import Blocked

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@pytest.mark.parametrize('phase', ['unobserved', 'pending_deploy', 'awaiting_handoff'])
def test_normal_wait(phase):
    error = ImportReferenceDeferred(phase, 'vpc', '004', 'EC2.Subnet', 'SubnetId', 'CodeBuild.Project.VpcConfig.Subnets[]')
    assert isinstance(error, Blocked) and failure_category(error) == 'deferred'
    assert error.iac_cause == dict(kind='import-reference-deferred', phase=phase,
        producer=dict(service='vpc', resource='004', resourceType='EC2.Subnet', attribute='SubnetId'),
        consumer_property='CodeBuild.Project.VpcConfig.Subnets[]')
    validate_cause(error.iac_cause)


def test_other_failures_are_not_normal_waits():
    for error in (Blocked('comparison deferred'), KeyError('IMPORT reference')):
        assert failure_category(error) == 'uncompared'
    for error in (ValueError(), TypeError(), OSError(), ImportError(), IndexError()):
        assert failure_category(error) == 'error'
    assert len(CATEGORIES) == len(set(CATEGORIES)) == 6
    with pytest.raises(ValueError, match='phase'):
        ImportReferenceDeferred('unknown', 'vpc', '004', 'EC2.Subnet', 'SubnetId', 'consumer')
    for cause in (None, {}, {'kind': 'import-reference-deferred', 'phase': 'unobserved'}):
        with pytest.raises(ValueError, match='cause'):
            validate_cause(cause)



@pytest.mark.parametrize('observed,phase', [(None, 'unobserved'), ('PENDING_DEPLOY', 'pending_deploy'), ('valid-id', 'awaiting_handoff')])
def test_phase_selection_uses_authoritative_observations(observed, phase):
    authority = {} if observed is None else {'observed.row.004-001.value': '`' + observed + '`'}
    inputs = SimpleNamespace(local_comparison=True, rows={'vpc': {'004': [('004-001', {'property': 'Test.Resource.Id'})]}},
        models={'vpc': SimpleNamespace(authoritative=authority)}, catalog=Mock())
    inputs.catalog.property_schema.return_value = {'type': 'string'}
    inputs.catalog.literal_errors.return_value = []
    symbol = {'$resource': ['vpc', '004'], '$attribute': 'Id'}
    with pytest.raises(ImportReferenceDeferred) as failure:
        defer_import_reference(inputs, symbol, {'resourceType': 'Test.Resource'}, 'Consumer.Resource.Reference')
    assert failure.value.iac_cause['phase'] == phase
    assert inputs.catalog.literal_errors.call_count == (1 if phase == 'awaiting_handoff' else 0)


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
