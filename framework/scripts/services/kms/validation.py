"""KMS KeyPolicy account constraints applied to CREATE Resources."""

import re

from contracts.model import RESOURCE_MODE_CREATE, RESOURCE_TYPE_KEY
from contracts.target import AWS_ACCOUNT_ID_KEY, AWS_EXECUTION_ACCOUNT_ID_KEY
from design import layout
from model.core import entries
from utils.json_format import policy_json
from validation.diagnostics import InputValidationError


def validate_kms_policy_accounts(values: dict[str, str], target: dict) -> None:
    """CREATE の KMS Policy についてアカウントと明示された例外を確認する。"""
    if not target:
        return
    execution = target.get(AWS_EXECUTION_ACCOUNT_ID_KEY, target[AWS_ACCOUNT_ID_KEY])
    keys = {
        identity
        for identity, resource in entries(values, "desired.resource.")
        if resource[RESOURCE_TYPE_KEY] == "KMS.Key"
        and layout.resource_mode(resource) == RESOURCE_MODE_CREATE
    }
    for identity, row in entries(values, "desired.row."):
        if (
            not any(identity.startswith(key + "-") for key in keys)
            or row.get("property") != "KMS.Key.KeyPolicy"
            or "document" not in row
        ):
            continue
        external = set(
            re.findall(
                r"\bcross-account:(arn:[A-Za-z0-9_+=,.@:/-]+)(?=$|[\s`])",
                row.get("comment", ""),
            )
        )
        document = policy_json(row["document"])
        if not isinstance(document, dict):
            raise InputValidationError(
                f"KMS.Key.KeyPolicy {identity}: document must be an object"
            )
        statements = document.get("Statement", [])
        for number, statement in enumerate(
            statements if isinstance(statements, list) else [statements], 1
        ):
            if not isinstance(statement, dict):
                raise InputValidationError(
                    f"KMS.Key.KeyPolicy {identity} Statement[{number}]: must be an object"
                )
            if statement.get("Effect") != "Allow":
                continue
            principal = statement.get("Principal", {})
            principals = principal.get("AWS", []) if isinstance(principal, dict) else []
            for arn in principals if isinstance(principals, list) else [principals]:
                match = re.fullmatch(
                    r"arn:[^:]+:iam::([0-9]{12}):(root|role/aws-service-role/macie(?:\.[a-z0-9-]+)?\.amazonaws\.com/AWSServiceRoleForAmazonMacie)",
                    str(arn),
                )
                if match and match[1] != execution and arn not in external:
                    raise InputValidationError(
                        f"KMS.Key.KeyPolicy {identity} Statement[{number}] Principal.AWS: {arn}: "
                        f"must use AWS execution account {execution}; explicit cross-account grant requires "
                        f"cross-account:{arn} in the policy row comment"
                    )
