"""Changed rule selection and zero Full-validation calls on synthetic Models."""

import hashlib
import json
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import design.policy_tables as policy_tables
import import_guard
import pytest
import sync_runtime
from generation_inputs import GenerationInputs
from issues.runner import mechanical
from model.format import serialize
from model.importing.scope import read_consumers, restrict
from model.operations import prepare_edit, publish_edit
from model.render import generate_files
from support.import_model_fixtures import service_values
from support.producer_identifier_reference_fixtures import resource, setup, write_model
from support.pytest_cli import run
from sync_files import save_files
from task_contract_core import selected_task, start
from validation import change
from validation.runner import Validator, run_validation

from model import change_plan, dependency_index, sources, validation

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def snapshot(root, values, service="logs"):
    path = root / "model/preview/team" / (service + ".properties")
    return SimpleNamespace(
        scope=sources.scope_for(path), authoritative=values, files={}
    )


def logs(number="001", retention="7"):
    return resource(
        number,
        "Logs.LogGroup",
        "logs-" + number,
        [("LogGroupName", "fixture-" + number), ("RetentionInDays", retention)],
    )


def evaluate(root, before, after, service="logs"):
    setup(root, [service], [])
    old, new = snapshot(root, before, service), snapshot(root, after, service)
    selected = change_plan.compare(old, new)
    with patch.object(
        validation,
        "check_model_inputs",
        side_effect=AssertionError("Full Validation called"),
    ) as full:
        result = validation.check_change_inputs(new.scope.path, after, root, selected)
        full.assert_not_called()
    return result


@pytest.mark.parametrize(
    "old,new,valid",
    [("bad", "7", True), ("bad", "also-bad", False), ("7", "bad", False)],
)
def check_changed_value(project_workspace, old, new, valid):
    result = evaluate(project_workspace, logs(retention=old), logs(retention=new))
    assert (not result.errors) == valid, result.errors


def check_unrelated_property_and_resource(project_workspace):
    before = {**logs(retention="bad"), **logs("002", "bad")}
    after = dict(before, **{"desired.row.001-001.value": "changed-name"})
    result = evaluate(project_workspace, before, after)
    assert not result.errors, result.errors
    full = validation.check_model_inputs(
        snapshot(project_workspace, after).scope.path, after, project_workspace
    )
    assert full.errors  # Full still reports the old errors.


def check_new_resource_requires_fields(project_workspace):
    before = logs()
    after = {
        **before,
        **resource("002", "Logs.LogGroup", "new", [("RetentionInDays", "7")]),
    }
    result = evaluate(project_workspace, before, after)
    # LogGroupName is optional in AWS; use a resource with a required provider field.
    assert not result.errors, result.errors
    after = {
        **before,
        **resource("003", "S3.BucketPolicy", "policy", [("Bucket", "fixture")]),
    }
    result = evaluate(project_workspace, before, after)
    assert any(
        "required provider schema property missing" in error for error in result.errors
    ), result.errors


def check_deleted_required_field(project_workspace):
    before = resource(
        "001",
        "S3.BucketPolicy",
        "policy",
        [
            ("Bucket", "fixture"),
            ("PolicyDocument", '`{"Version":"2012-10-17","Statement":[]}`'),
        ],
    )
    after = {
        key: value
        for key, value in before.items()
        if not key.startswith("desired.row.001-002.")
    }
    result = evaluate(project_workspace, before, after)
    assert any("PolicyDocument" in error for error in result.errors), result.errors


def check_row_renumbering(project_workspace):
    before = logs()
    after = {key.replace("001-001", "001-009"): value for key, value in before.items()}
    selected = change_plan.compare(
        snapshot(project_workspace, before), snapshot(project_workspace, after)
    )
    assert not selected.rows and not selected.properties


def check_save_delegates_without_full(project_workspace):
    setup(project_workspace, ["logs"], [])
    before = logs(retention="bad")
    after = dict(before, **{"desired.row.001-001.value": "changed-name"})
    path = project_workspace / "model/preview/team/logs.properties"
    write_model(path, before)
    old = sources.raw_model(path)
    new = sources.raw_model(
        path, sources.CandidateReads(sources.FileReads(), {path: serialize(after)})
    )
    with patch.object(
        validation,
        "check_model_inputs",
        side_effect=AssertionError("Full Validation called"),
    ) as full:
        change.validate_save(old, new, sources.FileReads())
        full.assert_not_called()


