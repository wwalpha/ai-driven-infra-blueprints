"""Audit Adapter cases with separate SDK request and result contracts."""

from copy import deepcopy
from functools import partial
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

import pytest
from model.adapters import aws as m
from support.aws_sdk_cases import SdkCase

from model import audit_runtime as audit


def verified_context(stub, root, allowed):
    target = {
        "awsRegion": stub.context[1],
        "awsAccountId": stub.context[2],
        "environment": "fixture",
        "directory": "team",
    }
    session = SimpleNamespace(client=partial(stub.client, stub.context))
    context = m.Context(root, target, session=session, services=[])
    context.allowed.update(allowed)
    # Identity verification has its own UT; these synthetic cases isolate Adapter reads.
    context.verified = True
    return context


def macie_case(tmp_path, monkeypatch, case):
    data = case["data"]
    adapter = m.service_module("macie")
    resource = SimpleNamespace(
        current=Mock(return_value=data["current"]),
        value=Mock(return_value="fixture-job"),
    )
    with SdkCase(data, tmp_path, monkeypatch) as stub:
        context = verified_context(stub, tmp_path, adapter.APIS)
        if data["selection"] in {"missing", "ambiguous"}:
            error_type = (
                m.AcquisitionError if data["selection"] == "missing" else m.Unresolved
            )
            with pytest.raises(error_type) as caught:
                adapter.fetch(context, resource, "job")
            if error_type is m.AcquisitionError:
                TestCase().assertEqual(caught.value.status, "resource_missing")
            result = {
                "error": type(caught.value).__name__,
                "message": str(caught.value),
            }
        else:
            result = {"record": adapter.fetch(context, resource, "job")}
        stub.finish()
        TestCase().assertEqual(len(context.trace), len(data["steps"]))
        return {**result, "trace": context.trace}


def guardduty_case(tmp_path, monkeypatch, case):
    data = case["data"]
    adapter = m.service_module("guardduty")
    resource = SimpleNamespace(current=Mock(return_value="plan-1"))
    TestCase().assertNotIn(("cloudcontrol", "get_resource"), adapter.APIS)
    with SdkCase(data, tmp_path, monkeypatch) as stub:
        context = verified_context(stub, tmp_path, adapter.APIS)
        record = adapter.fetch(context, resource, "plan")
        resource.current.assert_called_once_with("MalwareProtectionPlanId")
        stub.finish()
        TestCase().assertEqual(len(context.trace), 1)
        return {"record": record, "trace": context.trace}


def guardduty_invalid_case(case):
    adapter = m.service_module("guardduty")
    TestCase().assertNotIn(("cloudcontrol", "get_resource"), adapter.APIS)
    resource = SimpleNamespace(current=Mock(return_value="plan-1"))
    context = SimpleNamespace(
        call=Mock(return_value=deepcopy(case["data"]["response"]))
    )
    with pytest.raises(ValueError, match="invalid GuardDuty plan Tags") as caught:
        adapter.fetch(context, resource, "plan")
    context.call.assert_called_once_with(
        "guardduty", "get_malware_protection_plan", MalwareProtectionPlanId="plan-1"
    )
    resource.current.assert_called_once_with("MalwareProtectionPlanId")
    return {"error": "ValueError", "message": str(caught.value)}


def endpoint_case(tmp_path, monkeypatch, case):
    data = case["data"]
    row = deepcopy(data["row"])
    before = deepcopy(data["row"])
    with SdkCase(data, tmp_path, monkeypatch) as stub:
        context = verified_context(stub, tmp_path, {("ec2", "describe_vpc_endpoints")})
        audit.resolve_endpoint_aliases(
            m, context, {"referenceRows": {"route53": {"001": row}}}
        )
        TestCase().assertEqual(
            context.trace,
            [
                {
                    "api": "ec2.describe_vpc_endpoints",
                    "inputs": {"VpcEndpointIds": ["vpce-123"]},
                    "pagination": "all",
                }
            ],
        )
        stub.finish()
        TestCase().assertEqual(data["row"], before)
        return {
            "row": row,
            "error": audit.resolution_error(row),
            "trace": context.trace,
        }
