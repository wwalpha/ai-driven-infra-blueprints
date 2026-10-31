#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from collections import Counter
from functools import partial as _bind_framework_callback
from inspect import unwrap
from pathlib import Path
from types import SimpleNamespace as _CallbackState
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import model.adapters.observed as _imports_model_adapters_observed
import model.files as _imports_model_files
import model.files as model_files
import model.format as _imports_model_format
import model.sources as model_sources
import support.repository_fixtures as _fixture_publication_workspace
from deploy import observed as deploy_observed
from deploy import run_context
from deploy.model_cache import RunModels
from deploy.observed import removed_resources
from deploy.preparation import candidate
from model.adapters import observed
from model.adapters.observed import mappings, preflight, validate_mapping_targets
from model.format import parse
from model.format import patch as patch_properties
from model.sources import load_model, model_parts
from support import rotation_schedule_fixtures as rotation
from support.cloudformation_deploy_fixtures import (
    TARGET,
    Fake,
    M,
    Path,
    Runtime,
    SimpleNamespace,
    advance_group,
    copy,
    io,
    json,
    markdown_for,
    observation_contract,
    patch,
    properties,
    publish_collected,
    pytest,
    read_model,
    redirect_stdout,
    rejects,
    remove_model,
    run,
    snapshot_model,
    starts,
    states,
    subprocess,
    sys,
    units,
    write_model,
)
from support.model_sources import allocate_fixture as allocate
from support.model_v2_fixtures import deploy_properties_fixture
from support.repository_fixtures import fixture, git, start
from task_contract_core import paths_in, selected_task
from utils.aws_catalogs import catalog_outputs
from utils.input_cache import input_context, input_scope, memo_table

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

publication_workspace = _fixture_publication_workspace.publication_workspace

_CALLBACK_DEFAULT = object()


def check_inputs(tmp_path):
    values = {"desired.deployment.maxConcurrentStacks": "2"}
    for i, unit in enumerate(units(20, 10, 10), 1):
        values.update(
            {f"desired.stack.{i:03}.{key}": value for key, value in unit.items()}
        )
        values[f"display.stack.{i:03}.comment"] = "アプリケーションを配置するstack"
    root = tmp_path
    (root / "project.json").write_text(
        json.dumps(
            {"projectName": "test", "targets": [{"environment": "dev", **TARGET}]}
        )
    )
    path = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
    path.parent.mkdir(parents=True)
    path.write_text(markdown_for(path, values, root))
    source = root / "model/dev/123456789012/cloudformation-stacks.properties"
    source.parent.mkdir(parents=True)
    write_model(source, "\n".join(f"{key}={value}" for key, value in values.items()))
    limit, scoped = M.load_units(root, "dev", "123456789012", ["A", "C"])
    assert limit == 2 and [unit["name"] for unit in scoped] == ["C", "A"]
    rejects(
        lambda: M.load_units(root, "dev", "123456789012", ["unknown"]),
        "Deployment scope",
    )
    path.write_text(
        path.read_text().replace(
            "<!-- max-concurrent-stacks: 2 -->", "<!-- max-concurrent-stacks: 3 -->"
        )
    )
    rejects(lambda: M.load_units(root, "dev", "123456789012", ["A"]), "mismatch")
    (root / "tasks").mkdir()
    contract = root / "tasks/example.md"
    contract.write_text(
        "## Task contract\n- Task type: `governance`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n"
    )
    rejects(
        lambda: run_context.active_scope(root, ["A"], "dev", TARGET["awsAccountId"]),
        "infrastructure",
    )


def _callback_observed_collector_seed_resource(
    values, /, identity, kind, logical, anchor, rows
):
    values.update(
        {
            f"desired.resource.{identity}.resourceType": kind,
            f"desired.resource.{identity}.anchor": anchor,
            f"display.resource.{identity}.comment": "業務用ネットワークを構成するresource",
        }
    )
    values.update(allocate(values, [identity]))
    for index, (prop, value) in enumerate(rows, 1):
        key = f"desired.row.{identity}-{index:03d}"
        values.update(
            {
                key + ".property": kind + "." + prop,
                key + ".value": value,
                key + ".comment": "設定値を指定する属性",
            }
        )


def _callback_observed_collector_seed_save_model(design, root, source, values, /):
    write_model(source, "\n".join(k + "=" + v for k, v in values.items()) + "\n")
    design.write_text(markdown_for(design, values, root))


def observed_collector_seed(root):
    (root / "project.json").write_text(
        json.dumps(
            {
                "projectName": "test",
                "targets": [
                    {
                        "environment": "dev",
                        **TARGET,
                        "awsExecutionAccountId": "999999999999",
                    }
                ],
            }
        )
        + "\n"
    )
    source = root / "model/dev/123456789012/ec2.properties"
    source.parent.mkdir(parents=True)
    design = root / "docs/designs/dev/123456789012/ec2.md"
    design.parent.mkdir(parents=True)
    values = {
        "desired.service.ec2.serviceId": "ec2",
        "desired.service.ec2.ownedCatalogResourceTypes": "EC2.VPC,EC2.Subnet",
        "display.service.title": "# EC2 詳細設計",
    }
    resource = _bind_framework_callback(
        _callback_observed_collector_seed_resource, values
    )
    resource(
        "001",
        "EC2.VPC",
        "vpc-test-dev",
        "ec2-vpc-test-dev",
        [
            ("Name", "`vpc-test-dev`"),
            ("VpcId", "[EC2_VPC_001](ec2.md#ec2-vpc-test-dev)"),
            ("CidrBlock", "`10.1.0.0/16`"),
        ],
    )
    resource(
        "002",
        "EC2.Subnet",
        "sbnt-test-dev-private-app-a-01",
        "ec2-sbnt-test-dev-private-app-a-01",
        [
            ("Name", "`sbnt-test-dev-private-app-a-01`"),
            ("VpcId", "[EC2_VPC_001](ec2.md#ec2-vpc-test-dev)"),
            ("SubnetId", "[EC2_Subnet_001](ec2.md#ec2-sbnt-test-dev-private-app-a-01)"),
            ("CidrBlock", "`10.1.1.0/24`"),
        ],
    )
    values["desired.resource.001.cfn-logicalId"] = "A-VpcTestDev"
    values["desired.resource.002.resourceMode"] = "IMPORT"
    # Initialize the existing standard observed row format, including comments.
    for rid in ("001-002", "002-003", "002-002"):
        for field in ("property", "comment"):
            values[f"observed.row.{rid}.{field}"] = values[f"desired.row.{rid}.{field}"]
        values[f"observed.row.{rid}.value"] = (
            "PENDING_DEPLOY" if rid == "002-002" else "`PENDING_DEPLOY`"
        )
    save_model = _bind_framework_callback(
        _callback_observed_collector_seed_save_model, design, root, source, values
    )
    stack_values = {}
    for number, unit in enumerate(units(10, 20), 1):
        stack_values.update(
            {f"desired.stack.{number:03d}." + key: value for key, value in unit.items()}
        )
        stack_values[f"display.stack.{number:03d}.comment"] = "合成Stack"
    write_model(source.with_name("cloudformation-stacks.properties"), stack_values)
    save_model()
    unrelated = root / "model/prod/999999999999/broken.properties"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("# model-format: 2\ninvalid=one\n")
    project = root / "project.json"
    data = json.loads(project.read_text())
    data["targets"].append(
        {
            "environment": "prod",
            "awsAccountId": "999999999999",
            "awsRegion": "ap-northeast-1",
            "iacEngine": "cloudformation",
        }
    )
    project.write_text(json.dumps(data) + "\n")


@pytest.fixture
def observed_collector_root():
    with fixture() as primary:
        observed_collector_seed(primary)
        git(primary, "add", "project.json", "model", "docs")
        git(primary, "commit", "-qm", "synthetic observed baseline")
        root, state = start(primary, task_id="observation-fixture", files=("file.txt",))
        with selected_task(root, state["task_file"]):
            yield root


