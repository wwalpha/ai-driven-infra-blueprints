#!/usr/bin/env python3
"""Offline parent-scope, identity and failure cases for Import SDK inventories."""

import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from model.importing import cli, coverage, inventory, sdk_inventory
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ACCOUNT = "123456789012"
REGION = "ap-northeast-1"
TARGET = {
    "awsAccountId": ACCOUNT,
    "awsRegion": REGION,
    "environment": "dev",
    "directory": "cde",
}


class Context:
    def __init__(self, pages, details=None):
        self.target = dict(TARGET)
        self.allowed = set()
        self.responses = pages
        self.details = details or {}
        self.calls = []

    def pages(self, api, operation, **inputs):
        self.calls.append((api, operation, inputs))
        value = self.responses[(operation, tuple(sorted(inputs.items())))]
        if isinstance(value, Exception):
            raise value
        return value

    def call(self, api, operation, **inputs):
        self.calls.append((api, operation, inputs))
        value = self.details[(operation, tuple(sorted(inputs.items())))]
        if isinstance(value, Exception):
            raise value
        return value


def test_groups_preserve_namespace_and_selector_provenance():
    ctx = Context(
        {
            ("list_namespaces", (("AwsAccountId", ACCOUNT),)): {
                "Namespaces": [{"Name": "a"}, {"Name": "b"}]
            },
            ("list_groups", (("AwsAccountId", ACCOUNT), ("Namespace", "a"))): {
                "GroupList": [{"GroupName": "same", "PrincipalId": "one"}]
            },
            ("list_groups", (("AwsAccountId", ACCOUNT), ("Namespace", "b"))): {
                "GroupList": [{"GroupName": "same", "PrincipalId": "two"}]
            },
        }
    )
    records = sdk_inventory.collect(ctx, "QuickSight.Group")
    assert len({r["identity"] for r in records}) == 2
    assert records[0]["selectorProperties"]["QuickSight.Group.Namespace"] == "a"
    assert all(call[1] != "describe_data_source" for call in ctx.calls)
    key = ("list_groups", (("AwsAccountId", ACCOUNT), ("Namespace", "b")))
    ctx.responses[key]["GroupList"].append(
        {"GroupName": "same", "PrincipalId": "duplicate"}
    )
    with pytest.raises(ValueError, match="Duplicate scoped SDK identity"):
        sdk_inventory.collect(ctx, "QuickSight.Group")
    ctx.responses[("list_groups", (("AwsAccountId", ACCOUNT), ("Namespace", "b")))] = (
        ValueError("second parent failed")
    )
    with pytest.raises(ValueError, match="second parent"):
        sdk_inventory.collect(ctx, "QuickSight.Group")


def test_glue_all_catalogs_databases_and_same_named_tables():
    catalogs = [ACCOUNT, ACCOUNT + ":sub"]
    pages = {
        (
            "get_catalogs",
            (("IncludeRoot", True), ("ParentCatalogId", ACCOUNT), ("Recursive", True)),
        ): {
            "CatalogList": [
                {
                    "CatalogId": c,
                    "ResourceArn": f"arn:aws:glue:{REGION}:{ACCOUNT}:catalog/{c}",
                }
                for c in catalogs
            ]
        }
    }
    for catalog in catalogs:
        pages[("get_databases", (("CatalogId", catalog),))] = {
            "DatabaseList": [{"Name": n, "CatalogId": catalog} for n in ("a", "b")]
        }
        for database in ("a", "b"):
            pages[
                (
                    "get_tables",
                    (
                        ("CatalogId", catalog),
                        ("DatabaseName", database),
                        ("ResourceShareType", "ALL"),
                    ),
                )
            ] = {
                "TableList": [
                    {"CatalogId": catalog, "DatabaseName": database, "Name": "same"}
                ]
            }
    ctx = Context(pages)
    records = sdk_inventory.collect(ctx, "Glue.Table")
    assert len(records) == len({r["identity"] for r in records}) == 4
    assert Counter(call[1] for call in ctx.calls) == {
        "get_catalogs": 1,
        "get_databases": 2,
        "get_tables": 4,
    }
    pages[("get_databases", (("CatalogId", catalogs[1]),))] = {
        "DatabaseList": [{"Name": "a", "CatalogId": "999999999999"}]
    }
    with pytest.raises(ValueError, match="scope mismatch"):
        sdk_inventory.collect(ctx, "Glue.Table")


