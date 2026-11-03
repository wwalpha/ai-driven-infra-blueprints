import ast
import json
import subprocess
import sys
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from unittest import TestCase

import pytest
from botocore.exceptions import ClientError
from model.adapters import aws as adapter_aws
from model.adapters.aws import AcquisitionError, Unresolved, sdk_error, service_module
from model.audit import generate
from model.literal_values import normalize, value_shape
from support.aws_sdk_cases import SdkCase
from support.check_model_aws_fixtures import m
from support.fixture_cases import load_case
from support.model_sources import write_model
from support.model_test_adapter_cases import (
    guardduty_case,
    guardduty_invalid_case,
    macie_case,
    verified_context,
)
from support.model_test_references import ReferenceFixture
from support.regression_cases import case_ids
from utils.cloudformation.schema import native_type_errors

from model import audit_runtime as audit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


class SdkErrorTests(unittest.TestCase):
    def test_cli_structured_errors_match_sdk(self):
        message = "private secret"
        for code, status in (
            ("ResourceNotFoundException", "resource_missing"),
            ("AccessDeniedException", "acquisition_failed"),
            ("ValidationError", "acquisition_failed"),
        ):
            error = subprocess.CalledProcessError(
                1, "aws", stderr=json.dumps({"Code": code, "Message": message})
            )
            result = sdk_error("lambda.get_function", error, ())
            self.assertEqual((result.code, result.status), (code, status))
            self.assertNotIn(message, str(result))

    def test_cli_throttling_retries_and_uses_json_format(self):
        target = {"awsAccountId": "123456789012", "awsRegion": "us-east-1"}
        replies = [
            SimpleNamespace(
                returncode=1,
                stderr=json.dumps({"Code": "ThrottlingException", "Message": "secret"}),
                stdout="",
            ),
            SimpleNamespace(returncode=0, stdout='{"Exports": []}', stderr=""),
        ]
        runner = Mock(side_effect=replies)
        ctx = m.Context(Path.cwd(), target, cli_runner=runner, services=[])
        ctx.allowed.add(("cloudformation", "list_exports"))
        ctx.verified = True
        with (
            patch("utils.aws.client.time.sleep"),
            patch("utils.aws.client.random.uniform", return_value=0),
        ):
            self.assertEqual(
                ctx.call("cloudformation", "list_exports"), {"Exports": []}
            )
        self.assertEqual(runner.call_count, 2)
        self.assertTrue(
            all(
                (
                    call.kwargs["env"]["AWS_CLI_ERROR_FORMAT"] == "json"
                    for call in runner.call_args_list
                )
            )
        )

    def test_cli_errors_do_not_recover_codes(self):
        for code in (
            "ResourceNotFoundException",
            "AccessDeniedException",
            "ThrottlingException",
        ):
            error = subprocess.CalledProcessError(
                254,
                "aws",
                stderr=f"An error occurred ({code}) when calling GetFunction: secret",
            )
            result = sdk_error("lambda.get_function", error, ())
            self.assertEqual(
                (result.code, result.status), ("AwsCliError", "acquisition_failed")
            )
            self.assertNotIn("secret", str(result))


@pytest.mark.parametrize(
    "case_id", case_ids("model_test_sdk_errors", prefix="sdk-error-")
)
def test_sdk_error_classification(case_runner, case_id):
    case_runner.run("model_test_sdk_errors", case_id, _execute_sdk_error_case)


def _execute_sdk_error_case(case):
    data = case["data"]
    error = ClientError(
        {"Error": {"Code": data["code"], "Message": data["message"]}}, data["operation"]
    )
    before = deepcopy(error.response)
    request = tuple(data["request"])
    result = sdk_error(data["api"], error, request)
    TestCase().assertIs(type(result), AcquisitionError)
    TestCase().assertIs(result.request, request)
    TestCase().assertEqual(error.response, before)
    if data["message"] in str(result):
        pytest.fail("SDK error exposed private message before snapshot", pytrace=False)
    return {
        "api": result.api,
        "code": result.code,
        "status": result.status,
        "message": str(result),
    }


def test_sdk_error_secret_failure_before_snapshot(monkeypatch):
    case = load_case("model_test_sdk_errors", "sdk-error-denied")
    secret = case["data"]["message"]
    unsafe = AcquisitionError(case["data"]["api"], secret, request=())
    monkeypatch.setitem(
        _execute_sdk_error_case.__globals__, "sdk_error", Mock(return_value=unsafe)
    )
    with pytest.raises(pytest.fail.Exception, match="private message") as caught:
        _execute_sdk_error_case(case)
    TestCase().assertNotIn(secret, str(caught.value))