def _callback_check_observed_collector_aws(
    output, physical, removed, /, operation, **args
):
    if operation == "describe_stack_events":
        return {
            "StackEvents": [
                {
                    "StackId": "stack-A",
                    "ClientRequestToken": "token",
                    "LogicalResourceId": "VpcTestDev",
                    "ResourceType": "AWS::EC2::VPC",
                    "PhysicalResourceId": physical[0],
                    "ResourceStatus": "DELETE_COMPLETE",
                }
            ]
        }
    if operation == "describe_stacks":
        return {
            "Stacks": [
                {
                    "StackId": "stack-A",
                    "StackStatus": "CREATE_COMPLETE",
                    "Outputs": [{"OutputKey": "VpcIdentity", "OutputValue": output[0]}],
                }
            ]
        }
    assert operation == "list_stack_resources"
    return {
        "StackResourceSummaries": []
        if removed[0]
        else [
            {
                "LogicalResourceId": "VpcTestDev",
                "ResourceType": "AWS::EC2::VPC",
                "ResourceStatus": "CREATE_COMPLETE",
                "PhysicalResourceId": physical[0],
            }
        ]
    }


def check_observed_collector(observed_collector_root):
    root = observed_collector_root
    source = root / "model/dev/123456789012/ec2.properties"
    design = root / "docs/designs/dev/123456789012/ec2.md"
    values = properties(read_model(source))
    task = root / "tasks/observation-fixture.md"
    task.parent.mkdir(exist_ok=True)
    task.write_text(observation_contract(root, ["ec2", "cloudformation-stacks"]))
    backend = Runtime(root, "dev", "123456789012", TARGET)
    unit = units(10)[0]
    document = {
        "Resources": {"VpcTestDev": {"Type": "AWS::EC2::VPC"}},
        "Outputs": {"VpcIdentity": {"Value": {"Ref": "VpcTestDev"}}},
    }
    backend.templates = {"A": (document, {})}
    backend.target = {**TARGET, "awsExecutionAccountId": "999999999999"}
    document["Conditions"] = {
        "ThisStack": {
            "Fn::And": [
                {"Fn::Equals": [{"Ref": "AWS::StackName"}, "A"]},
                {"Fn::Equals": [{"Ref": "AWS::AccountId"}, "999999999999"]},
            ]
        }
    }
    document["Resources"]["VpcTestDev"]["Condition"] = "ThisStack"
    document["Outputs"]["VpcIdentity"]["Condition"] = "ThisStack"
    physical, output, removed = (
        ["vpc-0123456789abcdef0"],
        ["vpc-0123456789abcdef0"],
        [False],
    )
    aws = _bind_framework_callback(
        _callback_check_observed_collector_aws, output, physical, removed
    )
    backend.aws = aws
    before = snapshot_model(source)
    # One model scan collects missing identities and identifier rows across stacks.
    observed = _imports_model_adapters_observed
    subnet_identifier = values["desired.row.002-003.value"]
    values["desired.row.002-003.value"] = "`PENDING_DEPLOY`"
    write_model(source, "\n".join(k + "=" + v for k, v in values.items()) + "\n")
    broken_templates = {
        "A": (
            {
                "Resources": {
                    "MissingVpc": {"Type": "AWS::EC2::VPC"},
                    "SbntTestDevPrivateAppA01": {"Type": "AWS::EC2::Subnet"},
                }
            },
            {},
        ),
        "B": ({"Resources": {"MissingRole": {"Type": "AWS::IAM::Role"}}}, {}),
    }
    with patch.object(observed, "models", wraps=observed.models) as scan:
        with pytest.raises(observed.MappingError) as error:
            mappings(root, "dev", "123456789012", broken_templates, units(10, 20))
        assert (
            set(error.value.errors) == {"A", "B"} and len(error.value.errors["A"]) == 2
        )
        assert (
            "MissingVpc" in str(error.value)
            and "MissingRole" in str(error.value)
            and "SbntTestDevPrivateAppA01" in str(error.value)
            and "explicit mapping required" in str(error.value)
        )
        assert scan.call_count == 1
    values["desired.row.002-003.value"] = subnet_identifier
    write_model(source, values)
    output[0] = "vpc-different"
    uncertain = states([unit])
    deploy_observed.collect_successful(backend, [unit], uncertain)
    TestCase().assertEqual(
        uncertain["A"]["observedCoverage"]["VpcTestDev"]["status"], "UNCONFIRMED"
    )
    TestCase().assertEqual(snapshot_model(source), before)
    output[0] = physical[0]
    # Shared template identities cannot be assigned to one model row by guessing.
    duplicate = copy.deepcopy(document)
    duplicate["Resources"]["VpcTestDev"].pop("Condition")
    backend.templates["B"] = (duplicate, {})
    rejects(
        lambda: mappings(root, "dev", "123456789012", backend.templates, units(10, 10)),
        "cfn-logicalId matches=0",
    )
    assert snapshot_model(source) == before
    # Out-of-scope incoming references block before writes, even with broad Allowed paths.
    consumer = source.with_name("consumer.properties")
    write_model(
        consumer,
        'desired.resource.001.resourceType=EC2.Subnet\ndesired.resource.001.logicalId=EC2_Subnet_001\ndesired.resource.001.anchor=resource-EC2_Subnet_001\ndesired.service.identity.lastAllocated={"EC2.Subnet":1}\ndesired.row.001-001.property=EC2.Subnet.VpcId\ndesired.row.001-001.value=[EC2_VPC_001](ec2.md#ec2-vpc-test-dev)\ndesired.row.001-001.comment=接続先\n',
    )
    rejects(
        lambda: publish_collected(backend, [unit], states([unit])),
        "task scope violation",
    )
    assert snapshot_model(source) == before
    remove_model(consumer)
    unrelated = root / "model/prod/999999999999/broken.properties"
    # A malformed source cannot be classified as unrelated; syntactically valid
    # metadata with unrelated semantic errors does not block the selected update.
    original = unrelated.read_text()
    unrelated.write_text("broken syntax\n")
    saved = states([unit])
    rejects(
        lambda: publish_collected(backend, [unit], saved), "unsupported Model format"
    )
    assert snapshot_model(source) == before
    unrelated.write_text(original)
    with redirect_stdout(io.StringIO()):
        publish_collected(backend, [unit], saved)
    observed = properties(read_model(source))
    assert observed["observed.row.001-002.value"] == "`" + physical[0] + "`"
    TestCase().assertEqual(observed["observed.row.002-002.value"], "PENDING_DEPLOY")
    assert observed["observed.row.002-003.value"] == "`PENDING_DEPLOY`"
    assert {k: v for k, v in observed.items() if not k.startswith("observed.")} == {
        k: v for k, v in values.items() if not k.startswith("observed.")
    }
    assert saved["A"]["observedSynced"] and physical[0] in design.read_text()
    # Replacement/current ID and output-absent PhysicalResourceId fallback.
    document["Outputs"] = {}
    physical[0] = "vpc-1234567890abcdef0"
    with redirect_stdout(io.StringIO()):
        publish_collected(backend, [unit], saved)
    TestCase().assertEqual(
        properties(read_model(source))["observed.row.002-002.value"], "PENDING_DEPLOY"
    )
    assert "arn:aws" not in read_model(source)
    physical[0] = "arn:aws:ec2:ap-northeast-1:123456789012:vpc/secret"
    before = snapshot_model(source)
    deploy_observed.collect_successful(backend, [unit], saved)
    TestCase().assertEqual(
        saved["A"]["observedCoverage"]["VpcTestDev"]["status"], "UNCONFIRMED"
    )
    TestCase().assertEqual(snapshot_model(source), before)
    # Bounded template parts remain stable while only observed authority changes.
    physical[0] = "vpc-abcdef01234567890"
    indexed_values = properties(read_model(source)) | {
        f"desired.note.{number:03d}.text": "保持する設計注記"
        for number in range(1, 621)
    }
    write_model(source, indexed_values)
    template = source
    parts = model_parts(source)
    assert len(parts) > 1
    before_parts = {p: p.read_bytes() for p in [template, *parts]}
    with redirect_stdout(io.StringIO()):
        publish_collected(backend, [unit], saved)
    after_parts = load_model(source)
    assert set(after_parts.files) == set(before_parts)
    for file, raw in before_parts.items():
        if file == source:
            assert file.read_bytes() == raw
            continue
        part_document = parse(raw.decode())
        changes = {
            key: after_parts.authoritative[key]
            for key, value in part_document.values.items()
            if after_parts.authoritative.get(key) != value
        }
        assert all(
            key.startswith("observed.row.") and key.endswith(".value")
            for key in changes
        )
        assert file.read_bytes() == patch_properties(part_document, changes).encode()
    TestCase().assertEqual(
        properties(read_model(source))["observed.row.002-002.value"], "PENDING_DEPLOY"
    )

    # Approved physical deletion resets the formal row and every reference; retention blocks.
    document["Resources"] = {}
    saved["A"]["changes"] = [
        {
            "Action": "Remove",
            "LogicalResourceId": "VpcTestDev",
            "ResourceType": "AWS::EC2::VPC",
            "PolicyAction": "Retain",
        }
    ]
    removed[0] = True
    before = read_model(source)
    publish_collected(backend, [unit], saved)
    assert read_model(source) == before
    saved["A"]["changes"][0]["PolicyAction"] = "Delete"
    saved["A"].update(
        stackId="stack-A",
        changeSetId="cs-A",
        changeDigest="digest",
        clientToken="token",
    )
    saved["A"]["changes"][0]["PhysicalResourceId"] = physical[0]
    saved["A"]["executionEvidence"] = {
        "StackId": "stack-A",
        "ChangeSetId": "cs-A",
        "changeDigest": "digest",
        "clientToken": "token",
        "inputDigest": "input",
        "resources": copy.deepcopy(saved["A"]["changes"]),
    }
    with redirect_stdout(io.StringIO()):
        publish_collected(backend, [unit], saved)
    assert (
        properties(read_model(source))["observed.row.001-002.value"]
        == "`PENDING_DEPLOY`"
    )
    assert (
        properties(read_model(source))["observed.row.002-002.value"] == "PENDING_DEPLOY"
    )


