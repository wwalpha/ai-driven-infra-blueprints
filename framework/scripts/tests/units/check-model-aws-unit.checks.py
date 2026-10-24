#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import support.check_model_aws_fixtures as _retained_fixture_offline_network
from support.check_model_aws_fixtures import (
    Path,
    check,
    m,
    run,
    sys,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

offline_network = _retained_fixture_offline_network.offline_network


def check_summary_exit_codes():
    check(m.summarize([{'status': 'match'}])['exitCode'] == 0, 'match exit')
    check(m.summarize([{'status': 'difference'}])['exitCode'] == 1, 'difference exit')
    check(m.summarize([{'status': 'difference'}, {'status': 'sdk_unavailable'}])['exitCode'] == 2, 'incomplete takes precedence')
    check(m.summarize([])['exitCode'] == 2, 'empty scan incomplete')



def check_value_normalization():
    tags = {'Tags': [{'Key': 'b', 'Value': '2'}, {'Key': 'a', 'Value': '1'}]}
    check(m.canonical(tags)['Tags'] == [{'Key': 'a', 'Value': '1'}, {'Key': 'b', 'Value': '2'}], 'tag association')
    check(m.canonical({'Stages': ['b', 'a']})['Stages'] == ['b', 'a'], 'stage order')
    check(m.canonical({'SubnetIds': ['b', 'a']})['SubnetIds'] == ['b', 'a'], 'placement order')
    check(m.policy({'Statement': {'Effect': 'Allow', 'Action': 's3:GetObject', 'Resource': '*'}}) == m.policy({'Statement': [{'Resource': ['*'], 'Action': ['s3:GetObject'], 'Effect': 'Allow'}]}), 'policy scalar/set/object normalization')
    check(m.policy('{"Statement":[],"Id":"keep%2Fthis"}')['Id'] == 'keep%2Fthis', 'plain JSON policy preserves percent escapes')



def check_secret_redaction():
    check(m.redacted({'password': 'never print', 'nested': {'Token': 'never print'}}) == {'password': '[REDACTED]', 'nested': {'Token': '[REDACTED]'}}, 'secret output redaction')




def check_identity_delegation_and_sts_reuse(tmp_path):
    target = {'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1'}
    runner = Mock(return_value=SimpleNamespace(returncode=0, stdout='{"Account":"123456789012"}', stderr=''))
    ctx = m.Context(tmp_path, target, cli_runner=runner, services=(), import_mode=True)
    with patch.object(m, 'verify_account', return_value='123456789012') as verify:
        assert ctx.verify() == ctx.verify() == '123456789012'
        assert verify.call_count == 2
        verify.assert_called_with(target, '123456789012')
    assert runner.call_count == 1
    rejected = m.Context(tmp_path, target, cli_runner=runner, services=(), import_mode=True)
    with patch.object(m, 'verify_account', side_effect=ValueError('identity rejected')):
        with pytest.raises(m.AcquisitionError, match='AccountMismatch'):
            rejected.verify()
    with pytest.raises(ValueError, match='account has not been verified'):
        rejected.call('cloudcontrol', 'list_resources', TypeName='AWS::DataZone::Domain')
    assert runner.call_count == 2


def check_all_target_profiles_precede_aws(tmp_path):
    targets = [dict(awsAccountId='123456789012', awsRegion='ap-northeast-1', directory=name) for name in ('first', 'second')]
    items = [(target, tmp_path / 'vpc.properties') for target in targets]
    factory = Mock()
    with patch.object(m, 'select_profile', side_effect=[None, ValueError('identity rejected')]) as select, \
            patch.object(m.subprocess, 'run') as process:
        with pytest.raises(ValueError, match='identity rejected'):
            m.run(tmp_path, items, profile='explicit', session_factory=factory)
        assert [call.args for call in select.call_args_list] == [(target, 'explicit') for target in targets]
    factory.assert_not_called()
    process.assert_not_called()

if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
