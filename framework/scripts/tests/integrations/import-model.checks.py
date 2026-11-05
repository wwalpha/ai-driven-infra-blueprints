#!/usr/bin/env python3
"""Offline acquire/edit/publish integration. Run through tests/run_it.py in CI."""

import sys
from collections import Counter
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import socket
import subprocess
from unittest import TestCase
from unittest.mock import patch

import import_guard
import model.dependency_index as dependency_index
import model.importing.evidence as import_evidence
import model.sources
import pytest
import support.import_model_fixtures as _imports_support_import_model_fixtures
import sync_files
import sync_runtime
import task_contract_runtime as task_contract
from design.layout import expanded_display_rows
from model.core import entries
from model.format import parse, serialize
from model.identity import COUNTERS, allocate
from model.importing import approval as import_approval
from model.importing import repository
from model.importing.scope import read_context
from model.operations import operation_values
from model.render import resource_table_lines
from model.sources import json_text, load_model
from support.import_model_fixtures import (
    ACCOUNT,
    SUBNETS,
    TARGET,
    VPC_ID,
    AwsCli,
    CloudControlCli,
    aws,
    correspondence,
    exclusions,
    fixture,
    logs_edit,
    m,
    project_fixture,
    publish_fixture,
    resource_values,
    review_fixture,
    service_values,
    snapshot,
    stage,
)
from support.import_repository_fixtures import checkpoint, repositories, state
from support.model_sources import write_model
from task_contract_core import selected_task, start
from utils import sealed_evidence
from utils.json_format import document_sha256
from validation import change
from validation.task import TaskValidation

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _incomplete_runner(cli, command, **kwargs):
    if command[1:3] == ["logs", "describe-log-groups"]:
        return subprocess.CompletedProcess(
            command, 1, "", "Could not connect to the endpoint URL: private-token"
        )
    return cli(command, **kwargs)


def _callback_offline_without_git(popen, /, command, *args, **kwargs):
    assert Path(command[0]).stem != "git", "Import IT must not start Git"
    return popen(command, *args, **kwargs)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live network forbidden")),
    )
    popen = subprocess.Popen
    without_git = _bind_framework_callback(_callback_offline_without_git, popen)
    monkeypatch.setattr(subprocess, "Popen", without_git)
    with repositories(monkeypatch):
        yield
    assert "support.worktree_task_fixtures" not in sys.modules


def prepare(
    tmp_path, service="cloudwatch-logs", changed=True, dry_run=False, *, focused=True
):
    root = tmp_path / "case"
    fixture(root, service, register=not dry_run, focused=focused)
    cli = aws(service, changed=changed)
    acquisition = m.acquire(
        root,
        "dev",
        service,
        TARGET,
        dry_run,
        cli,
        resource_types=["Logs.LogGroup"] if service == "cloudwatch-logs" else None,
    )
    return root, acquisition, cli


def input_file(root, service="cloudwatch-logs", env="dev"):
    return root / "model" / env / TARGET / (service + ".properties")


def source_files(root):
    return {
        p.relative_to(root): p.read_bytes()
        for p in (root / "model").rglob("*")
        if p.is_file()
    }


def promote_logs(root, acquisition):
    files = logs_edit(root, acquisition)
    relative = next(iter(files))
    values = parse(files[relative]).values
    values["desired.row.003-004.value"] = "`INFREQUENT_ACCESS`"
    files[relative] = serialize(values)
    selected = [correspondence(acquisition, "managed-new")]
    stage(root, acquisition, files, selected, exclusions(acquisition, selected))
    return files


def check_logs_roundtrip(tmp_path):
    root, acquired, cli = prepare(tmp_path, focused=False)
    path = root / "model/dev/cde/cloudwatch-logs.properties"
    before = load_model(path)
    foreign = {
        p: raw for p, raw in source_files(root).items() if p != path.relative_to(root)
    }
    files = logs_edit(root, acquired)
    with patch.object(
        m, "import_context", side_effect=AssertionError("publish must not reacquire")
    ):
        result = publish_fixture(root, acquired)
    assert (
        result["model"] == "reflected"
        and result["markdown"] == "generated"
        and result["status"] == "complete"
    )
    assert cli.calls == [
        ("sts", "get-caller-identity", {}),
        ("logs", "describe-log-groups", {}),
    ]
    assert not (root / ".blueprint").exists()
    after = load_model(path)
    assert after.authoritative["desired.row.003-002.value"] == "`90`"
    assert after.authoritative["desired.row.003-001.value"] == "`managed-new`"
    display = (root / "docs/designs/dev/cde/cloudwatch-logs.md").read_text()
    assert (
        "| LogGroupName | `managed-new` |" in display
        and "``managed-new``" not in display
    )
    assert all(
        after.authoritative[key] == value
        for key, value in before.authoritative.items()
        if key != "desired.service.identity.lastAllocated"
    )
    assert len(files) == 1
    assert next(iter(files.values())) == path.read_text(encoding="utf-8")
    assert after.authoritative["desired.resource.002.resourceMode"] == "CREATE"
    assert after.authoritative["desired.resource.003.resourceMode"] == "IMPORT"
    assert all((root / p).read_bytes() == raw for p, raw in foreign.items())
    calls = list(cli.calls)
    assert (
        m.recover_display(root, "dev", "cloudwatch-logs", TARGET)["status"]
        == "complete"
    )
    assert cli.calls == calls
    import_guard.require_import_changes(root)


def check_config_sources(tmp_path):
    root, acquired, _ = prepare(tmp_path, "config", changed=False)
    path = root / "model/dev/cde/config.properties"
    before = path.read_bytes()
    stage(root, acquired, {}, excluded=exclusions(acquired, []))
    result = publish_fixture(root, acquired, "config")
    assert result["model"] == "unchanged" and path.read_bytes() == before
    values = load_model(path).values
    assert "AWSServiceRoleForConfig" in values["desired.row.001-007.value"]
    arn = (
        "arn:aws:iam::"
        + ACCOUNT
        + ":role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig"
    )
    values = values | {"desired.row.001-007.value": arn}
    document = root / "docs/designs/dev/cde/config.md"
    output = sync_runtime.generate_files(document, values, root)[document]
    assert (
        "| RoleARN | " + arn + " |" in output
        and "| RoleName | " + arn + " |" not in output
    )


def check_vpc_eight_instances(tmp_path):
    root = tmp_path / "case"
    path = fixture(root, "vpc")
    before = source_files(root)
    acquired = m.acquire(root, "dev", "vpc", TARGET, cli_runner=aws("vpc", noise=True))
    stage(root, acquired, {}, excluded=exclusions(acquired, []))
    result = publish_fixture(root, acquired, "vpc")
    assert result["model"] == "unchanged" and source_files(root) == before
    values = load_model(path).authoritative
    assert len(entries(values, "desired.resource.")) == 8
    assert {
        values[f"desired.row.{rid:03d}-004.value"].strip("`") for rid in range(2, 9)
    } == {name for name, _, _ in SUBNETS}
    assert len(exclusions(acquired, [])) == 10


