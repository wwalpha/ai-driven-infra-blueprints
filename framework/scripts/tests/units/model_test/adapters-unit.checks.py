import json
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from unittest import TestCase

import pytest
from botocore.exceptions import ClientError
from model.adapters.aws import AcquisitionError, Unresolved, sdk_error, service_module
from model.literal_values import normalize, value_shape
from support.check_model_aws_fixtures import m
from support.fixture_cases import load_case
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


class IamInlinePolicyTests(unittest.TestCase):
    def test_role_inline_outcomes(self):
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
            with self.subTest(case=case):
                ctx = Mock(import_mode=False)
                ctx.pages.return_value = {
                    "PolicyNames": [] if case == "missing_policy" else ["policy"]
                }
                ctx.fresh_pages.return_value = {
                    "PolicyNames": []
                    if case in {"missing_policy", "changed"}
                    else ["policy"]
                }
                ctx.call.return_value = {"PolicyDocument": {"Version": "2012-10-17"}}
                if case == "missing_role":
                    ctx.pages.side_effect = AcquisitionError(
                        "iam.list_role_policies", "NoSuchEntity", "resource_missing"
                    )
                if case in {"deleted", "denied"}:
                    ctx.call.side_effect = AcquisitionError(
                        "iam.get_role_policy",
                        "NoSuchEntity" if case == "deleted" else "AccessDenied",
                        "resource_missing"
                        if case == "deleted"
                        else "acquisition_failed",
                    )
                if case in {"present", "missing_policy"}:
                    result = adapter.fetch(ctx, resource, "inline")
                    self.assertEqual(
                        len(result["Policies"]), 1 if case == "present" else 0
                    )
                else:
                    with self.assertRaises(AcquisitionError) as raised:
                        adapter.fetch(ctx, resource, "inline")
                    self.assertEqual(
                        raised.exception.status,
                        "resource_missing"
                        if case == "missing_role"
                        else "acquisition_failed",
                    )
                self.assertEqual(
                    ctx.fresh_pages.call_count,
                    0 if case == "missing_role" else 2 if case == "deleted" else 1,
                )


class WriteOnlyArrayValidationTests(unittest.TestCase):
    def test_array_item_types(self):
        m = SimpleNamespace(
            normalize_literals=normalize,
            value_shape=value_shape,
            native_type_errors=native_type_errors,
            Unresolved=Unresolved,
        )
        row = {"property": "example"}
        snapshot = {
            "schemas": {"example": {"type": "array", "items": {"type": "string"}}}
        }
        for value, error in [
            (["SPARK"], None),
            ([123], "item 0"),
            (["SPARK", 123], "item 1"),
            ("SPARK", "must be array"),
        ]:
            with self.subTest(value=value):
                if error is None:
                    audit.validate_design_value(m, snapshot, row, value)
                else:
                    with self.assertRaisesRegex(Unresolved, error):
                        audit.validate_design_value(m, snapshot, row, value)


