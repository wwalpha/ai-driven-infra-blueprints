import ast
import json
import sys
import tempfile
import unittest
from functools import partial
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import copy
from datetime import datetime, timezone
from unittest import TestCase

import utils.input_cache as _imports_input_cache
from model.adapters.aws import AcquisitionError, service_module
from model.audit import (
    definitions,
    embed_adapter,
)
from support.check_model_aws_fixtures import FakeResource, SchemaOffline, m
from support.model_sources import write_model
from support.model_test_references import ReferenceFixture
from support.model_test_runner import (
    CLI,
    assert_result,
    execute,
    fixture,
    generated,
    load_fixture,
    prepare,
    snapshot,
)
from support.model_test_runtime import runtime
from support.pytest_cli import run
from support.repository_fixtures import contract

from model import audit as generator
from model import audit_runtime

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


class DataZoneDomainTests(unittest.TestCase):
    def test_confirmed_domain_selector(self):
        adapter = service_module("datazone")
        resource, ctx = (Mock(), Mock())
        resource.current.return_value = "dzdm-confirmed"
        adapter.fetch_sdk(ctx, resource, "get_domain")
        ctx.call.assert_called_once_with(
            "datazone", "get_domain", identifier="dzdm-confirmed"
        )
        resource.current.return_value = None
        ctx.reset_mock()
        ctx.target = {"awsAccountId": "123456789012"}
        ctx.pages.return_value = {"items": []}
        with self.assertRaises(AcquisitionError):
            adapter.fetch_sdk(ctx, resource, "get_domain")
        ctx.pages.assert_called_once_with("datazone", "list_domains")
        ctx.call.assert_not_called()

    def test_project_comparison(self):
        with tempfile.TemporaryDirectory(prefix="datazone-project-") as directory:
            ctx = SchemaOffline(Path(directory))
            ctx.egress = False
            ctx.verified = True
            for desired, expected in [
                ("fixture", "match"),
                ("different", "difference"),
            ]:
                resource = FakeResource(
                    ctx,
                    "datazone",
                    "DataZone.Project",
                    "DataZone.Project.DomainIdentifier",
                    desired,
                )
                self.assertTrue(
                    any(
                        (
                            item["status"] == expected
                            for item in m.compare_resource(ctx, resource)
                        )
                    )
                )

    def test_generated_standalone_domain_version(self):
        fixture = load_fixture("datazone/version")
        actual = execute(fixture)
        assert_result(actual, fixture)


def _datazone_inputs(kind):
    inputs = load_fixture("datazone/version")[0]
    logical = "DataZone_" + kind + "_001"
    rows = (
        {
            "Id": ReferenceFixture.ref(logical, "Id"),
            "Name": "fixture",
            "SingleSignOn.Type": "IAM_IDC",
        }
        if kind == "Domain"
        else {
            "Id": ReferenceFixture.ref(logical, "Id"),
            "DomainIdentifier": "dzd-confirmed",
            "DomainId": ReferenceFixture.ref(logical, "DomainId"),
            "Name": "fixture",
        }
    )
    inputs["model"] = ReferenceFixture.model("DataZone." + kind, logical, rows)
    inputs["model"]["observed.row.001-001.value"] = (
        "`dzd-confirmed`" if kind == "Domain" else "`project-confirmed`"
    )
    if kind == "Project":
        inputs["model"]["observed.row.001-003.value"] = "`dzd-confirmed`"
    return inputs


@pytest.mark.parametrize("kind", ["Domain", "Project"])
@pytest.mark.parametrize(
    "outcome", ["match", "difference", "missing", "denied", "not-found"]
)
def test_datazone_audit_sdk_projection(tmp_path, kind, outcome):
    inputs = _datazone_inputs(kind)
    namespace = generated(prepare(tmp_path, inputs), tmp_path)
    snap = namespace["SNAPSHOT"]
    operation = "get-domain" if kind == "Domain" else "get-project"
    response = (
        {"id": "dzd-confirmed", "name": "fixture", "singleSignOn": {"type": "IAM_IDC"}}
        if kind == "Domain"
        else {"id": "project-confirmed", "domainId": "dzd-confirmed", "name": "fixture"}
    )
    if outcome == "difference":
        response["name"] = "different"
    elif outcome == "missing":
        response.pop("name")
    elif outcome in {"denied", "not-found"}:
        response = {
            "$error": json.dumps(
                {
                    "Code": "AccessDeniedException"
                    if outcome == "denied"
                    else "ResourceNotFoundException"
                }
            )
        }
    cli = CLI({("datazone", operation): response})
    _, account, records = namespace["audit"](snap, None, cli)
    by_property = {item["propertiesKey"]: item for item in records}
    status = {
        "match": "match",
        "difference": "difference",
        "missing": "difference",
        "denied": "acquisition_failed",
        "not-found": "resource_missing",
    }[outcome]
    assert by_property["DataZone." + kind + ".Name"]["status"] == status, records
    if outcome in {"denied", "not-found"}:
        assert all(item["status"] == status for item in records), records
    else:
        assert all(
            item["status"] == "match"
            for key, item in by_property.items()
            if not key.endswith(".Name")
        ), records
    calls = [(api, args) for api, args, _ in cli.calls if api[0] != "sts"]
    assert calls == [
        (
            ("datazone", operation),
            {"identifier": "dzd-confirmed"}
            if kind == "Domain"
            else {
                "domainIdentifier": "dzd-confirmed",
                "identifier": "project-confirmed",
            },
        )
    ]
    mappings = snap["mappings"]["datazone"]
    for item in records:
        field = mappings["properties"][item["propertiesKey"]]["field"]
        assert field["getter"] == "sdk-datazone-" + kind.lower()
        assert field["classification"] == "supported"
    text, code = namespace["report"](
        snap, None, account, records, datetime.now(timezone.utc)
    )
    assert code == (0 if outcome == "match" else 2 if outcome == "denied" else 1)
    if outcome == "denied":
        assert "[ERROR]" in text
    elif outcome == "not-found":
        assert "[NG]" in text
    # Ordinary Compare retains its provider classification and read-only allowlist.
    _, original = generator.comparison(generator.ROOT, "datazone")
    assert (
        original["DataZone." + kind + ".Name"].field.classification == "sdk_unavailable"
    )
    assert ("cloudcontrol", "get_resource") not in service_module("datazone").APIS