def _check_shared_stack_mapping_save(path, data):
    write_model(path, data)


def _check_shared_stack_mapping_deletion_aws(operation, **args):
    if operation == "describe_stack_events":
        return {
            "StackEvents": [
                {
                    "LogicalResourceId": "DepartmentVpc",
                    "ResourceType": "AWS::EC2::VPC",
                    "StackId": "stack-removed",
                    "ClientRequestToken": "token",
                    "PhysicalResourceId": "vpc-deleted",
                    "ResourceStatus": "DELETE_COMPLETE",
                }
            ]
        }
    if operation == "describe_stacks":
        return {
            "Stacks": [{"StackId": "stack-removed", "StackStatus": "UPDATE_COMPLETE"}]
        }
    return {"StackResourceSummaries": []}


def _callback_check_shared_stack_mapping_aws(expected, /, operation, **args):
    assert (
        memo_table() is None
    )  # Mapping snapshots end before AWS waits and observed publication.
    name = args["StackName"]
    if operation == "describe_stacks":
        return {
            "Stacks": [
                {
                    "StackId": name,
                    "StackStatus": "CREATE_COMPLETE",
                    "Outputs": [{"OutputKey": "VpcId", "OutputValue": expected[name]}],
                }
            ]
        }
    assert operation == "list_stack_resources"
    return {
        "StackResourceSummaries": [
            {
                "LogicalResourceId": "DepartmentVpc",
                "ResourceType": "AWS::EC2::VPC",
                "ResourceStatus": "CREATE_COMPLETE",
                "PhysicalResourceId": expected[name],
            }
        ]
    }


def _callback_check_shared_stack_mapping_check(
    actual,
    backend,
    root,
    save,
    scoped,
    source,
    /,
    data=None,
    templates=None,
    message="",
):
    save(source, data if data is not None else actual)
    rejects(
        lambda: mappings(
            root, "dev", "123456789012", templates or backend.templates, scoped
        ),
        message,
    )


def _callback_check_shared_stack_mapping_changed_permission(
    backend, root, scoped, task, /
):
    original = task.read_text(encoding="utf-8")
    mappings(root, "dev", "123456789012", backend.templates, scoped)
    try:
        task.write_text(
            original.replace("dev/123456789012/ec2", "dev/123456789012/kms"),
            encoding="utf-8",
        )
        rejects(
            lambda: mappings(root, "dev", "123456789012", backend.templates, scoped),
            "outside Validation scope",
        )
    finally:
        task.write_text(original, encoding="utf-8")


def _callback_check_shared_stack_mapping_inherited(
    _state_check_shared_stack_mapping_395, /
):
    memo = memo_table()
    first = _state_check_shared_stack_mapping_395.entry(
        *_state_check_shared_stack_mapping_395.args
    )
    assert memo_table() is memo
    assert (
        _state_check_shared_stack_mapping_395.entry(
            *_state_check_shared_stack_mapping_395.args
        )
        == first
        and memo_table() is memo
    )


def _callback_check_shared_stack_mapping_measured_body(
    bodies, original, readers, /, scope, reads
):
    readers.append(reads)
    bodies[scope.path, id(reads)] += 1
    return original(scope, reads)


def _callback_check_shared_stack_mapping_measured(entry, *args):
    bodies = Counter()
    readers = []
    original = model_sources._read_model
    body = _bind_framework_callback(
        _callback_check_shared_stack_mapping_measured_body, bodies, original, readers
    )
    # Measure reuse only within an explicitly read-only input lifetime.
    with (
        input_context(read_only=True),
        patch.object(
            model_files, "load_model", wraps=model_sources.load_model
        ) as lookups,
        patch.object(model_sources, "_read_model", side_effect=body) as expanded,
    ):
        result = entry(*args)
    return result, lookups.call_count, bodies, expanded.call_count


