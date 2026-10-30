#!/usr/bin/env python3
"""Offline executable adapter contracts and coverage evidence."""

import socket
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from aws_mapping import runtime_registry
from model.importing import adapter_contracts, coverage
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(
        socket.socket, "connect", Mock(side_effect=AssertionError("network forbidden"))
    )


def test_real_adapter_and_sdk_fixture_results():
    mapping = runtime_registry(ROOT, "quicksight")
    vpc = adapter_contracts.run(ROOT, mapping, "QuickSight.VPCConnection")
    dns = vpc["vpc"]["properties"]["QuickSight.VPCConnection.DnsResolvers"]
    assert dns["status"] == "verified"
    assert {
        "normal",
        "empty",
        "missing-value",
        "access-denied",
        "missing-selector",
        "account-mismatch",
    } <= set(dns["branches"])
    assert vpc["vpc"]["status"] == "unverified"
    group = adapter_contracts.run(ROOT, mapping, "QuickSight.Group")
    assert (
        group["sdk-quicksight-group"]["properties"]["QuickSight.Group.GroupName"][
            "status"
        ]
        == "verified"
    )
    assert group["sdk-quicksight-group"]["status"] == "unverified"


def test_new_mapping_property_stays_unverified():
    mapping = runtime_registry(ROOT, "quicksight")
    original = mapping.properties["QuickSight.VPCConnection.DnsResolvers"]
    added = replace(original, field=replace(original.field, path="NewField"))
    copy = SimpleNamespace(
        service="quicksight",
        properties={**mapping.properties, "QuickSight.VPCConnection.NewField": added},
        getters=mapping.getters,
    )
    result = adapter_contracts.run(ROOT, copy, "QuickSight.VPCConnection")
    assert (
        result["vpc"]["properties"]["QuickSight.VPCConnection.NewField"]["status"]
        == "unverified"
    )
    missing = replace(original, field=replace(original.field, getter="not-registered"))
    copy.properties["QuickSight.VPCConnection.NewField"] = missing
    result = adapter_contracts.run(ROOT, copy, "QuickSight.VPCConnection")
    assert result["not-registered"]["status"] == "broken"


def test_failed_fixture_is_broken_and_coverage_keeps_levels(monkeypatch):
    monkeypatch.setattr(
        adapter_contracts,
        "vpc_fixture",
        Mock(side_effect=ValueError("fixture failure")),
    )
    result = coverage.report(ROOT, "quicksight")
    vpc = next(
        item
        for item in result["resources"]
        if item["resourceType"] == "QuickSight.VPCConnection"
    )
    dns = next(
        item
        for item in vpc["propertyDiagnostics"]
        if item["property"].endswith(".DnsResolvers")
    )
    assert dns["adapterContract"]["status"] == "broken"
    assert dns["status"] == "capturable"
    assert result["runtimeVerified"] is False
    assert result["summary"]["adapterContractGetters"]["broken"] >= 1


def test_fake_context_rejects_invalid_and_unknown_requests():
    fake = adapter_contracts.FakeCalls(
        SimpleNamespace(allowed={("quicksight", "describe_vpc_connection")}), {}
    )
    with pytest.raises(ValueError):
        fake.request(
            "quicksight",
            "describe_vpc_connection",
            {"AwsAccountId": 123, "VPCConnectionId": "x"},
        )
    with pytest.raises(ValueError, match="allowlist"):
        fake.request("quicksight", "delete_vpc_connection", {})


if __name__ == "__main__":
    raise SystemExit(run(__file__))
