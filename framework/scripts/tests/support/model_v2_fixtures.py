"""Explicit properties authorities and offline AWS transport; no executing project inputs."""

import json
import os
import subprocess
import sys
from contextlib import ExitStack
from datetime import datetime, timezone
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace
from types import SimpleNamespace as _CallbackState

import generation_inputs as _imports_generation_inputs
import import_guard as _imports_import_guard
import model.format as _imports_model_format
import model.importing.cli as _imports_model_importing_cli
import model.operations as _imports_model_operations
import model.sources as _imports_model_sources
import pytest as _imports_pytest
import support.import_repository_fixtures as _imports_support_import_repository_fixtures
import support.model_v2_fixtures as _imports_support_model_v2_fixtures
from model.format import parse, serialize
from model.sources import Scope, load_model
from task_contract_core import selected_task
from utils.json_format import document_sha256

from model import dependency_index

FRAMEWORK = Path(__file__).resolve().parents[4]


def logs_fixture(root):
    (root / "project.json").write_text(
        json.dumps(
            {
                "projectName": "fixture",
                "targets": [
                    {
                        "environment": "qa-synthetic",
                        "alias": "team-a",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    model = root / "model/qa-synthetic/team-a/cloudwatch-logs.properties"
    model.parent.mkdir(parents=True)
    values = {
        "desired.service.cloudwatch-logs.serviceId": "cloudwatch-logs",
        "desired.service.cloudwatch-logs.ownedCatalogResourceTypes": "Logs.LogGroup",
        "display.service.title": "# 合成 Log Group 詳細設計",
        "desired.resource.001.resourceType": "Logs.LogGroup",
        "desired.resource.001.logicalId": "Logs_LogGroup_001",
        "desired.resource.001.anchor": "logs-existing",
        "desired.service.identity.lastAllocated": '{"Logs.LogGroup":1}',
        "desired.resource.001.resourceMode": "IMPORT",
        "display.resource.001.comment": "合成 Log Group",
    }
    for index, (prop, value) in enumerate(
        [
            ("LogGroupName", "[logs](#logs-existing)"),
            ("RetentionInDays", "`30`"),
            ("DeletionProtectionEnabled", "`false`"),
            ("LogGroupClass", "`STANDARD`"),
        ],
        1,
    ):
        values.update(
            {
                f"desired.row.001-{index:03d}.property": "Logs.LogGroup." + prop,
                f"desired.row.001-{index:03d}.value": value,
                f"desired.row.001-{index:03d}.comment": "合成値",
            }
        )
    values["observed.row.001-001.value"] = "`fixture-001`"
    model.write_text(serialize(values), encoding="utf-8")
    return model


def import_contract(name, model):
    model = Path(model).as_posix()
    view = model.replace("model/", "docs/designs/", 1).replace(".properties", ".md")
    listed = "".join("- `" + path + "`\n" for path in (name, model, view))
    return (
        """# Synthetic Import
## Task contract
- Task type: `design`
- Task status: `running`
- Workflow: `import`
- IMPORT target: `qa-synthetic/team-a/cloudwatch-logs`
- AWS API execution: `read-only`
- deploy/apply: `forbidden`
## Validation scope
- `qa-synthetic/team-a/cloudwatch-logs`
## Required changes
- [R1] Synthetic explicit Import
## Acceptance checks
- [R1] `exists:project.json`
## Modified files
"""
        + listed
        + "\n## Allowed paths\n"
        + listed
    )


class LogsCli:
    def __init__(self, groups=None):
        self.calls = []
        self.groups = (
            groups
            if groups is not None
            else [
                {
                    "logGroupName": "fixture-001",
                    "retentionInDays": 90,
                    "deletionProtectionEnabled": True,
                    "logGroupClass": "STANDARD",
                }
            ]
        )

    def __call__(self, command, **kwargs):
        service, operation = command[1:3]
        self.calls.append((service, operation))
        assert command[0] == "aws" and kwargs["timeout"] == 60
        if (service, operation) == ("sts", "get-caller-identity"):
            value = {"Account": "123456789012"}
        elif (service, operation) == ("logs", "describe-log-groups"):
            value = {"logGroups": self.groups}
        else:
            raise AssertionError("unmocked AWS transport: " + service + "/" + operation)
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")


def format_fixture(root, *, target="one", environment="qa-custom", service="network"):
    project = {
        "targets": [
            {
                "environment": environment,
                "alias": "one",
                "awsAccountId": "123456789012",
                "awsRegion": "ap-northeast-1",
                "iacEngine": "cloudformation",
                "awsExecutionAccountId": "999999999999",
            },
            {
                "environment": environment,
                "alias": "two",
                "awsAccountId": "123456789012",
                "awsRegion": "ap-northeast-1",
                "iacEngine": "cloudformation",
            },
            {
                "environment": environment + "-single",
                "awsAccountId": "222222222222",
                "awsRegion": "ap-northeast-1",
                "iacEngine": "cloudformation",
            },
        ]
    }
    (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    scope = Scope(
        root,
        environment + "-single" if target == "222222222222" else environment,
        target,
        service,
    )
    values = {
        "desired.resource.007.resourceType": "EC2.VPC",
        "desired.resource.007.logicalId": "EC2_VPC_001",
        "desired.resource.007.anchor": "network-existing",
        "desired.service.identity.lastAllocated": '{"EC2.VPC":1}',
        "desired.resource.007.resourceMode": "IMPORT",
        "desired.row.007-001.property": "EC2.VPC.VpcId",
        "desired.row.007-001.value": "[vpc](#network-existing)",
        "desired.row.007-001.comment": "合成 ID",
        "observed.row.007-001.value": "",
        "desired.row.007-002.property": "EC2.VPC.CidrBlock",
        "desired.row.007-002.value": ' 010 \\ " ',
        "desired.row.007-002.comment": "原文保持",
    }
    scope.path.parent.mkdir(parents=True)
    scope.path.write_text(serialize(values), encoding="utf-8")
    return scope, values


def source_context(scope, *, imported=False):
    # Unit-only capability fixture: factory/worktree authorization is tested separately.

    GenerationInputs = _imports_generation_inputs.GenerationInputs
    SourceWriteContext = _imports_model_sources.SourceWriteContext
    values = parse(scope.path.read_text(encoding="utf-8")).values
    values["desired.resource.007.resourceMode"] = "IMPORT" if imported else "CREATE"
    scope.path.write_text(serialize(values), encoding="utf-8")
    task = scope.root / "tasks/example.md"
    task.parent.mkdir(exist_ok=True)
    listed = "".join(
        "- `" + path + "`\n"
        for path in ("tasks/example.md", scope.path.relative_to(scope.root).as_posix())
    )
    task.write_text(
        "## Task contract\n- Task type: `governance`\n- Task status: `running`\n"
        + "## Modified files\n"
        + listed
        + "## Allowed paths\n"
        + listed,
        encoding="utf-8",
    )
    inputs = GenerationInputs(scope.root, task_file="tasks/example.md")
    model = load_model(scope, inputs)
    context = SourceWriteContext._authorized(
        scope.root,
        inputs,
        SimpleNamespace(action="model-delete"),
        lambda changes: None,
        frozenset(model.files),
    )
    return model, context


def acquisition_fixture(snapshot, *, action="refresh", resource="007"):
    operation_values = _imports_model_operations.operation_values
    identity = "vpc-original" if action == "refresh" else "vpc-acquired"
    record = {
        "record": "record-one",
        "kind": "EC2.VPC",
        "identity": identity,
        "identityProperty": "EC2.VPC.VpcId",
        "properties": {
            "EC2.VPC.VpcId": {"status": "captured", "value": identity},
            "EC2.VPC.CidrBlock": {"status": "captured", "value": "10.0.0.0/16"},
        },
    }
    value = {
        "version": 3,
        "modelFormat": 2,
        "snapshotVersion": 2,
        "referenceMeaningVersion": 1,
        "task": "tasks/import.md",
        "root": str(snapshot.scope.root),
        "scope": [
            snapshot.scope.environment,
            snapshot.scope.target,
            snapshot.scope.service,
        ],
        "sources": {},
        "connection": {},
        "acquiredAt": datetime.now(timezone.utc).isoformat(),
        "records": [record],
        "inventory": {"EC2.VPC": {"status": "complete"}},
    }
    decision = {
        "record": record["record"],
        "resource": resource,
        "action": action,
        "reason": "合成 fixture の明示的選択",
        "basis": ["EC2.VPC.VpcId"],
    }
    if action in {"bind", "replace"}:
        decision["before"] = {
            "identity": None if action == "bind" else "vpc-original",
            "model": document_sha256(
                operation_values(snapshot.authoritative, resource)
            ),
        }
    return value, {"resources": [decision], "excluded": [], "unreflected": []}


def role_operation_fixture(root):
    Scope = _imports_model_sources.Scope
    root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "environment": "qa-synthetic",
                        "alias": "team-a",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    scope = Scope(root, "qa-synthetic", "team-a", "iam")
    values = {
        "desired.service.iam.serviceId": "iam",
        "desired.service.iam.ownedCatalogResourceTypes": "IAM.Role",
        "display.service.title": "# 合成 IAM Role",
        "desired.service.identity.lastAllocated": '{"IAM.Role":9}',
    }
    for rid, name in [("007", "source"), ("008", "destination"), ("009", "unrelated")]:
        values.update(
            {
                f"desired.resource.{rid}.resourceType": "IAM.Role",
                f"desired.resource.{rid}.resourceMode": "IMPORT",
                f"desired.resource.{rid}.logicalId": "IAM_Role_" + rid,
                f"desired.resource.{rid}.anchor": "role-" + name,
                f"display.resource.{rid}.comment": name,
                f"desired.row.{rid}-001.property": "IAM.Role.RoleName",
                f"desired.row.{rid}-001.value": f"[role](#role-{name})",
                f"desired.row.{rid}-001.comment": name + " identity",
                f"observed.row.{rid}-001.value": "`role-" + name + "`",
                f"desired.row.{rid}-002.property": "IAM.Role.AssumeRolePolicyDocument",
                f"desired.row.{rid}-002.value": f"[Policy](iam/{name}.json)",
                f"desired.row.{rid}-002.comment": name + " policy",
                f"desired.row.{rid}-002.document": json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Action": "sts:AssumeRole",
                                "Principal": {"AWS": f"[role](#role-{name})"},
                                "Condition": {"Bool": {"aws:SecureTransport": True}},
                                "fixture-order": [1, "1", False],
                            }
                        ],
                    }
                ),
            }
        )
    scope.path.parent.mkdir(parents=True)
    scope.path.write_text(serialize(values), encoding="utf-8")
    dependency_index.rebuild(root)
    return scope, values


def retarget_fixture(root):
    Scope = _imports_model_sources.Scope
    root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "environment": "qa-synthetic",
                        "alias": alias,
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                    for alias in ("team-a", "team-b")
                ]
            }
        ),
        encoding="utf-8",
    )
    producer = Scope(root, "qa-synthetic", "team-a", "network")
    values = {"desired.service.identity.lastAllocated": '{"EC2.VPC":8}'}
    for rid, name in [("007", "source"), ("008", "destination")]:
        values.update(
            {
                f"desired.resource.{rid}.resourceType": "EC2.VPC",
                f"desired.resource.{rid}.resourceMode": "IMPORT",
                f"desired.resource.{rid}.logicalId": "EC2_VPC_" + rid,
                f"desired.resource.{rid}.anchor": "vpc-" + name,
                f"desired.row.{rid}-001.property": "EC2.VPC.VpcId",
                f"desired.row.{rid}-001.value": f"[vpc](#vpc-{name})",
                f"desired.row.{rid}-001.comment": "合成 ID",
                f"observed.row.{rid}-001.value": "vpc-" + name,
            }
        )
    producer.path.parent.mkdir(parents=True)
    producer.path.write_text(serialize(values), encoding="utf-8")
    consumer = Scope(root, producer.environment, producer.target, "security-group")
    values = {
        "desired.resource.001.resourceType": "EC2.SecurityGroup",
        "desired.resource.001.resourceMode": "CREATE",
        "desired.resource.001.logicalId": "EC2_SecurityGroup_001",
        "desired.service.identity.lastAllocated": '{"EC2.SecurityGroup":1}',
        "desired.row.001-001.property": "EC2.SecurityGroup.VpcId",
        "desired.row.001-001.value": "qa-synthetic:123456789012:vpc-source",
        "desired.row.001-001.comment": "合成参照",
    }
    resource = {
        "consumerKey": "desired.row.001-001.value",
        "text": "vpc-source",
        "occurrence": "1",
        "producerKind": "resource",
        "producerScope": "qa-synthetic/team-a/network",
        "producerLogicalId": "EC2_VPC_007",
        "resourceType": "EC2.VPC",
        "format": "identifier",
        "property": "EC2.VPC.VpcId",
        "labelPolicy": "none",
    }
    context = {
        "consumerKey": "desired.row.001-001.value",
        "text": "123456789012",
        "occurrence": "1",
        "producerKind": "context",
        "producerScope": "qa-synthetic/team-a",
        "format": "literal",
        "labelPolicy": "none",
        "contextProperty": "executionAccountId",
    }
    for identity, spec in [("resource-use", resource), ("context-use", context)]:
        values.update(
            {
                f"desired.reference.{identity}.{field}": value
                for field, value in spec.items()
            }
        )
    consumer.path.write_text(serialize(values), encoding="utf-8")
    dependency_index.rebuild(root)
    return consumer, values