def test_lakeformation_detail_identity_is_checked():
    ctx = Context(
        {
            ("list_resources", ()): {
                "ResourceInfoList": [{"ResourceArn": "arn:aws:s3:::example"}]
            }
        },
        {
            ("describe_resource", (("ResourceArn", "arn:aws:s3:::example"),)): {
                "ResourceInfo": {"ResourceArn": "arn:aws:s3:::different"}
            }
        },
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        sdk_inventory.collect(ctx, "LakeFormation.Resource")


def test_datazone_domain_and_project_ids_are_not_names():
    domains = ["d-one", "d-two"]
    pages = {
        ("list_domains", ()): {
            "items": [
                {"id": d, "arn": f"arn:aws:datazone:{REGION}:{ACCOUNT}:domain/{d}"}
                for d in domains
            ]
        }
    }
    details = {}
    for domain in domains:
        pages[("list_projects", (("domainIdentifier", domain),))] = {
            "items": [{"domainId": domain, "id": "project", "name": "same"}]
        }
        details[
            ("get_project", (("domainIdentifier", domain), ("identifier", "project")))
        ] = {"domainId": domain, "id": "project", "name": "same"}
    ctx = Context(pages, details)
    records = sdk_inventory.collect(ctx, "DataZone.Project")
    assert len({r["identity"] for r in records}) == 2
    details[
        ("get_project", (("domainIdentifier", "d-two"), ("identifier", "project")))
    ] = {"domainId": "d-one", "id": "project", "name": "same"}
    with pytest.raises(ValueError, match="identity mismatch"):
        sdk_inventory.collect(ctx, "DataZone.Project")


def test_queue_policy_never_infers_grouping_or_merges_documents():
    urls = [
        f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/{n}" for n in ("a", "b", "empty")
    ]
    ctx = SimpleNamespace(
        target=dict(TARGET),
        allowed=set(),
        pages=Mock(return_value={"QueueUrls": urls}),
        call=Mock(
            side_effect=[
                {"Attributes": {"Policy": '{"Statement": []}'}},
                {"Attributes": {"Policy": '{"Statement": []}'}},
                {},
            ]
        ),
    )
    records = sdk_inventory.collect(
        ctx,
        "SQS.QueuePolicy",
        parents=[
            {"kind": "SQS.Queue", "cloudProperties": {"QueueUrl": url}} for url in urls
        ],
    )
    assert len(records) == 2
    assert all(r["structureStatus"] == "unresolved" for r in records)
    assert records[0]["identity"] != records[1]["identity"]


@pytest.mark.parametrize("kind", list(sdk_inventory.SCOPED_INVENTORIES))
def test_scoped_inventory_failure_is_not_empty(kind):
    ctx = SimpleNamespace(
        target=dict(TARGET),
        allowed=set(),
        pages=Mock(side_effect=ValueError("API failed")),
    )
    ctx.call = Mock(side_effect=ValueError("API failed"))
    parents = (
        [
            {
                "kind": "SQS.Queue",
                "cloudProperties": {
                    "QueueUrl": f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/queue"
                },
            }
        ]
        if kind == "SQS.QueuePolicy"
        else None
    )
    with pytest.raises(ValueError, match="API failed"):
        sdk_inventory.collect(ctx, kind, parents=parents)


def test_pagination_keeps_all_pages_and_rejects_second_page_error():
    module = cli.comparator()
    ctx = SimpleNamespace(
        allowed={("quicksight", "list_groups")},
        verified=True,
        import_mode=True,
        session=None,
        cache={},
        metrics=Counter(),
        call=Mock(
            side_effect=[
                {"GroupList": [{"GroupName": "one"}], "NextToken": "next"},
                {"GroupList": [{"GroupName": "two"}]},
            ]
        ),
    )
    result = module.Context._pages(
        ctx, "quicksight", "list_groups", AwsAccountId=ACCOUNT, Namespace="default"
    )
    assert len(result["GroupList"]) == 2
    assert ctx.call.call_args_list[1].kwargs["NextToken"] == "next"
    ctx.cache.clear()
    ctx.call = Mock(
        side_effect=[
            {"GroupList": [{"GroupName": "one"}], "NextToken": "next"},
            module.AcquisitionError("quicksight.list_groups", "AccessDenied"),
        ]
    )
    with pytest.raises(module.AcquisitionError):
        module.Context._pages(
            ctx, "quicksight", "list_groups", AwsAccountId=ACCOUNT, Namespace="default"
        )


@pytest.mark.parametrize(
    "service,kind,mode",
    [
        ("quicksight", "QuickSight.Group", "scoped_sdk"),
        ("macie", "Macie.ClassificationJob", "adapter"),
        ("codebuild", "CodeBuild.Project", "adapter"),
        ("glue", "Glue.Connection", "cloudcontrol"),
        ("glue", "Glue.Table", "scoped_sdk"),
        ("lake-formation", "LakeFormation.Resource", "scoped_sdk"),
        ("datazone", "DataZone.Project", "scoped_sdk"),
        ("sqs", "SQS.QueuePolicy", "scoped_sdk"),
        ("codepipeline", "CodePipeline.Pipeline", "cloudcontrol"),
    ],
)
def test_nine_inventory_paths_share_runtime_discovery(service, kind, mode):
    inspector = coverage.Coverage(cli.ROOT)
    mapping = coverage.runtime_registry(cli.ROOT, service)
    result = inspector.resource(mapping, kind)
    assert result["discovery"]["mode"] == mode
    assert result["properties"]["broken"] == 0
    assert result["identity"]["status"] == (
        "uncertain" if kind == "SQS.QueuePolicy" else "ready"
    )
    assert result["runtimeVerified"] is False


@pytest.mark.parametrize(
    "service,kind,values,getters,selectors",
    [
        (
            "quicksight",
            "QuickSight.Group",
            {"AwsAccountId": ACCOUNT, "Namespace": "default", "GroupName": "group"},
            {
                "sdk-quicksight-group": {
                    "Group": {
                        "GroupName": "group",
                        "Description": "fixture",
                        "PrincipalId": "principal",
                    }
                }
            },
            {"AwsAccountId": ACCOUNT, "Namespace": "default"},
        ),
        (
            "glue",
            "Glue.Table",
            {
                "CatalogId": ACCOUNT,
                "DatabaseName": "database",
                "TableInput.Name": "table",
            },
            {
                "base": {
                    "CatalogId": ACCOUNT,
                    "DatabaseName": "database",
                    "Name": "table",
                },
                "sdk-glue-table": {
                    "Table": {
                        "CatalogId": ACCOUNT,
                        "DatabaseName": "database",
                        "Name": "table",
                    }
                },
            },
            {"CatalogId": ACCOUNT, "DatabaseName": "database"},
        ),
        (
            "datazone",
            "DataZone.Project",
            {"DomainId": "dzd-abc123", "Id": "abc123456789"},
            {
                "sdk-datazone-project": {
                    "domainId": "dzd-abc123",
                    "id": "abc123456789",
                    "name": "project",
                },
                "provider-datazone-project": {
                    "DomainId": "dzd-abc123",
                    "Id": "abc123456789",
                    "Name": "project",
                },
            },
            {},
        ),
    ],
)
def test_scoped_records_normalize_through_existing_mapping(
    service, kind, values, getters, selectors
):
    raw = sdk_inventory.record(kind, values, getters, selectors=selectors)
    ctx = cli.import_context(
        cli.ROOT,
        TARGET,
        Mock(side_effect=AssertionError("Unexpected AWS request")),
        service,
        no_profile=True,
    )
    ctx.verified = True
    normalized = cli.normalize_records(ctx, service, [raw])[0]
    assert normalized["identityStatus"] == "known"
    assert all(
        capture["status"] != "unavailable"
        for capture in normalized["properties"].values()
    )
    for prop in selectors:
        assert (
            normalized["properties"][kind + "." + prop]["source"] == "verified_selector"
        )
    assert ctx.metrics["api_calls"] == 0


def test_withheld_environment_value_is_not_normalized_or_traced():
    ctx = cli.import_context(
        cli.ROOT,
        TARGET,
        Mock(side_effect=AssertionError("Unexpected AWS request")),
        "codebuild",
        no_profile=True,
    )
    ctx.verified = True
    record = {
        "kind": "CodeBuild.Project",
        "identity": "project",
        "getters": {
            "base": {
                "name": "project",
                "environment": {
                    "type": "LINUX_CONTAINER",
                    "image": "fixture",
                    "computeType": "BUILD_GENERAL1_SMALL",
                    "environmentVariables": [
                        {
                            "name": "PRIVATE",
                            "type": "PLAINTEXT",
                            "value": "DO-NOT-EXPOSE",
                        }
                    ],
                },
            }
        },
    }
    normalized = cli.normalize_records(ctx, "codebuild", [record])[0]
    capture = normalized["properties"][
        "CodeBuild.Project.Environment.EnvironmentVariables[].Value"
    ]
    assert capture["status"] == "withheld" and "value" not in capture
    assert "DO-NOT-EXPOSE" not in str(normalized) + str(ctx.trace)


def test_queue_parent_failure_is_not_an_empty_inventory():
    mapping, mapped = inventory.import_comparison(cli.ROOT, "sqs")
    collector = SimpleNamespace(
        mapping=lambda service: (mapping, mapped),
        inventory=Mock(return_value=[]),
        statuses={"SQS.Queue": {"status": "permission_denied"}},
        ctx=SimpleNamespace(),
        failure=Mock(),
        status=Mock(),
    )
    assert (
        inventory._callback_ImportInventory_inventory_collect(
            None, "SQS.QueuePolicy", collector, "sqs"
        )
        == []
    )
    assert collector.failure.call_args.args[1].code == "ParentInventoryIncomplete"
    collector.status.assert_not_called()


def test_scoped_getter_permission_and_registration_are_checked(monkeypatch):
    inspector = coverage.Coverage(cli.ROOT)
    mapping = coverage.runtime_registry(cli.ROOT, "quicksight")
    adapter = inspector.service_adapter("quicksight")
    monkeypatch.setattr(adapter, "SDK_OPERATIONS", {})
    result = inspector.resource(mapping, "QuickSight.Group")
    assert result["properties"]["broken"] == 3
    monkeypatch.setattr(
        adapter, "SDK_OPERATIONS", {"QuickSight.Group": "describe_group"}
    )
    monkeypatch.setattr(adapter, "APIS", set())
    result = inspector.resource(mapping, "QuickSight.Group")
    assert result["properties"]["broken"] == 3


if __name__ == "__main__":
    raise SystemExit(run(__file__))