def test_role_inline_outcomes(subtests):
    adapter = service_module("iam")
    resource = SimpleNamespace(kind="IAM.Role", value=lambda key: "role")
    for case in (
        "present",
        "missing_policy",
        "missing_role",
        "deleted",
        "denied",
        "changed",
    ):
        with subtests.test(case=case):
            ctx = Mock(import_mode=False)
            ctx.pages.return_value = {
                "PolicyNames": [] if case == "missing_policy" else ["policy"]
            }
            ctx.fresh_pages.return_value = {
                "PolicyNames": []
                if case in {"missing_policy", "changed"}
                else ["policy"]
            }
            ctx.call.return_value = load_case("model_test_sdk_errors", "iam-input")[
                "data"
            ]["response"]
            if case == "missing_role":
                ctx.pages.side_effect = AcquisitionError(
                    "iam.list_role_policies", "NoSuchEntity", "resource_missing"
                )
            if case in {"deleted", "denied"}:
                ctx.call.side_effect = AcquisitionError(
                    "iam.get_role_policy",
                    "NoSuchEntity" if case == "deleted" else "AccessDenied",
                    "resource_missing" if case == "deleted" else "acquisition_failed",
                )
            if case in {"present", "missing_policy"}:
                result = adapter.fetch(ctx, resource, "inline")
                TestCase().assertEqual(
                    len(result["Policies"]), 1 if case == "present" else 0
                )
            else:
                with TestCase().assertRaises(AcquisitionError) as raised:
                    adapter.fetch(ctx, resource, "inline")
                TestCase().assertEqual(
                    raised.exception.status,
                    "resource_missing"
                    if case == "missing_role"
                    else "acquisition_failed",
                )
            TestCase().assertEqual(
                ctx.fresh_pages.call_count,
                0 if case == "missing_role" else 2 if case == "deleted" else 1,
            )


def test_array_item_types(subtests):
    m = SimpleNamespace(
        normalize_literals=normalize,
        value_shape=value_shape,
        native_type_errors=native_type_errors,
        Unresolved=Unresolved,
    )
    row = {"property": "example"}
    snapshot = {"schemas": {"example": {"type": "array", "items": {"type": "string"}}}}
    for value, error in [
        (["SPARK"], None),
        ([123], "item 0"),
        (["SPARK", 123], "item 1"),
        ("SPARK", "must be array"),
    ]:
        with subtests.test(value=value):
            if error is None:
                audit.validate_design_value(m, snapshot, row, value)
            else:
                with TestCase().assertRaisesRegex(Unresolved, error):
                    audit.validate_design_value(m, snapshot, row, value)


def test_flow_log_selection():
    adapter = service_module("vpc")
    resource = Mock(kind="EC2.FlowLog")
    resource.current.return_value = None
    resource.value.return_value = "vpc-123"
    resource.rows_for.return_value = []
    ctx = Mock()
    record = load_case("model_test_sdk_errors", "flowlog-input")["data"]["record"]
    ctx.pages.return_value = {"FlowLogs": [record]}
    TestCase().assertEqual(adapter.fetch(ctx, resource, "base")["TrafficType"], "ALL")
    ctx.pages.assert_called_with(
        "ec2",
        "describe_flow_logs",
        Filter=[{"Name": "resource-id", "Values": ["vpc-123"]}],
    )
    resource.current.return_value = "fl-123"
    adapter.fetch(ctx, resource, "base")
    ctx.pages.assert_called_with("ec2", "describe_flow_logs", FlowLogIds=["fl-123"])
    resource.current.return_value = None
    ctx.pages.return_value = {}
    with TestCase().assertRaises(Unresolved):
        adapter.fetch(ctx, resource, "base")
    ctx.pages.return_value = {"FlowLogs": []}
    with TestCase().assertRaises(AcquisitionError) as missing:
        adapter.fetch(ctx, resource, "base")
    TestCase().assertEqual(missing.exception.status, "resource_missing")
    ctx.pages.return_value = {"FlowLogs": [record, {**record, "LogGroupName": "other"}]}
    resource.rows_for.side_effect = lambda prop: [1] if prop == "LogGroupName" else []
    resource.value.side_effect = (
        lambda prop, *args: "wanted" if prop == "LogGroupName" else "vpc-123"
    )
    ctx.pages.return_value["FlowLogs"][0]["LogGroupName"] = "wanted"
    TestCase().assertEqual(
        adapter.fetch(ctx, resource, "base")["LogGroupName"], "wanted"
    )
    ctx.pages.return_value = {"FlowLogs": [{**record, "LogGroupName": "other"}]}
    with TestCase().assertRaises(Unresolved):
        adapter.fetch(ctx, resource, "base")
    resource.rows_for.side_effect = None
    resource.rows_for.return_value = []
    resource.value.side_effect = None
    ctx.pages.return_value = {"FlowLogs": [record, record]}
    with TestCase().assertRaises(Unresolved):
        adapter.fetch(ctx, resource, "base")
    ctx.pages.side_effect = AcquisitionError(
        "ec2.describe_flow_logs", "AccessDenied", "acquisition_failed"
    )
    with TestCase().assertRaises(AcquisitionError) as denied:
        adapter.fetch(ctx, resource, "base")
    TestCase().assertEqual(denied.exception.status, "acquisition_failed")
    ctx.pages.reset_mock(side_effect=True)
    resource.value.side_effect = AcquisitionError(
        "ec2.describe_vpcs", "ResourceNotFound", "resource_missing"
    )
    with TestCase().assertRaises(Unresolved):
        adapter.fetch(ctx, resource, "base")
    ctx.pages.assert_not_called()
    resource.value.side_effect = None
    for invalid in (None, "UNSET", "vpc-", ["vpc-123"]):
        resource.value.return_value = invalid
        with TestCase().assertRaises(Unresolved):
            adapter.fetch(ctx, resource, "base")
        ctx.pages.assert_not_called()
    resource.value.side_effect = Unresolved("ResourceId unresolved")
    with TestCase().assertRaises(Unresolved):
        adapter.fetch(ctx, resource, "base")
    ctx.pages.assert_not_called()