def value_snapshot(values, provenance=None, files=None):
    """Minimal reader result for pure value-verifier tests; source guards use real snapshots."""

    runtime_values = _imports_model_sources.runtime_values
    if provenance:
        raise ValueError(
            "test fixture requires explicit reference metadata, not template provenance"
        )
    return SimpleNamespace(
        authoritative=dict(values),
        values=runtime_values(values),
        files=files or {},
        warnings=(),
    )


def _callback_import_publication_case_fail_407(
    finish, /, root, model=None, markdown=None
):
    if model is not None:
        finish(root, model, markdown)
        raise ValueError("injected receipt failure")
    return finish(root, model, markdown)


def _callback_import_publication_case_race(
    state, candidate, failure, original, original_outputs, path, /, *args, **kwargs
):
    result = original_outputs(*args, **kwargs)
    if not state.injected:
        state.injected = True
        if failure == "post-candidate":
            candidate.write_bytes(candidate.read_bytes() + b"# changed candidate\n")
        else:
            path.write_bytes(original + b"# external source edit\n")
    return result


def import_publication_case(monkeypatch, failure, *, workspace=None):
    _state_import_publication_case_250 = _CallbackState()
    pytest = _imports_pytest
    parse = _imports_model_format.parse
    patch = _imports_model_format.patch
    cli = _imports_model_importing_cli
    load_model = _imports_model_sources.load_model
    publication_workspace = (
        _imports_support_import_repository_fixtures.publication_workspace
    )
    LogsCli = _imports_support_model_v2_fixtures.LogsCli
    import_contract = _imports_support_model_v2_fixtures.import_contract
    logs_fixture = _imports_support_model_v2_fixtures.logs_fixture
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    with (
        (workspace or publication_workspace)() as (root, begin, advance),
        ExitStack() as selection_scope,
    ):
        model = logs_fixture(root)
        relative = model.relative_to(root)
        target, state = begin(root, relative)
        selection_scope.enter_context(selected_task(target, state["task_file"]))
        (target / state["task_file"]).write_text(
            import_contract(state["task_file"], relative), encoding="utf-8"
        )
        path = target / relative
        original = path.read_bytes()
        aws = LogsCli()

        result = cli.acquire(
            target,
            "qa-synthetic",
            "cloudwatch-logs",
            "team-a",
            cli_runner=aws,
            resource_types=["Logs.LogGroup"],
        )
        evidence = Path(result["evidence"])
        assert result["status"] == "acquired" and len(result["records"]) == 1, result
        record = result["records"][0]
        candidate = evidence.parent / "candidates" / relative
        candidate.parent.mkdir(parents=True)
        changes = {
            "desired.row.001-002.value": "`90`",
            "desired.row.001-003.value": "`true`",
        }
        chosen = {
            "record": record["record"],
            "resource": "001",
            "action": "refresh",
            "reason": "合成の明示的な対応選択",
            "basis": ["Logs.LogGroup.LogGroupName"],
        }
        candidate.write_text(
            patch(parse(original.decode("utf-8")), changes), encoding="utf-8"
        )
        (evidence.parent / "selection.json").write_text(
            json.dumps({"resources": [chosen], "excluded": [], "unreflected": []}),
            encoding="utf-8",
        )
        (evidence.parent / "review-input.json").write_text(
            json.dumps({"risks": {record["record"]: []}}), encoding="utf-8"
        )
        reviewed = cli.review_acquisition(
            target, "qa-synthetic", "cloudwatch-logs", evidence, "team-a"
        )
        assert reviewed["status"] == "reviewed" and path.read_bytes() == original
        calls = list(aws.calls)
        if failure == "review":
            file = evidence.parent / "review.json"
            changed = json.loads(file.read_text(encoding="utf-8"))
            changed["dispositions"][0]["risks"] = ["changed review"]
            file.write_text(json.dumps(changed), encoding="utf-8")
        elif failure == "head":
            advance(target)
        if failure in {"head", "review"}:
            with pytest.raises(ValueError, match="changed|stale|ancestor|worktree"):
                cli.publish_acquisition(
                    target, "qa-synthetic", "cloudwatch-logs", evidence, "team-a"
                )
            assert path.read_bytes() == original
            proof_path = _imports_import_guard.proof_path
            assert not proof_path(target).exists()
            assert aws.calls == calls
            return
        if failure.endswith("-crash"):
            program = "import sys,os\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom task_contract import selected_task\nfrom model.importing import cli\nimport sync_files\nroot,name,path,evidence=Path(sys.argv[2]),sys.argv[3],Path(sys.argv[4]),Path(sys.argv[5])\nmode=sys.argv[6]\nif mode=='receipt-crash':\n    original=cli.record_import\n    def crash(*args,**kwargs):\n        original(*args,**kwargs)\n        os._exit(17)\n    cli.record_import=crash\nelse:\n    original=sync_files.save_files\n    def crash(outputs):\n        selected=path if mode=='source-crash' else next((p for p in outputs if p.suffix=='.md'),None)\n        if selected in outputs:\n            selected.parent.mkdir(parents=True,exist_ok=True)\n            selected.write_bytes(b'partial child bytes')\n            os._exit(17)\n        return original(outputs)\n    sync_files.save_files=crash\nwith selected_task(root,name):\n    cli.publish_acquisition(root,'qa-synthetic','cloudwatch-logs',evidence,'team-a')\nraise AssertionError('injected crash did not execute')\n"
            crashed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    program,
                    str(FRAMEWORK / "framework/scripts"),
                    str(target),
                    state["task_file"],
                    str(path),
                    str(evidence),
                    failure,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            assert crashed.returncode == 17, crashed.stdout + crashed.stderr
            proof_path = _imports_import_guard.proof_path
            assert proof_path(target).is_file()
            with pytest.raises(ValueError, match="pending Model publication"):
                load_model(path)
            assert (
                cli.recover_transaction(
                    target, "qa-synthetic", "cloudwatch-logs", evidence, "team-a"
                )["status"]
                == "recovered"
            )
            if failure == "display-crash":
                assert path.read_bytes() == candidate.read_bytes()
                assert (
                    cli.recover_display(
                        target, "qa-synthetic", "cloudwatch-logs", "team-a"
                    )["status"]
                    == "complete"
                )
            else:
                assert path.read_bytes() == original and not proof_path(target).exists()
                assert (
                    cli.publish_acquisition(
                        target, "qa-synthetic", "cloudwatch-logs", evidence, "team-a"
                    )["status"]
                    == "complete"
                )
            assert aws.calls == calls
            assert (root / relative).read_bytes() == original
            return
        with monkeypatch.context() as injection:
            if failure.startswith("post-"):
                original_outputs = cli.record_outputs
                _state_import_publication_case_250.injected = False
                race = _bind_framework_callback(
                    _callback_import_publication_case_race,
                    _state_import_publication_case_250,
                    candidate,
                    failure,
                    original,
                    original_outputs,
                    path,
                )
                injection.setattr(cli, "record_outputs", race)
            if failure == "receipt":
                finish = cli.finish_import
                fail = _bind_framework_callback(
                    _callback_import_publication_case_fail_407, finish
                )
                injection.setattr(cli, "finish_import", fail)
            if failure == "receipt" or failure.startswith("post-"):
                with pytest.raises((OSError, ValueError)):
                    cli.publish_acquisition(
                        target, "qa-synthetic", "cloudwatch-logs", evidence, "team-a"
                    )
                assert path.read_bytes() == original + (
                    b"# external source edit\n" if failure == "post-baseline" else b""
                )
                proof_path = _imports_import_guard.proof_path
                assert not proof_path(target).exists()
                assert aws.calls == calls
                return
            if failure == "subprocess":
                command = [
                    sys.executable,
                    "-I",
                    "-B",
                    str(FRAMEWORK / "framework/scripts/model/cli.py"),
                    "import",
                    "publish",
                    "--repository-root",
                    str(target),
                    "--environment",
                    "qa-synthetic",
                    "--target",
                    "team-a",
                    "--service",
                    "cloudwatch-logs",
                    "--evidence",
                    str(evidence),
                    "--task-file",
                    state["task_file"],
                ]
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    env={
                        key: value
                        for key, value in os.environ.items()
                        if key not in {"PYTHONPATH", "BLUEPRINT_TASK_FILE"}
                    },
                )
                assert completed.returncode == 0, completed.stdout + completed.stderr
                published = json.loads(completed.stdout)
            else:
                published = cli.publish_acquisition(
                    target, "qa-synthetic", "cloudwatch-logs", evidence, "team-a"
                )
        assert published["model"] == "reflected", published
        assert published["status"] == "complete", published
        assert path.read_bytes() == candidate.read_bytes()
        assert aws.calls == calls
        assert (
            target / "docs/designs/qa-synthetic/team-a/cloudwatch-logs.md"
        ).is_file()
        assert (root / relative).read_bytes() == original