def check_shared_stack_mapping(publication_workspace):
    _state_check_shared_stack_mapping_395 = _CallbackState()
    read_model = _imports_model_files.read_model
    root = publication_workspace
    (root / "project.json").write_text(
        json.dumps(
            {"projectName": "test", "targets": [{"environment": "dev", **TARGET}]}
        )
        + "\n"
    )
    source = root / "model/dev/123456789012/ec2.properties"
    source.parent.mkdir(parents=True)
    view = root / "docs/designs/dev/123456789012/ec2.md"
    view.parent.mkdir(parents=True)
    values, stack_values = (
        {
            "desired.service.ec2.serviceId": "ec2",
            "desired.service.ec2.ownedCatalogResourceTypes": "EC2.VPC",
            "display.service.title": "# EC2 詳細設計",
        },
        {},
    )
    scoped = []
    expected = {}
    for index, department in enumerate(("ism", "ced", "sd"), 1):
        identity = f"{index:03d}"
        _ = identity
        name = "vpc-app-dev-" + department
        _ = "ec2-" + name
        unit = {
            "name": "cfn-stack-app-dev-" + department,
            "template": "department.yaml",
            "parameters": department + ".json",
            "deployOrder": "10",
        }
        scoped.append(unit)
        stack_values.update(
            {f"desired.stack.{identity}.{key}": value for key, value in unit.items()}
        )
        stack_values[f"display.stack.{identity}.comment"] = (
            department + "部署のネットワークを配置するstack"
        )
        values.update(
            {
                f"desired.resource.{identity}.resourceType": "EC2.VPC",
                f"desired.resource.{identity}.cfn-logicalId": unit["name"]
                + "-DepartmentVpc",
                f"display.resource.{identity}.comment": department
                + "部署のネットワーク",
            }
        )
        values.update(allocate(values, [identity]))
        for number, (prop, value) in enumerate(
            (
                ("Name", "`" + name + "`"),
                (
                    "VpcId",
                    f"[{identity}](#{values[f'desired.resource.{identity}.anchor']})",
                ),
                ("CidrBlock", f"`10.{index}.0.0/16`"),
            ),
            1,
        ):
            key = f"desired.row.{identity}-{number:03d}"
            values.update(
                {
                    key + ".property": "EC2.VPC." + prop,
                    key + ".value": value,
                    key + ".comment": "ネットワークの設定値",
                }
            )
        expected[unit["name"]] = "vpc-" + str(index) * 17
    save = _check_shared_stack_mapping_save
    save(source, values)
    stack_source = source.with_name("cloudformation-stacks.properties")
    save(stack_source, stack_values)
    view.write_text(markdown_for(view, values, root), encoding="utf-8")
    assert "cfn-logical-id:" not in view.read_text(encoding="utf-8")
    stack_view = view.with_name("cloudformation-stacks.md")
    stack_view.write_text(
        markdown_for(stack_view, stack_values, root), encoding="utf-8"
    )
    task = root / "tasks/observation-fixture.md"
    task.parent.mkdir(exist_ok=True)
    with selected_task(root, None):
        contract = observation_contract(root, ("ec2", "cloudformation-stacks"))
    task.write_text(contract)
    document = {
        "Parameters": {"Enabled": {"Type": "String", "Default": "yes"}},
        "Conditions": {
            "Active": {"Fn::Equals": [{"Ref": "Enabled"}, "yes"]},
            "Disabled": False,
        },
        "Resources": {
            "DepartmentVpc": {"Type": "AWS::EC2::VPC", "Condition": "Active"},
            "OptionalRepository": {
                "Type": "AWS::CodeCommit::Repository",
                "Condition": "Disabled",
            },
        },
        "Outputs": {
            "VpcId": {
                "Condition": "Active",
                "Value": {
                    "Fn::If": [
                        "Active",
                        {"Ref": "DepartmentVpc"},
                        {"Ref": "AWS::NoValue"},
                    ]
                },
            }
        },
    }
    backend = Runtime(root, "dev", "123456789012", TARGET)
    backend.templates = {
        unit["name"]: (document, {"Enabled": "yes"}) for unit in scoped
    }
    backend.mapping_plan = mappings(
        root, "dev", "123456789012", backend.templates, scoped
    )
    assert len(backend.mapping_plan[1]) == 3
    for index, unit in enumerate(scoped, 1):
        assert (
            backend.mapping_plan[1][unit["name"]]["DepartmentVpc"][1] == f"{index:03d}"
        )
    # Same parser and validator from the implementation CLI; defaults and stack inputs are local only.
    template = root / "infra/cloudformation/templates/department.yaml"
    template.parent.mkdir(parents=True)
    template.write_text(json.dumps(document))
    params = root / "infra/cloudformation/parameters/dev/123456789012"
    params.mkdir(parents=True)
    for unit in scoped:
        (params / unit["parameters"]).write_text("[]")

    measured = _callback_check_shared_stack_mapping_measured

    with patch.object(subprocess, "run") as no_aws:
        assert (
            preflight(root, "dev", "123456789012", [u["name"] for u in scoped])[1]
            == backend.mapping_plan[1]
        )
        for (
            _state_check_shared_stack_mapping_395.entry,
            _state_check_shared_stack_mapping_395.args,
            expected_before,
            expected_after,
        ) in (
            (mappings, (root, "dev", "123456789012", backend.templates, scoped), 5, 5),
            (
                preflight,
                (root, "dev", "123456789012", [u["name"] for u in scoped]),
                2,
                2,
            ),
        ):
            with patch.object(observed, "mappings", mappings.__wrapped__):
                before, hits_before, bodies_before, expansions_before = measured(
                    unwrap(_state_check_shared_stack_mapping_395.entry),
                    *_state_check_shared_stack_mapping_395.args,
                )
            after, hits_after, bodies_after, expansions_after = measured(
                _state_check_shared_stack_mapping_395.entry,
                *_state_check_shared_stack_mapping_395.args,
            )
            assert after == before
            assert hits_before == hits_after and hits_after >= 2, (
                hits_before,
                hits_after,
                dict(bodies_before),
                dict(bodies_after),
            )
            assert (
                sum(bodies_before.values()) == expansions_before == expected_before
            ), (dict(bodies_before), expansions_before, expected_before)
            assert sum(bodies_after.values()) == expansions_after == expected_after, (
                dict(bodies_after),
                expected_after,
            )
            assert max(bodies_after.values()) == 1 and memo_table() is None
            print(
                f"{_state_check_shared_stack_mapping_395.entry.__name__} synthetic reuse: lookups={hits_before}->{hits_after}, "
                f"expansion bodies={expansions_before}->{expansions_after}; mapping unchanged"
            )

            inherited = (input_scope)(
                _bind_framework_callback(
                    _callback_check_shared_stack_mapping_inherited,
                    _state_check_shared_stack_mapping_395,
                )
            )
            _, _, bodies, expanded = measured(inherited)
            assert max(bodies.values()) == 1
            if _state_check_shared_stack_mapping_395.entry is preflight:
                assert expanded == 2 * expected_after
            else:
                assert expected_after <= expanded < 2 * expected_after
            assert memo_table() is None
            assert (
                measured(
                    _state_check_shared_stack_mapping_395.entry,
                    *_state_check_shared_stack_mapping_395.args,
                )[3]
                == expected_after
            )  # Separate invocation re-expands.

        # Optional observed input creation/removal is visible on the very next mapping.
        original_source = source.read_bytes()
        source.write_bytes(original_source + b"observed.row.001-002.value=`[NaN]`\n")
        try:
            rejects(
                lambda: mappings(
                    root, "dev", "123456789012", backend.templates, scoped
                ),
                "invalid",
            )
            assert memo_table() is None
        finally:
            source.write_bytes(original_source)
        assert (
            mappings(root, "dev", "123456789012", backend.templates, scoped)
            == backend.mapping_plan
        )
        # Current contract scope is re-read, even when an outer snapshot already has the Model.
        changed_permission = (input_scope)(
            _bind_framework_callback(
                _callback_check_shared_stack_mapping_changed_permission,
                backend,
                root,
                scoped,
                task,
            )
        )
        changed_permission()
        assert memo_table() is None
        rejects(
            lambda: preflight(root, "dev", "123456789012", ["missing"]),
            "unique designed StackName",
        )
        assert memo_table() is None
        for name in (scoped[0]["name"], "missing"):
            results = []
            for _state_check_shared_stack_mapping_395.entry, mapping in (
                (unwrap(preflight), mappings.__wrapped__),
                (preflight, mappings),
            ):
                stdout = io.StringIO()
                with (
                    patch.object(
                        observed,
                        "preflight",
                        lambda unused,
                        *args,
                        entry=_state_check_shared_stack_mapping_395.entry: entry(
                            root, *args
                        ),
                    ),
                    patch.object(observed, "mappings", mapping),
                    patch.object(
                        sys,
                        "argv",
                        [
                            "cloudformation_observed.py",
                            "--environment",
                            "dev",
                            "--target-directory",
                            "123456789012",
                            "--stack",
                            name,
                        ],
                    ),
                    redirect_stdout(stdout),
                ):
                    code = observed.main()
                results.append((code, stdout.getvalue()))
            assert results[0] == results[1] and results[1][0] == int(name == "missing")
            assert memo_table() is None
        no_aws.run.assert_not_called()
    aws = _bind_framework_callback(_callback_check_shared_stack_mapping_aws, expected)
    task.write_text(observation_contract(root, ("ec2", "cloudformation-stacks")))
    backend.aws = aws
    with (
        patch(
            "model.adapters.observed.mappings",
            side_effect=AssertionError("must reuse validated mapping"),
        ),
        redirect_stdout(io.StringIO()),
    ):
        publish_collected(backend, scoped, states(scoped))
    actual = properties(read_model(source))
    for index, unit in enumerate(scoped, 1):
        assert (
            actual[f"observed.row.{index:03d}-002.value"]
            == "`" + expected[unit["name"]] + "`"
        )
    assert {k: v for k, v in actual.items() if not k.startswith("observed.")} == values
    before = snapshot_model(source)
    check = _bind_framework_callback(
        _callback_check_shared_stack_mapping_check,
        actual,
        backend,
        root,
        save,
        scoped,
        source,
    )
    check(
        actual | {"desired.resource.001.cfn-logicalId": "invalid"},
        message="invalid cfn-logicalId",
    )
    check(
        actual | {"desired.resource.001.cfn-logicalId": scoped[0]["name"] + "-Missing"},
        message="explicit mapping required",
    )
    check(
        actual
        | {"desired.resource.002.cfn-logicalId": scoped[0]["name"] + "-DepartmentVpc"},
        message="matches=2",
    )
    # A logicalId cannot repair an explicitly wrong CFn identity.
    check(
        actual
        | {
            "desired.resource.001.logicalId": "DepartmentVpc",
            "desired.resource.001.cfn-logicalId": scoped[0]["name"] + "-Missing",
        },
        message="logicalId",
    )
    check(
        actual | {"desired.resource.001.cfn-logicalId": "absent-DepartmentVpc"},
        message="undeclared stack",
    )
    save(source, actual)
    wrong_type = copy.deepcopy(document)
    wrong_type["Resources"]["DepartmentVpc"]["Type"] = "AWS::S3::Bucket"
    check(
        templates={u["name"]: (wrong_type, {"Enabled": "yes"}) for u in scoped},
        message="formal CFn type mismatch",
    )
    # False resources do not require model endpoints or identifier rows.
    save(source, actual)
    inactive = dict(backend.templates)
    inactive[scoped[1]["name"]] = (document, {"Enabled": "no"})
    assert not mappings(root, "dev", "123456789012", inactive, scoped)[1][
        scoped[1]["name"]
    ]
    save(stack_source, stack_values)
    values["desired.resource.001.resourceMode"] = "IMPORT"
    save(source, values)
    rejects(
        lambda: validate_mapping_targets(root, "dev", "123456789012", stack_values),
        "CREATE",
    )
    del values["desired.resource.001.resourceMode"]
    save(source, values)
    for condition in ({"Ref": "Unknown"}, {"Condition": "Active"}, "yes"):
        invalid = copy.deepcopy(document)
        invalid["Conditions"]["Active"] = condition
        rejects(
            lambda *, invalid=invalid: mappings(
                root,
                "dev",
                "123456789012",
                {u["name"]: (invalid, {}) for u in scoped},
                scoped,
            ),
            "Condition"
            if condition == "yes" or "Condition" in condition
            else "unsupported",
        )
    # CodeCommit identifier rows and non-primary EIP Outputs are diagnosed together.
    repo = source.with_name("codecommit.properties")
    repo_values = {
        "desired.resource.001.resourceType": "CodeCommit.Repository",
        "desired.resource.001.cfn-logicalId": scoped[0]["name"] + "-Repository",
    }
    repo_values.update(allocate(repo_values, ["001"]))
    save(repo, repo_values)
    eip = {
        "desired.resource.004.resourceType": "EC2.EIP",
        "desired.resource.004.cfn-logicalId": scoped[0]["name"] + "-Eip",
    }
    eip.update(allocate(eip, ["004"]))
    for number, prop in enumerate(("AllocationId", "PublicIp"), 1):
        eip.update(
            {
                f"desired.row.004-{number:03d}.property": "EC2.EIP." + prop,
                f"desired.row.004-{number:03d}.value": "[EC2_EIP_001](ec2.md#resource-EC2_EIP_001)",
                f"desired.row.004-{number:03d}.comment": "固定アドレスの識別子",
            }
        )
    eip["desired.service.identity.lastAllocated"] = json.dumps(
        json.loads(values["desired.service.identity.lastAllocated"])
        | json.loads(eip["desired.service.identity.lastAllocated"])
    )
    save(source, values | eip)
    save(stack_source, stack_values)
    repo_doc = copy.deepcopy(document)
    repo_doc["Resources"]["Repository"] = {"Type": "AWS::CodeCommit::Repository"}
    repo_doc["Resources"]["Eip"] = {"Type": "AWS::EC2::EIP"}
    repo_templates = dict(backend.templates)
    repo_templates[scoped[0]["name"]] = (repo_doc, {"Enabled": "yes"})
    # Extend fixture scope solely for this explicitly mapped resource.
    task.write_text(
        observation_contract(root, ("ec2", "codecommit", "cloudformation-stacks"))
    )
    try:
        mappings(root, "dev", "123456789012", repo_templates, scoped)
    except ValueError as error:
        assert "required GetAtt Output missing" in str(error)
        assert "CodeCommit.Repository.RepositoryId" not in str(error)
    repo_doc["Outputs"]["AllocationId"] = {
        "Value": {"Fn::GetAtt": "Eip.AllocationId"},
        "Condition": "Disabled",
    }
    repo_doc["Outputs"]["PublicIp"] = {"Value": {"Fn::GetAtt": ["Eip", "PublicIp"]}}
    rejects(
        lambda: mappings(root, "dev", "123456789012", repo_templates, scoped),
        "required GetAtt Output missing",
    )
    repo_doc["Outputs"]["AllocationId"].pop("Condition")
    repo_mapping = mappings(root, "dev", "123456789012", repo_templates, scoped)[1][
        scoped[0]["name"]
    ]["Repository"]
    assert repo_mapping[0] == repo and not repo_mapping[4]
    # A removal is checked before execution even though the new Condition is false.
    save(stack_source, stack_values)
    save(source, actual)
    remove_model(repo)
    backend.templates = inactive
    removing = {
        scoped[1]["name"]: {
            "DepartmentVpc": {"Type": "AWS::EC2::VPC", "PolicyAction": "Delete"}
        }
    }
    backend.mapping_plan = mappings(
        root, "dev", "123456789012", backend.templates, scoped, removing
    )
    deletion_aws = _check_shared_stack_mapping_deletion_aws
    backend.aws = deletion_aws
    deleted = states(scoped)
    deleted[scoped[1]["name"]]["changes"] = [
        {
            "Action": "Remove",
            "LogicalResourceId": "DepartmentVpc",
            "ResourceType": "AWS::EC2::VPC",
            "PolicyAction": "Delete",
        }
    ]
    removal_state = deleted[scoped[1]["name"]]
    removal_state.update(
        stackId="stack-removed",
        changeSetId="cs-removed",
        changeDigest="digest",
        clientToken="token",
    )
    removal_state["changes"][0]["PhysicalResourceId"] = "vpc-deleted"
    removal_state["executionEvidence"] = {
        "StackId": "stack-removed",
        "ChangeSetId": "cs-removed",
        "changeDigest": "digest",
        "clientToken": "token",
        "inputDigest": "input",
        "resources": copy.deepcopy(removal_state["changes"]),
    }

    with redirect_stdout(io.StringIO()):
        publish_collected(backend, [scoped[1]], deleted)
    assert (
        properties(read_model(source))["observed.row.002-002.value"]
        == "`PENDING_DEPLOY`"
    )
    # Resume restores removal ownership from the immutable recorded change set, without re-execution.
    backend.mapping_plan = mappings(
        root,
        "dev",
        "123456789012",
        backend.templates,
        scoped,
        removed_resources(scoped, deleted),
        target=TARGET,
    )
    with (
        patch(
            "model.adapters.observed.mappings",
            side_effect=AssertionError("resume must reuse validated plan"),
        ),
        redirect_stdout(io.StringIO()),
    ):
        publish_collected(backend, [scoped[1]], deleted)
    assert deleted[scoped[1]["name"]]["observedSynced"]
    print(
        "Shared stack mapping checks: PASS (ism/ced/sd identifiers, Conditions, explicit failures, CodeCommit Outputs, validated-plan reuse, deletion)"
    )