@pytest.mark.parametrize("action", ["import", "edit"])
@pytest.mark.parametrize(
    "case,error",
    [
        ("name-pending", "Name"),
        ("plaintext-link", "PLAINTEXT"),
        ("dependent-plaintext", "PLAINTEXT"),
        ("json-reference", "modelRef"),
        ("missing-producer", "producer"),
        ("name", None),
        ("environment-pending", None),
        ("unrelated-error", None),
        ("unrelated-reference", None),
        ("comment", None),
        ("warning", None),
    ],
)
def check_prepare_save_change_validation(project_workspace, action, case, error):
    root = project_workspace
    setup(root, ["codebuild"], ["CodeBuild.Project"])
    before = resource(
        "001",
        "CodeBuild.Project",
        "build",
        [
            ("Name", "fixture-build"),
            ("Description", "before"),
            ("Environment.EnvironmentVariables[].Name", "SETTING"),
            ("Environment.EnvironmentVariables[].Type", "PLAINTEXT"),
            ("Environment.EnvironmentVariables[].Value", "fixed"),
            ("ServiceRole", "arn:aws:iam::111111111111:role/build"),
        ],
    )
    if case == "unrelated-error":
        before.update(
            resource("002", "CodeBuild.Project", "old", [("Name", "PENDING_DEPLOY")])
        )
    if case == "unrelated-reference":
        before["desired.row.001-006.value"] = "[absent](iam.md#absent)"
    if case == "dependent-plaintext":
        before["desired.row.001-004.value"] = "PARAMETER_STORE"
        before["desired.row.001-005.value"] = "[absent](ssm.md#absent)"
    after = dict(before)
    if case == "name-pending":
        after["desired.row.001-001.value"] = "PENDING_DEPLOY"
    elif case == "plaintext-link":
        after["desired.row.001-005.value"] = "[absent](ssm.md#absent)"
    elif case == "dependent-plaintext":
        after["desired.row.001-004.value"] = "PLAINTEXT"
    elif case == "json-reference":
        after["desired.row.001-006.value"] = '`{"$modelRef":{"attribute":"Arn"}}`'
    elif case == "missing-producer":
        after["desired.row.001-006.value"] = "[absent](iam.md#absent)"
    elif case == "environment-pending":
        after["desired.row.001-005.value"] = "PENDING_DEPLOY"
    elif case == "warning":
        after["desired.row.001-006.value"] = '`{"Fn::ImportValue":"UnknownRole"}`'
    elif case == "comment":
        after["desired.row.001-001.comment"] = "説明のみ変更"
    else:
        after["desired.row.001-001.value"] = "updated-build"
    path = root / "model/preview/team/codebuild.properties"
    write_model(path, before)
    original = path.read_bytes()
    with (
        restrict(("preview", "team", "codebuild") if action == "import" else None),
        read_consumers({("preview", "team", "codebuild")}),
        closing(GenerationInputs(root)) as reads,
        patch.object(
            validation, "check_model_inputs", side_effect=AssertionError("Full called")
        ),
        patch.object(
            validation,
            "_check_model_inputs",
            side_effect=AssertionError("Full internal called"),
        ),
        patch.object(change, "validate_save", wraps=change.validate_save) as shared,
        patch.object(import_guard, "require_import_changes"),
    ):
        context = sources.SourceWriteContext._authorized(
            root,
            reads,
            SimpleNamespace(action=action),
            lambda changes: None,
            frozenset({path}),
        )
        try:
            if error:
                with pytest.raises(ValueError, match=error):
                    prepare_edit(path, {path: serialize(after)}, context)
                assert path.read_bytes() == original
            else:
                plan = prepare_edit(path, {path: serialize(after)}, context)
                assert publish_edit(plan, context) == (path,)
                assert sources.raw_model(path).authoritative == after
                if case == "warning":
                    assert any(
                        w["code"] == "json.intrinsic.unresolved"
                        for w in plan.candidate.warnings
                    )
            shared.assert_called_once()
        finally:
            context.close()


@pytest.mark.parametrize("action", ["import", "edit"])
@pytest.mark.parametrize("case", ["add", "broken-contract"])
def check_prepare_save_resource_contracts(project_workspace, action, case):
    root = project_workspace
    setup(
        root,
        ["s3", "lambda", "logs"],
        ["S3.Bucket", "Lambda.Function", "Logs.LogGroup"],
    )
    path = root / "model/preview/team/s3.properties"
    before = resource("001", "S3.Bucket", "bucket", [("BucketName", "fixture-bucket")])
    write_model(path, before)
    write_model(
        path.with_name("lambda.properties"),
        resource(
            "001",
            "Lambda.Function",
            "consumer",
            [("Code.S3Bucket", "[bucket](s3.md#bucket)")],
        ),
    )
    after = dict(before)
    if case == "add":
        path = path.with_name("logs.properties")
        before = {}
        after = logs()
        write_model(path, before)
    else:
        after = {
            key: value
            for key, value in before.items()
            if key.startswith("desired.service.")
        }
    original = path.read_bytes()
    identity = "preview", "team", path.stem
    with (
        restrict(identity if action == "import" else None),
        read_consumers({identity}),
        closing(GenerationInputs(root)) as reads,
        patch.object(
            validation, "check_model_inputs", side_effect=AssertionError("Full called")
        ),
        patch.object(
            validation,
            "_check_model_inputs",
            side_effect=AssertionError("Full internal called"),
        ),
        patch.object(import_guard, "require_import_changes"),
    ):
        context = sources.SourceWriteContext._authorized(
            root,
            reads,
            SimpleNamespace(action=action),
            lambda changes: None,
            frozenset({path}),
        )
        try:
            if case == "broken-contract":
                with pytest.raises(ValueError, match="BucketName|producer"):
                    prepare_edit(path, {path: serialize(after)}, context)
                assert path.read_bytes() == original
            else:
                plan = prepare_edit(path, {path: serialize(after)}, context)
                assert publish_edit(plan, context) == (path,)
        finally:
            context.close()


@pytest.mark.parametrize(
    "prop,value,valid",
    [
        ("EventSelectors[].IncludeManagementEvents", "`[true,false]`", True),
        ("EventSelectors[].IncludeManagementEvents", '`[true,"false"]`', False),
        ("EventSelectors[].ReadWriteType", '`["All","ReadOnly"]`', True),
        ("EventSelectors[].ReadWriteType", '`["All","bad"]`', False),
        ("EventSelectors[].DataResources[].Type", '`[["AWS::S3::Object"]]`', True),
        ("EventSelectors[].DataResources[].Values", '`[[["arn:aws:s3"]]]`', True),
    ],
)
def check_changed_column_array(project_workspace, prop, value, valid):
    before = resource("001", "CloudTrail.Trail", "trail", [("Name", "fixture-trail")])
    after = dict(before)
    after.update(
        {
            "desired.row.001-002.property": "CloudTrail.Trail." + prop,
            "desired.row.001-002.value": value,
            "desired.row.001-002.comment": "取得した配列",
        }
    )
    result = evaluate(project_workspace, before, after, "cloudtrail")
    assert (not result.errors) == valid, result.errors