def check_managed_resource_addition(tmp_path):
    root = tmp_path / "case"
    path = fixture(root, "vpc")
    original = load_model(path)
    foreign = {
        p: p.read_bytes() for p in (root / "model").rglob("*.properties") if p != path
    }
    cli = aws("vpc", changed=True)
    name, identity, source = "audit-private-1a", "subnet-managed-new", "002"
    cli.responses["ec2", "describe-subnets"]["Subnets"].append(
        {
            "SubnetId": identity,
            "VpcId": VPC_ID,
            "CidrBlock": "10.11.0.0/26",
            "AvailabilityZone": "ap-northeast-1a",
            "MapPublicIpOnLaunch": False,
            "Tags": [{"Key": "Name", "Value": name}],
        }
    )
    acquired = m.acquire(root, "dev", "vpc", TARGET, cli_runner=cli)
    values = dict(original.authoritative)
    for key, value in original.authoritative.items():
        if key.startswith(
            (
                f"desired.resource.{source}.",
                f"display.resource.{source}.",
                f"desired.row.{source}-",
                f"observed.row.{source}-",
            )
        ):
            values[key.replace("." + source, ".009", 1)] = value
    del values["desired.resource.009.logicalId"]
    values = allocate(values, ["009"])
    values["desired.resource.009.anchor"] = "vpc-managed-009"
    values["desired.row.009-001.value"] = (
        '`{"$modelRef":{"logicalId":"EC2_Subnet_009","attribute":"SubnetId"}}`'
    )
    values["observed.row.009-001.value"] = identity
    values["desired.row.009-003.value"] = m.model_literal("10.11.0.0/26")
    values["desired.row.009-004.value"] = m.model_literal(name)
    selected = [correspondence(acquired, identity, "009")]
    stage(
        root,
        acquired,
        {path.relative_to(root).as_posix(): serialize(values)},
        selected,
        exclusions(acquired, selected),
    )
    result = publish_fixture(root, acquired, "vpc")
    assert (
        result["status"] == "complete"
        and result["model"] == "reflected"
        and result["markdown"] == "generated"
    )
    assert {change["resource"] for change in result["changes"]} == {"009"}
    current = load_model(path)
    assert len(entries(current.authoritative, "desired.resource.")) == 9
    assert all(
        current.authoritative[k] == v
        for k, v in original.authoritative.items()
        if k != "desired.service.identity.lastAllocated"
    )
    assert current.authoritative["observed.row.009-001.value"] == identity
    assert (
        current.authoritative["desired.row.009-001.value"]
        == '`{"$modelRef":{"logicalId":"EC2_Subnet_009","attribute":"SubnetId"}}`'
    )
    assert (
        current.authoritative["desired.row.009-002.value"]
        == '`{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}`'
    )
    assert all(p.read_bytes() == data for p, data in foreign.items())


def check_optional_profile(tmp_path):
    root = tmp_path / "case"
    fixture(root, register=False, focused=True)
    target = json.loads((root / "project.json").read_text(encoding="utf-8"))
    target["targets"][0].pop("awsProfile")
    (root / "project.json").write_text(json_text(target), encoding="utf-8")
    acquired = m.acquire(
        root,
        "dev",
        "cloudwatch-logs",
        TARGET,
        True,
        aws(profile=None),
        resource_types=["Logs.LogGroup"],
    )
    assert acquired["connection"]["awsProfile"] is None
    import_evidence.discard_acquisition(root, acquired["evidence"])


def check_explicit_no_profile(tmp_path):
    root = tmp_path / "case"
    fixture(root)
    cli = aws(profile=None)
    acquired = m.acquire(
        root,
        "dev",
        "cloudwatch-logs",
        TARGET,
        cli_runner=cli,
        no_profile=True,
        resource_types=["Logs.LogGroup"],
    )
    assert acquired["connection"]["awsProfile"] is None
    assert cli.calls[0][0] == "sts"
    logs_edit(root, acquired)
    assert publish_fixture(root, acquired)["model"] == "reflected"


@pytest.mark.parametrize(
    ("execution_account", "caller_account"),
    [
        pytest.param(ACCOUNT, ACCOUNT, id="same-account"),
        pytest.param("210987654321", "210987654321", id="split-account"),
        pytest.param("210987654321", ACCOUNT, id="sts-mismatch"),
    ],
)
def check_quicksight_group_execution_account(
    tmp_path, execution_account, caller_account
):
    root = tmp_path / "case"
    fixture(root, "quicksight", register=False, focused=True)
    project_path = root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["targets"][0]["awsExecutionAccountId"] = execution_account
    project_path.write_text(json_text(project), encoding="utf-8")
    cli = AwsCli(account=caller_account)
    group = {"GroupName": "fixture-group", "PrincipalId": "list-principal"}
    cli.responses.update(
        {
            ("quicksight", "list-namespaces"): {"Namespaces": [{"Name": "default"}]},
            ("quicksight", "list-groups"): {"GroupList": [group]},
            ("quicksight", "describe-group"): {
                "Group": {
                    "GroupName": group["GroupName"],
                    "Arn": f"arn:aws:quicksight:ap-northeast-1:{execution_account}:group/default/fixture-group",
                    "PrincipalId": "describe-principal",
                }
            },
        }
    )
    kind = "QuickSight.Group"
    if caller_account != execution_account:
        with pytest.raises(ValueError, match="AWS account mismatch"):
            m.acquire(
                root, "dev", "quicksight", TARGET, True, cli, resource_types=[kind]
            )
        assert cli.calls == [("sts", "get-caller-identity", {})]
        return

    acquired = m.acquire(
        root, "dev", "quicksight", TARGET, True, cli, resource_types=[kind]
    )
    namespace_args = {"AwsAccountId": execution_account}
    list_args = dict(namespace_args, Namespace="default")
    describe_args = dict(list_args, GroupName=group["GroupName"])
    assert cli.calls == [
        ("sts", "get-caller-identity", {}),
        ("quicksight", "list-namespaces", namespace_args),
        ("quicksight", "list-groups", list_args),
        ("quicksight", "describe-group", describe_args),
    ]
    assert acquired["status"] == "acquired"
    (record,) = acquired["records"]
    assert record["identityStatus"] == "known"
    assert record["identityComponents"] == [
        {"property": f"{kind}.{name}", "value": value}
        for name, value in describe_args.items()
    ]
    account = record["properties"][kind + ".AwsAccountId"]
    assert account["status"] == "captured" and account["value"] == execution_account
    principal = record["properties"][kind + ".PrincipalId"]
    assert principal["status"] == "captured"
    assert principal["value"] == "describe-principal"
    import_evidence.discard_acquisition(root, acquired["evidence"])


def check_shared_property_and_bindings(tmp_path):
    root = tmp_path / "case"
    fixture(root)
    cli = aws(changed=True)
    cli.logs[-1]["logGroupClass"] = "INFREQUENT_ACCESS"
    acquired = m.acquire(
        root,
        "dev",
        "cloudwatch-logs",
        TARGET,
        cli_runner=cli,
        resource_types=["Logs.LogGroup"],
    )
    stg_path = input_file(root, env="stg")
    before = stg_path.read_bytes()
    promote_logs(root, acquired)
    result = publish_fixture(root, acquired)
    assert result["model"] == "reflected"
    assert stg_path.read_bytes() == before
    assert not (root / "docs/designs/stg").exists()
    assert not any("/stg/" in str(p) for p in result.get("files", []))


