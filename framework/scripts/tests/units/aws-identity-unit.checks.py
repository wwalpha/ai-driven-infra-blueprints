#!/usr/bin/env python3
"""The Profile/Account decision matrix; no AWS acquisition or SDK state."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from support.pytest_cli import run
from utils.aws import identity

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

ACCOUNT = "123456789012"
EXECUTION = "999999999999"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr('socket.socket.connect', lambda *args: pytest.fail('AWS/network access forbidden'))
    monkeypatch.setattr('socket.socket.connect_ex', lambda *args: pytest.fail('AWS/network access forbidden'))


@pytest.mark.parametrize('profile', ['default', 'team-dev', 'team_dev', 'team.name', 'internal space'])
def check_valid_profile(profile):
    assert identity.validate_profile(profile) == profile


@pytest.mark.parametrize('value', [None, 123, False, [], {}, '', ' ', '\t', ' padded ', 'UNSET',
                                 '\nprofile', 'bad\nprofile', 'bad\rprofile', 'bad\0profile'])
def check_invalid_profile(value):
    with pytest.raises(identity.IdentityError, match='profile is invalid'):
        identity.validate_profile(value)
    # Neither an explicit valid profile nor Import's exception hides invalid configuration.
    with pytest.raises(identity.IdentityError, match='profile is invalid'):
        identity.select_profile({'awsProfile': value}, 'valid')
    with pytest.raises(identity.IdentityError, match='profile is invalid'):
        identity.import_profile({'awsProfile': value}, no_profile=True)
    if value is not None:  # None is the CLI/API's omitted argument, not an explicit string.
        with pytest.raises(identity.IdentityError, match='profile is invalid'):
            identity.select_profile({}, value)
        with pytest.raises(identity.IdentityError, match='profile is invalid'):
            identity.select_profile({'awsProfile': 'valid'}, value)


@pytest.mark.parametrize('target,explicit,expected', [
    ({}, None, None), ({'awsProfile': 'configured'}, None, 'configured'),
    ({}, 'explicit', 'explicit'), ({'awsProfile': 'same'}, 'same', 'same'),
])
def check_profile_selection(target, explicit, expected):
    assert identity.select_profile(target, explicit) == expected


def check_profile_conflict():
    with pytest.raises(identity.IdentityError, match='explicit AWS profile does not match target awsProfile'):
        identity.select_profile({'awsProfile': 'configured'}, 'other')


@pytest.mark.parametrize('target,no_profile,expected', [
    ({}, False, None), ({}, True, None),
    ({'awsProfile': 'configured'}, False, 'configured'), ({'awsProfile': 'configured'}, True, None),
])
def check_import_selection(target, no_profile, expected):
    before = dict(target)
    assert identity.import_profile(target, no_profile=no_profile) == expected
    assert target == before


@pytest.mark.parametrize('account', [ACCOUNT, '000000000000'])
def check_valid_account(account):
    assert identity.validate_account_id(account) == account


@pytest.mark.parametrize('value', [None, 123456789012, False, [], {}, '', 'UNSET', '123', '1234567890123',
                                 ' 123456789012', '123456789012\n', '１２３４５６７８９０１２'])
def check_invalid_account(value):
    with pytest.raises(identity.IdentityError, match='account ID is invalid'):
        identity.validate_account_id(value)
    with pytest.raises(identity.IdentityError, match='target AWS account ID is invalid'):
        identity.execution_account({'awsAccountId': value})
    with pytest.raises(identity.IdentityError, match='target AWS execution account ID is invalid'):
        identity.execution_account({'awsAccountId': ACCOUNT, 'awsExecutionAccountId': value})
    with pytest.raises(identity.IdentityError, match='account ID is invalid'):
        identity.verify_account({'awsAccountId': value}, ACCOUNT)


@pytest.mark.parametrize('target,expected', [
    ({'awsAccountId': ACCOUNT}, ACCOUNT),
    ({'awsAccountId': ACCOUNT, 'awsExecutionAccountId': EXECUTION}, EXECUTION),
])
def check_execution_account(target, expected):
    assert identity.execution_account(target) == expected
    assert identity.verify_account(target, expected) == expected


@pytest.mark.parametrize('caller', [ACCOUNT, None, 999999999999, 'bad', '９９９９９９９９９９９９'])
def check_sts_mismatch(caller):
    target = {'awsAccountId': ACCOUNT, 'awsExecutionAccountId': EXECUTION}
    with pytest.raises(identity.IdentityError, match='AWS account mismatch: expected ' + EXECUTION) as caught:
        identity.verify_account(target, caller)
    assert caught.value.code == 'AccountMismatch'
    assert caught.value.__cause__ is None


if __name__ == '__main__':
    raise SystemExit(run(__file__))