@pytest.mark.parametrize(
    "producer_service,consumer_service,kind,field",
    [
        ("iam", "codebuild", "IAM.Role", "RoleName"),
        ("s3", "lambda", "S3.Bucket", "BucketName"),
    ],
)
def check_indexed_incoming_contract(
    project_workspace, producer_service, consumer_service, kind, field
):
    setup(project_workspace, [producer_service, consumer_service], [kind])
    producer = (
        project_workspace / "model/preview/team" / (producer_service + ".properties")
    )
    values = resource(
        "001", kind, "producer", [(field, "fixture"), ("Description", "old")]
    )
    write_model(producer, values)
    consumer = producer.with_name(consumer_service + ".properties")
    receiving = resource(
        "002",
        "Lambda.Function",
        "consumer",
        [
            (
                "Role",
                '`{"$modelRef":{"logicalId":"'
                + kind.replace(".", "_")
                + '_001","attribute":"Arn"}}`',
            ),
            ("Timeout", "bad"),
        ],
    )
    write_model(consumer, receiving)
    dependency_index.rebuild(project_workspace)
    old_root = project_workspace / "old"
    setup(old_root, [producer_service], [kind])
    write_model(old_root / producer.relative_to(project_workspace), values)
    write_model(producer, dict(values, **{"desired.row.001-002.value": "new"}))
    with patch.object(
        validation,
        "check_model_inputs",
        side_effect=AssertionError("Full Validation called"),
    ) as full:
        plan = change_plan.assemble(
            project_workspace,
            {("preview", "team", producer_service)},
            old_root,
            sources.FileReads(),
        )
        assert ("preview", "team", consumer_service) not in plan.views
        full.assert_not_called()
    producer.unlink()
    plan = change_plan.assemble(
        project_workspace,
        {("preview", "team", producer_service)},
        old_root,
        sources.FileReads(),
    )
    findings = change.validate_plan(project_workspace, plan)
    assert findings.errors


def check_missing_before_is_explicit(project_workspace):
    setup(project_workspace, ["logs"], [])
    write_model(project_workspace / "model/preview/team/logs.properties", logs())
    with pytest.raises(ValueError, match="before snapshot"):
        change_plan.assemble(
            project_workspace, {("preview", "team", "logs")}, None, sources.FileReads()
        )


def check_reference_value_reads_only_required_property(project_workspace):
    setup(project_workspace, ["s3"], ["S3.Bucket"])
    values = {
        **resource(
            "001",
            "S3.Bucket",
            "producer",
            [
                ("BucketName", "fixture-data"),
                ("VersioningConfiguration.Status", "PENDING_DEPLOY"),
            ],
        ),
        **resource("002", "S3.Bucket", "consumer", [("BucketName", "fixture-logs")]),
    }
    path = project_workspace / "model/preview/team/s3.properties"
    write_model(path, values)
    dependency_index.rebuild(project_workspace)
    old = sources.raw_model(path)
    candidate = dict(values)
    candidate.update(
        {
            "desired.row.002-002.property": "S3.Bucket.LoggingConfiguration.DestinationBucketName",
            "desired.row.002-002.value": '`{"$modelRef":{"logicalId":"S3_Bucket_001","attribute":"BucketName"}}`',
            "desired.row.002-002.comment": "ログ出力先",
        }
    )
    reads = sources.CandidateReads(sources.FileReads(), {path: serialize(candidate)})
    after = sources.raw_model(path, reads)
    with patch.object(
        validation, "check_model_inputs", side_effect=AssertionError("Full called")
    ) as full:
        change.validate_save(old, after, reads)
        full.assert_not_called()
    invalid = dict(candidate, **{"desired.row.001-001.value": "Invalid Bucket Name"})
    reads = sources.CandidateReads(sources.FileReads(), {path: serialize(invalid)})
    with pytest.raises(ValueError):
        change.validate_save(old, sources.raw_model(path, reads), reads)


@pytest.mark.parametrize("typed", [False, True])
def check_new_link_missing_target(project_workspace, typed):
    setup(project_workspace, ["s3"], ["S3.Bucket"])
    path = project_workspace / "model/preview/team/s3.properties"
    before = resource("001", "S3.Bucket", "consumer", [("BucketName", "fixture-logs")])
    write_model(path, before)
    dependency_index.rebuild(project_workspace)
    candidate = {
        **before,
        "desired.row.001-002.property": "S3.Bucket.LoggingConfiguration.DestinationBucketName",
        "desired.row.001-002.value": '`{"$modelRef":{"logicalId":"S3_Bucket_999","attribute":"BucketName"}}`'
        if typed
        else "[missing](s3.md#missing)",
        "desired.row.001-002.comment": "出力先",
    }
    reads = sources.CandidateReads(sources.FileReads(), {path: serialize(candidate)})
    with patch.object(
        validation, "check_model_inputs", side_effect=AssertionError("Full called")
    ) as full:
        with pytest.raises(ValueError):
            change.validate_save(
                sources.raw_model(path), sources.raw_model(path, reads), reads
            )
        full.assert_not_called()


def check_context_change_revalidates_dependent_value(project_workspace):
    before = resource(
        "001",
        "CodeBuild.Project",
        "build",
        [
            ("Name", "fixture"),
            ("Environment.EnvironmentVariables[].Name", "SECRET"),
            ("Environment.EnvironmentVariables[].Type", "SECRETS_MANAGER"),
            ("Environment.EnvironmentVariables[].Value", "PENDING_DEPLOY"),
        ],
    )
    after = dict(before, **{"desired.row.001-003.value": "PLAINTEXT"})
    selected = change_plan.compare(
        snapshot(project_workspace, before), snapshot(project_workspace, after)
    )
    assert "001-004" in selected.rows


def valid_project(root):
    path = root / "project.json"
    document = json.loads(path.read_text())
    document["projectName"] = "fixture"
    document["targets"].append(
        {**document["targets"][0], "alias": "other", "awsAccountId": "222222222222"}
    )
    document["targets"].sort(
        key=lambda target: (target["environment"], target["alias"])
    )
    path.write_text(json.dumps(document, indent=2) + "\n")


