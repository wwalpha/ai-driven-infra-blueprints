#!/usr/bin/env python3
"""Native YAML remains generic; Model references use fixed saved identities."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
from tempfile import TemporaryDirectory

import model.identity as _imports_model_identity
import pytest
from design.catalog import DesignSchemaCatalog
from design.services.codepipeline import pipeline_display_rows, pipeline_rows
from model.core import entries, literal, resource_row_index
from model.format import FORMAT, parse, serialize
from model.importing.cli import property_schema
from model.importing.sources import typed_row
from model.operations import CandidateReads
from model.references import usages
from model.sources import load_model
from support.import_model_fixtures import (
    reference_fields,
    resource_values,
    service_values,
)
from support.model_sources import write_model
from support.service_fixtures import TYPED_SERVICES, authored_service, topology
from utils.source_reads import FileReads
from utils.yaml_format import yaml_read

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_yaml_schema():
    assert yaml_read("value: on\ndate: 2026-10-11\nnumber: 001\nboolean: true\n") == {
        "value": "on",
        "date": "2026-10-11",
        "number": "001",
        "boolean": True,
    }
    for text in [
        "a: 1\na: 2",
        "a: {b: 1, b: 2}",
        "a: !!python/object:bad {}",
        "a: &x {b: 1}\nc: {<<: *x}",
    ]:
        with pytest.raises(ValueError, match="YAML"):
            yaml_read(text)


def check_embedded_parameter_type():
    # Ordinary scalars have no interpolation or type inference in properties v2.
    raw = 'x<<Flag>> \\ " 001'
    assert (
        parse(FORMAT + "\ndesired.note.literal.text=" + raw + "\n").values[
            "desired.note.literal.text"
        ]
        == raw
    )
    for value in (
        'a"b\\日本語=終',
        "",
        "<<not-reparsed>>",
        "${AWS::Region} {{resolve:ssm:literal}}",
        "<<Missing>>",
        "<<#Name>>x<</Name>>",
        "<<^Name>>x<</Name>>",
        "<<>partial>>",
        "<<&Name>>",
        "<<{Name}>>",
        "<<= x y =>>",
        "{{#Name}}",
        "{{>partial}}",
    ):
        assert (
            parse(FORMAT + "\ndesired.note.literal.text=" + value + "\n").values[
                "desired.note.literal.text"
            ]
            == value
        )


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize(
    "types,expected",
    [
        (["EC2.VPC"], "001"),
        (["EC2.Subnet"], "zero matching"),
        ([], "zero candidates"),
        (["EC2.VPC", "EC2.VPC"], "multiple matching"),
    ],
)
def check_reference_target_candidates(tmp_path, external, types, expected):
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "environment": "preview",
                        "alias": "team",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ]
            }
        )
    )
    path = tmp_path / "model/preview/team/consumer.properties"
    producer = path.with_name("producer.properties") if external else path
    values = service_values(
        "producer" if external else "consumer", types or ["EC2.VPC"]
    )
    for index, kind in enumerate(types, 1):
        rid = f"{index:03d}"
        values.update(resource_values(rid, kind, "anchor-" + rid, "CREATE", []))
    if external:
        write_model(producer, values)
        values = service_values("consumer", ["Example.Resource"])
    values.update(
        resource_values(
            "009",
            "Example.Resource",
            "consumer",
            "CREATE",
            [
                (
                    "Target",
                    "[resource]("
                    + ("producer" if external else "consumer")
                    + ".md#anchor-001)",
                )
            ],
        )
    )
    values.update(
        reference_fields(
            "fixed",
            "desired.row.009-001.value",
            values["desired.row.009-001.value"],
            "preview/team/" + ("producer" if external else "consumer") + "/001",
            kind="EC2.VPC",
            mode="link",
        )
    )
    state = {}
    for _, resource in entries(values, "desired.resource."):
        state[resource["resourceType"]] = max(
            state.get(resource["resourceType"], 0),
            int(resource["logicalId"].rsplit("_", 1)[1]),
        )
    values["desired.service.identity.lastAllocated"] = json.dumps(state)
    write_model(path, values)
    snapshot = load_model(path)
    if expected in {"001", "multiple matching"}:
        # An explicit fixed ID does not become ambiguous when another Resource has the same Type.
        assert not snapshot.warnings
        (record,) = usages(snapshot)
        assert record.producer_id == "001" and record.metadata_id == "fixed"
        if external:
            assert producer in snapshot.dependencies
    else:
        assert (
            snapshot.warnings
            and snapshot.authoritative["desired.reference.fixed.producerLogicalId"]
            == "EC2_VPC_001"
        )
        assert any(
            "absent" in warning["message"] if types else "absent" in warning["message"]
            for warning in snapshot.warnings
        )


@pytest.mark.parametrize("failure", [None, "collision", "format"])
def check_stack_target_identity(tmp_path, failure):
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "environment": "preview",
                        "alias": "team",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ]
            }
        )
    )
    path = tmp_path / "model/preview/team/consumer.properties"
    stack = path.with_name("cloudformation-stacks.properties")
    values = {
        "desired.stack.001.name": "StackName",
        "desired.stack.001.template": "stack.yaml",
        "desired.stack.001.parameters": "stack.json",
        "desired.stack.001.deployOrder": "1",
    }
    write_model(stack, values)
    values = service_values("consumer", ["Example.Resource"])
    values.update(
        resource_values(
            "001", "Example.Resource", "consumer", "CREATE", [("Target", "StackName")]
        )
    )
    fields = {
        "consumerKey": "desired.row.001-001.value",
        "text": "StackName",
        "occurrence": "1",
        "producerKind": "stack",
        "producerScope": "preview/team/cloudformation-stacks",
        "producerId": "001",
        "format": "name",
        "property": "name",
        "labelPolicy": "none",
    }
    if failure == "format":
        fields["format"] = "link"
    if failure == "collision":
        fields["resourceType"] = "CloudFormation.Stack"
    values.update(
        {"desired.reference.stack." + field: raw for field, raw in fields.items()}
    )
    write_model(path, values)
    if failure:
        with pytest.raises(ValueError, match="stack reference|forbidden"):
            load_model(path)
    else:
        snapshot = load_model(path)
        (record,) = usages(snapshot)
        assert (
            record.producer_kind == "stack"
            and record.producer_id == "001"
            and record.text == "StackName"
        )
        assert not snapshot.warnings


def cases(service):
    with TemporaryDirectory(prefix="service-contract-unit-") as directory:
        root = Path(directory)
        topology(root, ("dev",))
        if service == "cloudformation-stacks":
            path = root / "model/dev/team/cloudformation-stacks.properties"
            write_model(
                path,
                {
                    "desired.deployment.maxConcurrentStacks": "2",
                    "desired.stack.fixture.name": "fixture",
                    "desired.stack.fixture.placementName": "fixture",
                    "desired.stack.fixture.template": "fixture.yaml",
                    "desired.stack.fixture.parameters": "fixture.json",
                    "desired.stack.fixture.deployOrder": "1",
                },
            )
        else:
            kind = {
                "config": "Config.ConfigurationRecorder",
                "data-firehose": "KinesisFirehose.DeliveryStream",
                "guardduty": "GuardDuty.Detector",
                "macie": "Macie.Session",
                "quicksight": "QuickSight.DataSource",
                "codebuild": "CodeBuild.Project",
                "ec2": "EC2.Instance",
                "mwaa": "MWAA.Environment",
                "transit-gateway": "EC2.TransitGateway",
            }.get(service)
            resources = (
                TYPED_SERVICES[service]
                if kind is None
                else [("001", kind, service + "-fixture", [("Name", "`fixture`")])]
            )
            extra = (
                {"desired.row.001-004.comment": "BranchName: ブランチ"}
                if service == "codepipeline"
                else {}
            )
            path = authored_service(root, "dev", service, resources, extra=extra)
        yield load_model(path)


def property_key(snapshot, prop):
    keys = [
        key.removesuffix(".property") + ".value"
        for key, value in snapshot.authoritative.items()
        if key.endswith(".property") and value == prop
    ]
    assert len(keys) == 1, (prop, keys)
    return keys[0]


def candidate(before, changes):
    values = {**before.authoritative, **changes}
    values = {key: value for key, value in values.items() if value is not None}
    output = {before.scope.path: serialize(values)}
    after = load_model(before.scope, CandidateReads(FileReads(), output))
    assert {
        key
        for key in before.authoritative.keys() | after.authoritative.keys()
        if before.authoritative.get(key) != after.authoritative.get(key)
    } == {key for key in changes if before.authoritative.get(key) != changes[key]}
    assert all(
        path.read_bytes() == text.encode("utf-8") for path, text in before.files.items()
    )
    return after


def native_edit(before, prop, value):
    key = property_key(before, prop)
    row = {"property": prop}
    raw = (
        "`" + json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "`"
        if not isinstance(value, str)
        else "`" + value + "`"
    )
    assert type(typed_row(row, raw, property_schema(prop))) is type(value)
    kind = ".".join(prop.split(".")[:2])
    assert not DesignSchemaCatalog(Path(__file__).resolve().parents[4]).literal_errors(
        kind, prop[len(kind) + 1 :], literal(raw)
    )
    return candidate(before, {key: raw})


def check_kms():
    assert DesignSchemaCatalog(Path(__file__).resolve().parents[4]).literal_errors(
        "KMS.Key", "Enabled", "not-a-number"
    )
    for before in cases("kms"):
        after = native_edit(before, "KMS.Key.PendingWindowInDays", 20)
        assert (
            after.authoritative[property_key(before, "KMS.Key.PendingWindowInDays")]
            == "`20`"
        )
        key = property_key(before, "KMS.Alias.AliasName")
        renamed = candidate(before, {key: "`alias/log-acceptance`"})
        assert renamed.authoritative[key].endswith("-acceptance`")
        assert {
            key: raw
            for key, raw in renamed.authoritative.items()
            if key.startswith("desired.resource.")
        } == {
            key: raw
            for key, raw in before.authoritative.items()
            if key.startswith("desired.resource.")
        }


def check_security_group():
    assert DesignSchemaCatalog(Path(__file__).resolve().parents[4]).literal_errors(
        "EC2.SecurityGroup", "SecurityGroupIngress[].FromPort", "not-a-number"
    )
    for before in cases("security-group"):
        prop = "EC2.SecurityGroup.SecurityGroupIngress[].FromPort"
        previous = typed_row(
            {"property": prop},
            before.authoritative[property_key(before, prop)],
            property_schema(prop),
        )
        assert type(previous) is int
        assert (
            native_edit(before, prop, previous + 1).authoritative[
                property_key(before, prop)
            ]
            == "`444`"
        )


def check_route53():
    for before in cases("route53"):
        values = before.authoritative
        for _rid, rows in resource_row_index(values).items():
            (row,) = [
                (row_id, spec)
                for row_id, spec in rows
                if spec["property"] == "Route53.RecordSet.TTL"
            ]
            key = "desired.row." + row[0] + ".value"
            assert (
                typed_row(
                    row[1], row[1]["value"], property_schema("Route53.RecordSet.TTL")
                )
                == "60"
            )
            assert candidate(before, {key: "`61`"}).authoritative[key] == "`61`"
        names = {
            key.removesuffix(".property") + ".value": raw
            for key, raw in values.items()
            if raw == "Route53.RecordSet.Name"
        }
        changes = {key: values[key].replace("fixture.", "fixturex.") for key in names}
        renamed = candidate(before, changes)
        assert len(changes) == 2 and all(
            renamed.authoritative[key] == values[key]
            for key in values
            if key.endswith(".anchor")
        )
        # Duplicate TTL Properties belong to distinct fixed Resources, and remain typed separately.
        assert all(
            literal(values[key.removesuffix(".property") + ".value"]) == "60"
            for key, raw in values.items()
            if raw == "Route53.RecordSet.TTL"
        )


def check_iam():
    assert (
        typed_row(
            {"property": "IAM.Role.RoleName"},
            "001",
            property_schema("IAM.Role.RoleName"),
        )
        == "001"
    )
    objects = 0
    for before in cases("iam"):
        (key,) = [key for key in before.authoritative if key.endswith(".document")]
        document = json.loads(before.authoritative[key])
        assert isinstance(document["Statement"], (dict, list))
        objects += isinstance(document["Statement"], dict)
        updated = json.loads(before.authoritative[key])
        updated["Statement"]["Principal"]["AWS"] = "123456789012"
        after = candidate(before, {key: json.dumps(updated)})
        assert json.loads(after.values[key]) == updated
        assert after.values[key] != before.values[key]
    assert objects > 0


def check_s3():
    assert DesignSchemaCatalog(Path(__file__).resolve().parents[4]).literal_errors(
        "S3.Bucket", "LifecycleConfiguration.Rules[].ExpirationInDays", "not-a-number"
    )
    for before in cases("s3"):
        prop = "S3.Bucket.LifecycleConfiguration.Rules[].ExpirationInDays"
        assert (
            native_edit(before, prop, 31).authoritative[property_key(before, prop)]
            == "`31`"
        )


def check_glue():
    jobs = 0
    for before in cases("glue"):
        assert before.authoritative[property_key(before, "Glue.Job.Timeout")] == "`30`"
        key = property_key(before, "Glue.Job.SecurityConfiguration")
        name = property_key(before, "Glue.SecurityConfiguration.Name")
        logical = before.authoritative["desired.resource.002.logicalId"]
        address = _imports_model_identity.address
        after = candidate(
            before,
            {
                key: address(
                    before.scope,
                    dict(entries(before.authoritative, "desired.resource."))["002"],
                    consumer_scope=before.scope,
                ),
                name: "`glsc-a1b2c3`",
            },
        )
        assert after.authoritative["desired.resource.002.logicalId"] == logical
        raw = after.authoritative[property_key(before, "Glue.Job.DefaultArguments")]
        arguments = json.loads(literal(raw))
        assert isinstance(arguments, dict) and all(
            isinstance(value, str) for value in arguments.values()
        )
        jobs += 1
    assert jobs > 0


def check_lambda():
    functions = permissions = 0
    for before in cases("lambda"):
        for rid, rows in resource_row_index(before.authoritative).items():
            kind = before.authoritative["desired.resource." + rid + ".resourceType"]
            functions += kind == "Lambda.Function"
            permissions += kind == "Lambda.Permission"
            for _, row in rows:
                if row["property"] == "Lambda.Function.Architectures":
                    assert json.loads(literal(row["value"])) == ["x86_64"]
                if row["property"] == "Lambda.Permission.Principal":
                    assert literal(row["value"]) in (
                        "s3.amazonaws.com",
                        "events.amazonaws.com",
                    )
        assert (
            native_edit(before, "Lambda.Function.MemorySize", 129).authoritative[
                property_key(before, "Lambda.Function.MemorySize")
            ]
            == "`129`"
        )
    assert functions > 0 and permissions > 0


def check_eventbridge():
    rules = schedules = 0
    for before in cases("eventbridge"):
        for rid, rows in resource_row_index(before.authoritative).items():
            kind = before.authoritative["desired.resource." + rid + ".resourceType"]
            rules += kind == "Events.Rule"
            schedules += kind == "Scheduler.Schedule"
            for row_id, row in rows:
                if row["property"] == "Events.Rule.EventPattern":
                    doc = json.loads(
                        before.authoritative["desired.row." + row_id + ".document"]
                    )
                    assert doc["detail"]["eventName"] == ["GetObject"]
                    assert isinstance(doc["detail"]["userIdentity"]["userName"], list)
                    assert isinstance(
                        doc["detail"]["requestParameters"]["bucketName"], list
                    )
                elif row["property"].endswith(".ScheduleExpressionTimezone"):
                    assert literal(row["value"]) == "Asia/Tokyo"
                elif row["property"].endswith(".ScheduleExpression"):
                    assert literal(row["value"]).startswith("cron(")
                elif row["property"].endswith(".State"):
                    assert literal(row["value"]) in ("ENABLED", "DISABLED")
        for name, value in [
            ("MaximumEventAgeInSeconds", 3600),
            ("MaximumRetryAttempts", 3),
        ]:
            rows = [
                row
                for owned in resource_row_index(before.authoritative).values()
                for _, row in owned
                if row["property"].endswith(".RetryPolicy." + name)
            ]
            assert rows and all(row["value"] == f"`{value}`" for row in rows)
        assert not before.warnings
    assert rules > 0 and schedules > 0


def check_codepipeline():
    pipelines = configurations = 0
    for before in cases("codepipeline"):
        for rows in resource_row_index(before.authoritative).values():
            pipelines += 1
            formal = [
                [
                    row_id,
                    row["property"].removeprefix("CodePipeline.Pipeline."),
                    row["value"],
                    row["comment"],
                ]
                for row_id, row in rows
            ]
            restored = pipeline_display_rows(pipeline_rows(formal))
            assert [
                (row[1].removeprefix("CodePipeline.Pipeline."), row[2])
                for row in restored
            ] == [(row[1], row[2]) for row in formal]
            for row_id, row in rows:
                if row["property"].endswith(".Configuration"):
                    document = json.loads(literal(row["value"]))
                    assert all(type(value) is str for value in document.values())
                    key = "desired.row." + row_id + ".value"
                    after = candidate(
                        before,
                        {
                            key: "`"
                            + json.dumps(
                                {
                                    **document,
                                    "BranchName": document["BranchName"] + "-probe",
                                }
                            )
                            + "`"
                        },
                    )
                    assert json.loads(literal(after.authoritative[key])) == {
                        **document,
                        "BranchName": document["BranchName"] + "-probe",
                    }
                    configurations += 1
    assert pipelines > 0 and configurations > 0


def check_responsibilities():
    services = {
        "config",
        "data-firehose",
        "guardduty",
        "macie",
        "quicksight",
        "codebuild",
        "ec2",
        "mwaa",
        "cloudformation-stacks",
        "transit-gateway",
    }
    for service in sorted(services):
        for before in cases(service):
            assert before.authoritative and before.locations
            assert not any(
                key.endswith(".artifactSha256") for key in before.authoritative
            )
            assert before.scope.root / "project.json" in before.dependencies
            if service == "cloudformation-stacks":
                after = candidate(
                    before, {"desired.deployment.maxConcurrentStacks": "3"}
                )
                assert (
                    after.authoritative["desired.stack.fixture.placementName"]
                    == "fixture"
                )
                assert after.values["desired.deployment.maxConcurrentStacks"] == "3"
                with pytest.raises(ValueError):
                    candidate(before, {"desired.deployment.maxConcurrentStacks": "0"})
            else:
                (key,) = [key for key in before.authoritative if key.endswith(".value")]
                after = candidate(before, {key: "`changed`"})
                assert all(
                    after.authoritative[key] == raw
                    for key, raw in before.authoritative.items()
                    if key.startswith(("desired.resource.", "observed."))
                )


def check_log_group_native_scalars():
    for prop, raw, expected in [
        ("Logs.LogGroup.DeletionProtectionEnabled", "`false`", False),
        ("Logs.LogGroup.RetentionInDays", "`30`", 30),
    ]:
        value = typed_row({"property": prop}, raw, property_schema(prop))
        assert value == expected and type(value) is type(expected)


def check_declared_instance_inputs(tmp_path):
    root = tmp_path
    topology(root, ("preview",))
    for identity in ("001", "042"):
        values = service_values("explicit", ["Example.Resource"])
        values.update(
            resource_values(
                identity,
                "Example.Resource",
                "explicit-" + identity,
                "CREATE",
                [
                    (
                        "Value",
                        '`{"enabled":true,"fixed":"fixed","optional":3,"sequence":[3,1,2],"empty":null}`',
                    )
                ],
            )
        )
        path = root / "model/preview/team/explicit.properties"
        write_model(path, values)
        snapshot = load_model(path)
        key = "desired.row." + identity + "-001.value"
        native = json.loads(snapshot.authoritative[key][1:-1])
        assert native == {
            "enabled": True,
            "fixed": "fixed",
            "optional": 3,
            "sequence": [3, 1, 2],
            "empty": None,
        }
        assert type(native["enabled"]) is bool and type(native["optional"]) is int
        saved = path.read_bytes()
        assert (
            load_model(path).authoritative == snapshot.authoritative
            and path.read_bytes() == saved
        )


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