class FlowLogLookupTests(unittest.TestCase):
    def test_flow_log_selection(self):
        adapter = service_module("vpc")
        resource = Mock(kind="EC2.FlowLog")
        resource.current.return_value = None
        resource.value.return_value = "vpc-123"
        resource.rows_for.return_value = []
        ctx = Mock()
        record = {"FlowLogId": "fl-123", "TrafficType": "ALL"}
        ctx.pages.return_value = {"FlowLogs": [record]}
        self.assertEqual(adapter.fetch(ctx, resource, "base")["TrafficType"], "ALL")
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
        with self.assertRaises(Unresolved):
            adapter.fetch(ctx, resource, "base")
        ctx.pages.return_value = {"FlowLogs": []}
        with self.assertRaises(AcquisitionError) as missing:
            adapter.fetch(ctx, resource, "base")
        self.assertEqual(missing.exception.status, "resource_missing")
        ctx.pages.return_value = {
            "FlowLogs": [record, {**record, "LogGroupName": "other"}]
        }
        resource.rows_for.side_effect = (
            lambda prop: [1] if prop == "LogGroupName" else []
        )
        resource.value.side_effect = (
            lambda prop, *args: "wanted" if prop == "LogGroupName" else "vpc-123"
        )
        ctx.pages.return_value["FlowLogs"][0]["LogGroupName"] = "wanted"
        self.assertEqual(adapter.fetch(ctx, resource, "base")["LogGroupName"], "wanted")
        ctx.pages.return_value = {"FlowLogs": [{**record, "LogGroupName": "other"}]}
        with self.assertRaises(Unresolved):
            adapter.fetch(ctx, resource, "base")
        resource.rows_for.side_effect = None
        resource.rows_for.return_value = []
        resource.value.side_effect = None
        ctx.pages.return_value = {"FlowLogs": [record, record]}
        with self.assertRaises(Unresolved):
            adapter.fetch(ctx, resource, "base")
        ctx.pages.side_effect = AcquisitionError(
            "ec2.describe_flow_logs", "AccessDenied", "acquisition_failed"
        )
        with self.assertRaises(AcquisitionError) as denied:
            adapter.fetch(ctx, resource, "base")
        self.assertEqual(denied.exception.status, "acquisition_failed")
        ctx.pages.reset_mock(side_effect=True)
        resource.value.side_effect = AcquisitionError(
            "ec2.describe_vpcs", "ResourceNotFound", "resource_missing"
        )
        with self.assertRaises(Unresolved):
            adapter.fetch(ctx, resource, "base")
        ctx.pages.assert_not_called()
        resource.value.side_effect = None
        for invalid in (None, "UNSET", "vpc-", ["vpc-123"]):
            resource.value.return_value = invalid
            with self.assertRaises(Unresolved):
                adapter.fetch(ctx, resource, "base")
            ctx.pages.assert_not_called()
        resource.value.side_effect = Unresolved("ResourceId unresolved")
        with self.assertRaises(Unresolved):
            adapter.fetch(ctx, resource, "base")
        ctx.pages.assert_not_called()


class MacieLookupTests(unittest.TestCase):
    def test_job_lookup(self):
        adapter = service_module("macie")
        resource = Mock()
        resource.value.return_value = "fixture-job"
        ctx = Mock()
        ctx.call.return_value = {"name": "fixture-job"}
        resource.current.return_value = "confirmed-id"
        adapter.fetch(ctx, resource, "job")
        ctx.pages.assert_not_called()
        ctx.call.assert_called_once_with(
            "macie2", "describe_classification_job", jobId="confirmed-id"
        )
        resource.current.return_value = None
        ctx.reset_mock()
        ctx.pages.return_value = {
            "items": [{"name": "fixture-job", "jobId": "found-id"}]
        }
        adapter.fetch(ctx, resource, "job")
        ctx.pages.assert_called_once_with(
            "macie2",
            "list_classification_jobs",
            filterCriteria={
                "includes": [
                    {"key": "name", "comparator": "EQ", "values": ["fixture-job"]}
                ]
            },
        )
        ctx.call.assert_called_once_with(
            "macie2", "describe_classification_job", jobId="found-id"
        )
        for items, error in [
            ([], AcquisitionError),
            (
                [
                    {"name": "fixture-job", "jobId": "a"},
                    {"name": "fixture-job", "jobId": "b"},
                ],
                Unresolved,
            ),
        ]:
            with self.subTest(items=items):
                ctx.reset_mock()
                ctx.pages.return_value = {"items": items}
                with self.assertRaises(error):
                    adapter.fetch(ctx, resource, "job")
                ctx.call.assert_not_called()


class GuardDutyPlanAdapterTests(unittest.TestCase):
    def test_tags_normalization_and_invalid_types(self):
        adapter = service_module("guardduty")
        resource = SimpleNamespace(current=Mock(return_value="plan-1"))
        context = SimpleNamespace(call=Mock())
        tags = {"Name": "example", "Environment": "dev"}
        context.call.return_value = {"Tags": tags}
        record = adapter.fetch(context, resource, "plan")
        self.assertEqual(
            record["Tags"],
            [{"Key": key, "Value": value} for key, value in tags.items()],
        )
        self.assertEqual(record["MalwareProtectionPlanId"], "plan-1")
        context.call.return_value = {}
        self.assertEqual(adapter.fetch(context, resource, "plan")["Tags"], [])
        for tags in ([], {"Name": None}):
            context.call.return_value = {"Tags": tags}
            with self.subTest(tags=tags), self.assertRaises(ValueError):
                adapter.fetch(context, resource, "plan")
        self.assertNotIn(("cloudcontrol", "get_resource"), adapter.APIS)


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


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
