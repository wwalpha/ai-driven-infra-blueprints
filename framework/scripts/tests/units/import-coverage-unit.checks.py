#!/usr/bin/env python3
"""Small in-memory Mapping/SDK/Schema capability cases; no AWS, Model or Git writes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import socket
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from aws_mapping import Registry
from design.catalog import DesignSchemaCatalog
from model.cli import main
from model.importing import coverage, discovery, inventory
from support.fixture_cases import load_case
from support.pytest_cli import run
from utils.mapping_runtime import runtime_properties

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


class Schemas:
    api_paths = {}
    resource_types = {}

    def __init__(self, root, definitions):
        self.root = root
        self.directory = root
        self.definitions = definitions

    def cloudformation(self, name):
        return self.definitions[name.removeprefix("AWS::").replace("::", ".", 1)]


class Sdk:
    operation_names = ["ListItems", "DescribeItem"]

    def service_model(self, service):
        return self

    def operation_model(self, operation):
        item = SimpleNamespace(
            type_name="structure",
            members={
                key: SimpleNamespace(type_name="string")
                for key in ("Id", "Name", "Tenant")
            },
        )
        shape = SimpleNamespace(
            type_name="structure",
            members={
                "Items": SimpleNamespace(type_name="list", member=item),
                "Item": item,
            },
        )
        return SimpleNamespace(
            output_shape=shape,
            input_shape=SimpleNamespace(
                required_members=["Id"] if operation == "DescribeItem" else [],
                members={"Id": SimpleNamespace(type_name="string")},
            ),
        )


def fetch(ctx, resource, getter):
    raise ValueError("No declarative getter branch proof")


def fetch_sdk(ctx, resource, operation):
    return ctx.call("fixture", operation, Id=resource.value("Id"))


def conditional_sdk(ctx, resource, operation):
    if resource.kind == "Test.Item":
        return ctx.call("fixture", operation, Id=resource.value("Id"))
    raise ValueError("Unknown kind")


def mapping(root, document):
    return Registry(
        root, "fixture", document, runtime_properties(root, "fixture", document)
    )


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(
        socket.socket,
        "connect",
        Mock(side_effect=AssertionError("AWS/network forbidden")),
    )


@pytest.fixture
def case(tmp_path, monkeypatch):
    data = load_case("import-coverage", "defaults")["data"]
    inspector = coverage.Coverage.__new__(coverage.Coverage)
    inspector.root = tmp_path
    inspector.schemas = Schemas(tmp_path, {"Test.Item": data["schema"]})
    inspector.sdk = Sdk()
    inspector.catalog = DesignSchemaCatalog(tmp_path, definitions=inspector.schemas)
    adapter = SimpleNamespace(
        APIS={("fixture", "describe_item")},
        SDK_OPERATIONS={"Test.Item": "describe_item"},
        fetch=fetch,
        fetch_sdk=fetch_sdk,
    )
    inspector.adapter = SimpleNamespace(
        SERVICES=("fixture",), service_module=Mock(return_value=adapter)
    )
    monkeypatch.setattr(discovery, "ADAPTER_INVENTORIES", {})
    monkeypatch.setattr(coverage, "ADAPTER_INVENTORIES", discovery.ADAPTER_INVENTORIES)
    return data["document"], inspector, adapter


@pytest.mark.parametrize(
    "scenario,status,code",
    load_case("import-coverage", "provider-cases")["data"]["scenarios"],
)
def check_provider_discovery(case, scenario, status, code):
    document, inspector, _ = case
    if scenario == "no-schema":
        inspector.schemas.definitions.clear()
    elif scenario == "no-list":
        del inspector.schemas.definitions["Test.Item"]["handlers"]["list"]
    elif scenario == "no-model":
        for prop in document["resourceTypes"]["Test.Item"]["properties"].values():
            prop["model"]["include"] = False
    elif scenario == "conditional":
        inspector.schemas.definitions["Test.Item"]["handlers"]["list"] = {
            "handlerSchema": {"oneOf": [{"required": ["Tenant"]}]}
        }
    m = mapping(inspector.root, document)
    result = discovery.resolve(m, m.properties, "Test.Item", inspector.schema)
    assert (result.status, result.reason_code) == (status, code)
    if scenario == "no-schema":
        result = inspector.resource(m, "Test.Item")
        assert result["identity"]["status"] == "broken"


@pytest.mark.parametrize(
    "scenario,status,code",
    load_case("import-coverage", "parent-cases")["data"]["scenarios"],
)
def check_parent_filters(case, scenario, status, code):
    document, inspector, _ = case
    child = inspector.schemas.definitions["Test.Item"]
    child["handlers"]["list"] = {"handlerSchema": {"required": ["Tenant"]}}
    parent = deepcopy(child)
    parent["primaryIdentifier"] = ["/properties/Tenant"]
    parent["handlers"]["list"] = {}
    inspector.schemas.definitions["Test.Parent"] = parent
    document["resourceTypes"]["Test.Parent"] = deepcopy(
        document["resourceTypes"]["Test.Item"]
    )
    del document["resourceTypes"]["Test.Parent"]["identity"]
    if scenario == "no-list":
        del parent["handlers"]["list"]
    elif scenario == "not-modelled":
        for prop in document["resourceTypes"]["Test.Parent"]["properties"].values():
            prop["model"]["include"] = False
    elif scenario == "ambiguous":
        inspector.schemas.definitions["Test.Other"] = deepcopy(parent)
        document["resourceTypes"]["Test.Other"] = deepcopy(
            document["resourceTypes"]["Test.Parent"]
        )
    elif scenario == "no-parent":
        parent["primaryIdentifier"] = ["/properties/Id"]
    elif scenario == "no-read":
        del parent["handlers"]["read"]
    elif scenario == "sdk-parent":
        discovery.ADAPTER_INVENTORIES["Test.Parent"] = (
            "fixture",
            "list_items",
            "Items",
        )
        document["resourceTypes"]["Test.Parent"]["identity"] = deepcopy(
            document["resourceTypes"]["Test.Item"]["identity"]
        )
    elif scenario == "no-schema":
        del inspector.schemas.definitions["Test.Parent"]
    m = mapping(inspector.root, document)
    plan = discovery.resolve(m, m.properties, "Test.Item", inspector.schema)
    assert (plan.status, plan.reason_code) == (status, code)
    if scenario == "complete":
        assert plan.parents == ("Test.Parent",) and plan.required_filters == ("Tenant",)
        result = inspector.resource(m, "Test.Item")
        assert result["discovery"]["status"] == "ready"


@pytest.mark.parametrize(
    "scenario",
    ["complete", "no-identity", "id-path", "getter", "no-property", "input-selector"],
)
def check_sdk_identity(case, scenario):
    document, inspector, adapter = case
    discovery.ADAPTER_INVENTORIES["Test.Item"] = ("fixture", "list_items", "Items")
    resource = document["resourceTypes"]["Test.Item"]
    if scenario == "no-identity":
        del resource["identity"]
    elif scenario == "id-path":
        resource["identity"]["idPath"] = "Unknown"
        resource["properties"]["Id"]["aws"]["path"] = "Unknown"
    elif scenario == "getter":
        document["getters"]["base"]["resources"] = ["Test.Other"]
    elif scenario == "no-property":
        resource["identity"]["idPath"] = "Other"
    elif scenario == "input-selector":
        discovery.ADAPTER_INVENTORIES["Test.Item"] = (
            "fixture",
            "describe_item",
            "Item",
        )
    result = inspector.resource(mapping(inspector.root, document), "Test.Item")
    assert (result["identity"]["status"] == "ready") == (scenario == "complete")
    if scenario == "complete":
        assert result["discovery"]["status"] == "ready"
        assert result["propertyDiagnostics"][0]["status"] == "capturable"
        assert result["identity"]["components"] == ["Id"]
    elif scenario == "no-identity":
        assert result["discovery"]["mode"] == "cloudcontrol"
        assert result["identity"]["reasonCode"] == "SDK_IDENTITY_MISSING"
    else:
        assert result["discovery"]["status"] == "broken"
    assert adapter.fetch is fetch


@pytest.mark.parametrize(
    "scenario,status,code",
    load_case("import-coverage", "sdk-properties")["data"]["scenarios"],
)
def check_sdk_properties(case, scenario, status, code):
    document, inspector, adapter = case
    prop = document["resourceTypes"]["Test.Item"]["properties"]["Name"]
    prop["aws"]["getter"] = "sdk"
    if scenario == "not-allowed":
        adapter.APIS.clear()
    elif scenario == "no-selector":
        adapter.SDK_OPERATIONS.clear()
    elif scenario == "no-fetch":
        adapter.fetch_sdk = None
    elif scenario == "no-operation":
        document["getters"]["sdk"]["operation"] = "describe_missing"
    elif scenario == "bad-result":
        document["getters"]["sdk"]["result"] = "Missing"
    elif scenario == "bad-path":
        prop["aws"]["path"] = "Missing"
    elif scenario == "conditional":
        adapter.fetch_sdk = conditional_sdk
    elif scenario == "unseeded":
        document["resourceTypes"]["Test.Item"]["properties"]["Id"] = {
            "model": {"include": True},
            "source": {
                "kind": "model",
                "classification": "local_metadata",
                "constraint": "Human input",
            },
        }
    elif scenario == "missing-property":
        del document["resourceTypes"]["Test.Item"]["properties"]["Id"]
    result = inspector.resource(mapping(inspector.root, document), "Test.Item")
    found = next(
        p for p in result["propertyDiagnostics"] if p["property"].endswith(".Name")
    )
    assert (found["status"], found["reasonCode"]) == (status, code)


@pytest.mark.parametrize(
    "scenario,status,code",
    load_case("import-coverage", "provider-properties")["data"]["scenarios"],
)
def check_provider_properties(case, scenario, status, code):
    document, inspector, _ = case
    schema = inspector.schemas.definitions["Test.Item"]
    if scenario == "no-read":
        del schema["handlers"]["read"]
    elif scenario == "identifier":
        document["getters"]["provider"]["identifier"] = ["/properties/Name"]
    elif scenario == "write-only":
        schema["writeOnlyProperties"] = ["/properties/Name"]
    elif scenario == "path":
        document["resourceTypes"]["Test.Item"]["properties"]["Name"]["aws"]["path"] = (
            "Other"
        )
    elif scenario == "no-identity":
        del schema["primaryIdentifier"]
    elif scenario == "envelope":
        document["getters"]["provider"]["operation"] = "list_resources"
    result = inspector.resource(mapping(inspector.root, document), "Test.Item")
    found = next(
        p for p in result["propertyDiagnostics"] if p["property"].endswith(".Name")
    )
    assert (found["status"], found["reasonCode"]) == (status, code)


def check_local_and_unknown_adapter(case):
    document, inspector, _ = case
    resource = document["resourceTypes"]["Test.Item"]
    resource["properties"]["Name"] = {
        "model": {"include": True},
        "source": {
            "kind": "model",
            "classification": "local_metadata",
            "constraint": "Human-specified metadata, not an AWS response",
        },
    }
    result = inspector.resource(mapping(inspector.root, document), "Test.Item")
    assert result["properties"] == {
        "capturable": 0,
        "unobservable": 1,
        "broken": 0,
        "uncertain": 1,
    }
    assert (
        result["propertyDiagnostics"][0]["reasonCode"] == "ADAPTER_SELECTOR_UNCONFIRMED"
    )
    assert result["propertyDiagnostics"][1]["reasonCode"] == "LOCAL_METADATA"
    assert result["propertyDiagnostics"][1]["source"] == "model"


def check_composite_identity_and_filters(case):
    document, inspector, _ = case
    inspector.schemas.definitions["Test.Item"]["primaryIdentifier"] = [
        "/properties/Tenant",
        "/properties/Id",
    ]
    m = mapping(inspector.root, document)
    result = inspector.resource(m, "Test.Item")
    assert result["identity"]["status"] == "ready"
    assert result["identity"]["components"] == ["/properties/Tenant", "/properties/Id"]
    assert "/properties/Tenant" in result["identity"]["scope"]
    assert inventory.pointer_value(
        {"Tenant": "one", "Id": "same"}, "/properties/Tenant"
    ) != inventory.pointer_value({"Tenant": "two", "Id": "same"}, "/properties/Tenant")
    with pytest.raises(ValueError, match="read-only"):
        inspector.operation("fixture", "put_item")
    with pytest.raises(ValueError, match="Invalid CloudFormation"):
        discovery.required_filters(
            {"handlers": {"list": {"handlerSchema": {"required": "Tenant"}}}}
        )


def check_dynamic_owners_and_cli(case, monkeypatch, capsys):
    document, inspector, _ = case
    index = {"Test.Item": "fixture"}
    monkeypatch.setattr(coverage, "owners", Mock(return_value=index))
    monkeypatch.setattr(coverage, "Coverage", Mock(return_value=inspector))
    monkeypatch.setattr(
        coverage, "runtime_registry", lambda root, service: mapping(root, document)
    )
    before = coverage.report(inspector.root)
    resource = deepcopy(document["resourceTypes"]["Test.Item"])
    document["getters"]["base"]["resources"].append("Test.Added")
    document["getters"]["provider-added"] = dict(
        document["getters"]["provider"], resourceType="Test.Added"
    )
    resource["properties"]["Name"]["aws"]["getter"] = "provider-added"
    document["resourceTypes"]["Test.Added"] = resource
    inspector.schemas.definitions["Test.Added"] = deepcopy(
        inspector.schemas.definitions["Test.Item"]
    )
    index["Test.Added"] = "fixture"
    after = coverage.report(inspector.root)
    assert len(after["resources"]) == len(before["resources"]) + 1
    assert [r["resourceType"] for r in after["resources"]] == sorted(index)
    assert json.loads(json.dumps(after)) == after
    assert main(["import-coverage", "--service", "fixture", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["runtimeVerified"] is False
    assert main(["import-coverage", "--service", "fixture", "--strict"]) == 0
    assert "ADAPTER_SELECTOR_UNCONFIRMED" in capsys.readouterr().out
    del inspector.schemas.definitions["Test.Item"]["handlers"]["list"]
    assert main(["import-coverage", "--strict"]) == 1
    capsys.readouterr()
    assert main(["import-coverage", "--service", "unknown"]) == 2
    assert "Unknown Mapping service" in capsys.readouterr().err
    assert (
        main(["import-coverage", "--repository-root", str(inspector.root / "absent")])
        == 2
    )
    assert "not a directory" in capsys.readouterr().err
    monkeypatch.setattr(
        coverage, "runtime_registry", Mock(side_effect=ValueError("Invalid Mapping"))
    )
    assert main(["import-coverage"]) == 2
    assert "Invalid Mapping" in capsys.readouterr().err


def check_derived_and_real_mapping_gaps(monkeypatch):
    assert (
        inventory.ADAPTER_INVENTORIES
        is coverage.ADAPTER_INVENTORIES
        is discovery.ADAPTER_INVENTORIES
    )
    root = Path(__file__).resolve().parents[4]
    forbidden = Mock(
        side_effect=AssertionError("Coverage must remain offline and read-only")
    )
    runtime = coverage.aws_runtime()
    monkeypatch.setattr(runtime, "connection_session", forbidden)
    monkeypatch.setattr(runtime.boto3, "Session", forbidden)
    monkeypatch.setattr(runtime.session.Session, "get_credentials", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    full = coverage.report(root)
    assert {item["resourceType"] for item in full["resources"]} == set(
        coverage.owners(root)
    )
    assert all(item["runtimeVerified"] is False for item in full["resources"])
    assert full["summary"]["registeredTypes"] == len(coverage.owners(root))
    inspector = coverage.Coverage(root)
    m = coverage.runtime_registry(root, "vpc")
    result = inspector.resource(m, "EC2.SubnetRouteTableAssociation")
    assert result["discovery"]["mode"] == "parent_derived"
    assert result["identity"]["status"] == "ready"
    assert result["properties"]["capturable"] == 1
    broken = m.at_root(root)
    object.__setattr__(
        broken,
        "properties",
        {
            key: replace(prop, include=False)
            if key.startswith("EC2.RouteTable.")
            else prop
            for key, prop in m.properties.items()
        },
    )
    assert (
        inspector.resource(broken, "EC2.SubnetRouteTableAssociation")["identity"][
            "status"
        ]
        == "broken"
    )
    quicksight = inspector.resource(
        coverage.runtime_registry(root, "quicksight"), "QuickSight.Group"
    )
    assert quicksight["modelled"] and quicksight["staticStatus"] == "broken"
    assert quicksight["identity"]["status"] == "broken"
    assert any(
        p["reasonCode"] == "API_NOT_ALLOWED" for p in quicksight["propertyDiagnostics"]
    )
    assert all(r["runtimeVerified"] is False for r in (result, quicksight))


if __name__ == "__main__":
    raise SystemExit(run(__file__))
