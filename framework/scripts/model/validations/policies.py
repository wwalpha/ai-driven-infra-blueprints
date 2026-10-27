"""Model 検証: policies。"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

import design.layout as _dependency_design_layout
import design.policy_tables as _dependency_policy_tables
from design.services.definitions.registry import POLICY_FORMATS
from utils.json_format import policy_json
from validation.diagnostics import Diagnostic, InputValidationError, service_scope
from validation.findings import Findings

from model.core import (
    entries,
)


def validate_kms_policy_accounts(values: dict[str, str], target: dict) -> None:
    """CREATE の KMS Policy についてアカウントと明示された例外を確認する。"""
    if not target:
        return
    execution = target.get("awsExecutionAccountId", target["awsAccountId"])
    keys = {
        identity
        for identity, resource in entries(values, "desired.resource.")
        if resource["resourceType"] == "KMS.Key"
        and _dependency_design_layout.resource_mode(resource) == "CREATE"
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


def _callback__kms_policy_account_check_check(
    _state__kms_policy_account_check_266: _CallbackState,
    /,
    values: dict[str, str],
    target: dict,
) -> None:
    """直前に成功した同順序の入力だけを再利用し、失敗は保存しない。"""
    pass
    inputs = (tuple(values.items()), tuple(target.items()))
    if inputs != _state__kms_policy_account_check_266.successful:
        validate_kms_policy_accounts(values, target)
        _state__kms_policy_account_check_266.successful = inputs


def _kms_policy_account_check() -> Callable[[dict[str, str], dict], None]:
    """同一サービス内で直前の成功した KMS 判定だけを再利用する。"""
    _state__kms_policy_account_check_266 = _CallbackState()
    _state__kms_policy_account_check_266.successful = None

    check = _bind_framework_callback(
        _callback__kms_policy_account_check_check, _state__kms_policy_account_check_266
    )

    return check


def _check_policy_setting(
    row: dict,
    rid: str,
    policy: _dependency_policy_tables.Policy,
    findings: Findings,
    path: Path,
) -> None:
    """Policy Document の不正を既存の診断 ID で記録する。"""
    try:
        _dependency_policy_tables.validate_policy_document(
            policy_json(row["document"]), policy, design=True
        )
    except ValueError as error:
        findings.add_diagnostic(
            Diagnostic.create(
                findings.canonical_root,
                code="model.policy.invalid",
                cause_kind="input_invalid",
                check_id="model.policy." + rid,
                service=service_scope(findings.canonical_root, path),
                source_path=path,
                location=f"desired.row.{rid}.document",
                message=str(error),
            )
        )


def check_policy_settings(
    values: dict[str, str], findings: Findings, path: Path
) -> None:
    """Policy Document を持つ対象 Row を順に検証する。"""
    for rid, row in entries(values, "desired.row."):
        if row["property"] not in POLICY_FORMATS or "document" not in row:
            continue
        policy = _dependency_policy_tables.Policy(
            row["property"], row["value"], "", "", row["property"]
        )
        findings.evaluate(
            "model.policy." + rid,
            None,
            _bind_framework_callback(
                _check_policy_setting, row, rid, policy, findings, path
            ),
        )
