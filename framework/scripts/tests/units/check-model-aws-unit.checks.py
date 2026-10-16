#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.check_model_aws_fixtures import *

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



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
