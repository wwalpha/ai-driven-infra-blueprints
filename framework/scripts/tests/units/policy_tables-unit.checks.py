#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.policy_tables_fixtures import *

@pytest.mark.parametrize(("logical_id", "role_id"), [
    ("cde-stg-example-role", "stg-example-role"),
    ("CDEIFINBOUNDGLUEROLE01", "ifinboundgluerole01"),
    ("cdemwaaexecutionrole01", "mwaaexecutionrole01"),
    ("RoleA", "role-a"),
    ("non-cde-role", "non-cde-role"),
    ("VPCFlowLogsToCloudWatchLogs", "vpc-flow-logs-to-cloud-watch-logs"),
])
def check_iam_artifact_names(logical_id, role_id):
    assert iam_role_policy_artifact_filename(logical_id) == f"{role_id}-trust-policy.json"
    assert iam_role_policy_artifact_filename(logical_id, "CDEAccess") == f"{role_id}-cde-access.json"


@pytest.mark.parametrize('property_name', ['KMS.Key.KeyPolicy', 'S3.BucketPolicy.PolicyDocument'])
@pytest.mark.parametrize('version', ['2012-10-17', '2008-10-17'])
def check_statement_metadata(property_name, version):
    from policy_tables import Policy, policy_document_lines
    document = {'Id': 'key-default', 'Version': version,
                'Statement': [{'Effect': 'Allow', 'Action': 'kms:DescribeKey', 'Resource': '*'}]}
    original = json.dumps(document)
    policy = Policy('ResourcePolicy', 'Policy', 'policy.json', 'policy', property_name)
    rendered = '\n'.join(policy_document_lines(document, policy))
    assert '| Id |' not in rendered and '| Version |' not in rendered
    assert '| No. | Effect | Action | Resource |' in rendered
    assert '`kms:DescribeKey`' in rendered
    assert json.dumps(document) == original


def check_lossless_generation():
    from policy_tables import Policy, policy_document_lines, validate_policy_document
    policy = Policy('ResourcePolicy', 'Policy', 'policy.json', 'policy', 'Logs.ResourcePolicy.PolicyDocument')
    document = {'PolicyDocument': {'Statement': [{'Effect': 'Unknown', 'Extra': {'keep': 1}}]}}
    rendered = '\n'.join(policy_document_lines(document, policy))
    assert json.dumps(document, ensure_ascii=False, indent=2) in rendered
    with pytest.raises(ValueError):
        validate_policy_document(document, policy)



@pytest.mark.parametrize('key', ['Resource', 'NotResource'])
@pytest.mark.parametrize('value', [{'unexpected': '*'}, [{'unexpected': '*'}], ['*', 1], None, 3, True])
def check_resource_types(key, value):
    from policy_tables import Policy, validate_policy_document
    policy = Policy('test', 'policy.json', 'test', 'policy', 'IAM.ManagedPolicy.PolicyDocument')
    with pytest.raises(ValueError, match=key + ' must be a string or string array'):
        validate_policy_document({'Statement': [{'Effect': 'Allow', 'Action': '*', key: value}]}, policy)


@pytest.mark.parametrize('key', ['Resource', 'NotResource'])
@pytest.mark.parametrize('value', ['*', ['arn:aws:s3:::bucket/${aws:username}', '*']])
def check_valid_resource_types(key, value):
    from policy_tables import Policy, validate_policy_document
    policy = Policy('test', 'policy.json', 'test', 'policy', 'IAM.ManagedPolicy.PolicyDocument')
    document = {'Statement': {'Effect': 'Allow', 'NotAction': ['s3:DeleteObject'], key: value,
        'Principal': {'AWS': ['111111111111']},
        'Condition': {'StringEquals': {'aws:username': '${aws:username}'}}}}
    validate_policy_document(document, policy)


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