def _callback_check_import_implementation_mapping_mapping_656(
    root, unit, _default_doc, /, doc=_CALLBACK_DEFAULT, **kwargs
):
    if doc is _CALLBACK_DEFAULT:
        doc = _default_doc
    return mappings(
        root,
        "dev",
        "123456789012",
        {unit["name"]: (doc, {})},
        [unit],
        target=TARGET,
        **kwargs,
    )


def check_import_implementation_mapping(project_workspace):
    root = project_workspace
    (root / "project.json").write_text(
        json.dumps(
            {"projectName": "test", "targets": [{"environment": "dev", **TARGET}]}
        )
    )
    model = root / "model/dev/123456789012"
    unit = {
        "name": "cfn-stack-app-dev-import",
        "template": "app.yaml",
        "parameters": "app.json",
        "deployOrder": "10",
    }
    write_model(
        model / "cloudformation-stacks.properties",
        {
            **{f"desired.stack.001.{key}": value for key, value in unit.items()},
            "display.stack.001.comment": "既存ネットワークへのログ設定",
        },
    )
    imported = {
        f"desired.resource.{identity}.{key}": value
        for identity, kind in (("001", "EC2.VPC"), ("002", "EC2.Subnet"))
        for key, value in (
            ("resourceType", kind),
            ("resourceMode", "IMPORT"),
            ("logicalId", kind.replace(".", "_") + "_001"),
        )
    }
    imported["desired.service.identity.lastAllocated"] = '{"EC2.VPC":1,"EC2.Subnet":1}'
    write_model(model / "ec2.properties", imported)
    repository = {
        "desired.resource.001.resourceType": "CodeCommit.Repository",
        "desired.resource.001.cfn-logicalId": unit["name"] + "-Repository",
    }
    repository.update(allocate(repository, ["001"]))
    write_model(model / "codecommit.properties", repository)
    write_model(
        model / "quicksight.properties",
        {
            "desired.resource.001.resourceType": "QuickSight.Group",
            "desired.resource.001.logicalId": "QuickSight_Group_001",
            "desired.resource.001.anchor": "resource-QuickSight_Group_001",
            "desired.service.identity.lastAllocated": '{"QuickSight.Group":1}',
        },
    )
    task = root / "tasks/example.md"
    task.parent.mkdir()
    task.write_text(
        "## Task contract\n- Task type: `design`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n## Validation scope\n- `dev/123456789012/ec2`\n- `dev/123456789012/codecommit`\n"
    )
    document = {
        "Resources": {
            "Vpc": {"Type": "AWS::EC2::VPC"},
            "Subnet": {"Type": "AWS::EC2::Subnet"},
            "Association": {
                "Type": "AWS::EC2::SubnetRouteTableAssociation",
                "Properties": {"SubnetId": {"Ref": "Subnet"}},
            },
            "Repository": {"Type": "AWS::CodeCommit::Repository"},
        }
    }
    mapping = _bind_framework_callback(
        _callback_check_import_implementation_mapping_mapping_656, root, unit, document
    )
    assert set(mapping(implementation=True)[1][unit["name"]]) == {"Repository"}
    rejects(
        mapping, "explicit mapping required"
    )  # Deployment cannot adopt unowned template resources.
    template = root / "infra/cloudformation/templates/app.yaml"
    template.parent.mkdir(parents=True)
    template.write_text(json.dumps(document))
    params = root / "infra/cloudformation/parameters/dev/123456789012/app.json"
    params.parent.mkdir(parents=True)
    params.write_text("[]")
    with patch.object(subprocess, "run") as no_aws:
        assert set(
            preflight(root, "dev", "123456789012", [unit["name"]])[1][unit["name"]]
        ) == {"Repository"}
        no_aws.run.assert_not_called()
    for logical, definition, message in (
        ("Vpc", {"Type": "AWS::EC2::VPC", "Condition": "Unknown"}, "Condition"),
        (
            "Association",
            {
                "Type": "AWS::EC2::SubnetRouteTableAssociation",
                "Properties": {"SubnetId": {"Ref": "Vpc"}},
            },
            "formal CFn type mismatch",
        ),
        ("Unknown", {"Type": "AWS::S3::Bucket"}, "explicit mapping required"),
        ("Repository", {"Type": "AWS::S3::Bucket"}, "formal CFn type mismatch"),
    ):
        changed = copy.deepcopy(document)
        changed["Resources"][logical] = definition
        rejects(
            lambda *, changed=changed: mapping(changed, implementation=True), message
        )
    mixed = allocate(
        imported | {"desired.resource.003.resourceType": "EC2.Subnet"}, ["003"]
    )
    write_model(model / "ec2.properties", mixed)
    rejects(lambda: mapping(implementation=True), "Subnet: cfn-logicalId matches=0")
    write_model(
        model / "ec2.properties",
        imported | {"desired.resource.001.cfn-logicalId": unit["name"] + "-Vpc"},
    )
    rejects(lambda: mapping(implementation=True), "cfn-logicalId requires CREATE")
    print(
        "IMPORT implement mapping: PASS (no creation mapping/Outputs, integrated parent, CREATE/mixed/unknown guards, Conditions, deploy unchanged, no AWS)"
    )