def test_datazone_audit_domain_discovery_reports_pending_ng(tmp_path):
    inputs = _datazone_inputs("Domain")
    inputs["project"]["targets"][0].update(
        awsAccountId="111111111111", awsExecutionAccountId="123456789012"
    )
    inputs["model"]["observed.row.001-001.value"] = "`PENDING_DEPLOY`"
    namespace = generated(prepare(tmp_path, inputs), tmp_path)
    snap = namespace["SNAPSHOT"]
    cli = CLI(
        {
            ("datazone", "list-domains"): {
                "items": [
                    {
                        "id": "dzd-other-account",
                        "name": "fixture",
                        "managedAccountId": "999999999999",
                    },
                    {
                        "id": "dzd-other-name",
                        "name": "other",
                        "managedAccountId": "123456789012",
                    },
                    {
                        "id": "dzd-discovered",
                        "name": "fixture",
                        "managedAccountId": "123456789012",
                    },
                ]
            },
            ("datazone", "get-domain"): {
                "id": "dzd-discovered",
                "name": "fixture",
                "singleSignOn": {"type": "IAM_IDC"},
            },
        }
    )
    _, account, records = namespace["audit"](snap, None, cli)
    by_property = {item["propertiesKey"]: item for item in records}
    assert by_property["DataZone.Domain.Name"]["status"] == "match"
    assert by_property["DataZone.Domain.SingleSignOn.Type"]["status"] == "match"
    pending = by_property["DataZone.Domain.Id"]
    assert pending["status"] == "pending_identifier", pending
    assert "PENDING_DEPLOY" in pending["reason"]
    assert [(api, args) for api, args, _ in cli.calls if api[0] != "sts"] == [
        (("datazone", "list-domains"), {}),
        (("datazone", "get-domain"), {"identifier": "dzd-discovered"}),
    ]
    text, code = namespace["report"](
        snap, None, account, records, datetime.now(timezone.utc)
    )
    assert code == 1 and "[NG]" in text and '  Design: "PENDING_DEPLOY"' in text


@pytest.mark.parametrize("selector", ["Id", "DomainIdentifier"])
@pytest.mark.parametrize("pending", ["PENDING_DEPLOY", "UNSET"])
def test_datazone_audit_project_unresolved_selector(tmp_path, selector, pending):
    inputs = _datazone_inputs("Project")
    if selector == "Id":
        inputs["model"]["observed.row.001-001.value"] = "`" + pending + "`"
    else:
        inputs["model"]["desired.row.001-002.value"] = (
            "`" + json.dumps(ReferenceFixture.ref("DataZone_Domain_001", "Id")) + "`"
        )
        domain = ReferenceFixture.model(
            "DataZone.Domain",
            "DataZone_Domain_001",
            {"Id": ReferenceFixture.ref("DataZone_Domain_001", "Id")},
        )
        inputs["model"].update(
            {
                key.replace("resource.001.", "resource.002.").replace(
                    "row.001-", "row.002-"
                ): value
                for key, value in domain.items()
                if key != "desired.service.identity.lastAllocated"
            }
        )
        inputs["model"]["desired.service.identity.lastAllocated"] = json.dumps(
            {"DataZone.Domain": 1, "DataZone.Project": 1}
        )
        inputs["model"]["observed.row.002-001.value"] = "`" + pending + "`"
    namespace = generated(prepare(tmp_path, inputs), tmp_path)
    snap = namespace["SNAPSHOT"]
    cli = CLI({})
    _, account, records = namespace["audit"](snap, None, cli)
    records = [item for item in records if item["resourceType"] == "DataZone.Project"]
    assert len(records) == 4
    assert all(item["status"] == "design_unresolved" for item in records), records
    assert all(item["reason"] for item in records), records
    if pending == "PENDING_DEPLOY":
        assert all("REFERENCE_PENDING_DEPLOY" in item["reason"] for item in records), (
            records
        )
    assert [api for api, _, _ in cli.calls] == [("sts", "get-caller-identity")]
    text, code = namespace["report"](
        snap, None, account, records, datetime.now(timezone.utc)
    )
    if pending == "PENDING_DEPLOY":
        assert code == 1 and text.count("[NG]") == 4
        assert text.count('  Design: "PENDING_DEPLOY"') == 4
    else:
        assert code == 2 and text.count("[ERROR]") == 4


def test_datazone_audit_project_pending_output_is_not_confirmed_by_sdk(tmp_path):
    inputs = _datazone_inputs("Project")
    inputs["model"]["observed.row.001-003.value"] = "`PENDING_DEPLOY`"
    namespace = generated(prepare(tmp_path, inputs), tmp_path)
    snap = namespace["SNAPSHOT"]
    cli = CLI(
        {
            ("datazone", "get-project"): {
                "id": "project-confirmed",
                "domainId": "dzd-confirmed",
                "name": "fixture",
            }
        }
    )
    _, account, records = namespace["audit"](snap, None, cli)
    pending = next(
        item for item in records if item["propertiesKey"] == "DataZone.Project.DomainId"
    )
    assert pending["status"] == "pending_identifier", pending
    assert "REFERENCE_PENDING_DEPLOY" in pending["reason"]
    assert all(item["status"] == "match" for item in records if item is not pending), (
        records
    )
    assert [api for api, _, _ in cli.calls] == [
        ("sts", "get-caller-identity"),
        ("datazone", "get-project"),
    ]
    text, code = namespace["report"](
        snap, None, account, records, datetime.now(timezone.utc)
    )
    assert code == 1 and text.count("[NG]") == 1
    assert '  Design: "PENDING_DEPLOY"' in text and "[ERROR]" not in text