def check_generation_and_task_checks_never_call_full(project_workspace):
    root = project_workspace
    setup(root, ["logs"], ["Logs.LogGroup"])
    valid_project(root)
    path = root / "model/preview/team/logs.properties"
    before = {**logs(retention="bad"), **service_values("logs", ["Logs.LogGroup"])}
    after = dict(before, **{"desired.row.001-001.value": "changed-name"})
    write_model(path, after)
    view = root / "docs/designs/preview/team/logs.md"
    save_files(generate_files(view, after, root))
    new = sources.raw_model(path)
    selected = change_plan.compare(snapshot(root, before), new)
    plan = change_plan.ChangePlan(
        changes={("preview", "team", "logs"): selected},
        views={("preview", "team", "logs")},
        reads=sources.FileReads(),
    )
    with (
        patch.object(
            validation, "check_model_inputs", side_effect=AssertionError("Full called")
        ) as full,
        patch.object(
            validation,
            "_check_model_inputs",
            side_effect=AssertionError("Full internal called"),
        ) as internal,
    ):
        generator = sync_runtime.prepare_generation(root, plan.views, write=False)
        try:
            sync_runtime.validate_generation(generator, write=False)
            assert generator.generated and not generator.failures, generator.failures
        finally:
            generator.close()
        validator = Validator(root, plan.views, model_validation="change")
        validator.change_plan = plan
        validator.check_changed_designs()
        assert not validator.errors, validator.errors
        full.assert_not_called()
        internal.assert_not_called()


@pytest.mark.parametrize("final", [False, True])
def check_runner_selects_change_for_task_and_final(project_workspace, final):
    root = project_workspace
    name = "tasks/change.md"
    contract = root / name
    contract.parent.mkdir()
    contract.write_text(
        "## Task contract\n- Task type: `design`\n- Task status: `running`\n## Modified files\n- `tasks/change.md`\n## Allowed paths\n- `tasks/change.md`\n## Validation scope\n- `preview/team/logs`\n"
    )
    scope = frozenset({("preview", "team", "logs")})
    candidate = (
        SimpleNamespace(
            root=root,
            task_file=name,
            scope=scope,
            definitions_root=Path(__file__).resolve().parents[4],
        )
        if final
        else None
    )
    options = SimpleNamespace(
        task_file=name,
        write=False,
        all=False,
        fresh=True,
        jobs=1,
        repository_wide_iac=False,
        contract_scope=False,
    )
    with (
        patch.object(Validator, "run", return_value=0),
        patch(
            "validation.runner._imports_deploy_inputs.task_deployment_input_paths",
            return_value=[],
        ),
        patch.object(
            validation, "check_model_inputs", side_effect=AssertionError("Full called")
        ) as full,
    ):
        result = run_validation(root, options, final_candidate=candidate)
        assert result.model_validation == "change"
        full.assert_not_called()


def check_issue_scan_explicitly_keeps_full(project_workspace):
    root = project_workspace
    setup(root, ["logs"], ["Logs.LogGroup"])
    valid_project(root)
    path = root / "model/preview/team/logs.properties"
    values = {**logs(retention="bad"), **service_values("logs", ["Logs.LogGroup"])}
    write_model(path, values)
    view = root / "docs/designs/preview/team/logs.md"
    save_files(generate_files(view, values, root))
    with (
        patch(
            "import_guard.changed_sources",
            side_effect=AssertionError("Issue Scan must not inspect Git differences"),
        ),
        patch.object(
            validation, "check_model_inputs", wraps=validation.check_model_inputs
        ) as full,
    ):
        errors, _, _ = mechanical(root, {("preview", "team", "logs")}, jobs=1)
        assert errors and full.call_count > 0


def check_nested_changed_schema_value(project_workspace):
    before = resource(
        "001",
        "S3.Bucket",
        "bucket",
        [
            ("BucketName", "fixture-data"),
            ("VersioningConfiguration", '`{"Status":"Enabled"}`'),
        ],
    )
    after = dict(before, **{"desired.row.001-002.value": '`{"Status":"invalid"}`'})
    result = evaluate(project_workspace, before, after, "s3")
    assert result.errors


def check_partial_view_generation_is_not_task_pass(project_workspace):
    root = project_workspace
    setup(root, ["logs"], ["Logs.LogGroup"])
    path = root / "model/preview/team/logs.properties"
    before, after = logs(), logs(retention="14")
    write_model(path, after)
    item = change_plan.compare(snapshot(root, before), sources.raw_model(path))
    scope = {("preview", "team", "logs")}
    plan = change_plan.ChangePlan(
        changes={next(iter(scope)): item}, views=scope, reads=sources.FileReads()
    )
    validator = Validator(root, scope, model_validation="change")
    validator.change_plan = plan
    with patch.object(
        Validator,
        "_check_generated_service_models",
        return_value={
            "complete": False,
            "status": "NOT_RUN",
            "unverified": [{"reason": "reference", "status": "NOT_RUN"}],
        },
    ):
        validator.check_changed_designs()
    assert validator.findings.status == "NOT_RUN" and validator.report() != 0


def check_stage_does_not_load_unaffected_incoming_peer(project_workspace):
    root = project_workspace
    setup(root, ["logs", "codebuild"], ["Logs.LogGroup"])
    path = root / "model/preview/team/logs.properties"
    values = {**logs(), **service_values("logs", ["Logs.LogGroup"])}
    write_model(path, values)
    view = root / "docs/designs/preview/team/logs.md"
    save_files(generate_files(view, values, root))
    broken = path.with_name("codebuild.properties")
    broken.write_text("invalid unrelated Model\n")
    peer = view.with_name("codebuild.md")
    peer.write_text("# Existing peer\n### Consumer\n[logs](logs.md#logs-001)\n")
    stage = root / "stage"
    stage.mkdir()
    with patch.object(
        sync_runtime, "load_model", wraps=sync_runtime.load_model
    ) as reads:
        sync_runtime.stage_inputs(
            stage, root, {view: values}, [path], [view], ["logs"], True
        )
    assert all(call.args[0] != broken for call in reads.call_args_list)