def _callback_check_integrated_child_mapping_reject_change(
    document, mapping, /, logical, definition, message
):
    doc = copy.deepcopy(document)
    doc["Resources"][logical] = definition
    rejects(lambda: mapping(doc), message)


def _callback_check_integrated_child_mapping_mapping_737(
    root, unit, _default_doc, /, doc=_CALLBACK_DEFAULT
):
    if doc is _CALLBACK_DEFAULT:
        doc = _default_doc
    return mappings(
        root, "dev", "123456789012", {unit["name"]: (doc, {})}, [unit], target=TARGET
    )


def check_integrated_child_mapping(project_workspace):
    root = project_workspace
    (root / "project.json").write_text(
        json.dumps({"targets": [{"environment": "dev", **TARGET}]}) + "\n"
    )
    model = root / "model/dev/123456789012"
    model.mkdir(parents=True)
    task = root / "tasks/example.md"
    task.parent.mkdir()
    task_text = "## Task contract\n- Task type: `design`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n## Validation scope\n- `dev/123456789012/s3`\n- `dev/123456789012/ec2`\n- `dev/123456789012/codecommit`\n## Allowed paths\n- `tasks/example.md`\n- `model/dev/123456789012/**`\n- `docs/designs/dev/123456789012/**`\n"
    task_text = task_text.replace(
        "## Allowed paths",
        "- `dev/123456789012/cloudformation-stacks`\n## Allowed paths",
    )
    task.write_text(task_text)
    resources, documents = {}, {}
    unit = {
        "name": "cfn-stack-app-dev-integrated",
        "template": "integrated.yaml",
        "parameters": "integrated.json",
        "deployOrder": "10",
    }
    child_ids = []
    # Reproduce all 17 reported failures with identity-free child rows and no RepositoryId.
    for kind, parent_kind, parent_property, setting, count in (
        ("S3.BucketPolicy", "S3.Bucket", "Bucket", "PolicyDocument", 11),
        (
            "EC2.SubnetRouteTableAssociation",
            "EC2.Subnet",
            "SubnetId",
            "RouteTableId",
            5,
        ),
    ):
        values = {}
        for number in range(1, count + 1):
            identity = f"{number:03d}"
            logical = parent_kind.split(".")[1] + str(number)
            child = "Child" + logical
            _ = "resource-" + logical.lower()
            values.update(
                {
                    f"desired.resource.{identity}.resourceType": parent_kind,
                    f"desired.resource.{identity}.cfn-logicalId": unit["name"]
                    + "-"
                    + logical,
                    f"desired.row.{identity}-001.property": parent_kind
                    + (".BucketName" if parent_kind == "S3.Bucket" else ".SubnetId"),
                    f"desired.row.{identity}-001.value": f"[{identity}](#resource-{parent_kind.replace('.', '_')}_{number:03d})",
                    f"desired.row.{identity}-001.comment": "親識別子",
                    f"desired.row.{identity}-002.property": kind + "." + setting,
                    f"desired.row.{identity}-002.value": "`設定値`",
                    f"desired.row.{identity}-002.comment": "統合した子設定",
                }
            )
            values.update(allocate(values, [identity]))
            # Child precedes parent; ownership must not depend on template order.
            resources[child] = {
                "Type": "AWS::" + kind.replace(".", "::"),
                "Properties": {parent_property: {"Ref": logical}},
            }
            resources[logical] = {"Type": "AWS::" + parent_kind.replace(".", "::")}
            child_ids.append(child)
        path = model / (
            "s3.properties" if parent_kind == "S3.Bucket" else "ec2.properties"
        )
        write_model(path, "\n".join(k + "=" + v for k, v in values.items()) + "\n")
        documents[path] = values
    repo = model / "codecommit.properties"
    write_model(
        repo,
        f'desired.resource.001.resourceType=CodeCommit.Repository\ndesired.resource.001.cfn-logicalId={unit["name"]}-Repository\ndesired.resource.001.logicalId=CodeCommit_Repository_001\ndesired.service.identity.lastAllocated={{"CodeCommit.Repository":1}}\n',
    )
    resources["Repository"] = {"Type": "AWS::CodeCommit::Repository"}
    write_model(
        model / "cloudformation-stacks.properties",
        {f"desired.stack.001.{key}": value for key, value in unit.items()}
        | {"display.stack.001.comment": "合成Stack"},
    )
    document = {
        "Conditions": {"Enabled": True, "Disabled": False},
        "Resources": resources,
    }
    mapping = _bind_framework_callback(
        _callback_check_integrated_child_mapping_mapping_737, root, unit, document
    )
    plan = mapping()
    mapped = plan[1][unit["name"]]
    assert len(mapped) == 33  # 16 parents plus the 17 originally failing resources.
    for child in child_ids:
        assert not mapped[child][4] and len(mapped[child][3]) == 1
        parent = resources[child]["Properties"]
        assert mapped[child][:2] == mapped[next(iter(parent.values()))["Ref"]][:2]
    assert not mapped["Repository"][4]
    reject_change = _bind_framework_callback(
        _callback_check_integrated_child_mapping_reject_change, document, mapping
    )
    child = resources["ChildBucket1"]
    reject_change(
        "ChildBucket1", {**child, "Properties": {}}, "unambiguous local parent Ref"
    )
    reject_change(
        "ChildBucket1",
        {**child, "Properties": {"Bucket": "unknown"}},
        "unambiguous local parent Ref",
    )
    reject_change(
        "ChildBucket1",
        {**child, "Properties": {"Bucket": {"Ref": "Subnet1"}}},
        "formal CFn type mismatch",
    )
    reject_change(
        "Bucket1",
        {**resources["Bucket1"], "Condition": "Disabled"},
        "parent missing, inactive",
    )
    reject_change("DuplicateChild", child, "model resource also owned")
    reject_change(
        "ChildBucket1",
        {**child, "Condition": "Unknown"},
        "unresolved or cyclic Condition",
    )
    conditional = {
        **child,
        "Properties": {
            "Bucket": {"Fn::If": ["Enabled", {"Ref": "Bucket1"}, "unknown"]}
        },
    }
    assert (
        mapping({**document, "Resources": resources | {"ChildBucket1": conditional}})[
            1
        ][unit["name"]]["ChildBucket1"]
        == mapped["ChildBucket1"]
    )
    assert (
        "ChildBucket1"
        not in mapping(
            {
                **document,
                "Resources": resources
                | {"ChildBucket1": {**child, "Condition": "Disabled"}},
            }
        )[1][unit["name"]]
    )
    source = model / "s3.properties"
    original = read_model(source)
    write_model(source, original + "desired.resource.001.resourceMode=IMPORT\n")
    rejects(mapping, "requires CREATE")
    write_model(
        source,
        original.replace(
            "S3.BucketPolicy.PolicyDocument",
            "S3.Bucket.VersioningConfiguration.Status",
            1,
        ),
    )
    rejects(mapping, "integrated child settings missing")
    write_model(
        source,
        original.replace(unit["name"] + "-Bucket1\n", unit["name"] + "-Wrong\n", 1),
    )
    rejects(mapping, "explicit mapping required")
    write_model(source, original)
    task.write_text(
        "## Task contract\n- Task type: `design`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n## Validation scope\n- `dev/123456789012/codecommit`\n"
    )
    rejects(mapping, "task scope violation")
    task.write_text(task_text)
    task.write_text(
        observation_contract(
            root, ("s3", "ec2", "codecommit", "cloudformation-stacks")
        ).replace("tasks/observation-fixture.md", "tasks/example.md")
    )
    before = {
        path: path.read_bytes()
        for path in model.rglob("*.properties")
        if path.stem != "cloudformation-stacks"
    }
    # Empty identifier sets must not collect child physical IDs or reset the parent's ID.
    children = {key: mapped[key] for key in [*child_ids, "Repository"]}
    backend = SimpleNamespace(
        root=root,
        environment="dev",
        directory="123456789012",
        target=TARGET,
        templates={
            unit["name"]: (
                {
                    **document,
                    "Resources": {k: v for k, v in resources.items() if k in children},
                },
                {},
            )
        },
    )
    backend.aws = lambda operation, **args: (
        {"Stacks": [{"StackStatus": "UPDATE_COMPLETE"}]}
        if operation == "describe_stacks"
        else {
            "StackResourceSummaries": [
                {
                    "LogicalResourceId": key,
                    "ResourceType": resources[key]["Type"],
                    "PhysicalResourceId": "arn:aws:ignored",
                }
                for key in children
            ]
        }
    )
    backend.templates[unit["name"]][0]["Resources"].update(
        {k: v for k, v in resources.items() if k not in children}
    )
    state = states([unit])
    with (
        patch("deploy.observed.selected_resources", return_value=set(children)),
        patch(
            "deploy.observed.resolve_resources",
            return_value=(plan[0], {unit["name"]: children}),
        ),
    ):
        publish_collected(backend, [unit], state)
    assert state[unit["name"]]["observedSynced"]
    state[unit["name"]]["changes"] = [
        {
            "Action": "Remove",
            "LogicalResourceId": "ChildBucket1",
            "ResourceType": child["Type"],
            "PolicyAction": "Delete",
        }
    ]
    backend.aws = (
        lambda operation, **args: {"Stacks": [{"StackStatus": "UPDATE_COMPLETE"}]}
        if operation == "describe_stacks"
        else {
            "StackResourceSummaries": [
                {"LogicalResourceId": key, "ResourceType": resources[key]["Type"]}
                for key in children
                if key != "ChildBucket1"
            ]
        }
    )
    with (
        patch("deploy.observed.selected_resources", return_value=set(children)),
        patch(
            "deploy.observed.resolve_resources",
            return_value=(plan[0], {unit["name"]: children}),
        ),
    ):
        publish_collected(backend, [unit], state)
    assert before == {path: path.read_bytes() for path in before}
    print(
        "Integrated child mapping: PASS (11 BucketPolicies, 5 associations, hidden RepositoryId, strict ownership/scope/Conditions, identifier-free sync/deletion)"
    )