class EmbeddedImportTests(unittest.TestCase):
    def test_static_cache_tracks_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.py"
            path.write_text("def example(): return 1\n", encoding="utf-8")
            generator._definitions.cache_clear()
            first = definitions(path, ["example"])
            self.assertEqual(first, definitions(path, ["example"]))
            self.assertEqual(generator._definitions.cache_info().hits, 1)
            path.write_text("def example(): return 2\n", encoding="utf-8")
            self.assertNotEqual(first, definitions(path, ["example"]))
            self.assertEqual(generator._definitions.cache_info().misses, 2)
            generator._definitions.cache_clear()
        embed_adapter.cache_clear()
        source = "from model.adapters.aws import value\n"
        first = embed_adapter(source, "sqs", "value = 1\n")
        self.assertEqual(first, embed_adapter(source, "sqs", "value = 1\n"))
        self.assertEqual(embed_adapter.cache_info().hits, 1)
        with self.assertRaises(ValueError):
            embed_adapter(source, "sqs", "other = 1\n")
        embed_adapter.cache_clear()

    def test_runtime_compilation_cache_tracks_content(self):
        audit_runtime.compile.cache_clear()
        first = audit_runtime.compile("value = 1", "<test>", "exec")
        self.assertIs(first, audit_runtime.compile("value = 1", "<test>", "exec"))
        self.assertIsNot(first, audit_runtime.compile("value = 2", "<test>", "exec"))
        self.assertEqual(audit_runtime.compile.cache_info().hits, 1)
        audit_runtime.compile.cache_clear()

        engine = "def policy(value): return value\nMISSING = 3\n"
        source = "from model.adapters.aws import policy as normalize, MISSING\nimport model.adapters.aws as aws\nresult = (normalize(aws.MISSING), MISSING)\n"
        transformed = embed_adapter(source, "sqs", engine)
        comparison = SimpleNamespace(policy=lambda value: value, MISSING=3)
        with patch.dict(sys.modules, {"audit_comparison": comparison}):
            namespace = {"_audit_comparison": comparison}
            exec(transformed, namespace)
        self.assertEqual(namespace["result"], (3, 3))
        self.assertIs(namespace["aws"], comparison)

    def test_unknown_dependencies_fail(self):
        for source in (
            "import model.unknown as x",
            "from model.adapters.aws import absent",
            "from model.importing.sdk_inventory import absent",
        ):
            with (
                self.subTest(source=source),
                self.assertRaisesRegex(ValueError, "sqs: model.*unresolved dependency"),
            ):
                embed_adapter(source, "sqs", "MISSING = 1")

    def test_route53_definitions_copied(self):
        path = Path(__file__).resolve().parents[3] / "model/importing/sdk_inventory.py"
        source = definitions(
            path, ["identifier", "route53_pages", "route53_projection"]
        )
        self.assertEqual(
            {node.name for node in ast.parse(source).body},
            {"identifier", "route53_pages", "route53_projection"},
        )
        self.assertIn(
            "from audit_comparison import route53_pages as pages",
            embed_adapter(
                "from model.importing.sdk_inventory import route53_pages as pages\n",
                "route53",
                source,
            ),
        )


def test_quicksight_embedded_sdk_validation(monkeypatch):
    session = generator.aws_runtime().sdk_session()
    output = (
        session.get_service_model("quicksight")
        .operation_model("DescribeGroup")
        .output_shape
    )
    monkeypatch.setattr(
        generator,
        "AUDIT_SDK_SHAPES",
        {("quicksight", "describe_group"): generator.audit_sdk_shape(output)},
    )
    getter = {"service": "quicksight", "operation": "describe_group"}
    valid = {"Group": {"Arn": "arn", "GroupName": "group"}, "Status": 200}
    assert generator.sdk_response(None, getter, valid)
    for invalid in (
        {**valid, "Status": 400},
        {**valid, "ResponseMetadata": {"HTTPStatusCode": 503}},
        {"Group": {"GroupName": ""}},
        {"Group": {"unknown": "value"}},
        {"Group": []},
    ):
        assert not generator.sdk_response(None, getter, invalid)


def test_guardduty_plan_generated_comparison():
    fixture = load_fixture("guardduty/comparison")
    actual = execute(fixture)
    assert_result(actual, fixture)


def test_guardduty_prefix_shapes_generated():
    fixture = load_fixture("guardduty/prefix-shapes")
    actual = execute(fixture)
    assert_result(actual, fixture)


def _endpoint_responses(dns, endpoints, zone="Z"):
    return {
        ("ec2", "describe-vpc-endpoints"): {"VpcEndpoints": endpoints},
        ("route53", "list-resource-record-sets"): {
            "ResourceRecordSets": [
                {
                    "Name": "www.example.com.",
                    "Type": "A",
                    "AliasTarget": {
                        "DNSName": dns,
                        "HostedZoneId": zone,
                        "EvaluateTargetHealth": False,
                    },
                }
            ],
            "IsTruncated": False,
        },
    }