def check_repeat_without_reformat(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired)
    publish_fixture(root, acquired)
    before = source_files(root)
    import_guard.require_import_changes(root)
    old_name, new_name = "tasks/import-fixture.md", "tasks/reimport.md"
    checkpoint(root, task=new_name)
    text = (root / old_name).read_text().replace(old_name, new_name)
    start(root, new_name, text)
    with selected_task(root, new_name):
        again = m.acquire(
            root,
            "dev",
            "cloudwatch-logs",
            TARGET,
            cli_runner=aws(changed=True),
            resource_types=["Logs.LogGroup"],
        )
        path = input_file(root)
        selected = [correspondence(again, "managed-new", "003", action="refresh")]
        stage(
            root,
            again,
            {path.relative_to(root).as_posix(): path.read_text()},
            selected,
            exclusions(again, selected),
        )
        assert publish_fixture(root, again)["status"] == "complete"
        import_guard.require_import_changes(root)
    with selected_task(root, old_name):
        assert sealed_evidence.read_sealed(root, import_guard.proof_path(root))[
            "complete"
        ]

    TestCase().assertEqual(source_files(root), before)


def check_empty_inventory_preserves_sources(tmp_path):
    root = tmp_path / "case"
    fixture(root, focused=True)
    cli = aws()
    cli.logs = []
    before = source_files(root)
    acquired = m.acquire(
        root,
        "dev",
        "cloudwatch-logs",
        TARGET,
        cli_runner=cli,
        resource_types=["Logs.LogGroup"],
    )
    assert acquired["records"] == []
    stage(root, acquired, {})
    result = publish_fixture(root, acquired)
    assert result["model"] == "unchanged" and source_files(root) == before


def check_reflection_validation_boundary(tmp_path):
    root, acquired, _ = prepare(tmp_path)
    logs_edit(root, acquired)
    with (
        patch(
            "import_guard.snapshots",
            wraps=import_guard.snapshots,
        ) as snapshots,
        patch(
            "model.validations.full_inputs.check_model_inputs",
            side_effect=AssertionError("no whole design validation"),
        ),
        patch(
            "model.validations.full_inputs._check_model_inputs",
            side_effect=AssertionError("no internal whole design validation"),
        ),
        patch.object(
            m.comparator(),
            "compare_resource",
            side_effect=AssertionError("no AWS comparison phase"),
        ),
        patch.object(change, "validate_save", wraps=change.validate_save) as saving,
    ):
        result = publish_fixture(root, acquired)
    assert result["model"] == "reflected" and result["designValidation"] == "not-run"
    assert saving.call_count == 1
    assert snapshots.call_args_list
    assert all(
        "model" not in call.kwargs["source_paths"] for call in snapshots.call_args_list
    )


def check_dry_run_cleanup(tmp_path):
    root, acquired, _ = prepare(tmp_path, dry_run=True)
    before = snapshot(root)
    logs_edit(root, acquired)
    reviewed = review_fixture(root, acquired, dry_run=True)
    assert reviewed["model"] == "unchanged" and snapshot(root) == before
    assert len(reviewed["review"]["dispositions"]) == len(acquired["records"])
    result = publish_fixture(root, acquired, dry_run=True)
    assert result["status"] == "dry-run"
    assert any(
        item["key"] == "desired.row.003-002.value"
        for disposition in result["review"]["dispositions"]
        for item in disposition["changes"]
    )
    assert snapshot(root) == before and Path(acquired["evidence"]).is_file()
    assert not (root / "tasks").exists() and not (root / ".blueprint/import").exists()


def check_generic_acquisition_roundtrip(tmp_path):
    root = tmp_path / "case"
    root.mkdir()
    project_fixture(root)
    path = root / "model/dev" / ACCOUNT / "datazone.properties"
    write_model(
        path,
        {
            "desired.service.datazone.serviceId": "datazone",
            "desired.service.datazone.ownedCatalogResourceTypes": "DataZone.Domain",
            "display.service.title": "# DataZone 詳細設計",
        },
    )
    checkpoint(root)
    cli = CloudControlCli(
        {
            "DataZone.Domain": [
                {
                    "identifier": "dzd-fixture",
                    "properties": {
                        "Id": "dzd-fixture",
                        "Name": "fixture",
                        "DomainVersion": "V2",
                        "SingleSignOn": {"Type": "DISABLED"},
                    },
                }
            ]
        }
    )
    before = source_files(root)
    acquired = m.acquire(
        root, "dev", "datazone", ACCOUNT, True, cli, resource_types=["DataZone.Domain"]
    )
    assert acquired["status"] == "acquired" and len(acquired["records"]) == 1
    assert acquired["records"][0]["identityComponents"] == [
        {"property": "DataZone.Domain.Id", "value": "dzd-fixture"}
    ]
    stage(root, acquired, {}, excluded=exclusions(acquired, []))
    count = len(cli.calls)
    with patch.object(
        m, "import_context", side_effect=AssertionError("publish cannot acquire")
    ):
        review_fixture(root, acquired, dry_run=True)
        result = m.publish_acquisition(
            root, "dev", "datazone", acquired["evidence"], ACCOUNT, True
        )
    assert (
        result["status"] == "dry-run"
        and source_files(root) == before
        and len(cli.calls) == count
    )


class Route53Cli(CloudControlCli):
    def __call__(self, command, **kwargs):
        if command[1:3] != ["route53", "list-resource-record-sets"]:
            return super().__call__(command, **kwargs)
        inputs = json.loads(command[command.index("--cli-input-json") + 1])
        self.calls.append(("route53", "list-resource-record-sets", inputs))
        assert inputs == {"HostedZoneId": "Z1"}
        body = {
            "IsTruncated": False,
            "ResourceRecordSets": [
                {
                    "Name": "Example.COM.",
                    "Type": "A",
                    "SetIdentifier": "blue",
                    "TTL": 60,
                    "ResourceRecords": [{"Value": "192.0.2.1"}],
                },
                {
                    "Name": "example.com.",
                    "Type": "A",
                    "SetIdentifier": "green",
                    "TTL": 60,
                    "ResourceRecords": [{"Value": "192.0.2.2"}],
                },
            ],
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(body), "")