def check_stale_dependency_metadata_refreshes_without_full(project_workspace):
    root = project_workspace
    setup(root, ["s3", "logs"], ["S3.Bucket"])
    producer = root / "model/preview/team/s3.properties"
    values = resource("001", "S3.Bucket", "bucket", [("BucketName", "fixture-data")])
    write_model(producer, values)
    consumer = producer.with_name("logs.properties")
    write_model(consumer, logs())
    dependency_index.rebuild(root)
    old = root / "old"
    setup(old, ["s3"], ["S3.Bucket"])
    write_model(old / producer.relative_to(root), values)
    consumer.write_text(consumer.read_text() + "# external Model edit\n")
    write_model(producer, dict(values, **{"desired.row.001-001.value": "changed-data"}))
    with patch.object(
        validation, "check_model_inputs", side_effect=AssertionError("Full called")
    ) as full:
        plan = change_plan.assemble(
            root, {("preview", "team", "s3")}, old, sources.FileReads()
        )
        result = change.validate_plan(root, plan)
        assert not result.errors, result.errors
        project = root / "project.json"
        project.write_text(project.read_text().replace("ap-northeast-1", "us-east-1"))
        plan = change_plan.assemble(root, set(), old, sources.FileReads(), context=True)
        assert not plan.contracts
        full.assert_not_called()


def check_api_rule_dependencies_are_selected(project_workspace):
    before = resource(
        "001",
        "Macie.ClassificationJob",
        "job",
        [
            ("name", "fixture-job"),
            ("jobType", "SCHEDULED"),
            ("scheduleFrequency", '`{"dailySchedule":{}}`'),
            ("managedDataIdentifierSelector", "NONE"),
        ],
    )
    after = dict(before, **{"desired.row.001-001.value": "updated-job"})
    result = evaluate(project_workspace, before, after, "macie")
    assert not result.errors, result.errors
    after = dict(before, **{"desired.row.001-002.value": "ONE_TIME"})
    result = evaluate(project_workspace, before, after, "macie")
    assert any("ONE_TIME must omit" in error for error in result.errors), result.errors


def check_generation_does_not_validate_unchanged_policy_quality(project_workspace):
    root = project_workspace
    setup(root, ["iam"], ["IAM.Role"])
    valid_project(root)
    values = {
        **resource(
            "001",
            "IAM.Role",
            "role",
            [
                ("RoleName", "fixture-role"),
                ("AssumeRolePolicyDocument", "[trust](iam/trust.json)"),
                ("Description", "old"),
            ],
        ),
        **service_values("iam", ["IAM.Role"]),
    }
    values["desired.row.001-002.document"] = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "invalid",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
    )
    path = root / "model/preview/team/iam.properties"
    write_model(path, values)
    after = dict(values, **{"desired.row.001-003.value": "new"})
    with (
        patch.object(
            policy_tables,
            "validate_policy_document",
            side_effect=AssertionError("policy quality ran during generation"),
        ) as quality,
        patch.object(
            validation, "check_model_inputs", side_effect=AssertionError("Full called")
        ) as full,
    ):
        selected = change_plan.compare(
            snapshot(root, values, "iam"), snapshot(root, after, "iam")
        )
        findings = validation.check_change_inputs(path, after, root, selected)
        assert not findings.errors, findings.errors
        generated = sync_runtime.prepare_generation(
            root, {("preview", "team", "iam")}, write=False
        )
        try:
            sync_runtime.validate_generation(generated, write=False)
            assert generated.generated and not generated.failures, generated.failures
        finally:
            generated.close()
        quality.assert_not_called()
        full.assert_not_called()
    findings = validation.check_model_inputs(path, values, root)
    assert any("Statement Effect" in error for error in findings.errors), (
        findings.errors
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))


def check_invalid_before_identity_can_be_corrected(project_workspace):
    root = project_workspace
    setup(root, ["logs"], ["Logs.LogGroup"])
    before = {**logs(), **logs("002")}
    before["desired.resource.002.logicalId"] = before["desired.resource.001.logicalId"]
    path = root / "model/preview/team/logs.properties"
    write_model(path, before)
    old = change_plan.comparison_snapshot(sources.edit_base(path, sources.FileReads()))
    after = {**logs(), **logs("002")}
    write_model(path, after)
    new = sources.raw_model(path)
    selected = change_plan.compare(old, new)
    result = change.validate_plan(
        root,
        change_plan.ChangePlan(
            changes={("preview", "team", "logs"): selected}, reads=sources.FileReads()
        ),
    )
    assert not result.errors, result.errors


def check_write_validator_checks_changes_before_generation(project_workspace):
    root = project_workspace
    setup(root, ["logs"], ["Logs.LogGroup"])
    before, after = logs(), logs(retention="invalid")
    write_model(root / "model/preview/team/logs.properties", after)
    current = sources.raw_model(root / "model/preview/team/logs.properties")
    validator = Validator(
        root, {("preview", "team", "logs")}, model_validation="change", write=True
    )
    validator.change_plan = change_plan.ChangePlan(
        changes={
            ("preview", "team", "logs"): change_plan.compare(
                snapshot(root, before), current
            )
        },
        reads=sources.FileReads(),
    )
    with (
        patch.object(
            sync_runtime,
            "prepare_generation",
            side_effect=AssertionError("invalid change reached generation"),
        ),
        patch.object(
            validation, "check_model_inputs", side_effect=AssertionError("Full called")
        ) as full,
    ):
        validator.generate_and_validate(
            SimpleNamespace(
                expected_task=(
                    "tasks/change.md",
                    "## Task contract\n- Task status: `running`\n",
                )
            ),
            {},
        )
        assert validator.errors
        full.assert_not_called()