def _callback_check_secretsmanager_arn_identifiers_mapping(backend, root, selected, /):
    return mappings(
        root, "dev", "123456789012", backend.templates, selected, target=TARGET
    )


def _callback_check_secretsmanager_arn_identifiers_aws(
    actual, outputs, /, operation, **args
):
    return (
        {
            "Stacks": [
                {
                    "StackId": "stack-A",
                    "StackStatus": "CREATE_COMPLETE",
                    "Outputs": outputs,
                }
            ]
        }
        if operation == "describe_stacks"
        else {"StackResourceSummaries": actual}
    )


def check_secretsmanager_arn_identifiers(publication_workspace, monkeypatch):
    root = publication_workspace
    (root / "project.json").write_text(
        json.dumps(
            {"projectName": "test", "targets": [{"environment": "dev", **TARGET}]}
        )
        + "\n"
    )
    model = root / "model/dev/123456789012"
    model.mkdir(parents=True)
    task = root / "tasks/observation-fixture.md"
    task.parent.mkdir(exist_ok=True)
    _ = "## Task contract\n- Task type: `design`\n- Task status: `running`\n## Modified files\n- `tasks/example.md`\n## Validation scope\n- `dev/123456789012/secretsmanager`\n- `dev/123456789012/kms`\n## Allowed paths\n- `tasks/example.md`\n- `model/dev/123456789012/**`\n- `docs/designs/dev/123456789012/**`\n"
    task.write_text(
        observation_contract(root, ("secretsmanager", "kms", "cloudformation-stacks"))
    )
    selected = units(1, 2)
    secrets = rotation.fixture()
    for identity, logical in (("001", "Secret1"), ("002", "Secret1Rotation")):
        secrets[f"desired.resource.{identity}.cfn-logicalId"] = "A-" + logical
    for field, value in {
        "property": "SecretsManager.Secret.KmsKeyId",
        "value": "[KMS_Key_001](kms.md#kms-app-dev-key)",
        "comment": "secretの暗号化鍵",
    }.items():
        secrets[f"desired.row.001-002.{field}"] = value
    key = rotation.HELPERS.model(
        "kms",
        "KMS.Key",
        "app-dev-key",
        [
            ("KeyId", "[KMS_Key_001](kms.md#kms-app-dev-key)", "暗号化鍵のID"),
            ("KeyPolicy", "[KeyPolicy](kms/key-policy.json)", "鍵の権限"),
        ],
        "Key",
        "app-dev-key",
    )
    key["desired.resource.001.cfn-logicalId"] = "A-Key"
    key["desired.row.001-002.document"] = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "secretsmanager.amazonaws.com"},
                    "Action": "kms:Decrypt",
                    "Resource": "*",
                }
            ],
        }
    )
    stacks = {
        f"desired.stack.{i:03d}.{field}": value
        for i, unit in enumerate(selected, 1)
        for field, value in unit.items()
    }
    for number in range(1, len(selected) + 1):
        stacks[f"display.stack.{number:03d}.comment"] = "合成Stack"
    for path, values in (
        (model / "secretsmanager.properties", secrets),
        (model / "kms.properties", key),
        (model / "cloudformation-stacks.properties", stacks),
    ):
        write_model(path, rotation.HELPERS.text(values))
    secret_ref = {"Ref": "Secret1"}
    document = {
        "Conditions": {"Enabled": True, "Disabled": False},
        "Resources": {
            "Secret1": {"Type": "AWS::SecretsManager::Secret"},
            "Secret1Rotation": {
                "Type": "AWS::SecretsManager::RotationSchedule",
                "Properties": {"SecretId": secret_ref},
            },
            "Key": {"Type": "AWS::KMS::Key"},
        },
        "Outputs": {"KeyId": {"Value": {"Ref": "Key"}}},
    }
    backend = Fake()
    backend.root, backend.environment, backend.directory, backend.target = (
        root,
        "dev",
        "123456789012",
        TARGET,
    )
    backend.templates = {"A": (document, {}), "B": ({}, {})}
    mapping = _bind_framework_callback(
        _callback_check_secretsmanager_arn_identifiers_mapping, backend, root, selected
    )
    backend.mapping_plan = mapping()
    assert not catalog_outputs(root, rotation.SECRET) and not catalog_outputs(
        root, rotation.ROTATION
    )
    assert catalog_outputs(root, "KMS.Key") == {"KMS.Key.KeyId"}
    arn = "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:app-dev-secret-1-abcdef"
    actual = [
        {
            "LogicalResourceId": logical,
            "ResourceType": resource["Type"],
            "ResourceStatus": "CREATE_COMPLETE",
            "PhysicalResourceId": "key-current" if logical == "Key" else arn,
        }
        for logical, resource in document["Resources"].items()
    ]
    outputs = [{"OutputKey": "KeyId", "OutputValue": "key-current"}]
    aws = _bind_framework_callback(
        _callback_check_secretsmanager_arn_identifiers_aws, actual, outputs
    )
    task.write_text(
        observation_contract(root, ("secretsmanager", "kms", "cloudformation-stacks"))
    )
    backend.aws = aws
    for arn_outputs in (False, True):
        if arn_outputs:
            document["Outputs"]["SecretArn"] = {"Value": secret_ref}
            document["Outputs"]["RotationArn"] = {
                "Value": {"Fn::GetAtt": ["Secret1Rotation", "Id"]}
            }
            outputs.extend(
                {"OutputKey": name, "OutputValue": arn}
                for name in ("SecretArn", "RotationArn")
            )
        backend.mapping_plan = mapping()
        saved = states(selected)
        publish_collected(backend, selected, saved)
        assert all(state["observedSynced"] for state in saved.values())
    current = properties(read_model(model / "secretsmanager.properties"))
    TestCase().assertNotIn("observed.row.001-002.value", current)
    TestCase().assertEqual(
        properties(read_model(model / "kms.properties"))["observed.row.001-001.value"],
        "`key-current`",
    )
    assert (
        current["desired.row.002-003.value"]
        == secrets["desired.resource.002.parentReference"]
    )
    assert not any(
        value in {rotation.SECRET + ".Id", rotation.ROTATION + ".Id"}
        for value in current.values()
    )
    artifacts = list((root / "docs/designs").rglob("*.json"))
    assert artifacts and json.loads(artifacts[0].read_text()) == json.loads(
        key["desired.row.001-002.document"]
    )
    assert all(
        arn not in path.read_text()
        for parent in (model, root / "docs/designs")
        for path in parent.rglob("*")
        if path.is_file()
    )
    # Current observations distinguish fallback from unconfirmed identifiers.
    before = {path: path.read_bytes() for path in model.rglob("*.properties")}
    actual[2]["ResourceType"] = "AWS::S3::Bucket"
    uncertain = states(selected)
    deploy_observed.collect_successful(backend, selected, uncertain)
    TestCase().assertEqual(
        uncertain["A"]["observedCoverage"]["Key"]["status"], "UNCONFIRMED"
    )
    actual[2]["ResourceType"] = document["Resources"]["Key"]["Type"]
    missing = outputs.pop(0)
    fallback = states(selected)
    deploy_observed.collect_successful(backend, selected, fallback)
    TestCase().assertEqual(
        fallback["A"]["observedCoverage"]["Key"]["status"], "MATCHED"
    )
    outputs.insert(0, {**missing, "OutputValue": "wrong-key"})
    uncertain = states(selected)
    deploy_observed.collect_successful(backend, selected, uncertain)
    TestCase().assertEqual(
        uncertain["A"]["observedCoverage"]["Key"]["status"], "UNCONFIRMED"
    )
    outputs[0]["OutputValue"] = actual[2]["PhysicalResourceId"] = arn
    uncertain = states(selected)
    deploy_observed.collect_successful(backend, selected, uncertain)
    TestCase().assertEqual(
        uncertain["A"]["observedCoverage"]["Key"]["status"], "UNCONFIRMED"
    )
    outputs[0]["OutputValue"] = actual[2]["PhysicalResourceId"] = "key-current"
    TestCase().assertEqual(before, {path: path.read_bytes() for path in before})
    # Explicit advances and collection remain separate at the current controller boundary.
    session = {"states": states(selected)}
    session["states"]["A"]["stackId"] = "stack-A"
    for unit in selected:
        advance_group(selected, 1, session["states"], backend)
        publish_collected(backend, [unit], session["states"])
    assert starts(backend) == ["A", "B"]
    failed = Fake()
    for field in (
        "root",
        "environment",
        "directory",
        "target",
        "templates",
        "mapping_plan",
        "aws",
    ):
        setattr(failed, field, getattr(backend, field))
    outputs[0]["OutputValue"] = "wrong-key"
    session = {
        "states": states(selected),
        "metrics": {"observedSyncSeconds": 0},
    }
    session["states"]["A"]["stackId"] = "stack-A"
    for unit in selected:
        advance_group(selected, 1, session["states"], failed)
        publish_collected(failed, [unit], session["states"])
    TestCase().assertEqual(starts(failed), ["A", "B"])
    TestCase().assertEqual(
        session["states"]["A"]["observedCoverage"]["Key"]["status"], "UNCONFIRMED"
    )
    TestCase().assertNotIn(
        "observed.row.001-001.value", properties(read_model(model / "kms.properties"))
    )
    print(
        "Secrets Manager ARN identifiers: PASS (no required ARN Outputs/storage/propagation, logical parent, JSON, KMS guards, DeployOrder barrier)"
    )