def check_route53_acquired_identity_evidence(tmp_path):
    root = tmp_path / "case"
    root.mkdir()
    project_fixture(root)
    path = root / "model/dev" / ACCOUNT / "route53.properties"
    values = service_values("route53", ["Route53.HostedZone", "Route53.RecordSet"])
    values.update(
        resource_values(
            "001",
            "Route53.RecordSet",
            "route53-record",
            "IMPORT",
            [
                ("HostedZoneId", "`/hostedzone/Z1`"),
                ("Name", "`example.com.`"),
                ("Type", "`A`"),
            ],
        )
    )
    write_model(path, values)
    checkpoint(root)
    listed = [
        f"- `{path.relative_to(root).as_posix()}`",
        f"- `docs/designs/dev/{ACCOUNT}/route53.md`",
        "- `tasks/import-fixture.md`",
    ]
    start(
        root,
        "tasks/import-fixture.md",
        "\n".join(
            [
                "## Task contract",
                "- Task type: `design`",
                "- Task status: `running`",
                "- Workflow: `import`",
                f"- IMPORT target: `dev/{ACCOUNT}/route53`",
                "## Goal",
                "Bind the selected record",
                "## Required changes",
                "- [R1] Bind record",
                "## Acceptance checks",
                f"- [R1] `exists:docs/designs/dev/{ACCOUNT}/route53.md`",
                "## Validation scope",
                f"- `dev/{ACCOUNT}/route53`",
                "## Modified files",
                *listed,
                "## Allowed paths",
                *listed,
            ]
        ),
    )
    cli = Route53Cli(
        {
            "Route53.HostedZone": [
                {"identifier": "Z1", "properties": {"Id": "Z1", "Name": "example.com."}}
            ]
        }
    )
    before = load_model(path)
    acquired = m.acquire(
        root,
        "dev",
        "route53",
        ACCOUNT,
        False,
        cli,
        resource_types=["Route53.RecordSet"],
    )
    assert acquired["status"] == "acquired", acquired
    assert len(acquired["records"]) == 2
    components = [record["identityComponents"] for record in acquired["records"]]
    assert {item[-1]["value"] for item in components} == {"blue", "green"}
    assert all(
        item[0]["value"] == "Z1" and item[1]["value"] == "example.com"
        for item in components
    )
    sealed = import_evidence.read_acquisition(
        root, Path(acquired["evidence"]), ("dev", ACCOUNT, "route53"), False
    )
    assert [record["identityComponents"] for record in sealed["records"]] == components
    record = next(
        r for r in acquired["records"] if r["identityComponents"][-1]["value"] == "blue"
    )
    selected = [
        {
            "record": record["record"],
            "resource": "001",
            "action": "bind",
            "reason": "Human identifies the existing record",
            "basis": [],
            "before": {
                "identity": None,
                "model": document_sha256(operation_values(before.authoritative, "001")),
            },
        }
    ]
    values["desired.row.001-004.property"] = "Route53.RecordSet.SetIdentifier"
    values["desired.row.001-004.value"] = "`blue`"
    values["desired.row.001-004.comment"] = "合成テストの取得設定"
    values["desired.row.001-005.property"] = "Route53.RecordSet.TTL"
    values["desired.row.001-005.value"] = "`60`"
    values["desired.row.001-005.comment"] = "合成テストの取得設定"
    values["desired.row.001-006.property"] = "Route53.RecordSet.ResourceRecords"
    values["desired.row.001-006.value"] = m.model_literal(["192.0.2.1"])
    values["desired.row.001-006.comment"] = "合成テストの取得設定"
    stage(
        root,
        acquired,
        {path.relative_to(root).as_posix(): serialize(values)},
        selected,
        exclusions(acquired, selected),
    )
    result = publish_fixture(root, acquired, "route53")
    assert result["status"] == "complete", result
    assert load_model(path).authoritative["desired.row.001-004.value"] == "`blue`"
    assert import_evidence.read_proof(root)["complete"] is True


def _callback_check_reference_publication_counted(
    original_read, reads, root, /, scope, *args, **kwargs
):
    if scope.service == "s3":
        reads[read_context(root), args[0]] += 1
    return original_read(scope, *args, **kwargs)