@pytest.mark.parametrize("workflow", ["update", "import"])
def check_real_final_candidate_guard_never_calls_full(project_workspace, workflow):
    root = project_workspace
    setup(root, ["logs"], ["Logs.LogGroup"])
    path = root / "model/preview/team/logs.properties"
    before = logs(retention="bad")
    write_model(path, before)
    dependency_index.rebuild(root)
    for args in (
        ("init",),
        ("config", "user.name", "Fixture"),
        ("config", "user.email", "fixture@example.invalid"),
        ("add", "."),
        ("commit", "-m", "synthetic baseline"),
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    relative = path.relative_to(root).as_posix()
    name = "tasks/change.md"
    listing = "".join("- `" + entry + "`\n" for entry in (name, relative))
    start(
        root,
        name,
        "## Task contract\n- Task type: `design`\n- Task status: `running`\n- Workflow: `"
        + workflow
        + "`\n- AWS API execution: `forbidden`\n- AWS mutation: `forbidden`\n- Deploy/apply: `forbidden`\n## Validation scope\n- `preview/team/logs`\n## Modified files\n"
        + listing
        + "## Allowed paths\n"
        + listing,
    )
    write_model(path, dict(before, **{"desired.row.001-001.value": "changed-name"}))
    candidate = SimpleNamespace(
        base_commit=base, changed_paths={relative}, scope={("preview", "team", "logs")}
    )
    proof = {
        "sources": {relative: hashlib.sha256(path.read_bytes()).hexdigest()},
        "model": "reflected",
        "complete": True,
    }
    with (
        selected_task(root, name),
        patch.object(import_guard, "read_proof", return_value=proof),
        patch.object(
            validation, "check_model_inputs", side_effect=AssertionError("Full called")
        ) as full,
        patch.object(
            validation,
            "_check_model_inputs",
            side_effect=AssertionError("Full internal called"),
        ) as internal,
    ):
        import_guard.require_import_changes(root, final_candidate=candidate)
        write_model(path, dict(before, **{"desired.row.001-002.value": "new-invalid"}))
        proof["sources"][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        with pytest.raises(ValueError, match="RetentionInDays"):
            import_guard.require_import_changes(root, final_candidate=candidate)
        full.assert_not_called()
        internal.assert_not_called()


@pytest.mark.parametrize(
    "comment,valid", [("更新した説明", True), ("invalid comment", False)]
)
def check_comment_only_change_selects_comment_rule(project_workspace, comment, valid):
    before = logs(retention="bad")
    after = dict(before, **{"desired.row.001-001.comment": comment})
    result = evaluate(project_workspace, before, after)
    assert bool(result.errors) is not valid, result.errors


@pytest.mark.parametrize(
    "defect",
    ["cfn-logicalId", "deploymentEncryption", "missing-logical", "duplicate-logical"],
)
def check_unrelated_resource_identity_defect(project_workspace, defect):
    root = project_workspace
    setup(root, ["logs"], ["Logs.LogGroup"])
    before = {**logs(), **logs("002"), **logs("003")}
    if defect == "missing-logical":
        before.pop("desired.resource.002.logicalId")
    elif defect == "duplicate-logical":
        before["desired.resource.003.logicalId"] = before[
            "desired.resource.002.logicalId"
        ]
    else:
        before["desired.resource.002." + defect] = "invalid!"
    path = root / "model/preview/team/logs.properties"
    write_model(path, before)
    reads = sources.FileReads()
    old = change_plan.comparison_snapshot(sources.edit_base(path, reads))
    candidate = dict(before, **{"desired.row.001-001.value": "changed-name"})
    current_reads = sources.CandidateReads(
        sources.FileReads(), {path: serialize(candidate)}
    )
    new = sources.raw_model(path, current_reads)
    with patch.object(
        validation, "check_model_inputs", side_effect=AssertionError("Full called")
    ):
        change.validate_save(old, new, current_reads)
    with pytest.raises(ValueError):
        validation.check_model_inputs(path, candidate, root)


@pytest.mark.parametrize("field", ["cfn-logicalId", "deploymentEncryption"])
def check_changed_resource_metadata_is_validated(project_workspace, field):
    before = logs()
    after = dict(before, **{"desired.resource.001." + field: "invalid!"})
    result = evaluate(project_workspace, before, after)
    assert result.errors


@pytest.mark.parametrize("index_state", ["missing", "current", "stale"])
@pytest.mark.parametrize("typed", [False, True])
def check_dependency_discovery_and_broken_consumer(
    project_workspace, index_state, typed
):
    root = project_workspace
    setup(root, ["s3", "lambda", "logs"], ["S3.Bucket", "Lambda.Function"])
    producer = root / "model/preview/team/s3.properties"
    values = resource("001", "S3.Bucket", "bucket", [("BucketName", "fixture-data")])
    write_model(producer, values)
    consumer = producer.with_name("lambda.properties")
    receiving = resource(
        "001",
        "Lambda.Function",
        "consumer",
        [
            (
                "Code.S3Bucket",
                '`{"$modelRef":{"logicalId":"S3_Bucket_001","attribute":"BucketName"}}`'
                if typed
                else "[bucket](s3.md#bucket)",
            )
        ],
    )
    if index_state == "stale":
        write_model(
            consumer,
            resource(
                "001",
                "Lambda.Function",
                "consumer",
                [("Code.S3Bucket", "fixture-data")],
            ),
        )
        dependency_index.rebuild(root)
    write_model(consumer, receiving)
    if index_state == "current":
        dependency_index.rebuild(root)
    # Unrelated quality defects in a different service and the producer's own service.
    write_model(
        producer.with_name("logs.properties"),
        dict(logs(), **{"desired.resource.001.cfn-logicalId": "bad!"}),
    )
    extra = resource("002", "S3.Bucket", "unrelated", [("BucketName", "fixture-extra")])
    extra["desired.resource.002.deploymentEncryption"] = "bad"
    values.update(extra)
    write_model(producer, values)
    old = root / "old"
    setup(old, ["s3"], ["S3.Bucket"])
    write_model(old / producer.relative_to(root), values)
    after = dict(values, **{"desired.row.001-001.value": "changed-data"})
    write_model(producer, after)
    with (
        patch.object(
            validation, "check_model_inputs", side_effect=AssertionError("Full called")
        ),
        patch.object(
            validation,
            "_check_model_inputs",
            side_effect=AssertionError("Full internal called"),
        ),
        patch.object(
            dependency_index,
            "write_sealed",
            side_effect=AssertionError("transient discovery persisted"),
        ),
        patch.object(
            dependency_index, "inventory", wraps=dependency_index.inventory
        ) as inventories,
        patch.object(sources, "raw_model", wraps=sources.raw_model) as raw,
    ):
        plan = change_plan.assemble(
            root, {("preview", "team", "s3")}, old, sources.FileReads()
        )
        assert ("preview", "team", "lambda") in plan.contracts
        result = change.validate_plan(root, plan)
        assert not result.errors, result.errors
        assert inventories.call_count == 1
        paths = [
            call.args[0].path
            if isinstance(call.args[0], sources.Scope)
            else call.args[0]
            for call in raw.call_args_list
        ]
        assert len(paths) == len(set(paths)), paths
    producer.unlink()
    plan = change_plan.assemble(
        root, {("preview", "team", "s3")}, old, sources.FileReads()
    )
    result = change.validate_plan(root, plan)
    assert (
        result.errors
    )  # Incoming contract cannot silently disappear with its producer.
    if index_state == "missing":
        assert not dependency_index.location(root).exists()
        with pytest.raises(ValueError, match="index missing"):
            dependency_index.load(root)  # Deploy still requires its sealed index.


def check_missing_index_without_consumer(project_workspace):
    root = project_workspace
    setup(root, ["logs"], ["Logs.LogGroup"])
    path = root / "model/preview/team/logs.properties"
    old = root / "old"
    setup(old, ["logs"], ["Logs.LogGroup"])
    write_model(old / path.relative_to(root), logs())
    write_model(path, logs(retention="14"))
    plan = change_plan.assemble(
        root, {("preview", "team", "logs")}, old, sources.FileReads()
    )
    result = change.validate_plan(root, plan)
    assert not result.errors, result.errors
    assert not dependency_index.location(root).exists()


def check_ambiguous_changed_resource_and_reference_stop(project_workspace):
    values = {**logs(), **logs("002"), **logs("003")}
    values["desired.resource.003.logicalId"] = values["desired.resource.002.logicalId"]
    after = dict(values, **{"desired.row.002-001.value": "changed-name"})
    with pytest.raises(ValueError, match="cannot identify changed Resource"):
        change_plan.compare(
            snapshot(project_workspace, values), snapshot(project_workspace, after)
        )
    with pytest.raises(ValueError, match="ambiguous producer logicalId"):
        change_plan.signature(values, "Logs_LogGroup_002", "Arn")


def check_unidentifiable_reference_metadata_stops(project_workspace):
    root = project_workspace
    setup(root, ["logs"], ["Logs.LogGroup"])
    path = root / "model/preview/team/logs.properties"
    write_model(
        path,
        dict(
            logs(),
            **{"desired.row.001-001.value": '`{"$modelRef":{"attribute":"Arn"}}`'},
        ),
    )
    with pytest.raises(
        ValueError,
        match="cannot determine reference metadata.*desired.row.001-001.value",
    ):
        dependency_index.check_change_inventory(root, set())


@pytest.mark.parametrize("typed", [True, False])
def check_unrelated_ambiguous_producer_reference(project_workspace, typed):
    root = project_workspace
    setup(root, ["s3", "lambda"], ["S3.Bucket", "Lambda.Function"])
    producer = root / "model/preview/team/s3.properties"
    values = {
        **resource("001", "S3.Bucket", "bucket", [("BucketName", "fixture-data")]),
        **resource("002", "S3.Bucket", "old-bucket", [("BucketName", "fixture-old")]),
        **resource(
            "003", "S3.Bucket", "duplicate", [("BucketName", "fixture-duplicate")]
        ),
    }
    values["desired.resource.003.logicalId"] = "S3_Bucket_002"
    write_model(producer, values)
    receiving = resource(
        "001",
        "Lambda.Function",
        "consumer",
        [
            (
                "Code.S3Bucket",
                '`{"$modelRef":{"logicalId":"S3_Bucket_001","attribute":"BucketName"}}`'
                if typed
                else "[bucket](s3.md#bucket)",
            ),
            (
                "Environment.Variables",
                '`{"old":{"$modelRef":{"logicalId":"S3_Bucket_002","attribute":"BucketName"}}}`'
                if typed
                else "[old](s3.md#old-bucket)",
            ),
        ],
    )
    write_model(producer.with_name("lambda.properties"), receiving)
    old = root / "old"
    setup(old, ["s3"], ["S3.Bucket"])
    write_model(old / producer.relative_to(root), values)
    write_model(producer, dict(values, **{"desired.row.001-001.value": "changed-data"}))
    plan = change_plan.assemble(
        root, {("preview", "team", "s3")}, old, sources.FileReads()
    )
    _, keys = plan.contracts[("preview", "team", "lambda")]
    assert keys == {"desired.row.001-001.value"}
    result = change.validate_plan(root, plan)
    assert not result.errors, result.errors


def check_unrelated_non_model_text_has_no_dependency_edges(project_workspace):
    root = project_workspace
    setup(root, ["logs", "broken"], ["Logs.LogGroup"])
    path = root / "model/preview/team/logs.properties"
    old = root / "old"
    setup(old, ["logs"], ["Logs.LogGroup"])
    write_model(old / path.relative_to(root), logs())
    write_model(path, logs(retention="14"))
    broken = path.with_name("broken.properties")
    broken.write_text("invalid unrelated text\n", encoding="utf-8")
    plan = change_plan.assemble(
        root, {("preview", "team", "logs")}, old, sources.FileReads()
    )
    result = change.validate_plan(root, plan)
    assert not result.errors, result.errors
    broken.write_text("invalid [ref](logs.md#logs-001)\n", encoding="utf-8")
    with pytest.raises(
        ValueError, match="cannot read reference metadata.*broken.properties"
    ):
        change_plan.assemble(
            root, {("preview", "team", "logs")}, old, sources.FileReads()
        )


def require_test_candidate(changes):
    assert all(path.is_absolute() for path in changes)


@pytest.mark.parametrize("action", ["edit", "import"])
@pytest.mark.parametrize("valid", [True, False])
@pytest.mark.parametrize(
    "defect", ["retention", "cfn-logicalId", "deploymentEncryption"]
)
def check_save_preparation_uses_change_validation(
    project_workspace, action, valid, defect
):
    root = project_workspace
    setup(root, ["logs"], ["Logs.LogGroup"])
    before = {**logs(), **logs("002", "old-invalid")}
    if defect != "retention":
        before["desired.resource.002." + defect] = "old-invalid!"
    path = root / "model/preview/team/logs.properties"
    write_model(path, before)
    name = "tasks/save.md"
    listed = "\n".join(
        "- `" + value + "`" for value in (name, path.relative_to(root).as_posix())
    )
    start(
        root,
        name,
        "## Task contract\n- Task type: `design`\n- Task status: `running`\n"
        "- Workflow: `" + ("import" if action == "import" else "update") + "`\n"
        "## Required changes\n- [R1] 合成保存\n## Acceptance checks\n"
        "- [R1] `exists:project.json`\n## Validation scope\n- `preview/team/logs`\n"
        "## Modified files\n" + listed + "\n## Allowed paths\n" + listed + "\n",
    )
    with (
        restrict(("preview", "team", "logs") if action == "import" else None),
        read_consumers({("preview", "team", "logs")}),
        selected_task(root, name),
    ):
        inputs = GenerationInputs(root, task_file=name)
        # Unit capability fixture; Import's acquisition/approval issuer has separate IT.
        context = sources.SourceWriteContext._authorized(
            root,
            inputs,
            SimpleNamespace(action=action),
            require_test_candidate,
            frozenset({path}),
        )
        original = path.read_bytes()
        candidate = dict(
            before, **{"desired.row.001-002.value": "14" if valid else "bad"}
        )
        with (
            patch.object(
                validation,
                "check_model_inputs",
                side_effect=AssertionError("Full called"),
            ) as full,
            patch.object(
                validation,
                "_check_model_inputs",
                side_effect=AssertionError("Full internal called"),
            ) as internal,
            patch.object(change, "validate_save", wraps=change.validate_save) as saving,
        ):
            if valid:
                plan = prepare_edit(path, {path: serialize(candidate)}, context)
                assert not plan.candidate.warnings
                assert publish_edit(plan, context) == (path,)
                assert path.read_text(encoding="utf-8") == serialize(candidate)
            else:
                with pytest.raises(ValueError, match="RetentionInDays"):
                    prepare_edit(path, {path: serialize(candidate)}, context)
                context.close()
                assert path.read_bytes() == original
            assert saving.call_count >= 1
            full.assert_not_called()
            internal.assert_not_called()


@pytest.mark.parametrize("field", ["cfn-logicalId", "deploymentEncryption"])
def check_same_resource_old_metadata_does_not_block_property(project_workspace, field):
    root = project_workspace
    setup(root, ["logs"], ["Logs.LogGroup"])
    before = dict(logs(), **{"desired.resource.001." + field: "old-invalid!"})
    path = root / "model/preview/team/logs.properties"
    write_model(path, before)
    candidate = dict(before, **{"desired.row.001-002.value": "14"})
    reads = sources.CandidateReads(sources.FileReads(), {path: serialize(candidate)})
    with patch.object(
        validation, "check_model_inputs", side_effect=AssertionError("Full called")
    ):
        change.validate_save(
            sources.raw_model(path), sources.raw_model(path, reads), reads
        )


@pytest.mark.parametrize("index_state", ["missing", "stale"])
def check_save_preparation_rejects_incoming_reference_break(
    project_workspace, index_state
):
    root = project_workspace
    setup(root, ["s3", "lambda"], ["S3.Bucket", "Lambda.Function"])
    path = root / "model/preview/team/s3.properties"
    before = resource("001", "S3.Bucket", "bucket", [("BucketName", "fixture-data")])
    write_model(path, before)
    if index_state == "stale":
        dependency_index.rebuild(root)
    consumer = path.with_name("lambda.properties")
    write_model(
        consumer,
        resource(
            "001",
            "Lambda.Function",
            "consumer",
            [("Code.S3Bucket", "[bucket](s3.md#bucket)")],
        ),
    )
    old = sources.raw_model(path)
    candidate = {
        key: value
        for key, value in before.items()
        if not key.startswith(
            ("desired.resource.", "desired.row.", "display.resource.")
        )
    }
    reads = sources.CandidateReads(sources.FileReads(), {path: serialize(candidate)})
    with (
        patch.object(
            validation, "check_model_inputs", side_effect=AssertionError("Full called")
        ),
        pytest.raises(ValueError, match="producer Resource is absent"),
    ):
        change.validate_save(old, sources.raw_model(path, reads), reads)


@pytest.mark.parametrize(
    "value,valid", [('`["All"]`', True), ('`["bad"]`', False), ('`[["All"]]`', False)]
)
def check_wildcard_occurrence_keeps_scalar_constraints(project_workspace, value, valid):
    before = resource(
        "001",
        "CloudTrail.Trail",
        "trail",
        [("EventSelectors[].ReadWriteType", '`["ReadOnly"]`')],
    )
    after = dict(before, **{"desired.row.001-001.value": value})
    result = evaluate(project_workspace, before, after, "cloudtrail")
    assert (not result.errors) == valid, result.errors


def check_current_index_reuses_unaffected_metadata(project_workspace):
    root = project_workspace
    setup(root, ["logs"], ["Logs.LogGroup"])
    path = root / "model/preview/team/logs.properties"
    peer = root / "model/preview/team/peer.properties"
    write_model(path, logs())
    write_model(peer, logs("002"))
    dependency_index.rebuild(root)
    sealed = dependency_index.location(root).read_bytes()
    old = sources.raw_model(path)
    reads = sources.CandidateReads(
        sources.FileReads(), {path: serialize(logs(retention="14"))}
    )
    after = sources.raw_model(path, reads)
    with (
        patch.object(sources, "raw_model", wraps=sources.raw_model) as raw,
        patch.object(
            dependency_index, "snapshot_record", wraps=dependency_index.snapshot_record
        ) as record,
    ):
        change.validate_save(old, after, reads)
        raw.assert_not_called()
        assert record.call_count == 1
        assert record.call_args.args[0] is after
    assert dependency_index.location(root).read_bytes() == sealed
