"""Successful KMS checks are private to one ordered service validation."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import aws_mapping_display
import model.validation as validation
import pytest
import validation.design as design

import model as _imports_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def inputs():
    arn = "arn:aws:iam::222222222222:root"
    return {
        "desired.resource.001.resourceType": "KMS.Key",
        "desired.resource.001.resourceMode": "CREATE",
        "desired.row.001-001.property": "KMS.Key.KeyPolicy",
        "desired.row.001-001.value": "[Policy](kms/policy.json)",
        "desired.row.001-001.document": json.dumps(
            {"Statement": {"Effect": "Allow", "Principal": {"AWS": arn}}}
        ),
    }, {"awsAccountId": "111111111111", "awsExecutionAccountId": "222222222222"}


def check_success_invalidation_and_scope():
    values, target = inputs()
    check = validation._kms_policy_account_check()
    with patch.object(
        validation,
        "validate_kms_policy_accounts",
        wraps=validation.validate_kms_policy_accounts,
    ) as actual:
        check(values, target)
        check(dict(values), dict(target))
        assert actual.call_count == 1
        values["desired.row.001-001.comment"] = "変更"
        check(values, target)
        target["awsRegion"] = "ap-northeast-1"
        check(values, target)
        check(dict(reversed(list(values.items()))), target)
        check(values, dict(reversed(list(target.items()))))
        validation._kms_policy_account_check()(values, target)
        assert actual.call_count == 6
        target["awsExecutionAccountId"] = "333333333333"
        for _ in range(2):
            with pytest.raises(ValueError, match="Principal.AWS"):
                check(values, target)
        assert actual.call_count == 8
        values["desired.row.001-001.document"] = '{"Statement": null}'
        for _ in range(2):
            with pytest.raises(ValueError, match="must be an object"):
                check(values, target)
        assert actual.call_count == 10


@pytest.mark.parametrize(
    "document",
    [
        '{"Statement":[],"Statement":[]}',
        '{"Statement":NaN}',
        "[]",
        "null",
        '{"Statement":[0]}',
        '{"Statement":null}',
    ],
)
def check_strict_documents_repeat_failure(document):
    values, target = inputs()
    values["desired.row.001-001.document"] = document
    check = validation._kms_policy_account_check()
    errors = []
    for function in (validation.validate_kms_policy_accounts, check, check):
        with pytest.raises(ValueError) as error:
            function(values, target)
        errors.append(str(error.value))
    assert errors[0] == errors[1] == errors[2]


def check_no_kms_still_parses_malformed_rows():
    values = {"desired.row.001-001": "malformed"}
    target = {"awsAccountId": "111111111111"}
    check = validation._kms_policy_account_check()
    for function in (validation.validate_kms_policy_accounts, check, check):
        with pytest.raises(ValueError):
            function(values, target)


def check_service_reuse_and_direct_call_diagnostics(tmp_path, monkeypatch):
    model = _imports_model
    model = _imports_model
    model = _imports_model
    model = _imports_model
    model = _imports_model

    values, target = inputs()
    values["desired.resource.002.resourceType"] = "KMS.Key"
    values["desired.resource.002.resourceMode"] = "IMPORT"
    monkeypatch.setattr(model.core, "validate_authority", lambda *a: None)
    monkeypatch.setattr(model.core, "validate_runtime_keys", lambda *a: None)
    monkeypatch.setattr(model.sources, "runtime_values", lambda v: v)
    monkeypatch.setattr(model.files, "resource_row_index", lambda *a: None)
    monkeypatch.setattr(
        validation, "validate_required_properties", lambda *a, **k: None
    )
    monkeypatch.setattr(aws_mapping_display, "validate_mappings", lambda *a: None)
    monkeypatch.setattr(validation, "resource_rows", lambda *a: [])
    monkeypatch.setattr(validation, "naming_errors", lambda *a: [])
    monkeypatch.setattr(validation, "catalog_outputs", lambda *a: {"KMS.Key.KeyPolicy"})
    monkeypatch.setattr(validation, "DesignSchemaCatalog", lambda *a: None)
    monkeypatch.setattr(design, "check_observed_values", lambda *a, **k: None)
    monkeypatch.setattr(model.render, "resource_details", lambda *a, **k: None)
    monkeypatch.setattr(validation, "bound_resource_anchors", lambda *a: {})
    monkeypatch.setattr(validation, "design_target", lambda *a: dict(target))
    path = tmp_path / "model/dev/target/kms.properties"
    with patch.object(
        validation,
        "validate_kms_policy_accounts",
        wraps=validation.validate_kms_policy_accounts,
    ) as actual:
        first = validation.check_model_inputs(path, values, tmp_path)
        assert not first.errors, first.errors
        assert actual.call_count == 1
        validation.check_model_inputs(path, values, tmp_path)
        assert actual.call_count == 2
        for _ in range(2):
            validation.validate_resource_identities(path, values, tmp_path, [])
        assert actual.call_count == 4
        target["awsExecutionAccountId"] = "333333333333"
        findings = validation.check_model_inputs(path, values, tmp_path)
        assert actual.call_count == 6
        assert len(findings.errors) == 2 and findings.errors[0] == findings.errors[1]
        with patch.object(
            validation,
            "_kms_policy_account_check",
            return_value=validation.validate_kms_policy_accounts,
        ):
            baseline = validation.check_model_inputs(path, values, tmp_path)
        assert (
            findings.errors == baseline.errors
            and findings.warnings == baseline.warnings
        )


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