@pytest.mark.parametrize("case_id", case_ids("model_test_sdk_errors", prefix="macie-"))
def test_macie_job_lookup(case_runner, tmp_path, monkeypatch, case_id):
    case_runner.run(
        "model_test_sdk_errors", case_id, partial(macie_case, tmp_path, monkeypatch)
    )


@pytest.mark.parametrize(
    "case_id",
    case_ids("model_test_sdk_errors", prefix="guardduty-tags")
    + case_ids("model_test_sdk_errors", prefix="guardduty-missing"),
)
def test_guardduty_plan_tags(case_runner, tmp_path, monkeypatch, case_id):
    case_runner.run(
        "model_test_sdk_errors", case_id, partial(guardduty_case, tmp_path, monkeypatch)
    )


@pytest.mark.parametrize(
    "case_id",
    case_ids("model_test_sdk_errors", prefix="guardduty-null")
    + case_ids("model_test_sdk_errors", prefix="guardduty-list")
    + case_ids("model_test_sdk_errors", prefix="guardduty-invalid"),
)
def test_guardduty_plan_invalid_tags(case_runner, case_id):
    case_runner.run("model_test_sdk_errors", case_id, guardduty_invalid_case)


def test_adapter_read_only_scope_precedes_sdk(tmp_path, monkeypatch):
    data = load_case("model_test_sdk_errors", "macie-confirmed")["data"]
    with SdkCase(data, tmp_path, monkeypatch) as stub:
        context = verified_context(stub, tmp_path, service_module("macie").APIS)
        with patch.object(
            stub.clients["adapter"],
            "_make_api_call",
            side_effect=AssertionError("forbidden SDK dispatch"),
        ) as dispatch:
            with pytest.raises(ValueError, match="read-only"):
                context.call("macie2", "create_classification_job")
            dispatch.assert_not_called()
        context.call("macie2", "describe_classification_job", jobId="confirmed-id")


def test_adapter_extra_api_fails_before_result(tmp_path, monkeypatch):
    data = load_case("model_test_sdk_errors", "macie-confirmed")["data"]
    with SdkCase(data, tmp_path, monkeypatch) as stub:
        context = verified_context(stub, tmp_path, service_module("macie").APIS)
        with pytest.raises(adapter_aws.AcquisitionError) as caught:
            context.call("macie2", "get_macie_session")
        TestCase().assertEqual(caught.value.code, "StubResponseError")
        context.call("macie2", "describe_classification_job", jobId="confirmed-id")


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))