def test_route53_alias_producer_observation():
    with tempfile.TemporaryDirectory(prefix="route53-producer-") as directory:
        root = Path(directory)
        root.joinpath("project.json").write_text(
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
        ref = {
            "$modelRef": {"logicalId": "EC2_VPCEndpoint_001", "attribute": "DnsEntries"}
        }
        expression = {"Fn::Select": [1, {"Fn::Split": [":", {"Fn::Select": [0, ref]}]}]}
        route = fixture(
            {},
            "route53",
            [
                (
                    "001",
                    "Route53.RecordSet",
                    "record",
                    [
                        ("HostedZoneId", "`Z123`", None),
                        ("Name", "`www.example.com.`", None),
                        ("Type", "`A`", None),
                        (
                            "AliasTarget.DNSName",
                            "`" + json.dumps(expression) + "`",
                            None,
                        ),
                        (
                            "AliasTarget.HostedZoneId",
                            "`"
                            + json.dumps(
                                {"Fn::Select": [0, expression["Fn::Select"][1]]}
                            )
                            + "`",
                            None,
                        ),
                    ],
                )
            ],
        )["models"]["dev/cde/route53"]
        endpoint = fixture(
            {},
            "vpc-endpoint",
            [("001", "EC2.VPCEndpoint", "endpoint", [("Id", "`vpce-123`", None)])],
        )["models"]["dev/cde/vpc-endpoint"]
        endpoint["observed.row.001-001.value"] = "`vpce-123`"
        for service, values in [("route53", route), ("vpc-endpoint", endpoint)]:
            write_model(root / "model/dev/cde" / (service + ".properties"), values)
        source = generator.generate(root, "dev", "cde", "route53")[0]
        snap = snapshot(source)
        row = snap["referenceRows"]["dev/cde/route53"]["001-004"]
        assert row["status"] == "unresolved", row
        assert row["producer"]["endpointId"] == "vpce-123", row
        namespace = {"__name__": "audit_fixture", "SNAPSHOT": snap}
        exec(compile(source, "<generated-audit>", "exec"), namespace)

        responses = _endpoint_responses

        endpoint_record = {
            "VpcEndpointId": "vpce-123",
            "VpcEndpointType": "Interface",
            "State": "available",
            "DnsEntries": [{"HostedZoneId": "Z", "DnsName": "producer.example"}],
        }
        for actual, zone, producers, status in [
            ("producer.example", "Z", [endpoint_record], "match"),
            ("different.example", "Z-OTHER", [endpoint_record], "difference"),
            ("producer.example", "Z", [], "design_unresolved"),
        ]:
            cli = CLI(responses(actual, producers, zone))
            records = namespace["audit"](snap, cli_runner=cli)[2]
            item = next(
                x
                for x in records
                if x["propertiesKey"] == "Route53.RecordSet.AliasTarget.DNSName"
            )
            assert item["status"] == status, item
            if status == "design_unresolved":
                assert "EC2_VPCEndpoint_001.DnsEntries" in item["reason"], item
            else:
                assert item["designValue"] == "producer.example", item
            zone_item = next(
                x
                for x in records
                if x["propertiesKey"] == "Route53.RecordSet.AliasTarget.HostedZoneId"
            )
            assert zone_item["status"] == status, zone_item
            if status != "design_unresolved":
                assert zone_item["designValue"] == "Z", zone_item
            assert (
                sum(call[0] == ("ec2", "describe-vpc-endpoints") for call in cli.calls)
                == 1
            )
        route["desired.row.001-006.property"] = "Route53.RecordSet.ResourceRecords"
        route["desired.row.001-006.value"] = "`" + json.dumps([expression]) + "`"
        route["desired.row.001-006.comment"] = "fixture"
        write_model(root / "model/dev/cde/route53.properties", route)
        array_snap = snapshot(generator.generate(root, "dev", "cde", "route53")[0])
        array_row = array_snap["referenceRows"]["dev/cde/route53"]["001-006"]
        assert array_row["producer"]["endpointId"] == "vpce-123", array_row
        assert array_row["expression"] == [expression], array_row
        audit_runtime.resolve_endpoint_aliases(
            SimpleNamespace(AcquisitionError=AcquisitionError, Unresolved=ValueError),
            SimpleNamespace(
                target={"awsRegion": "us-east-1"},
                pages=lambda *args, **kwargs: {"VpcEndpoints": [endpoint_record]},
            ),
            array_snap,
        )
        assert array_row["value"] == ["producer.example"], array_row
        endpoint.pop("observed.row.001-001.value")
        write_model(root / "model/dev/cde/vpc-endpoint.properties", endpoint)
        unresolved = snapshot(generator.generate(root, "dev", "cde", "route53")[0])
        row = unresolved["referenceRows"]["dev/cde/route53"]["001-004"]
        assert "endpointId" not in row["producer"], row
        assert "EC2_VPCEndpoint_001.DnsEntries" in namespace["resolution_error"](row)
        (root / "model/dev/cde/vpc-endpoint.properties").unlink()
        missing = snapshot(generator.generate(root, "dev", "cde", "route53")[0])
        row = missing["referenceRows"]["dev/cde/route53"]["001-004"]
        assert row["status"] == "unresolved", row
        assert "EC2_VPCEndpoint_001.DnsEntries" in namespace["resolution_error"](row)
        endpoint["observed.row.001-001.value"] = "`vpce-123`"
        endpoint.update(
            {
                "desired.row.001-002.property": "EC2.VPCEndpoint.DnsEntries",
                "desired.row.001-002.value": '`["Z:producer.example"]`',
                "desired.row.001-002.comment": "fixture",
            }
        )
        endpoint["observed.row.001-002.value"] = '`["Z:producer.example"]`'
        write_model(root / "model/dev/cde/vpc-endpoint.properties", endpoint)
        resolved = snapshot(generator.generate(root, "dev", "cde", "route53")[0])[
            "referenceRows"
        ]["dev/cde/route53"]["001-004"]
        assert (
            resolved["status"] == "resolved" and resolved["value"] == "producer.example"
        ), resolved


def test_endpoint_dns_selection_offline():
    ref = {"$modelRef": {"logicalId": "EndpointA", "attribute": "DnsEntries"}}
    expression = {"Fn::Select": [1, {"Fn::Split": [":", {"Fn::Select": [0, ref]}]}]}
    regional = "vpce-123-abc.service.us-east-1.vpce.amazonaws.com"
    entries = [
        {"DnsName": regional, "HostedZoneId": "Z"},
        {
            "DnsName": "vpce-123-abc-us-east-1a.service.us-east-1.vpce.amazonaws.com",
            "HostedZoneId": "Z",
        },
    ]
    record = {
        "VpcEndpointId": "vpce-123",
        "VpcEndpointType": "Interface",
        "State": "available",
        "DnsEntries": entries,
    }
    m = SimpleNamespace(AcquisitionError=AcquisitionError, Unresolved=ValueError)
    for wrapped in (False, True):
        for response, expected in [
            ([record], regional),
            ([{**record, "DnsEntries": entries[::-1]}], None),
            ([{**record, "DnsEntries": []}], None),
            ([{**record, "DnsEntries": [{"DnsName": None}]}], None),
            ([{**record, "DnsEntries": [entries[0], {}]}], None),
            ([{**record, "VpcEndpointType": "Gateway"}], None),
            ([{**record, "State": "pending"}], None),
            ([], None),
        ]:
            row = {
                "status": "logical_only",
                "producer": {"logicalId": "EndpointA", "endpointId": "vpce-123"},
                "expression": [expression] if wrapped else expression,
            }
            snap = {"referenceRows": {"route53": {"001": row}}}
            ctx = SimpleNamespace(
                target={"awsRegion": "us-east-1"},
                pages=lambda *args, response=response, **kwargs: {
                    "VpcEndpoints": response
                },
            )
            audit_runtime.resolve_endpoint_aliases(m, ctx, snap)
            assert row["status"] == ("resolved" if expected else "logical_only"), row
            if expected:
                assert row["value"] == ([expected] if wrapped else expected)
        row = {
            "status": "logical_only",
            "producer": {"logicalId": "EndpointA", "endpointId": "vpce-123"},
            "expression": {
                "Fn::Select": [2, {"Fn::Split": [":", {"Fn::Select": [0, ref]}]}]
            },
        }
        audit_runtime.resolve_endpoint_aliases(
            m, ctx, {"referenceRows": {"route53": {"001": row}}}
        )
        assert row["status"] == "logical_only"
        row["expression"] = {
            "Fn::Select": [1, {"Fn::Split": [":", {"Fn::Select": [9, ref]}]}]
        }
        audit_runtime.resolve_endpoint_aliases(
            m, ctx, {"referenceRows": {"route53": {"001": row}}}
        )
        assert row["status"] == "logical_only"


def test_codebuild_boolean_generated():
    fixture = load_fixture("codebuild/boolean")
    actual = execute(fixture)
    assert_result(actual, fixture)


class WindowsSnapshotPath(PureWindowsPath):
    def resolve(self):
        return WindowsSnapshotPath("C:/", self)

    def is_symlink(self):
        return False


def test_generated_codebuild_loads_model_with_windows_drive(tmp_path):
    inputs, _ = load_fixture("codebuild/boolean")
    namespace = generated(prepare(tmp_path, inputs), tmp_path)
    embedded = namespace["SNAPSHOT"]
    with patch("pathlib.Path", WindowsSnapshotPath):
        engine = namespace["engine"](embedded)
    context = engine.Context(engine.ROOT, embedded["target"])
    model = context.model(engine.ROOT / "model/dev/cde/codebuild.properties")
    assert model.values == embedded["models"]["dev/cde/codebuild"]


def test_generated_boundaries():
    inputs = load_fixture("audit/runtime")[0]
    with tempfile.TemporaryDirectory(prefix="audit-boundaries-") as directory:
        root = Path(directory)
        (root / "project.json").write_text(
            json.dumps(inputs["project"]), encoding="utf-8"
        )
        iam = fixture({}, "iam", inputs["resources"]["base-iam"])
        vpc = fixture({}, "vpc", inputs["resources"]["base-vpc"])
        for service, data in [("vpc", vpc), ("iam", iam)]:
            write_model(
                root / "model/dev/cde" / (service + ".properties"),
                data["models"]["dev/cde/" + service],
            )
        kms = fixture({}, "kms", inputs["resources"]["kms-write-only"])
        kms_values = kms["models"]["dev/cde/kms"]
        kms_values["observed.row.001-001.value"] = (
            "`12345678-1234-1234-1234-123456789012`"
        )
        write_model(root / "model/dev/cde/kms.properties", kms_values)
        kms_source = generator.generate(root, "dev", "cde", "kms")[0]
        kms_snapshot = snapshot(kms_source)
        assert "KMS.Key.PendingWindowInDays" in kms_snapshot["exclusions"]
        kms_runtime = runtime(kms_snapshot)
        kms_responses = {
            tuple(item["api"]): item["response"]
            for item in inputs["responses"]["kms_responses"]
        }
        records = kms_runtime["audit"](kms_snapshot, None, CLI(kms_responses))[2]
        assert sorted(item["status"] for item in records) == [
            "excluded",
            "match",
            "match",
        ], records
        assert (
            kms_runtime["report"](
                kms_snapshot, None, "123456789012", records, datetime.now(timezone.utc)
            )[1]
            == 0
        )
        bad = copy.deepcopy(kms_responses)
        bad[("kms", "describe-key")]["KeyMetadata"]["Enabled"] = False
        records = kms_runtime["audit"](kms_snapshot, None, CLI(bad))[2]
        assert "difference" in [item["status"] for item in records]
        assert (
            kms_runtime["report"](
                kms_snapshot, None, "123456789012", records, datetime.now(timezone.utc)
            )[1]
            == 1
        )
        records = kms_runtime["audit"](
            kms_snapshot, None, CLI(kms_responses, fail=("kms", "describe-key"))
        )[2]
        assert (
            kms_runtime["report"](
                kms_snapshot, None, "123456789012", records, datetime.now(timezone.utc)
            )[1]
            == 2
        )
        denied = kms_runtime["audit"](
            kms_snapshot, None, CLI(kms_responses, account="999999999999")
        )[2]
        assert all(item["status"] != "excluded" for item in denied), denied
        assert (
            kms_runtime["report"](
                kms_snapshot, None, "unverified", denied, datetime.now(timezone.utc)
            )[1]
            == 2
        )
        unconfirmed = copy.deepcopy(kms_snapshot)
        unconfirmed["exclusions"] = {}
        records = runtime(unconfirmed)["audit"](unconfirmed, None, CLI(kms_responses))[
            2
        ]
        assert (
            next(
                item
                for item in records
                if item["propertiesKey"] == "KMS.Key.PendingWindowInDays"
            )["status"]
            == "sdk_unavailable"
        )
        assert (
            kms_runtime["report"](
                unconfirmed, None, "123456789012", records, datetime.now(timezone.utc)
            )[1]
            == 2
        )
        excluded_only = copy.deepcopy(kms_snapshot)
        values = excluded_only["models"]["dev/cde/kms"]
        for key in list(values):
            if key.startswith(
                (
                    "desired.row.001-001.",
                    "desired.row.001-002.",
                    "observed.row.001-001.",
                )
            ):
                del values[key]
        records = runtime(excluded_only)["audit"](
            excluded_only, None, CLI(kms_responses)
        )[2]
        assert [item["status"] for item in records] == ["excluded"], records
        assert (
            kms_runtime["report"](
                excluded_only, None, "123456789012", records, datetime.now(timezone.utc)
            )[1]
            == 2
        )
        for value in (
            "`31`",
            "`not-a-number`",
            '`{"$modelRef":{"logicalId":"Missing","attribute":"KeyId"}}`',
        ):
            changed = copy.deepcopy(kms_snapshot)
            changed["models"]["dev/cde/kms"]["desired.row.001-003.value"] = value
            records = runtime(changed)["audit"](changed, None, CLI(kms_responses))[2]
            assert (
                next(
                    item
                    for item in records
                    if item["propertiesKey"] == "KMS.Key.PendingWindowInDays"
                )["status"]
                == "design_unresolved"
            ), records
        sources = {
            service: generator.generate(root, "dev", "cde", service)[0]
            for service in ("vpc", "iam")
        }
        for service, source in list(sources.items())[:1]:
            TestCase().assertEqual(
                generator.build_snapshot(root, "dev", "cde", service)[0],
                snapshot(source),
            )
            assert generator.generate(root, "dev", "cde", service)[0] == source
            compile(source, service + ".py", "exec")
            embedded = {}
            exec(snapshot(source)["engine"], embedded)
            cache, value = {}, object()
            load = Mock(return_value=value)
            lock = embedded["RLock"]()
            assert embedded["load_once"](lock, cache, "audit", load) is value
            assert embedded["load_once"](lock, cache, "audit", load) is value
            load.assert_called_once_with()
        name_root = root / "name-synthetic"
        name_root.mkdir()
        (name_root / "project.json").write_text(
            (root / "project.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        name_data = fixture({}, "vpc", inputs["resources"]["duplicate-names"])
        name_data["models"]["dev/cde/vpc"]["observed.row.001-002.value"] = "`vpc-a`"
        name_data["models"]["dev/cde/vpc"]["observed.row.002-002.value"] = "`vpc-b`"
        for number, allocation, address in (
            ("005", "eipalloc-11111111111111111", "192.0.2.1"),
            ("006", "eipalloc-22222222222222222", "192.0.2.2"),
        ):
            name_data["models"]["dev/cde/vpc"][f"observed.row.{number}-003.value"] = (
                f"`{allocation}`"
            )
            name_data["models"]["dev/cde/vpc"][f"observed.row.{number}-004.value"] = (
                f"`{address}`"
            )
        name_data["models"]["dev/cde/vpc"]["observed.row.003-001.value"] = (
            "`vpc-confirmed`"
        )
        write_model(
            name_root / "model/dev/cde/vpc.properties",
            name_data["models"]["dev/cde/vpc"],
        )
        names = snapshot(generator.generate(name_root, "dev", "cde", "vpc")[0])["names"]
        TestCase().assertEqual(
            [
                names[f"EC2_VPC_{number}"]
                for number in ("001", "002", "007", "003", "004")
            ],
            [
                "duplicate (vpc-a)",
                "duplicate (vpc-b)",
                "duplicate",
                "vpc-confirmed",
                "（名前未設定）",
            ],
        )
        TestCase().assertEqual(names["EC2_EIP_005"], "duplicate (192.0.2.1)")
        TestCase().assertEqual(names["EC2_EIP_006"], "duplicate (192.0.2.2)")
        TestCase().assertEqual(names["EC2_EIP_008"], "duplicate")
        TestCase().assertNotIn("EC2_EIP_", " ".join(names.values()))
        name_data["models"]["dev/cde/vpc"].pop("observed.row.005-004.value")
        name_data["models"]["dev/cde/vpc"].pop("observed.row.006-003.value")
        name_data["models"]["dev/cde/vpc"]["observed.row.006-004.value"] = (
            "`198.51.100.22`"
        )
        write_model(
            name_root / "model/dev/cde/vpc.properties",
            name_data["models"]["dev/cde/vpc"],
        )
        partial_names = snapshot(generator.generate(name_root, "dev", "cde", "vpc")[0])[
            "names"
        ]
        TestCase().assertEqual(
            [partial_names[f"EC2_EIP_{number}"] for number in ("005", "006", "008")],
            [
                "duplicate (eipalloc-11111111111111111)",
                "duplicate (198.51.100.22)",
                "duplicate",
            ],
        )
        for index, value in enumerate(("PENDING_DEPLOY", "EC2_VPC_001")):
            name_data["models"]["dev/cde/vpc"]["observed.row.001-002.value"] = (
                f"`{value}`"
            )
            value_root = root / f"unconfirmed-{index}"
            value_root.mkdir()
            (value_root / "project.json").write_text(
                (root / "project.json").read_text(encoding="utf-8"), encoding="utf-8"
            )
            write_model(
                value_root / "model/dev/cde/vpc.properties",
                name_data["models"]["dev/cde/vpc"],
            )
            source, _, unsupported = generator.generate(value_root, "dev", "cde", "vpc")
            unresolved_names = snapshot(source)["names"]
            TestCase().assertEqual(unresolved_names["EC2_VPC_001"], "duplicate")
            TestCase().assertEqual(unresolved_names["EC2_VPC_002"], "duplicate (vpc-b)")
            if value != "EC2_VPC_001":
                TestCase().assertIn(
                    (
                        "EC2.VPC.VpcId",
                        "observed identifier is PENDING_DEPLOY; outcome depends on AWS",
                    ),
                    unsupported,
                )
        # Same account, duplicate Alias/service names and another environment stay distinct.
        crossroot = root / "cross-synthetic"
        crossroot.mkdir()
        project = json.loads((root / "project.json").read_text())
        project["targets"][1]["awsAccountId"] = "123456789012"
        project["targets"].append({**project["targets"][0], "environment": "prod"})
        (crossroot / "project.json").write_text(json.dumps(project), encoding="utf-8")
        write_model(
            crossroot / "model/dev/cde/iam.properties", iam["models"]["dev/cde/iam"]
        )
        for env, alias in [("dev", "other"), ("prod", "cde")]:
            write_model(
                crossroot / "model" / env / alias / "vpc.properties",
                vpc["models"]["dev/cde/vpc"],
            )
            gateway = fixture({}, "ec2", inputs["resources"]["cross-scope-gateway"])
            write_model(
                crossroot / "model" / env / alias / "ec2.properties",
                gateway["models"]["dev/cde/ec2"],
            )
        cross_values = dict(vpc["models"]["dev/cde/vpc"])
        write_model(crossroot / "model/dev/cde/vpc.properties", cross_values)
        input_context = _imports_input_cache.input_context
        with input_context():
            cross = snapshot(generator.generate(crossroot, "dev", "cde", "vpc")[0])
        assert {"dev/other/vpc", "prod/cde/vpc"}.isdisjoint(cross["models"])
        # Embedded independent scopes still cannot expand the authorized AWS retrieval scope.
        for env, alias in (("dev", "other"), ("prod", "cde")):
            for service, data in (("vpc", vpc), ("ec2", gateway)):
                cross["models"][env + "/" + alias + "/" + service] = data["models"][
                    "dev/cde/" + service
                ]
        gateway_snapshot = snapshot(
            generator.generate(crossroot, "dev", "other", "ec2")[0]
        )
        for field in ("mappings", "schemas", "outputs", "adapters"):
            cross[field].update(gateway_snapshot[field])
        with patch.dict(sys.modules):
            m = runtime(cross)["engine"](cross)
            ctx = m.Context(
                m.ROOT,
                cross["target"],
                cli_runner=lambda *a, **k: (_ for _ in ()).throw(
                    AssertionError("AWS forbidden")
                ),
            )
            consumer = ctx.model(m.ROOT / "model/dev/cde/vpc.properties").resources[1]
            for address in ("dev/other/vpc", "prod/cde/vpc"):
                producer = ctx.model(
                    m.ROOT / "model" / (address + ".properties")
                ).resources[0]
                assert producer.model.path == m.ROOT / "model" / (
                    address + ".properties"
                )
                gateway_resource = ctx.model(
                    m.ROOT / "model" / (address.removesuffix("vpc") + "ec2.properties")
                ).resources[0]
                assert gateway_resource.kind == "EC2.TransitGateway"
                local = consumer.reference(
                    {"$modelRef": {"logicalId": "EC2_VPC_001", "attribute": "VpcId"}}
                )
                TestCase().assertEqual(
                    local.model.path, m.ROOT / "model/dev/cde/vpc.properties"
                )
                for selected in (producer, gateway_resource):
                    key = (selected.model.path, selected.number, "base")
                    ctx.fetch_cache[key], ctx.fetch_trace[key] = {"id": "cached"}, []
                    for acquire in (
                        lambda *, selected=selected: selected.identity(),
                        lambda *, selected=selected: ctx.fetch(selected, "base"),
                        lambda *, selected=selected: ctx._fetch(selected, "base"),
                    ):
                        try:
                            acquire()
                        except m.Unresolved as error:
                            assert "outside authorized AWS retrieval scope" in str(
                                error
                            )
                        else:
                            raise AssertionError(
                                "cross-scope reference expanded AWS authorization"
                            )
            try:
                consumer.reference(
                    {"$modelRef": {"logicalId": "EC2_VPC_999", "attribute": "VpcId"}}
                )
            except m.Unresolved as error:
                assert "no unique producer" in str(error)
            else:
                raise AssertionError("absent producer used another scope")


def test_pipeline_generation_membership():
    inputs, expected = load_fixture("audit/runtime")
    with tempfile.TemporaryDirectory(prefix="pipeline-projection-") as directory:
        root = Path(directory)
        (root / "project.json").write_text(
            json.dumps(inputs["project"]), encoding="utf-8"
        )
        model = dict(inputs["pipeline"]["model"])
        path = root / "model/dev/cde/codepipeline.properties"
        write_model(path, model)
        source, _, notices = generator.generate(root, "dev", "cde", "codepipeline")
        assert not any("membership unresolved" in reason for _, reason in notices), (
            notices
        )
        namespace = {"__name__": "pipeline_fixture", "__file__": str(root / "audit.py")}
        exec(compile(source, "<pipeline-audit>", "exec"), namespace)
        stages = inputs["pipeline"]["stages"]
        for status in ("match", "different"):
            if status == "different":
                stages[1]["actions"][3]["configuration"]["Extra3"] = "wrong"
                stages[1]["actions"][2]["runOrder"] = 2
            cli = CLI(
                {
                    ("codepipeline", "get-pipeline"): {
                        "pipeline": {"name": "fixture-pipeline", "stages": stages}
                    }
                }
            )
            records = namespace["audit"](namespace["SNAPSHOT"], None, cli)[2]
            actual = {
                item["propertiesKey"].removeprefix("CodePipeline.Pipeline."): item[
                    "status"
                ]
                for item in records
                if item["propertiesKey"].endswith((".Configuration", ".RunOrder"))
            }
            assert actual == expected["pipeline"][status], actual
        for suffix in ("property", "value", "comment"):
            del model["desired.row.001-002." + suffix]
        write_model(path, model)
        _, _, notices = generator.generate(root, "dev", "cde", "codepipeline")
        assert any(
            expected["pipeline"]["missingRow"] in key
            and "membership unresolved" in reason
            for key, reason in notices
        ), notices


def test_fixture_comparator_rejects_mismatches():
    actual = [
        {
            "records": [{"status": "match", "designValue": False}],
            "calls": [["api", {}]],
            "report": "[OK] visible",
            "code": 0,
        }
    ]
    expected = [
        {
            "records": [{"status": "match", "designValue": False}],
            "calls": [["api", {}]],
            "report": {
                "contains": ["visible"],
                "absent": ["secret"],
                "counts": [["[OK]", 1]],
            },
            "code": 0,
        }
    ]
    assert_result(actual, ({}, expected))
    for change in ("status", "type", "record", "call", "report"):
        candidate = copy.deepcopy(actual)
        if change == "status":
            candidate[0]["records"][0]["status"] = "difference"
        elif change == "type":
            candidate[0]["records"][0]["designValue"] = 0
        elif change == "record":
            candidate[0]["records"].append(dict(candidate[0]["records"][0]))
        elif change == "call":
            candidate[0]["calls"] = []
        else:
            candidate[0]["report"] = "[OK] secret"
        with pytest.raises(AssertionError):
            assert_result(candidate, ({}, expected))


def _audit_cli_source(task, change, *args):
    if change:
        task.write_bytes(task.read_bytes() + b"# concurrent contract edit\n")
    return "generated source", {}, []


@pytest.mark.parametrize(
    "failure", ["completed", "suspend", "missing", "scope", "changed"]
)
@pytest.mark.parametrize("existing", [False, True])
def test_audit_cli_failure_preserves_output(tmp_path, failure, existing):
    check = TestCase()
    task = tmp_path / "tasks/audit.md"
    task.parent.mkdir()
    text = (
        contract("audit", ["tests/dev/cde/vpc.py"])
        .replace("`governance`", "`migration`")
        .replace("`framework`", "`dev/cde/vpc`")
    )
    if failure in {"completed", "suspend"}:
        text = text.replace("`running`", "`" + failure + "`")
        if failure == "suspend":
            text += "\n## Suspension reason\nExplicit stop\n"
    if failure == "scope":
        text = text.replace("tests/dev/cde/vpc.py", "tests/dev/cde/other.py")
    if failure != "missing":
        task.write_text(text)
    output = tmp_path / "tests/dev/cde/vpc.py"
    output.parent.mkdir(parents=True)
    if existing:
        output.write_bytes(b"preserve existing output")
    with (
        patch.object(generator._imports_task_contract, "validate_contract"),
        patch.object(
            generator,
            "generate",
            side_effect=partial(_audit_cli_source, task, failure == "changed"),
        ) as generate,
    ):
        check.assertEqual(
            generator.main(
                [
                    "--repository-root",
                    str(tmp_path),
                    "--environment",
                    "dev",
                    "--target",
                    "cde",
                    "--service",
                    "vpc",
                    "--task-file",
                    "tasks/audit.md",
                ]
            ),
            2,
        )
    check.assertEqual(
        output.read_bytes() if output.exists() else None,
        b"preserve existing output" if existing else None,
    )
    check.assertEqual(generate.call_count, int(failure == "changed"))


def _role_tags_response(tags):
    role = {"RoleName": "fixture-role"}
    if tags is not None:
        role["Tags"] = tags
    return [{"api": ["iam", "get-role"], "response": {"Role": role}}]


def test_iam_role_tags_reuse_get_role_and_preserve_pairs():
    inputs, _ = load_fixture("iam/model-reference")
    inputs.pop("models")
    inputs["model"] = {
        key: value
        for key, value in inputs["model"].items()
        if not key.startswith("desired.row.001-002.")
    }
    for number, field, value in [
        (2, "Key", "a"),
        (3, "Value", "one"),
        (4, "Key", "b"),
        (5, "Value", "two"),
    ]:
        prefix = f"desired.row.001-{number:03d}."
        inputs["model"].update(
            {
                prefix + "property": "IAM.Role.Tags[]." + field,
                prefix + "value": f"`{value}`",
                prefix + "comment": "fixture",
            }
        )
    inputs["fields"] = ["propertiesKey", "status"]
    inputs["properties"] = ["IAM.Role.Tags[].Key", "IAM.Role.Tags[].Value"]
    inputs["report"] = False

    response = _role_tags_response

    inputs["scenarios"] = [
        {"responses": response(None)},
        {
            "responses": response(
                [{"Key": "b", "Value": "two"}, {"Key": "a", "Value": "one"}]
            )
        },
        {
            "responses": response(
                [{"Key": "b", "Value": "one"}, {"Key": "a", "Value": "two"}]
            )
        },
        {"fail": ["iam", "get-role"]},
    ]
    results = execute((inputs, []))
    assert [[row["status"] for row in result["records"]] for result in results] == [
        ["difference", "difference"],
        ["match", "match"],
        ["match", "difference"],
        ["acquisition_failed", "acquisition_failed"],
    ]
    for result in results:
        assert result["calls"] == [[["iam", "get-role"], {"RoleName": "fixture-role"}]]


if __name__ == "__main__":
    raise SystemExit(run(__file__))