def main():
    return run(
        __file__,
        message="CloudFormation controller checks: PASS (scheduler, exact approvals, S3 mappings/uploads, byte limits, checksum/source drift and scoped generation)",
    )


def check_deploy_preparation_separates_producer_reads_from_writes(
    tmp_path, monkeypatch
):
    parse = _imports_model_format.parse
    patch = _imports_model_format.patch
    serialize = _imports_model_format.serialize
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    scope, stacks = deploy_properties_fixture(tmp_path)
    producer = scope.path.with_name("security.properties")
    producer.write_text(
        serialize(
            {
                "desired.resource.009.resourceType": "EC2.VPC",
                "desired.resource.009.logicalId": "EC2_VPC_001",
                "desired.resource.009.anchor": "resource-EC2_VPC_001",
                "desired.service.identity.lastAllocated": '{"EC2.VPC":1}',
                "desired.resource.009.resourceMode": "IMPORT",
            }
        ),
        encoding="utf-8",
    )
    scope.path.write_text(
        patch(
            parse(scope.path.read_text(encoding="utf-8")),
            {
                "desired.row.007-002.property": "EC2.VPC.Name",
                "desired.row.007-002.value": "[EC2_VPC_001](security.md#vpc-test-dev)",
                "desired.row.007-002.comment": "合成参照",
            },
        ),
        encoding="utf-8",
    )
    text, sources, _, _ = candidate(
        tmp_path,
        "tasks/deploy.md",
        scope.environment,
        scope.target,
        {"awsAccountId": "123456789012", "alias": scope.target},
        ["CurrentName"],
        ["network", "cloudformation-stacks"],
    )
    allowed = paths_in(text, "## Allowed paths")
    assert producer not in sources
    cache = RunModels(tmp_path, {})
    with model_sources.model_session(cache):
        snapshot = load_model(scope.path)
    assert producer in snapshot.dependencies
    assert producer.relative_to(tmp_path).as_posix() in cache.run_context["modelInputs"]
    assert producer.relative_to(tmp_path).as_posix() not in allowed
    assert "project.json" not in allowed and tmp_path / "project.json" in sources
    assert scope.path.relative_to(tmp_path).as_posix() in allowed
    assert stacks.relative_to(tmp_path).as_posix() in allowed


if __name__ == "__main__":
    raise SystemExit(main())