def test_secrets_rotation_parent_reference():
    adapter = service_module("secrets-manager")
    parent = SimpleNamespace(
        kind="SecretsManager.Secret",
        model=SimpleNamespace(path=Path("secret")),
        number="001",
        value=Mock(return_value="parent-name"),
    )
    other = SimpleNamespace(kind=parent.kind, model=parent.model, number="002")
    ref = {"$modelRef": {"logicalId": "Secret_001", "attribute": "Id"}}
    resource = SimpleNamespace(
        kind="SecretsManager.RotationSchedule",
        parent=Mock(return_value=parent),
        rows_for=Mock(return_value=[("001", {"value": "`" + json.dumps(ref) + "`"})]),
        reference=Mock(return_value=parent),
        value=Mock(side_effect=Unresolved("logical_only")),
    )
    response = {"RotationRules": {"AutomaticallyAfterDays": 30}}
    ctx = SimpleNamespace(call=Mock(return_value=response))
    assert adapter.fetch(ctx, resource, "base") == response
    ctx.call.assert_called_once_with(
        "secretsmanager", "describe_secret", SecretId="parent-name"
    )
    resource.value.assert_not_called()
    resource.reference.return_value = other
    ctx.call.reset_mock()
    with pytest.raises(Unresolved, match="does not identify its parent"):
        adapter.fetch(ctx, resource, "base")
    ctx.call.assert_not_called()
    resource.reference.return_value = parent
    ctx.call.side_effect = AcquisitionError(
        "secretsmanager.describe_secret", "AccessDenied", "acquisition_failed"
    )
    with pytest.raises(AcquisitionError):
        adapter.fetch(ctx, resource, "base")


def test_secrets_rotation_generated_audit(tmp_path):
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "projectName": "fixture",
                "targets": [
                    {
                        "environment": "dev",
                        "alias": "cde",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    model = ReferenceFixture.model
    ref = ReferenceFixture.ref("SecretsManager_Secret_001", "Id")
    values = model(
        "SecretsManager.Secret", "SecretsManager_Secret_001", {"Name": "fixture-secret"}
    )
    schedule = model(
        "SecretsManager.RotationSchedule",
        "SecretsManager_RotationSchedule_001",
        {
            "SecretId": ref,
            "RotationRules.AutomaticallyAfterDays": "30",
            "RotationRules.Duration": "2h",
        },
    )
    for key, value in schedule.items():
        if key.startswith("desired.resource.001.") or key.startswith(
            "desired.row.001-"
        ):
            values[key.replace(".001", ".002", 1)] = value
    values["desired.service.identity.lastAllocated"] = json.dumps(
        {"SecretsManager.Secret": 1, "SecretsManager.RotationSchedule": 1}
    )
    values["desired.resource.002.parentReference"] = json.dumps(ref)
    values["desired.resource.002.parentProperty"] = (
        "SecretsManager.RotationSchedule.SecretId"
    )
    write_model(tmp_path / "model/dev/cde/secrets-manager.properties", values)
    source = generate(tmp_path, "dev", "cde", "secrets-manager")[0]
    snapshot = json.loads(ast.literal_eval(ast.parse(source).body[1].value.args[0]))
    calls = []

    def cli(command, **kwargs):
        calls.append(command)
        if command[1] == "sts":
            result = {
                "Account": "123456789012",
                "Arn": "arn:aws:iam::123456789012:user/offline",
            }
        else:
            result = {
                "Name": "fixture-secret",
                "ARN": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:fixture",
                "RotationRules": {"AutomaticallyAfterDays": 60, "Duration": "2h"},
                "SecretString": "never-print-secret-value",
            }
        return subprocess.CompletedProcess(command, 0, json.dumps(result), "")

    records = audit.audit(snapshot, cli_runner=cli)[2]
    selected = {
        item["propertiesKey"].rsplit(".", 1)[-1]: item
        for item in records
        if item["propertiesKey"].startswith("SecretsManager.RotationSchedule.")
    }
    assert selected["SecretId"]["status"] == "design_unresolved", selected
    assert selected["AutomaticallyAfterDays"]["status"] == "difference", selected
    assert selected["Duration"]["status"] == "match", selected
    assert all(
        command[1] in {"sts", "secretsmanager"}
        and (command[1] != "secretsmanager" or command[2] == "describe-secret")
        for command in calls
    )
    report, _ = audit.report(
        snapshot, None, "account", records, datetime.now(timezone.utc)
    )
    assert "never-print-secret-value" not in report

    def denied(command, **kwargs):
        if command[1] == "sts":
            return cli(command, **kwargs)
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            json.dumps(
                {"Code": "AccessDeniedException", "Message": "never-print-secret-value"}
            ),
        )

    failed = audit.audit(snapshot, cli_runner=denied)[2]
    days = next(
        item
        for item in failed
        if item["propertiesKey"].endswith(".AutomaticallyAfterDays")
    )
    assert days["status"] == "acquisition_failed", days
    report, _ = audit.report(
        snapshot, None, "account", failed, datetime.now(timezone.utc)
    )
    assert "never-print-secret-value" not in report
