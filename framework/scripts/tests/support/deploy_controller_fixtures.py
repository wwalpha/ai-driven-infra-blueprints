"""Private Project data and operation-specific SDK replies for the real controller.

Only synthetic AWS state, diagnostic snapshots and unfinished journals survive a child process. Framework definitions
are read from the installed source; no Framework copy or controller substitution.
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import urllib.parse as _imports_urllib_parse

import model.format as _imports_model_format
import sync_files as _imports_sync_files
import sync_runtime
import utils.cloudformation.inputs as _imports_cfn_inputs
from botocore.exceptions import ClientError
from deploy import operation_journal, run_context
from deploy.controller import main
from model.core import properties, stack_model
from model.dependency_index import rebuild as rebuild_index
from model.files import read_model
from support.fixture_cases import load_case, materialize_files
from support.model_sources import allocate_fixture, write_model
from support.publication_fixtures import publication_repository
from task_contract_core import selected_task, start
from utils.cloudformation.format import decode
from utils.cloudformation.inputs import condition_active
from utils.function_wrapper import BoundCallback as _bind_framework_callback

SCRIPTS = Path(__file__).resolve().parents[2]


ACCOUNT = "123456789012"
REGION = "ap-northeast-1"


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def seed(root, state_path, case="orders", *, same_group=False):
    fixture = load_case(
        "deploy_controller", "orders" if case in {"remove", "multi-observed"} else case
    )
    root.mkdir()
    materialize_files(root, fixture["files"])
    multi_observed = case in {"multi-observed", "observed-peers"}
    if case == "remove" or multi_observed:
        template = root / "infra/cloudformation/templates/first.yaml"
        document, errors = decode(template.read_text())
        assert not errors
        if case == "remove":
            for logical in ("Subnet", "Association"):
                document["Resources"].pop(logical)
            fixture["data"]["ec2"]["observed.row.002-001.value"] = "`subnet-before`"
        else:
            document["Resources"]["VpcFirst"] = {
                "Type": "AWS::EC2::VPC",
                "Properties": {"CidrBlock": "10.1.0.0/16"},
            }
            values = fixture["data"]["ec2"]
            values.update(
                {
                    key.replace(".001.", ".003.").replace(".001-", ".003-"): value
                    for key, value in list(values.items())
                    if key.startswith(("desired.resource.001.", "desired.row.001-"))
                }
            )
            values.update(
                {
                    "desired.resource.003.cfn-logicalId": "cfn-stack-app-dev-first-VpcFirst",
                    "desired.row.003-001.value": "[vpc](#resource-EC2_VPC_002)",
                    "desired.row.003-002.value": "`10.1.0.0/16`",
                    "desired.row.003-003.value": "`app-dev-observed-vpc`",
                }
            )
        template.write_text(json.dumps(document))
    services = ["s3", "ec2"]
    fixture["data"]["s3"].update(fixture["data"].get("s3_extra", {}))
    model = root / "model/dev" / ACCOUNT
    stack_values = {"desired.deployment.maxConcurrentStacks": "2"}
    stacks = fixture["data"]["stacks"]
    if same_group or fixture["data"].get("same_group"):
        for item in stacks:
            item["order"] = 10
    for number, item in enumerate(stacks, 1):
        name = "cfn-stack-app-dev-" + item["name"]
        for key, value in {
            "name": name,
            "template": item["name"] + ".yaml",
            "parameters": item["name"] + ".json",
            "deployOrder": str(item["order"]),
        }.items():
            stack_values[f"desired.stack.{number:03}.{key}"] = value
        stack_values[f"display.stack.{number:03}.comment"] = "合成Stack"
    if fixture["data"].get("delivery"):
        stack_values.update(
            {
                "desired.deployment.templateBucket": "[assets](s3.md#resource-S3_Bucket_002)",
                "desired.deployment.templateKeyPrefix": "templates/",
            }
        )
        for item in stacks:
            name = item["name"]
            template = root / "infra/cloudformation/templates" / (name + ".yaml")
            template.write_text(
                template.read_text() + "Description: " + "x" * 52000 + "\n"
            )
    write_model(model / "cloudformation-stacks.properties", stack_values)
    for service in services:
        values = fixture["data"][service]
        identities = sorted(
            {key.split(".")[2] for key in values if key.startswith("desired.resource.")}
        )
        values.update(allocate_fixture(values, identities))
        values[f"desired.service.{service}.serviceId"] = service
        values[f"desired.service.{service}.ownedCatalogResourceTypes"] = ",".join(
            sorted(
                {v for k, v in values.items() if k.endswith(".resourceType")}
                | {
                    ".".join(v.split(".")[:2])
                    for k, v in values.items()
                    if k.startswith("desired.row.") and k.endswith(".property")
                }
            )
        )
        values["display.service.title"] = "# 合成詳細設計"
        for identity in identities:
            values[f"display.resource.{identity}.comment"] = "合成resource"
        source = model / (service + ".properties")
        write_model(source, values)
        if service == "ec2" and multi_observed:
            split = _imports_model_format.split
            save_files = _imports_sync_files.save_files
            save_files(split(source, values, limit=1))

    # This is fixture initialization through real generation; publication is tested by the controller.
    task = root / "tasks/deploy.md"
    files = {task.relative_to(root).as_posix()}
    files.update(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    for service in [*services, "cloudformation-stacks"]:
        files.add(f"docs/designs/dev/{ACCOUNT}/{service}.md")
    files.add(f"docs/designs/dev/{ACCOUNT}/s3/s3-bucket-001-bucket-policy.json")
    listed = "".join("- `" + value + "`\n" for value in sorted(files))
    contract = (
        "## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n"
        "- Infrastructure phase: `deploy`\n- AWS API execution: `allowed`\n- Deploy/apply: `allowed`\n"
        f"- Target environment: `dev`\n- Target AWS account: `{ACCOUNT}`\n"
        "- Deployment scope: "
        + ", ".join("`cfn-stack-app-dev-" + item["name"] + "`" for item in stacks)
        + "\n- Authorized delete/replacement: `none`\n"
        "- Runtime recovery: `allowed`\n- External IaC repair: `allowed`\n"
        "## Required changes\n- [R1] Synthetic deployment\n## Acceptance checks\n- [R1] `exists:project.json`\n"
        "## Validation scope\n"
        + "".join(
            f"- `dev/{ACCOUNT}/{s}`\n" for s in [*services, "cloudformation-stacks"]
        )
        + "## Modified files\n"
        + listed
        + "## Allowed paths\n"
        + listed
    )
    start(root, "tasks/deploy.md", contract)
    with selected_task(root, "tasks/deploy.md"):
        assert (
            sync_runtime.sync(
                root,
                True,
                "dev",
                ACCOUNT,
                services=[*services, "cloudformation-stacks"],
            )
            == 0
        )
    rebuild_index(root)
    ignore = root / ".gitignore"
    ignore.write_text("tasks/**\n__pycache__/\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Offline Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "Synthetic inputs")
    saved_contract = (
        "\n".join(
            line
            for line in task.read_text().splitlines()
            if not line.startswith("- `infra/")
        )
        + "\n"
    )
    task.write_text(saved_contract)
    return root


def stack_names(root):
    task = root / "tasks/deploy.md"
    if not task.is_file():
        return [
            "cfn-stack-app-dev-" + item["name"]
            for item in load_case("deploy_controller", "orders")["data"]["stacks"]
        ]
    scope = next(
        line
        for line in task.read_text().splitlines()
        if line.startswith("- Deployment scope:")
    )
    return [part for number, part in enumerate(scope.split("`")) if number % 2]


def designed_stacks(root):
    return [
        unit
        for _, unit in stack_model(
            properties(
                read_model(
                    root / f"model/dev/{ACCOUNT}/cloudformation-stacks.properties"
                )
            )
        )[1]
    ]


def aws_state(path, **knobs):
    stacks = {}
    if knobs.get("remove"):
        name = "cfn-stack-app-dev-first"
        stacks[name] = {
            "status": "UPDATE_COMPLETE",
            "id": f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{name}/fixture",
        }
    path.write_text(
        json.dumps(
            {
                "stacks": stacks,
                "changes": {},
                "calls": [],
                "objects": {},
                "knobs": knobs,
            }
        )
    )


def _callback_clients_client(operations, request, /, context, service, *, read=False):
    return SimpleNamespace(
        **{op: partial(request, service, op) for op in operations[service]}
    )


def _callback_clients_request_persist(aws_path, state, /):
    aws_path.write_text(json.dumps(state))


def _callback_clients_request_active(name, /, definition, change):
    return condition_active(
        change["document"],
        {p["ParameterKey"]: p["ParameterValue"] for p in change.get("parameters", [])},
        {"AWS::AccountId": ACCOUNT, "AWS::Region": REGION, "AWS::StackName": name},
        definition,
    )


def _callback_clients_request_error(
    operation, persist, /, code, message="", status=400
):
    persist()
    raise ClientError(
        {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operation,
    )


def _callback_clients_request(
    aws_path, gate, root, state_path, /, service, operation, **arguments
):
    with gate:
        state = json.loads(aws_path.read_text())
        knobs = state["knobs"]
        public = {
            k: v
            for k, v in arguments.items()
            if k not in {"Body", "SecretString", "TemplateBody"}
        }
        state["calls"].append([service, operation, public])
        persist = _bind_framework_callback(
            _callback_clients_request_persist, aws_path, state
        )
        error = _bind_framework_callback(
            _callback_clients_request_error, operation, persist
        )
        name = arguments.get("StackName", "")
        name = name.split(":stack/")[-1].split("/")[0]
        stack_id = (
            state["stacks"].get(name, {}).get("id")
            or state["changes"].get(name, {}).get("stackId")
            or f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{name}/fixture"
        )
        active = _bind_framework_callback(_callback_clients_request_active, name)
        result = None
        if service == "sts" and operation == "get_caller_identity":
            result = {
                "Account": ACCOUNT,
                "Arn": f"arn:aws:iam::{ACCOUNT}:user/fixture",
                "UserId": "fixture",
            }
        elif service == "cloudformation":
            stack = state["stacks"].get(name)
            if operation == "get_template":
                result = {"TemplateBody": state["changes"][name]["document"]}
            elif operation == "validate_template":
                result = {"Parameters": []}
            elif operation == "describe_stacks":
                if stack is None:
                    error(
                        "ValidationError",
                        f"Stack with id {arguments['StackName']} does not exist",
                    )
                result = {
                    "Stacks": [
                        {
                            "StackId": stack_id,
                            "StackName": name,
                            "StackStatus": stack["status"],
                            **(
                                {"Outputs": knobs["fence_exports"].get(name, [])}
                                if "fence_exports" in knobs
                                else {}
                            ),
                        }
                    ]
                }
            elif operation == "create_change_set":
                if arguments.get("ChangeSetType") == "CREATE":
                    stack_id = (
                        f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{name}/"
                        + arguments["ChangeSetName"]
                    )
                designed = designed_stacks(root)
                current_order = next(
                    int(u["deployOrder"]) for u in designed if u["name"] == name
                )
                saved = json.loads(state_path.read_text())
                earlier = [
                    u["name"] for u in designed if int(u["deployOrder"]) < current_order
                ]
                assert all(
                    saved["states"][n]["status"] == "SUCCESS"
                    and saved["states"][n].get("observedSynced")
                    for n in earlier
                )
                values = properties(
                    read_model(root / f"model/dev/{ACCOUNT}/ec2.properties")
                )
                if "cfn-stack-app-dev-first" in earlier:
                    expected = (
                        "PENDING_DEPLOY" if knobs.get("remove") else "subnet-fixture"
                    )
                    assert values["observed.row.002-001.value"].strip("`") == expected
                if "cfn-stack-app-dev-second" in earlier:
                    assert (
                        values["observed.row.001-001.value"].strip("`") == "vpc-fixture"
                    )
                if knobs.get("delivery"):
                    assert saved["states"][name].get("delivery", {}).get("objects")
                state.setdefault("barriers", {})[name] = {
                    "earlier": earlier,
                    "states": {n: saved["states"][n] for n in earlier},
                    "observed": values,
                }
                if "TemplateBody" in arguments:
                    document, errors = decode(arguments["TemplateBody"])
                else:
                    unquote = _imports_urllib_parse.unquote
                    urlsplit = _imports_urllib_parse.urlsplit
                    key = unquote(
                        urlsplit(arguments["TemplateURL"])
                        .path.lstrip("/")
                        .partition("/")[2]
                    )
                    document, errors = decode(
                        base64.b64decode(state["objects"][key]["data"]).decode()
                    )
                assert not errors
                change = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:changeSet/{arguments['ChangeSetName']}/fixture"
                state["changes"][name] = {
                    "id": change,
                    "alias": arguments["ChangeSetName"],
                    "document": document,
                    "executed": False,
                    "stackId": stack_id,
                    "parameters": arguments.get("Parameters", []),
                    **(
                        {"type": arguments["ChangeSetType"]}
                        if knobs.get("reset_updates")
                        else {}
                    ),
                }
                result = {"Id": change, "StackId": stack_id}
            elif operation == "describe_change_set":
                change = state["changes"][name]
                assert arguments["ChangeSetName"] in (change["id"], change["alias"])
                changes = [
                    {
                        "ResourceChange": {
                            "Action": "Add",
                            "Replacement": "False",
                            "LogicalResourceId": logical,
                            "ResourceType": definition["Type"],
                        }
                    }
                    for logical, definition in change["document"]["Resources"].items()
                    if active(definition, change)
                ]
                if knobs.get("remove") and name == "cfn-stack-app-dev-first":
                    for change_entry in changes:
                        change_entry["ResourceChange"].update(
                            Action="Modify", Replacement="False"
                        )
                    changes.append(
                        {
                            "ResourceChange": {
                                "Action": "Remove",
                                "LogicalResourceId": "Subnet",
                                "ResourceType": "AWS::EC2::Subnet",
                                "PhysicalResourceId": "subnet-before",
                                "PolicyAction": "Delete",
                            }
                        }
                    )
                result = {
                    "ChangeSetId": change["id"],
                    "StackId": change["stackId"],
                    "StackName": name,
                    "Status": "CREATE_COMPLETE",
                    "ExecutionStatus": "EXECUTE_COMPLETE"
                    if change["executed"]
                    else "AVAILABLE",
                    "Changes": changes,
                }
            elif operation == "execute_change_set":
                change = state["changes"][name]
                assert not change["executed"], "duplicate Execute"
                assert arguments["ChangeSetName"] == change["id"]
                change.update(executed=True, token=arguments["ClientRequestToken"])
                vpc_properties = (
                    change["document"]
                    .get("Resources", {})
                    .get("Vpc", {})
                    .get("Properties", {})
                )
                if isinstance(vpc_properties.get("CidrBlock"), dict):
                    resolve_value = _imports_cfn_inputs.resolve_value
                    vpc_properties = {
                        **vpc_properties,
                        "CidrBlock": resolve_value(
                            vpc_properties["CidrBlock"],
                            {
                                p["ParameterKey"]: p["ParameterValue"]
                                for p in change.get("parameters", [])
                            },
                            {},
                        ),
                    }
                failed = (
                    name == "cfn-stack-app-dev-second"
                    and knobs.get("repair")
                    and vpc_properties.get("CidrBlock") != "10.0.0.0/16"
                )
                state["stacks"][name] = {
                    "status": "ROLLBACK_COMPLETE"
                    if failed
                    else "UPDATE_COMPLETE"
                    if (knobs.get("remove") and name == "cfn-stack-app-dev-first")
                    or change.get("type") == "UPDATE"
                    else "CREATE_COMPLETE",
                    "id": stack_id,
                }
                change["failed"] = failed
                if knobs.pop("crash_execute", False):
                    persist()
                    os._exit(73)
                result = {}
            elif operation == "list_imports" and "fence_imports" in knobs:
                result = {
                    "Imports": knobs["fence_imports"].get(arguments["ExportName"], [])
                }
            elif operation == "describe_stack_events":
                change = state["changes"].get(name)
                failed = change and change.get("failed")
                events = (
                    []
                    if not change or not change["executed"]
                    else [
                        {
                            "StackId": stack_id,
                            "ResourceType": "AWS::CloudFormation::Stack",
                            "ClientRequestToken": change["token"],
                            "ResourceStatus": state["stacks"][name]["status"],
                        }
                    ]
                )
                if change and change["executed"] and not failed:
                    events.extend(
                        {
                            "StackId": stack_id,
                            "ClientRequestToken": change["token"],
                            "ResourceStatus": "CREATE_COMPLETE",
                            "LogicalResourceId": logical,
                            "ResourceType": definition["Type"],
                        }
                        for logical, definition in change["document"][
                            "Resources"
                        ].items()
                        if active(definition, change)
                    )
                if (
                    knobs.get("remove")
                    and change
                    and change["executed"]
                    and name == "cfn-stack-app-dev-first"
                ):
                    events.append(
                        {
                            "StackId": stack_id,
                            "ClientRequestToken": change["token"],
                            "LogicalResourceId": "Subnet",
                            "PhysicalResourceId": "subnet-before",
                            "ResourceType": "AWS::EC2::Subnet",
                            "ResourceStatus": "DELETE_COMPLETE",
                        }
                    )
                if failed:
                    events.append(
                        {
                            "StackId": stack_id,
                            "ClientRequestToken": change["token"],
                            "ResourceStatus": "CREATE_FAILED",
                            "LogicalResourceId": "Vpc",
                            "ResourceType": "AWS::EC2::VPC",
                            "ResourceStatusReason": "invalid CidrBlock",
                        }
                    )
                if (
                    name == "cfn-stack-app-dev-second"
                    and events
                    and knobs.pop("defer_peer", False)
                ):
                    events[0]["ResourceStatus"] = "UPDATE_IN_PROGRESS"
                result = {"StackEvents": events}
            elif operation == "list_stack_resources":
                document = state["changes"].get(name, {}).get("document", {})
                result = {
                    "StackResourceSummaries": [
                        {
                            "LogicalResourceId": logical,
                            "ResourceType": definition["Type"],
                            "PhysicalResourceId": "app-dev-third"
                            if logical == "ThirdBucket"
                            else "app-dev-bucket"
                            if logical == "Bucket"
                            else "vpc-first-fixture"
                            if logical == "VpcFirst"
                            else "vpc-fixture"
                            if definition["Type"] == "AWS::EC2::VPC"
                            else "subnet-fixture"
                            if logical == "Subnet"
                            else "integrated-child",
                            "ResourceStatus": "CREATE_COMPLETE",
                        }
                        for logical, definition in document.get("Resources", {}).items()
                        if active(definition, state["changes"][name])
                    ]
                }
                if stack and stack["status"] == "ROLLBACK_COMPLETE":
                    result = {"StackResourceSummaries": []}
                if (
                    knobs.get("remove")
                    and name == "cfn-stack-app-dev-first"
                    and not state["changes"].get(name, {}).get("executed")
                ):
                    result["StackResourceSummaries"].append(
                        {
                            "LogicalResourceId": "Subnet",
                            "ResourceType": "AWS::EC2::Subnet",
                            "PhysicalResourceId": "subnet-before",
                            "ResourceStatus": "CREATE_COMPLETE",
                        }
                    )
            elif operation == "delete_stack":
                assert stack and stack["status"] == "ROLLBACK_COMPLETE"
                state["stacks"].pop(name)
                if knobs.pop("crash_cleanup", False):
                    persist()
                    os._exit(74)
                result = {}
            else:
                raise AssertionError((service, operation))
        elif service == "s3":
            assert arguments["ExpectedBucketOwner"] == ACCOUNT
            if operation == "head_bucket":
                result = {}
            elif operation == "get_bucket_location":
                result = {"LocationConstraint": REGION}
            elif operation == "get_bucket_encryption":
                result = {
                    "ServerSideEncryptionConfiguration": {
                        "Rules": [
                            {
                                "ApplyServerSideEncryptionByDefault": {
                                    "SSEAlgorithm": "AES256"
                                }
                            }
                        ]
                    }
                }
            elif operation == "get_bucket_policy":
                error("NoSuchBucketPolicy", status=404)
            elif operation == "put_object":
                if knobs.get("delivery_fail"):
                    error("AccessDenied", status=403)
                assert arguments["IfNoneMatch"] == "*"
                key = arguments["Key"]
                if key in state["objects"]:
                    error("PreconditionFailed", status=412)
                data = arguments["Body"].read()
                checksum = base64.b64encode(hashlib.sha256(data).digest()).decode()
                assert checksum == arguments["ChecksumSHA256"]
                state["objects"][key] = {
                    "data": base64.b64encode(data).decode(),
                    "ChecksumSHA256": checksum,
                    "ContentLength": len(data),
                    "VersionId": "v1",
                    "ServerSideEncryption": "AES256",
                }
                result = {"VersionId": "v1"}
            elif operation == "head_object":
                if arguments["Key"] not in state["objects"]:
                    error("NotFound", status=404)
                result = {
                    k: v
                    for k, v in state["objects"][arguments["Key"]].items()
                    if k != "data"
                }
            else:
                raise AssertionError((service, operation))
        else:
            raise AssertionError((service, operation))
        assert result is not None, (service, operation)
        persist()
        return result


def clients(root, state_path, aws_path):
    """A finite set of SDK operations; unexpected calls have no network fallback."""
    gate = RLock()

    request = _bind_framework_callback(
        _callback_clients_request, aws_path, gate, root, state_path
    )

    operations = {
        "sts": ["get_caller_identity"],
        "cloudformation": [
            "validate_template",
            "describe_stacks",
            "create_change_set",
            "describe_change_set",
            "execute_change_set",
            "describe_stack_events",
            "list_stack_resources",
            "delete_stack",
            "get_template",
            "list_imports",
        ],
        "s3": [
            "head_bucket",
            "get_bucket_location",
            "get_bucket_encryption",
            "get_bucket_policy",
            "put_object",
            "head_object",
        ],
    }
    client = _bind_framework_callback(_callback_clients_client, operations, request)
    return client


def _callback_invoke_write(
    fault,
    journal,
    original_write,
    root,
    state_path,
    aws_path,
    witnessed,
    /,
    path,
    text,
    *args,
    **kwargs,
):
    if fault == "design-io" and path.is_relative_to(root / "docs/designs"):
        if not witnessed:
            saved, provider = (
                json.loads(state_path.read_text()),
                json.loads(aws_path.read_text()),
            )
            provider["observedFailure"] = {
                "statuses": {
                    name: state["status"] for name, state in saved["states"].items()
                },
                "executionEvidence": {
                    name: state.get("executionEvidence")
                    for name, state in saved["states"].items()
                },
                "observedSynced": sorted(
                    name
                    for name, state in saved["states"].items()
                    if state.get("observedSynced")
                ),
                "pendingGeneration": sorted(saved["pendingGeneration"]),
            }
            original_write(aws_path, json.dumps(provider))
            witnessed.append(True)
        raise OSError("injected design I/O failure")
    result = original_write(path, text, *args, **kwargs)
    if (
        fault == "model-partial"
        and path.is_relative_to(root / "model")
        and path.suffix == ".properties"
        and "observed.row." in text
    ):
        assert journal.is_file()
        os._exit(76)
    return result


def fake_sleep(delays, seconds):
    # Two synthetic stacks must terminate; bound polling even when real waiting is removed.
    assert len(delays) < 100, "Fake AWS polling did not terminate"
    delays.append(seconds)


def save_diagnostics(real_save, report, /, path, backend):
    real_save(path, backend)
    report.write_text(json.dumps(backend.run_context), encoding="utf-8")


def invoke(root, state_path, aws_path, options=(), fault=None):
    journal = (
        Path(tempfile.gettempdir())
        / "blueprint-model-publication"
        / (hashlib.sha256(str(root).encode()).hexdigest() + ".json")
    )
    write = _bind_framework_callback(
        _callback_invoke_write,
        fault,
        journal,
        Path.write_text,
        root,
        state_path,
        aws_path,
        [],
    )
    delays = []
    sleep = partial(fake_sleep, delays)
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                operation_journal,
                "location",
                return_value=state_path.with_suffix(".operations.json"),
            )
        )
        stack.enter_context(
            patch.object(
                operation_journal,
                "save",
                partial(save_diagnostics, operation_journal.save, state_path),
            )
        )

        stack.enter_context(
            patch.object(
                run_context, "run_deploy", partial(run_context.run_deploy, sleep=sleep)
            )
        )
        stack.enter_context(
            patch.object(
                run_context, "run_group", partial(run_context.run_group, sleep=sleep)
            )
        )
        stack.enter_context(
            patch("utils.aws.client.client", clients(root, state_path, aws_path))
        )
        stack.enter_context(
            patch(
                "socket.socket.connect", side_effect=AssertionError("network forbidden")
            )
        )
        stack.enter_context(
            patch(
                "socket.socket.connect_ex",
                side_effect=AssertionError("network forbidden"),
            )
        )
        if fault:
            assert fault in {"design-io", "model-partial"}
            stack.enter_context(patch.object(Path, "write_text", write))
        selection = [arg for name in stack_names(root) for arg in ("--stack", name)]
        return main(
            [
                "--environment",
                "dev",
                "--aws-account-id",
                ACCOUNT,
                *selection,
                "--timing-log",
                str(state_path.with_suffix(".timing.jsonl")),
                *options,
            ]
        )


def child_environment():
    return {
        **{
            k: v
            for k, v in os.environ.items()
            if k
            not in {"AWS_PROFILE", "AWS_DEFAULT_PROFILE", "BLUEPRINT_OBSERVED_FAULT"}
        },
        "PYTHONPATH": os.pathsep.join(
            [str(SCRIPTS), str(Path(__file__).resolve().parents[2] / "tests")]
        ),
        "BLUEPRINT_TASK_FILE": "tasks/deploy.md",
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_CONFIG_FILE": os.devnull,
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
        "AWS_ACCESS_KEY_ID": "synthetic",
        "AWS_SECRET_ACCESS_KEY": "synthetic",
    }


def recover_owned_lock(root, child):
    assert child.returncode is not None  # subprocess.run has reaped this exact child.

    state_path = Path(child.args[child.args.index(str(root)) + 1])
    lock = state_path.with_suffix(".operations.lock")
    assert lock.exists()
    lock.unlink()


def ordinary_base(root, name):
    return git(root, "rev-list", "--max-parents=0", "HEAD").strip()


if __name__ == "__main__":
    root, state_path, aws_path = map(lambda arg: Path(arg).resolve(), sys.argv[1:4])
    os.chdir(root)
    with (
        publication_repository(),
        patch("deploy.contracts.task_start_commit", ordinary_base),
    ):
        raise SystemExit(
            invoke(
                root,
                state_path,
                aws_path,
                sys.argv[4:],
                fault=os.environ.get("BLUEPRINT_OBSERVED_FAULT"),
            )
        )