def check_reference_publication(tmp_path):
    CloudControlCli = _imports_support_import_model_fixtures.CloudControlCli
    project_fixture = _imports_support_import_model_fixtures.project_fixture
    reference_fields = _imports_support_import_model_fixtures.reference_fields
    service_values = _imports_support_import_model_fixtures.service_values
    root = tmp_path / "reference-publication"
    root.mkdir()
    project_fixture(root)
    (root / "project.json").write_text(
        json_text(
            {
                "targets": [
                    {
                        "environment": "dev",
                        "alias": TARGET,
                        "awsAccountId": ACCOUNT,
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ]
            }
        )
        + "\n"
    )
    path = root / "model/dev/cde/cloudtrail.properties"
    write_model(path, service_values("cloudtrail", ["CloudTrail.Trail"]))
    producer = path.with_name("s3.properties")
    write_model(
        producer,
        resource_values(
            "001",
            "S3.Bucket",
            "s3-audit-bucket",
            "CREATE",
            [("BucketName", "`audit-bucket`")],
        ),
    )
    checkpoint(root)
    files = {path, root / "docs/designs/dev/cde/cloudtrail.md"}
    listed = ["- `" + p.relative_to(root).as_posix() + "`" for p in sorted(files)] + [
        "- `tasks/import-fixture.md`"
    ]
    text = "\n".join(
        [
            "# Reference fixture",
            "## Task contract",
            "- Task type: `design`",
            "- Task status: `running`",
            "- Workflow: `import`",
            "- IMPORT target: `dev/cde/cloudtrail`",
            "## Goal",
            "Synthetic reference addition",
            "## Required changes",
            "- [R1] Add acquired resource",
            "## Acceptance checks",
            "- [R1] `exists:docs/designs/dev/cde/cloudtrail.md`",
            "## Validation scope",
            "- `dev/cde/cloudtrail`",
            "## Modified files",
            *listed,
            "## Allowed paths",
            *listed,
        ]
    )
    start(root, "tasks/import-fixture.md", text)
    cli = CloudControlCli(
        {
            "CloudTrail.Trail": [
                {
                    "identifier": "audit",
                    "properties": {
                        "TrailName": "audit",
                        "S3BucketName": "audit-bucket",
                        "IsLogging": True,
                        "EventSelectors": [
                            {
                                "ReadWriteType": "All",
                                "IncludeManagementEvents": True,
                                "DataResources": [
                                    {
                                        "Type": "AWS::S3::Object",
                                        "Values": ["audit-bucket"],
                                    }
                                ],
                            }
                        ],
                    },
                }
            ]
        }
    )
    foreign = {
        p: p.read_bytes() for p in (root / "model").rglob("*.properties") if p != path
    }
    acquired = m.acquire(
        root,
        "dev",
        "cloudtrail",
        TARGET,
        cli_runner=cli,
        resource_types=["CloudTrail.Trail"],
    )
    record = acquired["records"][0]
    captured = {
        prop: item["value"]
        for prop, item in record["properties"].items()
        if item["status"] == "captured"
    }
    values = dict(load_model(path).authoritative)
    values.update(
        resource_values(
            "009",
            "CloudTrail.Trail",
            "cloudtrail-audit",
            "IMPORT",
            [
                (prop.removeprefix("CloudTrail.Trail."), m.model_literal(value))
                for prop, value in captured.items()
            ],
        )
    )
    values[COUNTERS] = load_model(path).authoritative.get(COUNTERS, "{}")
    del values["desired.resource.009.logicalId"]
    values = allocate(values, ["009"])
    values["desired.resource.009.anchor"] = "vpc-managed-009"
    link = '`{"$modelRef":{"logicalId":"S3_Bucket_001","attribute":"BucketName"}}`'
    for index, (prop, actual) in enumerate(captured.items(), 1):
        key = f"desired.row.009-{index:03d}.value"
        values[f"desired.row.009-{index:03d}.valueShape"] = record["properties"][prop][
            "valueShape"
        ]
        if prop == "CloudTrail.Trail.S3BucketName":
            values[key] = link
            values[f"observed.row.009-{index:03d}.value"] = m.model_literal(actual)
        elif prop == "CloudTrail.Trail.EventSelectors[].DataResources[].Values":
            values.update(
                reference_fields(
                    "nested-bucket",
                    key,
                    "audit-bucket",
                    "dev/cde/s3/001",
                    kind="S3.Bucket",
                    mode="name",
                    prop="S3.Bucket.BucketName",
                    pointer="/0/0/0",
                )
            )
            assert values[key] == m.model_literal(actual)
    selected = [correspondence(acquired, record["identity"], "009")]
    stage(
        root, acquired, {path.relative_to(root).as_posix(): serialize(values)}, selected
    )
    review_fixture(root, acquired, "cloudtrail")
    calls = len(cli.calls)
    reads = Counter()
    original_read = model.sources._read_model
    counted = _bind_framework_callback(
        _callback_check_reference_publication_counted, original_read, reads, root
    )
    with (
        patch.object(model.sources, "_read_model", counted),
    ):
        result = m.publish_acquisition(
            root, "dev", "cloudtrail", acquired["evidence"], TARGET
        )
    assert (
        result["status"] == "complete"
        and result["model"] == "reflected"
        and result["markdown"] == "generated"
    ), result
    assert all(count == 1 for count in reads.values()), reads
    assert reads
    assert len(cli.calls) == calls
    document = root / "docs/designs/dev/cde/cloudtrail.md"
    markdown = document.read_text()
    assert "](s3.md#s3-audit-bucket)" in markdown
    saved = load_model(path).authoritative
    key = values["desired.reference.nested-bucket.consumerKey"]
    assert saved[key] == values[key]
    assert saved["desired.reference.nested-bucket.format"] == "name"
    assert saved["desired.reference.nested-bucket.pointer"] == "/0/0/0"
    assert all(p.read_bytes() == raw for p, raw in foreign.items())
    assert not (root / "docs/designs/dev/cde/s3.md").exists()
    before_recovery = source_files(root)
    assert m.recover_display(root, "dev", "cloudtrail", TARGET)["status"] == "complete"
    assert source_files(root) == before_recovery and document.read_text() == markdown


@pytest.mark.parametrize("action", ["replace", "bind"])
def check_user_selected_overwrite_publication(tmp_path, action):
    root = tmp_path / "case"
    path = fixture(root, register=True)
    if action == "bind":
        values = dict(load_model(path).authoritative)
        values["desired.row.001-001.value"] = "UNSET"
        path.write_text(serialize(values), encoding="utf-8")
        checkpoint(root)
    cli = aws(changed=True)
    acquired = m.acquire(
        root,
        "dev",
        "cloudwatch-logs",
        TARGET,
        False,
        cli,
        resource_types=["Logs.LogGroup"],
    )
    before = load_model(path)
    original = snapshot(root)
    values = dict(before.authoritative)
    identity = "managed-new"
    values.update(
        {
            "desired.row.001-001.value": m.model_literal(identity),
            "desired.row.001-002.value": "`90`",
        }
    )
    selected = [correspondence(acquired, identity, "001", action)]
    selected[0]["before"] = {
        "identity": None if action == "bind" else "fixture-001",
        "model": document_sha256(operation_values(before.authoritative, "001")),
    }
    stage(
        root,
        acquired,
        {path.relative_to(root).as_posix(): serialize(values)},
        selected,
        exclusions(acquired, selected),
    )
    result = publish_fixture(root, acquired)
    assert result["status"] == "complete"
    review = json.loads((Path(acquired["evidence"]).parent / "review.json").read_text())
    assert (
        next(
            item
            for item in review["dispositions"]
            if item["record"] == selected[0]["record"]
        )["operation"]
        == action
    )
    assert cli.calls == [
        ("sts", "get-caller-identity", {}),
        ("logs", "describe-log-groups", {}),
    ]
    assert Path(acquired["evidence"]).is_file()
    after = load_model(path)
    assert after.authoritative["desired.row.001-002.value"] == "`90`"
    assert after.authoritative["desired.row.001-001.value"] == m.model_literal(identity)
    assert operation_values(before.authoritative, "002") == operation_values(
        after.authoritative, "002"
    )
    assert len(entries(after.authoritative, "desired.resource.")) == 2
    assert all(
        (root / rel).read_bytes() == data
        for rel, data in original.items()
        if "stg" in rel.parts
    )
    import_guard.require_import_changes(root)


def _callback_check_mixed_add_refresh_single_publication_save(
    calls, original_save, /, output
):
    calls.append(set(output))
    return original_save(output)


def check_mixed_add_refresh_single_publication(tmp_path):
    root, acquired, cli = prepare(tmp_path)
    files = logs_edit(root, acquired)
    file = input_file(root)
    relative = file.relative_to(root).as_posix()
    values = parse(files[relative]).values
    values["desired.row.001-002.value"] = "`90`"
    files[relative] = serialize(values)
    selected = [
        correspondence(acquired, "managed-new"),
        correspondence(acquired, "fixture-001", "001", "refresh"),
    ]
    stage(root, acquired, files, selected, exclusions(acquired, selected))
    calls = []
    original_save = sync_files.save_files
    save = _bind_framework_callback(
        _callback_check_mixed_add_refresh_single_publication_save,
        calls,
        original_save,
    )
    with patch.object(sync_files, "save_files", side_effect=save):
        result = publish_fixture(root, acquired)
        assert {item["resource"] for item in result["changes"]} == {"001", "003"}
        values = load_model(file).authoritative
        assert (
            values["desired.row.001-002.value"]
            == values["desired.row.003-002.value"]
            == "`90`"
        )
    assert sum(file in output for output in calls) == 1
    assert len(cli.calls) == 2


def check_replace_warns_incoming_references(tmp_path):
    root = tmp_path / "case"
    path = fixture(root, "vpc")
    before = load_model(path)
    acquired = m.acquire(
        root, "dev", "vpc", TARGET, cli_runner=aws("vpc", changed=True, noise=True)
    )
    values = dict(before.authoritative)
    values.update(
        {
            "desired.row.001-002.value": "`172.16.0.0/16`",
            "desired.row.001-003.value": "`unmanaged`",
            "observed.row.001-001.value": "vpc-00000000000000000",
        }
    )
    selected = [correspondence(acquired, "vpc-00000000000000000", "001", "replace")]
    selected[0]["before"] = {
        "identity": VPC_ID,
        "model": document_sha256(operation_values(before.authoritative, "001")),
    }
    stage(
        root,
        acquired,
        {path.relative_to(root).as_posix(): serialize(values)},
        selected,
        exclusions(acquired, selected),
    )
    original = snapshot(root)
    _ = publish_fixture(root, acquired, "vpc")
    reviewed = json.loads(
        (Path(acquired["evidence"]).parent / "review.json").read_text()
    )
    assert any(
        w["code"] == "reference.replace_impact"
        for w in reviewed["referenceImpact"]["warnings"]
    )
    assert snapshot(root) != original
    assert (
        load_model(path).authoritative["observed.row.001-001.value"]
        == "vpc-00000000000000000"
    )
    assert Path(acquired["evidence"]).is_file()


@pytest.mark.parametrize("missing,other_environment", [(False, False), (True, True)])
def check_first_resource_uses_existing_source_format(
    tmp_path, missing, other_environment
):
    root = tmp_path / "case"
    path = fixture(root)
    seed = dict(load_model(path).authoritative)
    if not other_environment:
        input_file(root, env="stg").unlink()
    service = {
        key: value
        for key, value in seed.items()
        if key.startswith(("desired.service.", "display.service."))
    }
    if missing:
        path.unlink()
        assert not path.exists()
    else:
        path.write_text(serialize(service), encoding="utf-8")
        assert not entries(load_model(path).authoritative, "desired.resource.")
    checkpoint(root)
    cli = aws(changed=True)
    acquired = m.acquire(
        root,
        "dev",
        "cloudwatch-logs",
        TARGET,
        cli_runner=cli,
        resource_types=["Logs.LogGroup"],
    )
    service.update(operation_values(seed, "001"))
    del service["desired.resource.001.logicalId"]
    if missing:
        service.pop("desired.service.identity.lastAllocated", None)
    service = allocate(service, ["001"])
    service["desired.row.001-002.value"] = "`90`"
    selected = [correspondence(acquired, "fixture-001", "001")]
    stage(
        root,
        acquired,
        {path.relative_to(root).as_posix(): serialize(service)},
        selected,
        exclusions(acquired, selected),
    )
    foreign = input_file(root, env="stg")
    original = foreign.read_bytes() if foreign.is_file() else None
    result = publish_fixture(root, acquired)
    assert result["status"] == "complete"
    assert len(entries(load_model(path).authoritative, "desired.resource.")) == 1
    assert path.read_text(encoding="utf-8").startswith("# model-format: 2\n")
    assert (foreign.read_bytes() if foreign.is_file() else None) == original
    assert len(cli.calls) == 2


def check_refresh_switches_definition_without_foreign_changes(tmp_path):
    root = tmp_path / "case"
    file = fixture(root)
    before = source_files(root)
    values = dict(load_model(file).authoritative)
    values.update(
        {
            "desired.row.001-002.value": "`90`",
            "desired.row.001-004.value": "`INFREQUENT_ACCESS`",
        }
    )
    cli = aws(changed=True)
    cli.logs[0]["logGroupClass"] = "INFREQUENT_ACCESS"
    acquired = m.acquire(
        root,
        "dev",
        "cloudwatch-logs",
        TARGET,
        cli_runner=cli,
        resource_types=["Logs.LogGroup"],
    )
    selected = [correspondence(acquired, "fixture-001", "001", "refresh")]
    stage(
        root,
        acquired,
        {file.relative_to(root).as_posix(): serialize(values)},
        selected,
        exclusions(acquired, selected),
    )
    result = publish_fixture(root, acquired)
    assert result["status"] == "complete"
    current = load_model(file).authoritative
    assert current["desired.row.001-004.value"] == "`INFREQUENT_ACCESS`"
    assert current["desired.row.002-004.value"] == "`STANDARD`"
    assert all(
        (root / rel).read_bytes() == data
        for rel, data in before.items()
        if "stg" in rel.parts
    )
    assert (
        load_model(input_file(root, env="stg")).authoritative[
            "desired.row.001-004.value"
        ]
        == "`STANDARD`"
    )


@pytest.mark.parametrize("index_state", ["missing", "stale"])
def check_import_refreshes_reference_metadata_without_full(tmp_path, index_state):
    root, acquired, _ = prepare(tmp_path, focused=False)
    logs_edit(root, acquired)
    if index_state == "missing":
        dependency_index.location(root).unlink()
    else:
        path = input_file(root, env="stg")
        path.touch()  # Stale revision with unchanged approved authoritative bytes.
    with (
        patch(
            "model.validations.full_inputs.check_model_inputs",
            side_effect=AssertionError("Full called"),
        ),
        patch(
            "model.validations.full_inputs._check_model_inputs",
            side_effect=AssertionError("Full internal called"),
        ),
    ):
        result = publish_fixture(root, acquired)
    assert result["model"] == "reflected"


def check_repository_snapshot_detects_real_changes(tmp_path):
    root = tmp_path / "case"
    path = fixture(root)
    baseline = state(root).baseline.copy()
    path.write_bytes(path.read_bytes() + b"# comment change\n")
    added = path.with_name("extra.properties")
    added.write_bytes(b"# model-format: 2\n")
    deleted = input_file(root, env="stg")
    deleted.unlink()
    task = root / "tasks/import-fixture.md"
    task.write_text(task.read_text() + "\n# Task change\n")
    assert repository.changed_paths(root) == {
        p.relative_to(root).as_posix() for p in (path, added, deleted, task)
    }
    assert state(root).baseline == baseline


def _callback_limited_task_paths(self, args):
    return repository.changed_paths(self.root)


def check_limited_acquisition_preserves_values_and_completes(tmp_path):
    root = tmp_path / "limited"
    root.mkdir()
    project_fixture(root)
    service, kind = "lake-formation", "LakeFormation.Resource"
    path = root / "model/dev" / ACCOUNT / (service + ".properties")
    arn = "arn:aws:s3:::limited-fixture"
    role = (
        "arn:aws:iam::"
        + ACCOUNT
        + ":role/aws-service-role/lakeformation.amazonaws.com/AWSServiceRoleForLakeFormationDataAccess"
    )
    values = {
        **service_values(service, [kind]),
        **resource_values(
            "001",
            kind,
            "registered-data",
            "IMPORT",
            [
                ("ResourceArn", m.model_literal(arn)),
                ("UseServiceLinkedRole", "`true`"),
                ("RoleArn", m.model_literal(role)),
                ("WithFederation", "`false`"),
                ("HybridAccessEnabled", "`false`"),
            ],
        ),
    }
    write_model(path, values)
    checkpoint(root)
    source = path.relative_to(root).as_posix()
    document = "docs/designs/dev/" + ACCOUNT + "/" + service + ".md"
    files = ["tasks/import-fixture.md", source, document]
    listing = "\n".join("- `" + name + "`" for name in files)
    contract = (
        "# Limited Import fixture\n## Task contract\n- Task type: `design`\n- Workflow: `import`\n- Task status: `running`\n- IMPORT target: `dev/"
        + ACCOUNT
        + "/"
        + service
        + "`\n## Goal\nReflect acquired values with explicit retained input\n## Required changes\n- [R1] Reflect selected resource\n## Validation scope\n- `dev/"
        + ACCOUNT
        + "/"
        + service
        + "`\n## Modified files\n"
        + listing
        + "\n## Allowed paths\n"
        + listing
        + "\n## Acceptance checks\n- [R1] `exists:"
        + document
        + "`\n"
    )
    start(root, "tasks/import-fixture.md", contract)
    cli = AwsCli()
    cli.responses["lakeformation", "list-resources"] = {
        "ResourceInfoList": [{"ResourceArn": arn}]
    }
    cli.responses["lakeformation", "describe-resource"] = {
        "ResourceInfo": {
            "ResourceArn": arn,
            "RoleArn": role,
            "WithFederation": True,
            "HybridAccessEnabled": False,
        }
    }
    acquired = m.acquire(
        root, "dev", service, ACCOUNT, cli_runner=cli, resource_types=[kind]
    )
    assert acquired["inventory"][kind]["status"] == "limited"
    assert (
        acquired["records"][0]["properties"][kind + ".UseServiceLinkedRole"]["status"]
        == "unobservable"
    )
    proposed = {**values, "desired.row.001-004.value": "`true`"}
    selected = [
        {
            "record": acquired["records"][0]["record"],
            "resource": "001",
            "action": "refresh",
            "reason": "Human-selected existing registration",
            "basis": [],
        }
    ]
    stage(root, acquired, {source: serialize(proposed)}, selected)
    first = review_fixture(root, acquired, service)
    assert first["review"]["limitations"][0]["treatment"] is None
    selection_path = Path(acquired["selection"])
    selection = json.loads(selection_path.read_text())
    selection["limitations"] = [
        {
            "record": selected[0]["record"],
            "property": kind + ".UseServiceLinkedRole",
            "reasonCode": "REQUEST_INPUT_NOT_OBSERVABLE",
            "treatment": "retain_existing",
            "reason": "Explicitly retain the existing input without an AWS confirmation",
        }
    ]
    selection_path.write_text(json_text(selection))
    reviewed = review_fixture(root, acquired, service)
    binding = import_approval.review_binding(
        reviewed["review"],
        import_evidence.read_acquisition(
            root, Path(acquired["evidence"]), ("dev", ACCOUNT, service), False
        ),
    )
    count = len(cli.calls)
    sealed = import_evidence.read_acquisition(
        root, Path(acquired["evidence"]), ("dev", ACCOUNT, service), False
    )
    (Path(acquired["evidence"]).parent / "checkpoint.json").write_text(
        json_text(import_approval.checkpoint(sealed, selected))
    )
    resumed = m.resume_acquisition(root, "dev", service, acquired["evidence"], ACCOUNT)
    assert resumed["status"] == "resumed" and resumed["answers"] == selected
    # The fixture represents consent to this unchanged Review; Python checks integrity only.
    result = m.publish_acquisition(root, "dev", service, acquired["evidence"], ACCOUNT)
    assert result["status"] == "complete" and len(cli.calls) == count
    proof = import_evidence.read_proof(root)
    assert proof["complete"] and proof["completion"] == {
        "acquisition": True,
        "properties": True,
        "review": True,
    }
    assert proof["observationComplete"] is False and proof["reviewBinding"] == binding
    after = load_model(path)
    assert (
        after.authoritative["desired.row.001-002.value"]
        == values["desired.row.001-002.value"]
    )
    assert "observed.row.001-002.value" not in after.authoritative
    import_guard.require_import_changes(root)
    with patch.object(TaskValidation, "git_paths", _callback_limited_task_paths):
        task_contract.complete(root, "tasks/import-fixture.md")
    assert "Task status: `completed`" in (root / "tasks/import-fixture.md").read_text()


@pytest.mark.parametrize(
    "route",
    [
        "cloudcontrol",
        "sdk",
        "sdk-evidence-tamper",
        "sdk-review-tamper",
        "sdk-invalid-no-description",
        "sdk-invalid-present-description",
        "sdk-invalid-omitted-description",
    ],
)
def check_optional_provider_retention_completes(tmp_path, route):
    root = tmp_path / "limited"
    root.mkdir()
    project_fixture(root)
    sdk = route.startswith("sdk")
    service, kind = (
        ("quicksight", "QuickSight.Group") if sdk else ("ec2", "EC2.TransitGateway")
    )
    path = root / "model/dev" / ACCOUNT / (service + ".properties")
    arn = "tgw-1234567890abcdef0"
    values = {
        **service_values(service, [kind]),
        **resource_values(
            "001",
            kind,
            "registered-data",
            "IMPORT",
            [
                ("GroupName", "`group`"),
                ("Description", "`retained description`"),
                ("AwsAccountId", m.model_literal(ACCOUNT)),
                ("Namespace", "`default`"),
                ("PrincipalId", "`old-principal`"),
            ]
            if sdk
            else [
                ("Id", m.model_literal(arn)),
                ("Description", "`retained description`"),
                ("AmazonSideAsn", "`64512`"),
                ("DnsSupport", "`disable`"),
                ("VpnEcmpSupport", "`enable`"),
                ("AutoAcceptSharedAttachments", "`disable`"),
                ("DefaultRouteTableAssociation", "`enable`"),
                ("DefaultRouteTablePropagation", "`enable`"),
            ],
        ),
    }
    if route == "sdk-invalid-no-description":
        values = {
            key: value for key, value in values.items() if ".row.001-002." not in key
        }
    write_model(path, values)
    checkpoint(root)
    source = path.relative_to(root).as_posix()
    document = "docs/designs/dev/" + ACCOUNT + "/" + service + ".md"
    files = ["tasks/import-fixture.md", source, document]
    listing = "\n".join("- `" + name + "`" for name in files)
    contract = (
        "# Limited Import fixture\n## Task contract\n- Task type: `design`\n- Workflow: `import`\n- Task status: `running`\n- IMPORT target: `dev/"
        + ACCOUNT
        + "/"
        + service
        + "`\n## Goal\nReflect acquired values with explicit retained input\n## Required changes\n- [R1] Reflect selected resource\n## Validation scope\n- `dev/"
        + ACCOUNT
        + "/"
        + service
        + "`\n## Modified files\n"
        + listing
        + "\n## Allowed paths\n"
        + listing
        + "\n## Acceptance checks\n- [R1] `exists:"
        + document
        + "`\n"
    )
    start(root, "tasks/import-fixture.md", contract)
    cli = CloudControlCli(
        {
            kind: [
                {
                    "identifier": arn,
                    "properties": {
                        "Id": arn,
                        "AmazonSideAsn": 64512,
                        "DnsSupport": "enable",
                        "VpnEcmpSupport": "enable",
                        "AutoAcceptSharedAttachments": "disable",
                        "DefaultRouteTableAssociation": "enable",
                        "DefaultRouteTablePropagation": "enable",
                    },
                }
            ]
        }
    )
    if sdk:
        cli = AwsCli()
        cli.responses.update(
            {
                ("quicksight", "list-namespaces"): {
                    "Namespaces": [{"Name": "default"}]
                },
                ("quicksight", "list-groups"): {"GroupList": [{"GroupName": "group"}]},
                ("quicksight", "describe-group"): {
                    "Group": {
                        "GroupName": "group",
                        "Arn": f"arn:aws:quicksight:ap-northeast-1:{ACCOUNT}:group/default/group",
                        "PrincipalId": "new-principal",
                    }
                },
            }
        )
    if route.startswith("sdk-invalid"):
        detail = cli.responses[("quicksight", "describe-group")]["Group"]
        detail["Arn"] = detail["Arn"].replace("/default/group", "/default/other")
        if route == "sdk-invalid-present-description":
            detail["Description"] = "wrong resource description"
    before_acquisition = path.read_bytes()
    acquired = m.acquire(
        root, "dev", service, ACCOUNT, cli_runner=cli, resource_types=[kind]
    )
    if route.startswith("sdk-invalid"):
        assert acquired["inventory"][kind]["status"] == "failed"
        assert acquired["status"] == "incomplete"
        if route == "sdk-invalid-no-description":
            assert kind + ".Description" not in values.values()
        with pytest.raises(ValueError, match="complete acquisition"):
            m.publish_acquisition(root, "dev", service, acquired["evidence"], ACCOUNT)
        assert path.read_bytes() == before_acquisition
        return
    assert acquired["inventory"][kind]["status"] == "limited"
    assert (
        acquired["records"][0]["properties"][kind + ".Description"]["status"]
        == "not_returned"
    )
    proposed = {
        **values,
        **(
            {"desired.row.001-005.value": "`new-principal`"}
            if sdk
            else {"desired.row.001-004.value": "`enable`"}
        ),
    }
    selected = [
        {
            "record": acquired["records"][0]["record"],
            "resource": "001",
            "action": "refresh",
            "reason": "Human-selected existing registration",
            "basis": [],
        }
    ]
    stage(root, acquired, {source: serialize(proposed)}, selected)
    first = review_fixture(root, acquired, service)
    assert not first["review"]["completion"]["propertiesResolved"]
    assert first["review"]["limitations"][0]["treatment"] is None
    before_publish = path.read_bytes()
    with pytest.raises(ValueError):
        m.publish_acquisition(root, "dev", service, acquired["evidence"], ACCOUNT)
    assert path.read_bytes() == before_publish
    selection_path = Path(acquired["selection"])
    selection = json.loads(selection_path.read_text())
    selection["limitations"] = [
        {
            "record": selected[0]["record"],
            "property": kind + ".Description",
            "reasonCode": "OPTIONAL_PROPERTY_NOT_RETURNED",
            "treatment": "retain_existing",
            "reason": "Explicitly retain the existing input without an AWS confirmation",
        }
    ]
    selection_path.write_text(json_text(selection))
    reviewed = review_fixture(root, acquired, service)
    assert not reviewed["review"]["completion"]["allPropertiesObserved"]
    binding = import_approval.review_binding(
        reviewed["review"],
        import_evidence.read_acquisition(
            root, Path(acquired["evidence"]), ("dev", ACCOUNT, service), False
        ),
    )
    count = len(cli.calls)
    sealed = import_evidence.read_acquisition(
        root, Path(acquired["evidence"]), ("dev", ACCOUNT, service), False
    )
    (Path(acquired["evidence"]).parent / "checkpoint.json").write_text(
        json_text(import_approval.checkpoint(sealed, selected))
    )
    resumed = m.resume_acquisition(root, "dev", service, acquired["evidence"], ACCOUNT)
    assert resumed["status"] == "resumed" and resumed["answers"] == selected
    if route.endswith("tamper"):
        evidence_file = Path(acquired["evidence"])
        tampered_file = (
            evidence_file
            if route == "sdk-evidence-tamper"
            else evidence_file.parent / "review.json"
        )
        tampered = json.loads(tampered_file.read_text(encoding="utf-8"))
        if route == "sdk-evidence-tamper":
            tampered["payload"]["records"][0]["properties"][kind + ".Description"][
                "evidence"
            ]["identity"] = "other"
        else:
            tampered["completion"]["allPropertiesObserved"] = True
        tampered_file.write_text(json_text(tampered), encoding="utf-8")
        with pytest.raises(ValueError):
            m.publish_acquisition(root, "dev", service, acquired["evidence"], ACCOUNT)
        assert path.read_bytes() == before_publish
        return
    # The fixture represents consent to this unchanged Review; Python checks integrity only.
    result = m.publish_acquisition(root, "dev", service, acquired["evidence"], ACCOUNT)
    assert result["status"] == "complete" and len(cli.calls) == count, result
    proof = import_evidence.read_proof(root)
    assert proof["complete"] and proof["completion"] == {
        "acquisition": True,
        "properties": True,
        "review": True,
    }
    assert proof["observationComplete"] is False and proof["reviewBinding"] == binding
    after = load_model(path)
    assert (
        after.authoritative["desired.row.001-002.value"]
        == values["desired.row.001-002.value"]
    )
    assert m.limitations.row_state(
        values, "001", kind + ".Description"
    ) == m.limitations.row_state(after.authoritative, "001", kind + ".Description")
    import_guard.require_import_changes(root)
    with patch.object(TaskValidation, "git_paths", _callback_limited_task_paths):
        task_contract.complete(root, "tasks/import-fixture.md")
    assert "Task status: `completed`" in (root / "tasks/import-fixture.md").read_text()


@pytest.mark.parametrize("comment", ["", "action name"])
def test_codepipeline_packed_import_display_and_required_rows(comment):
    kind = "CodePipeline.Pipeline"
    resource = {"resourceType": kind, "resourceMode": "IMPORT", "logicalId": "Pipeline"}
    rows = [
        [
            "001-001",
            kind + ".Stages[].Actions[].Name",
            '`[["source"],["build-a","build-b"]]`',
            comment,
        ],
        ["001-002", kind + ".Stages[].Actions[].RunOrder", '`[["1"],["1","2"]]`', ""],
        ["001-003", kind + ".Stages[].Name", '`["Source","Build"]`', ""],
    ]
    table = resource_table_lines(resource, "fixture", rows, [], m.ROOT)
    text = "\n".join(table)
    assert "Stages[1].Actions[1].Name" in text
    assert "Stages[2].Actions[2].Name" in text
    assert "compact-source" in text
    restored = expanded_display_rows(
        ['<a id="pipeline"></a>', "### CodePipeline.Pipeline: fixture", *table],
        m.ROOT,
        modes={"pipeline": "IMPORT"},
    )
    for row in rows:
        assert row[1] in "\n".join(restored) and row[2] in "\n".join(restored)
    with pytest.raises(
        ValueError, match="stage/action display selection is incomplete"
    ):
        resource_table_lines(resource, "fixture", rows[:-1], [], m.ROOT)


def test_complete_checkpoint_resume_does_not_reacquire(tmp_path):
    root, acquired, cli = prepare(tmp_path, dry_run=True)
    evidence = Path(acquired["evidence"])
    value = import_evidence.read_acquisition(
        root, evidence, ("dev", TARGET, "cloudwatch-logs"), True
    )
    (evidence.parent / "checkpoint.json").write_text(
        json_text(import_approval.checkpoint(value, [])), encoding="utf-8"
    )
    count = len(cli.calls)
    resumed = m.resume_acquisition(
        root, "dev", "cloudwatch-logs", evidence, TARGET, True
    )
    assert resumed["status"] == "resumed" and resumed["answers"] == []
    assert len(cli.calls) == count


def test_incomplete_evidence_cannot_publish(tmp_path):
    root = tmp_path / "case"
    fixture(root, register=False, focused=True)
    cli = aws()

    runner = _bind_framework_callback(_incomplete_runner, cli)

    before = source_files(root)
    result = m.acquire(
        root,
        "dev",
        "cloudwatch-logs",
        TARGET,
        True,
        runner,
        resource_types=["Logs.LogGroup"],
    )
    assert result["status"] == "incomplete"
    evidence = Path(result["evidence"])
    value = import_evidence.read_acquisition(
        root, evidence, ("dev", TARGET, "cloudwatch-logs"), True
    )
    (evidence.parent / "checkpoint.json").write_text(
        json_text(import_approval.checkpoint(value, [])), encoding="utf-8"
    )
    assert (
        m.resume_acquisition(root, "dev", "cloudwatch-logs", evidence, TARGET, True)[
            "status"
        ]
        == "incomplete"
    )
    with pytest.raises(ValueError, match="complete acquisition"):
        m.publish_acquisition(root, "dev", "cloudwatch-logs", evidence, TARGET, True)
    assert source_files(root) == before and evidence.exists()
    assert "private-token" not in evidence.read_text(encoding="utf-8")


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))