def properties_fixture(root):
    Scope = _imports_model_sources.Scope
    scope = Scope(root, "qa-synthetic", "team-a", "network")
    (root / "project.json").write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "environment": scope.environment,
                        "alias": scope.target,
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    scope.path.parent.mkdir(parents=True)
    scope.path.write_text(
        serialize(
            {
                "desired.resource.007.resourceType": "EC2.VPC",
                "desired.resource.007.logicalId": "EC2_VPC_001",
                "desired.resource.007.anchor": "network-existing",
                "desired.resource.007.cfn-logicalId": "fixture-OriginalVpc",
                "desired.service.identity.lastAllocated": '{"EC2.VPC":1}',
                "desired.resource.007.resourceMode": "IMPORT",
                "desired.row.007-001.property": "EC2.VPC.VpcId",
                "desired.row.007-001.value": "[vpc](#network-existing)",
                "desired.row.007-001.comment": "合成 ID",
                "observed.row.007-001.value": "vpc-original",
            }
        ),
        encoding="utf-8",
    )
    return scope


def deploy_properties_fixture(root):
    serialize = _imports_model_format.serialize
    scope = properties_fixture(root)
    stacks = scope.path.with_name("cloudformation-stacks.properties")
    stacks.write_text(
        serialize(
            {
                "desired.stack.009.name": "CurrentName",
                "desired.stack.009.placementName": "FixedPlacement",
                "desired.stack.009.template": "stack.yaml",
                "desired.stack.009.parameters": "stack.json",
                "desired.stack.009.deployOrder": "1",
            }
        ),
        encoding="utf-8",
    )
    tasks = root / "tasks"
    tasks.mkdir()
    (tasks / "active.md").write_text(
        """# Deploy fixture
## Task contract
- Task type: `infrastructure`
- Task status: `running`
## Validation scope
- `qa-synthetic/team-a/network`
## Modified files
- `tasks/active.md`
## Allowed paths
- `tasks/active.md`
""",
        encoding="utf-8",
    )
    return scope, stacks