def test_namespace_four_stage_packed_display_preserves_positions():
    kind = "CodePipeline.Pipeline"
    resource = {"resourceType": kind, "resourceMode": "IMPORT", "logicalId": "Pipeline"}
    values = {
        "Stages[].Actions[].Commands": [
            [["hidden"]],
            [["hidden"], ["hidden"]],
            [["hidden"]],
            [["hidden"]],
        ],
        "Stages[].Actions[].Name": [
            ["source"],
            ["approve", "check"],
            ["sign"],
            ["publish"],
        ],
        "Stages[].Actions[].Namespace": [
            ["QuarantineSource"],
            [{"absent": True}, "Checks"],
            [{"absent": True}],
            [{"absent": True}],
        ],
        "Stages[].Name": [
            "source",
            "quarantine",
            "quarantine-approval",
            "quarantine-sign",
        ],
    }
    rows = [
        [
            f"001-{i:03}",
            kind + "." + prop,
            "`" + json.dumps(value, separators=(",", ":")) + "`",
            "",
        ]
        for i, (prop, value) in enumerate(values.items(), 1)
    ]
    text = "\n".join(resource_table_lines(resource, "fixture", rows, [], m.ROOT))
    assert "hidden" not in text
    assert "Stages[4].Actions[1].Name" in text, text
    assert "Stages[2].Actions[2].Namespace" in text and "Checks" in text
    assert "QuarantineSource" in text
    assert text.count(".Name |") == 9
    assert "Stages[2].Actions[1].Name" in text and "Stages[2].Actions[2].Name" in text
    restored = "\n".join(
        expanded_display_rows(
            [
                '<a id="pipeline"></a>',
                "### CodePipeline.Pipeline: fixture",
                *text.splitlines(),
            ],
            m.ROOT,
            modes={"pipeline": "IMPORT"},
        )
    )
    for row in rows[1:]:
        assert row[1] in restored and row[2] in restored
