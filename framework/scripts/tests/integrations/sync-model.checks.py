#!/usr/bin/env python3
"""Focused checks; test sources define the current verification responsibilities."""

import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as _CallbackState
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import io
import json
import os
import shutil
import threading
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import import_guard
import model.impact as model_impact
import model.render as model_design
import model.sources as model_sources
import pytest
import support.sync_model_fixtures as _fixture_generated_policy
import sync_progress as progress
import sync_runtime
import sync_views
import task_contract_core as tasks
import task_contract_runtime as task_runtime
from design.document import DesignIndex
from model.files import load_model, read_model
from support.model_design_fixtures import collapsed_json
from support.model_reference_fixtures import reference, resource, save
from support.model_sources import allocate_fixture as allocate
from support.model_sources import write_model as write_model
from support.model_templates_fixtures import config_model, fixture, write_fixture
from support.pytest_cli import run
from support.sync_model_fixtures import MODULE
from support.validator import commit, diagnostics, load
from utils.aws_mappings import definition_root, mapping_alias, mappings_for
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.input_cache import input_scope, memo_table
from utils.script_loader import module
from validation import change as change_validation
from validation import cloudformation, design_links, design_tables
from validation import design as design_checks
from validation import runner as validation_runner

from model import dependency_index

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

generated_policy = _fixture_generated_policy.generated_policy

pytestmark = pytest.mark.usefixtures("catalog_display_fixture")


def _callback_check_stage_definition_sources_inspect(
    _state_check_stage_definition_sources_90, root, unrelated, /, plan, **kwargs
):
    result = _state_check_stage_definition_sources_90.validate(plan, **kwargs)
    assert (
        not (plan.stage / "framework").exists()
        and not (plan.stage / "framework").is_symlink()
    )
    assert not (root / "framework").exists()
    assert all(not (plan.stage / p.relative_to(root)).exists() for p in unrelated)
    assert set(p.relative_to(plan.stage).parts[0] for p in plan.stage.rglob("*")) <= {
        "model",
        "docs",
        "project.json",
    }
    # An unrelated log's content is not a generation dependency.
    assert unrelated[-1] not in plan.snapshot.contents
    unrelated[-1].write_text("log changed during generation\n")
    return result


def check_stage_definition_sources(generated_policy, tmp_path):
    _state_check_stage_definition_sources_90 = _CallbackState()
    root, model, values, design, artifact, _ = generated_policy
    originals = {design: design.read_bytes()}
    definitions = {
        p: p.read_bytes()
        for p in (definition_root(root) / "framework").rglob("*")
        if p.is_file()
    }
    stage = tmp_path / "candidates"
    staged = stage / design.relative_to(root)
    with mapping_alias(root, stage):
        sync_runtime.stage_inputs(
            stage, root, {design: values}, [model], [design], ["iam"], False
        )
        assert mappings_for(stage) is mappings_for(root)
        failures = []
        sync_runtime.generate_views(stage, root, {design: values}, failures)
        assert not failures, failures
        assert (
            not (stage / "framework").exists()
            and not (stage / "framework").is_symlink()
        )
        assert (
            load_model(stage / model.relative_to(root)).values
            == load_model(model).values
        )
        assert {
            p: (stage / p.relative_to(root)).read_bytes() for p in originals
        } == originals
        assert (
            DesignIndex(root).get(staged).headings.expanded
            == DesignIndex(root).get(design).headings.expanded
        )
        validator = sync_views.view_validator(stage, root)
        assert (
            validator.root == stage
            and validator.definitions_root == definition_root(root)
        )
        assert validator.findings.canonical_root == stage.resolve()
        validator.check_resource_layout()
        assert not validator.errors, validator.errors
    values["desired.note.001.text"] = "最小stageの通常保存を検証する。"
    write_model(model, values)
    register = generated_policy[-1]
    unrelated = [
        root / "docs/designs/dev/123456789012/unrelated.md",
        root / "infra/unrelated.yaml",
        root / "tests/results/unrelated.log",
    ]
    for path in unrelated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("unrelated input\n")
    _state_check_stage_definition_sources_90.validate = sync_runtime.validate_generation
    inspect = _bind_framework_callback(
        _callback_check_stage_definition_sources_inspect,
        _state_check_stage_definition_sources_90,
        root,
        unrelated,
    )
    with (
        patch.dict(os.environ, register([design, artifact])),
        patch.object(sync_runtime, "validate_generation", side_effect=inspect),
    ):
        assert (
            MODULE.sync(
                root,
                True,
                "dev",
                "123456789012",
                ["iam"],
                definitions_root=definition_root(root),
            )
            == 0
        )
    assert {p: p.read_bytes() for p in definitions} == definitions
    assert values["desired.note.001.text"] in design.read_text()


def check_stage_candidate_isolation(generated_policy, tmp_path):
    root, model, values, design, artifact, _ = generated_policy
    stage = tmp_path / "candidates"
    staged = stage / design.relative_to(root)
    originals = {p: p.read_bytes() for p in (model, design)}
    with mapping_alias(root, stage):
        sync_runtime.stage_inputs(
            stage, root, {design: values}, [model], [design], ["iam"], False
        )
        validator = sync_views.view_validator(stage, root)
        validator.scope = {("dev", "123456789012", "iam")}
        validator.check_project_topology()
        metadata, *catalog = validator.check_design_service_ownership([staged])
        validator.check_resource_names(metadata, [staged])
        validator.check_design_tables(metadata, *catalog, [staged])
        validator.check_design_overviews([staged])
        validator.check_design_links(catalog[2], [staged])
        validator.check_policy_tables()
        errors = diagnostics(validator)
        TestCase().assertFalse(errors, errors)
        assert all(
            str(root) not in error and str(stage) not in error
            for error in validator.errors
        )
        assert not (stage / "framework").exists()
    assert {p: p.read_bytes() for p in originals} == originals


def check_stage_cloudformation_definitions(generated_policy, tmp_path):
    root, model, values, design, _, _ = generated_policy
    stack_model = model.with_name("cloudformation-stacks.properties")
    stack_design = design.with_name("cloudformation-stacks.md")
    stacks = {
        "desired.deployment.maxConcurrentStacks": "1",
        "desired.stack.001.name": "cfn-stack-app-dev-iam",
        "desired.stack.001.template": "iam.yaml",
        "desired.stack.001.parameters": "iam.json",
        "desired.stack.001.deployOrder": "10",
        "display.stack.001.comment": "アプリケーションの実行権限",
    }
    write_model(stack_model, stacks)
    values = values | {
        "desired.resource.001.cfn-logicalId": "cfn-stack-app-dev-iam-AppRole"
    }
    write_model(model, values)
    expected = design.read_bytes()
    expected_stack = model_design.markdown_for(
        stack_design, stacks, root, definitions_root=definition_root(root)
    ).encode("utf-8")
    stack_design.write_bytes(expected_stack)
    stage = tmp_path / "candidates"
    staged = stage / design.relative_to(root)
    staged_stack = stage / stack_design.relative_to(root)
    with mapping_alias(root, stage):
        sources = {design: values, stack_design: stacks}
        sync_runtime.stage_inputs(
            stage,
            root,
            sources,
            [model, stack_model],
            list(sources),
            ["iam", "cloudformation-stacks"],
            False,
        )
        failures = []
        generated = sync_runtime.generate_views(stage, root, sources, failures)
        context = sync_views.validation_context(stage, root, generated, sources)
        validation = {None: context.findings}
        assert not failures, failures
        assert (
            staged.read_bytes() == expected
            and staged_stack.read_bytes() == expected_stack
        )
        scope = {
            ("dev", "123456789012", service)
            for service in ("iam", "cloudformation-stacks")
        }
        metadata = (
            validation[None]
            .result("design.stacks", scope)
            .metadata["stack_definitions"]
        )
        assert metadata[staged_stack][0]["name"] == "cfn-stack-app-dev-iam"
        # IaC uses the validated candidate, even when the saved stack is stale.
        stack_design.write_bytes(expected_stack.replace(b"iam.json", b"stale.json"))
        parameter = root / "infra/cloudformation/parameters/dev/123456789012/iam.json"
        parameter.parent.mkdir(parents=True, exist_ok=True)
        parameter.write_text("[]\n")
        template = root / "infra/cloudformation/templates/iam.yaml"
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text("Resources: {}\n")
        iac_validator = validation_runner.Validator(
            root, scope, iac_paths={template, parameter}
        )
        iac_validator.check_project_topology()
        logical = {
            root / path.relative_to(stage): definitions
            for path, definitions in metadata.items()
        }
        with patch(
            "validation.cloudformation.stack_design",
            side_effect=AssertionError("candidate stack reparsed"),
        ):
            iac_validator.check_cloudformation_environment_parameters(
                stack_definitions=logical
            )
        assert not iac_validator.errors, iac_validator.errors
        stack_design.write_bytes(expected_stack)
    assert (
        stack_design.read_bytes() == expected_stack
        and not (stage / "framework").exists()
    )


def _callback_check_normal_writer_contents_check_stage(materialize, stages, /, inputs):
    stage = materialize(inputs)
    assert not (stage / "framework").exists()
    assert not (stage / "framework").is_symlink()
    stages.append(stage)
    return stage


def check_normal_writer_contents(generated_policy):
    root, model, values, design, artifact, register = generated_policy
    values["desired.note.001.text"] = "一回の候補を保存する。"
    document = json.loads(values["desired.row.001-002.document"])
    document["Statement"][0]["Sid"] = "WrittenOnce"
    values["desired.row.001-002.document"] = json.dumps(document)
    write_model(model, values)

    materialize = sync_runtime.GenerationInputs.open_stage
    stages = []
    check_stage = _bind_framework_callback(
        _callback_check_normal_writer_contents_check_stage, materialize, stages
    )
    stdout, stderr = io.StringIO(), io.StringIO()
    with ExitStack() as stack, redirect_stdout(stdout), redirect_stderr(stderr):
        stack.enter_context(
            patch.object(sync_runtime.GenerationInputs, "open_stage", check_stage)
        )
        checks = [
            (design_checks, name)
            for name in (
                "check_design_service_ownership",
                "check_resource_names",
                "check_observed_values",
                "check_policy_tables",
            )
        ]
        checks += [
            (sync_runtime, "validate_required_properties"),
            (design_tables, "check_design_tables"),
            (design_links, "check_design_overviews"),
            (design_links, "check_design_links"),
            (design_links, "check_design_artifacts"),
            (cloudformation, "check_stack_designs"),
        ]
        counters = [
            stack.enter_context(patch.object(module, name, wraps=getattr(module, name)))
            for module, name in checks
        ]
        with (
            patch.dict(os.environ, register([design, artifact])),
            patch.object(
                sync_runtime, "generate_views", wraps=sync_runtime.generate_views
            ) as generate,
            patch.object(
                sync_views, "validate_views", wraps=sync_views.validate_views
            ) as validate,
            patch.object(
                sync_runtime.GenerationInputs,
                "verify",
                autospec=True,
                side_effect=sync_runtime.GenerationInputs.verify,
            ) as verify,
            patch.object(
                model_sources, "_read_model", wraps=model_sources._read_model
            ) as expand,
            patch.object(
                sync_runtime,
                "verify_saved",
                side_effect=AssertionError("post-save readback"),
            ),
        ):
            generate_cli = progress.reported_main(
                _bind_framework_callback(
                    sync_runtime.sync, root, True, "dev", "123456789012", ["iam"]
                )
            )
            assert generate_cli() == 0
        assert len(set(stages)) == generate.call_count == verify.call_count == 1
        validate.assert_not_called()
        contexts = [
            (call.args[0], id(call.args[1]))
            for call in expand.call_args_list
            if call.args[0].service == "iam"
        ]
        assert contexts and len(contexts) == len(set(contexts)), expand.call_args_list
        assert all(counter.call_count == 0 for counter in counters)
    assert stdout.getvalue() == (
        "Design Markdown sync: PASS (docs/designs/dev/123456789012/iam.md)\n"
        "Design Markdown generation: 1 services succeeded; 0 services failed; 0 services unavailable\n"
        "Design Markdown sync: PASS (1 services)\n"
    )
    for stage in (
        "snapshot",
        "dependency-model",
        "stage-placement",
        "candidate-generation",
        "publication",
        "completed=1/1",
    ):
        assert stage in stderr.getvalue()
    assert values["desired.note.001.text"] in design.read_text()
    assert not artifact.exists()
    assert collapsed_json(design.read_text(encoding="utf-8")) == json.loads(
        values["desired.row.001-002.document"]
    )


@pytest.mark.parametrize("note", [False, True])
def check_unchanged_sidecar(generated_policy, note):
    root, model, values, design, artifact, register = generated_policy
    if note:
        values["desired.note.001.text"] = "利用開始前に実行主体の権限を確認する。"
        write_model(model, values)
    env = register([design] if note else [])
    original_design = design.read_bytes()
    with (
        patch.dict(os.environ, env),
        patch.object(
            sync_runtime,
            "_publish_transaction",
            wraps=sync_runtime._publish_transaction,
        ) as publish,
        patch.object(
            sync_runtime, "validate_generation", wraps=sync_runtime.validate_generation
        ) as validate,
    ):
        assert MODULE.sync(root, True, "dev", "123456789012", ["iam"]) == 0
    assert validate.call_count == 1, "no-op outputs still require frozen bytes"
    assert publish.call_count == int(note)
    if not note:
        assert design.read_bytes() == original_design
    if note:
        assert set(publish.call_args.args[1]) == {design}, (
            "unchanged JSON must not enter publication"
        )
        assert values["desired.note.001.text"] in design.read_text(encoding="utf-8")
    assert not artifact.exists()


@pytest.mark.parametrize("cli", [False, True])
def check_pending_artifact_transaction(generated_policy, cli):
    root, model, values, design, trust, register = generated_policy
    artifact = trust.with_name("iam-role-001-pending.json")
    arn = "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789abc"
    document = {
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "kms:Decrypt",
                "Resource": ["arn:aws:s3:::confirmed-bucket", arn],
            }
        ]
    }
    values.update(
        {
            "desired.row.001-003.property": "IAM.Role.Policies[].PolicyName",
            "desired.row.001-003.value": "`pending`",
            "desired.row.001-003.comment": "合成",
            "desired.row.001-004.property": "IAM.Role.Policies[].PolicyDocument",
            "desired.row.001-004.value": "[Policy](iam/iam-role-001-pending.json)",
            "desired.row.001-004.document": json.dumps(document),
            "desired.row.001-004.comment": "合成",
        }
    )
    write_model(model, values)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(document) + "\n", encoding="utf-8")
    design.write_text(
        model_design.generate_markdown(
            design, load_model(model).values, definition_root(root)
        ),
        encoding="utf-8",
    )
    producer, key = resource(
        root,
        "kms",
        "KMS.Key",
        target="123456789012",
        environment="dev",
        attribute="KeyId",
        observed="PENDING_DEPLOY",
    )
    producer = model_sources.Scope(root, "dev", "123456789012", "kms")
    save(producer, key)
    document["Statement"][0]["Resource"][1] = reference()
    values["desired.row.001-004.document"] = json.dumps(document)
    write_model(model, values)
    {p: p.read_bytes() for p in (design, artifact)}
    authority = {p: p.read_bytes() for p in (model, producer.path)}
    selector = register({design, trust, artifact})
    if cli:
        contract = root / selector[tasks.SELECTOR]
        contract.write_text(
            contract.read_text(encoding="utf-8").replace(
                "- Task type: `design`",
                "- Task type: `infrastructure`\n- Infrastructure phase: `deploy`\n- Deploy execution method: `cli`\n- CLI AWS account: `123456789012`\n- CLI AWS region: `ap-northeast-1`\n- CLI AWS partition: `aws`",
            ),
            encoding="utf-8",
        )
    with patch.dict(os.environ, selector):
        with sync_runtime.generation_context(root, True):
            plan = sync_runtime.prepare_generation(
                root, {("dev", "123456789012", "iam")}
            )
            try:
                assert not plan.failures and (not plan.unavailable), plan.failures
                assert design in plan.generated
                sync_runtime.validate_generation(plan, jobs=1)
                metadata = sync_runtime.generation_metadata(plan)
                assert metadata["status"] == "PASS" and metadata["complete"]
                assert not metadata["unverified"]
                assert any(
                    (
                        warning.get("category") == "REFERENCE_PENDING_DEPLOY"
                        for warning in metadata["warnings"]
                    )
                )
                candidate = plan.expected_outputs[design]
                assert (
                    collapsed_json(candidate[design], "pending")["Statement"][0][
                        "Resource"
                    ][1]
                    == "PENDING_DEPLOY"
                )
                assert candidate[artifact] is None
                sync_runtime.publish_generation(plan)
                assert not plan.failures and design in plan.saved
                assert not artifact.exists()
                assert design.read_text(encoding="utf-8") == candidate[design]
                assert not trust.exists()
            finally:
                plan.close()
        assert {p: p.read_bytes() for p in authority} == authority
        key["observed.row.001-001.value"] = "`12345678-1234-1234-1234-123456789abc`"
        save(producer, key)
        authority[producer.path] = producer.path.read_bytes()
        expected = json.loads(json.dumps(document))
        expected["Statement"][0]["Resource"][1] = arn
        with sync_runtime.generation_context(root, True):
            plan = sync_runtime.prepare_generation(
                root, {("dev", "123456789012", "iam")}
            )
            try:
                assert not plan.failures and (not plan.unavailable), plan.failures
                sync_runtime.validate_generation(plan, jobs=1)
                metadata = sync_runtime.generation_metadata(plan)
                assert metadata["status"] == "PASS" and metadata["complete"] is True
                assert not metadata["unverified"]
                candidate = plan.expected_outputs[design]
                assert (
                    collapsed_json(candidate[design], "pending") == expected
                    and artifact not in candidate
                )
                assert "iam/iam-role-001-pending.json" not in candidate[design]
                assert arn in candidate[design]
                assert (
                    "$modelRef" not in candidate[design]
                    and "confirmed-bucket" in candidate[design]
                )
                sync_runtime.publish_generation(plan)
                assert (
                    not plan.failures
                    and collapsed_json(design.read_text(encoding="utf-8"), "pending")
                    == expected
                )
                assert not trust.exists()
                assert design.read_text(encoding="utf-8") == candidate[design]
                assert not list(root.glob(".model-publication*.json"))
            finally:
                plan.close()
        assert {p: p.read_bytes() for p in authority} == authority
        assert "$modelRef" in values["desired.row.001-004.document"]
        assert "PENDING_DEPLOY" not in design.read_text(encoding="utf-8")


def check_changed_sidecar_publication(generated_policy):
    root, model, values, design, artifact, register = generated_policy
    document = json.loads(values["desired.row.001-002.document"])
    document["Id"] = "Changed"
    values["desired.row.001-002.document"] = json.dumps(document)
    write_model(model, values)
    before = design.read_bytes()
    env = register([design, artifact])
    with (
        patch.dict(os.environ, env),
        patch.object(
            sync_runtime,
            "_publish_transaction",
            wraps=sync_runtime._publish_transaction,
        ) as publish,
    ):
        assert MODULE.sync(root, True, "dev", "123456789012", ["iam"]) == 0
    assert publish.call_count == 1 and set(publish.call_args.args[1]) == {design}
    assert not artifact.exists()
    assert collapsed_json(design.read_text(encoding="utf-8")) == json.loads(
        values["desired.row.001-002.document"]
    )
    assert design.read_bytes() != before
    assert '"Id": "Changed"' in design.read_text(encoding="utf-8")


def _callback_check_incoming_reference_models_check_snapshot(
    incoming, models, /, stage, root, paths, *, definitions_root=None
):
    assert stage / incoming.relative_to(root) not in paths
    assert not (stage / (models / "kms.properties").relative_to(root)).exists()
    return {}


def check_incoming_reference_models(project_workspace, tmp_path) -> None:
    root = project_workspace
    (root / "project.json").write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "environment": "dev",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ]
            }
        )
    )
    models = root / "model/dev/123456789012"
    docs = root / "docs/designs/dev/123456789012"
    docs.mkdir(parents=True)
    for service in ("s3", "kms"):
        write_model(
            models / f"{service}.properties",
            f"desired.service.{service}.serviceId={service}\n",
        )
        (docs / f"{service}.md").write_text(
            f"# {service}\n### {service}\n", encoding="utf-8"
        )
    selected = docs / "s3.md"
    incoming = docs / "kms.md"
    incoming.write_text("# kms\n### kms\n[S3](s3.md#s3)\n", encoding="utf-8")
    stage = tmp_path / "stage"
    stage.mkdir()

    check_snapshot = _bind_framework_callback(
        _callback_check_incoming_reference_models_check_snapshot, incoming, models
    )
    with patch.object(
        sync_views, "broken_design_links", side_effect=check_snapshot
    ) as check:
        saved = sync_runtime.stage_inputs(
            stage,
            root,
            {selected: {}},
            [models / "s3.properties"],
            [selected],
            ["s3"],
            True,
        )
    assert incoming not in saved
    assert check.call_count == 0
    assert not (stage / incoming.relative_to(root)).exists()
    assert not (stage / (models / "kms.properties").relative_to(root)).exists()


def _callback_check_required_property_parents_design_errors(design, root, /, content):
    design.write_text(content)
    validator = sync_views.view_validator(root, root)
    validator.check_design_tables(
        {design: ("glue", ("Glue.Connection",))}, *validator.catalog_design_properties()
    )
    return validator.errors


def check_required_property_parents(tmp_path) -> None:
    root = tmp_path
    (root / "project.json").write_text(
        json.dumps(
            {
                "projectName": "test",
                "targets": [
                    {
                        "environment": "dev",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "cloudformation",
                    }
                ],
            }
        )
        + "\n"
    )
    model = root / "model/dev/123456789012/glue.properties"
    model.parent.mkdir(parents=True)
    values = {
        "desired.service.glue.serviceId": "glue",
        "desired.service.glue.ownedCatalogResourceTypes": "Glue.Connection",
        "desired.resource.001.resourceType": "Glue.Connection",
        "desired.resource.001.cfn-logicalId": "fixture-Connection",
        "display.service.title": "# AWS Glue 詳細設計",
        "display.resource.001.comment": "データ取得に使用する接続",
    }
    values.update(allocate(values, ["001"]))
    for number, (field, value) in enumerate(
        (
            ("ConnectionInput.Name", "`sample`"),
            (
                "Name",
                '`{"$modelRef":{"logicalId":"Glue_Connection_001","attribute":"Name"}}`',
            ),
            ("CatalogId", "`123456789012`"),
            ("ConnectionInput.ConnectionType", "`JDBC`"),
            (
                "ConnectionInput.PhysicalConnectionRequirements.AvailabilityZone",
                "`ap-northeast-1a`",
            ),
            ("ConnectionInput.ValidateCredentials", "`true`"),
        ),
        1,
    ):
        key = f"001-{number:03d}"
        comment = "一意に識別するID" if field == "Name" else "接続の設定"
        values.update(
            {
                f"desired.row.{key}.property": "Glue.Connection." + field,
                f"desired.row.{key}.value": value,
                f"desired.row.{key}.comment": comment,
            }
        )
    values.update(
        {
            "observed.row.001-002.property": "Glue.Connection.Name",
            "observed.row.001-002.value": "`sample`",
            "observed.row.001-002.comment": "一意に識別するID",
        }
    )
    source = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    write_model(model, source)
    source = read_model(model)
    design = root / "docs/designs/dev/123456789012/glue.md"
    write_model(
        model.with_name("cloudformation-stacks.properties"),
        {
            "desired.stack.001.name": "fixture",
            "desired.stack.001.placementName": "fixture",
            "desired.stack.001.template": "fixture.yaml",
            "desired.stack.001.parameters": "fixture.json",
            "desired.stack.001.deployOrder": "1",
            "display.stack.001.comment": "合成Stack",
        },
    )
    assert MODULE.sync(root, True, "dev", "123456789012") == 0
    assert read_model(model) == source
    assert (
        "| ConnectionInput |" not in design.read_text()
    )  # Presence is inferred without inventing a row.

    design_errors = _bind_framework_callback(
        _callback_check_required_property_parents_design_errors, design, root
    )

    original = design.read_text()
    assert not design_errors(original), design_errors(original)


def main():
    return run(
        __file__,
        message="sync-model: PASS (generation, changed outputs, publication drift and rollback)",
    )


def _callback_check_publication_lock_wait_notify(emit, waiting, /, state, event):
    emit(state, event)
    if state[5] == "lock-wait":
        waiting.set()


def _callback_check_publication_lock_wait_worker(errors, reporter, tmp_path, /):
    try:
        with reporter.worker("dev/team/iam"), model_sources.publication_lock(tmp_path):
            with model_sources.publication_lock(tmp_path):
                pass
    except BaseException as error:
        errors.append(error)


def check_publication_lock_wait(tmp_path):
    output = io.StringIO()
    waiting = threading.Event()
    reporter = progress.Progress()
    errors = []
    emit = reporter.emit
    notify = _bind_framework_callback(
        _callback_check_publication_lock_wait_notify, emit, waiting
    )
    reporter.emit = notify
    worker = _bind_framework_callback(
        _callback_check_publication_lock_wait_worker, errors, reporter, tmp_path
    )
    with redirect_stderr(output):
        with model_sources.publication_lock(tmp_path):
            thread = threading.Thread(target=worker)
            thread.start()
            observed = waiting.wait(5)
        thread.join(5)
    assert observed and not thread.is_alive() and not errors
    assert "lock-wait" in output.getvalue()


def _callback_check_two_consumer_cli_prepare(stages, original, /, *args, **kwargs):
    plan = original(*args, **kwargs)
    stages.append((plan.stage, plan.snapshot))
    return plan


def check_two_consumer_cli(generated_policy):
    root, _, _, design, artifact, register = generated_policy
    shutil.copytree(root / "model/dev", root / "model/stg")
    shutil.copytree(root / "docs/designs/dev", root / "docs/designs/stg")
    project = json.loads((root / "project.json").read_text())
    project["targets"].append({**project["targets"][0], "environment": "stg"})
    (root / "project.json").write_text(json.dumps(project) + "\n")
    for arguments in [
        ("init", "-q"),
        ("add", "."),
        (
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "baseline",
        ),
    ]:
        subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)
    outputs = [
        design,
        root / "docs/designs/stg/123456789012/iam.md",
    ]
    environment = register(outputs)
    name = environment[tasks.SELECTOR]
    (root / name).write_text(
        (root / name)
        .read_text()
        .replace(
            "- `dev/123456789012/iam`",
            "- `dev/123456789012/iam`\n- `stg/123456789012/iam`",
        )
    )
    (root / name).write_text(
        (root / name)
        .read_text()
        .replace(
            "## Modified files\n",
            "## Modified files\n- `model/stg/123456789012/iam.properties`\n",
        )
        .replace(
            "## Allowed paths\n",
            "## Allowed paths\n- `model/stg/123456789012/iam.properties`\n",
        )
    )
    task_runtime.refresh(root, name)
    for selected_env in ("dev", "stg"):
        source = root / "model" / selected_env / "123456789012/iam.properties"
        source.write_text(
            source.read_text().replace("アプリケーションの実行権限", "更新後の処理権限")
        )
    dependency_index.rebuild(root)
    cli = load("sync-model")
    arguments = [
        "sync-model.py",
        "--repository-root",
        str(root),
        "--scope",
        "dev/123456789012/iam",
        "--scope",
        "stg/123456789012/iam",
        "--jobs",
        "2",
    ]
    stdout, stderr = io.StringIO(), io.StringIO()
    with (
        patch.dict(os.environ, environment),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        with patch.object(sys, "argv", [*arguments, "--write"]):
            assert cli.main() == 0, stdout.getvalue() + stderr.getvalue()
        written = {file: file.read_bytes() for file in outputs}
        stages = []
        prepare = _bind_framework_callback(
            _callback_check_two_consumer_cli_prepare,
            stages,
            sync_runtime.prepare_generation,
        )
        with (
            patch.object(sys, "argv", arguments),
            patch.object(sync_runtime, "prepare_generation", side_effect=prepare),
        ):
            assert cli.main() == 0, stdout.getvalue() + stderr.getvalue()
        assert len(stages) == 2
        assert len({stage for stage, _ in stages}) == 2
        assert len({id(snapshot) for _, snapshot in stages}) == 2
        assert written == {file: file.read_bytes() for file in outputs}
    assert "sync-model progress:" not in stdout.getvalue()
    assert "stage=impact-scope" in stderr.getvalue()
    assert "completed=2/2" in stderr.getvalue()
    TestCase().assertNotIn("state=failed", stderr.getvalue())
    for document in outputs:
        assert "更新後の処理権限" in document.read_text()


@pytest.fixture
def internal_sync_project(tmp_path):
    definitions = definition_root(tmp_path)
    lifetime = ExitStack()
    lifetime.enter_context(mapping_alias(definitions, tmp_path))
    fixture(tmp_path, ("dev", "stg"))
    for env in ("dev", "stg"):
        write_fixture(tmp_path, env, "config", config_model())
    active = tmp_path / "tasks/example.md"
    active.write_text(
        active.read_text()
        .replace("## Allowed paths\n", "## Allowed paths\n- `project.json`\n")
        .replace(
            "## Modified files\n",
            "## Modified files\n- `project.json`\n"
            + "".join(
                "- `" + path.relative_to(tmp_path).as_posix() + "`\n"
                for path in (tmp_path / "model").rglob("*.properties")
            ),
        )
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    dependency_index.rebuild(tmp_path)
    try:
        yield tmp_path
    finally:
        lifetime.close()


def _callback_check_internal_sync_isolation_observed(
    _state_check_internal_sync_isolation_1166, sync, /, *args, **kwargs
):
    _state_check_internal_sync_isolation_1166.barrier.wait(timeout=10)
    _state_check_internal_sync_isolation_1166.workers.add(threading.get_ident())
    assert memo_table() is not _state_check_internal_sync_isolation_1166.parent_memo
    assert sync_views._saved_design_validation.get() is None
    assert (
        progress._current.get()[0]
        is not _state_check_internal_sync_isolation_1166.parent_progress
    )
    return sync(*args, **kwargs)


def _callback_check_internal_sync_isolation_calls(
    _state_check_internal_sync_isolation_1166,
    design,
    entry,
    inputs,
    jobs,
    memories,
    observed,
    original,
    root,
    runner,
    saved,
    selection,
    source,
    /,
):
    parent = memo_table()
    _state_check_internal_sync_isolation_1166.parent_memo = parent
    load_model(source)
    parent_snapshot = dict(parent)
    with (
        sync_views.saved_design_validation(root, entry),
        _state_check_internal_sync_isolation_1166.parent_progress.worker("parent"),
        patch.object(runner, "sync", side_effect=observed),
    ):
        for invalid in (False, True, False):
            # Parent memo retains the old source; the runner must read it again.
            inputs.write_bytes(original + (b"broken: [\n" if invalid else b""))
            code, text = runner.run(
                ["--jobs", str(jobs), *selection], repository_root=root
            )
            assert code == (1 if invalid else 0), text
            assert (
                "Design Markdown sync: FAIL"
                if invalid
                else "Design Markdown sync: PASS"
            ) in text, text
            assert "consumer=parent" not in text
            assert memo_table() is parent and parent == parent_snapshot
            assert sync_views._saved_design_validation.get() == (root, entry)
            memories.append(text)
    assert design.read_bytes() == saved


def check_internal_sync_isolation(internal_sync_project, capsys):
    selection = ["--scope", "dev/team/config", "--scope", "stg/team/config"]
    jobs = 2
    _state_check_internal_sync_isolation_1166 = _CallbackState(
        barrier=threading.Barrier(2), workers=set()
    )
    runner = module("sync-model.py", "blueprint_sync_model")
    root = internal_sync_project
    entry = ("dev", "team", "config")
    source = root / "model/dev/team/config.properties"
    design = root / "docs/designs/dev/team/config.md"
    saved = design.read_bytes()
    inputs = root / "model/dev/team/config.properties"
    original = inputs.read_bytes()
    memories = []
    sync = runner.sync
    observed = _bind_framework_callback(
        _callback_check_internal_sync_isolation_observed,
        _state_check_internal_sync_isolation_1166,
        sync,
    )
    calls = (input_scope)(
        _bind_framework_callback(
            _callback_check_internal_sync_isolation_calls,
            _state_check_internal_sync_isolation_1166,
            design,
            entry,
            inputs,
            jobs,
            memories,
            observed,
            original,
            root,
            runner,
            saved,
            selection,
            source,
        )
    )
    _state_check_internal_sync_isolation_1166.parent_progress = progress.Progress()
    capsys.readouterr()
    # Keep the parent's progress out of the streams under test as well.
    _state_check_internal_sync_isolation_1166.parent_progress.output = io.StringIO()
    calls()
    captured = capsys.readouterr()
    assert not captured.out and not captured.err, captured
    assert progress._current.get() is None and memo_table() is None
    assert sync_views._saved_design_validation.get() is None
    assert len(memories) == 3
    assert len(_state_check_internal_sync_isolation_1166.workers) >= 2


def _callback_check_integrated_validator_candidate_policy_check(
    original_policy_check, root, /, validator
):
    if validator.root == root:
        raise AssertionError("post-save content handler")
    return original_policy_check(validator)


def _callback_check_integrated_validator_read(
    _state_check_integrated_validator_1251, read_bytes, root, /, path
):
    return read_bytes(path)


def _callback_check_integrated_validator_publish(
    _state_check_integrated_validator_1251, transaction, /, *args, **kwargs
):
    result = transaction(*args, **kwargs)
    _state_check_integrated_validator_1251.published = True
    return result


@pytest.mark.parametrize("initial", [False, True])
def check_integrated_validator(generated_policy, initial):
    _state_check_integrated_validator_1251 = _CallbackState()
    root, model, values, design, artifact, register = generated_policy
    env = register([design, artifact, artifact.parent / "extra.json"])
    task = root / env["BLUEPRINT_TASK_FILE"]
    task.write_text(
        task.read_text().replace(
            "## Required changes\n- [R1] Apply synthetic Model candidate\n## Acceptance checks\n- [R1] `exists:project.json`\n",
            "## Required changes\n- [R1] Generate the selected service.\n"
            "## Acceptance checks\n- [R1] `check:framework.generated-service-model`\n"
            "- [R1] `check:framework.policy-tables`\n- [R1] `exists:docs/designs/dev/123456789012/iam.md`\n",
        )
    )
    start_validator_repository(root)
    originals = {design: design.read_bytes()}
    if initial:
        shutil.rmtree(design.parent)
        assert not design.exists() and not artifact.exists()
    values["desired.note.001.text"] = "統合した生成と検証を確認する。"
    write_model(model, values)
    source_bytes = {path: path.read_bytes() for path in load_model(model).files}
    validator_module = validation_runner
    _state_check_integrated_validator_1251.published = False
    read_bytes, transaction = Path.read_bytes, sync_runtime._publish_transaction
    read = _bind_framework_callback(
        _callback_check_integrated_validator_read,
        _state_check_integrated_validator_1251,
        read_bytes,
        root,
    )
    publish = _bind_framework_callback(
        _callback_check_integrated_validator_publish,
        _state_check_integrated_validator_1251,
        transaction,
    )
    with (
        patch.dict(os.environ, env),
        patch.object(model_impact, "analyze", wraps=model_impact.analyze) as impact,
        patch.object(
            import_guard,
            "require_import_changes",
            wraps=import_guard.require_import_changes,
        ) as import_check,
        patch.object(
            sync_runtime, "_publish_transaction", side_effect=publish
        ) as publication,
        patch.object(Path, "read_bytes", read),
        patch.object(
            change_validation, "validate_plan", wraps=change_validation.validate_plan
        ) as change_check,
        patch.object(
            model_sources, "_read_model", wraps=model_sources._read_model
        ) as expand,
        patch.object(
            sync_runtime, "generate_views", wraps=sync_runtime.generate_views
        ) as generate,
        patch.object(
            sync_views, "validate_views", wraps=sync_views.validate_views
        ) as validate,
        patch.object(
            sync_runtime.GenerationInputs,
            "verify",
            autospec=True,
            side_effect=sync_runtime.GenerationInputs.verify,
        ) as verify,
        patch.object(
            validator_module.Validator,
            "check_generated_service_models",
            side_effect=AssertionError("regenerated for Acceptance"),
        ),
    ):
        validator = validator_module.Validator(
            root,
            {("dev", "123456789012", "iam")},
            write=True,
            model_validation="change",
        )
        assert validator.run() == 0, validator.errors
        assert len(validator.acceptance_results) == 3
        assert _state_check_integrated_validator_1251.published
    assert generate.call_count == verify.call_count == 1
    validate.assert_not_called()
    assert publication.call_count == 1
    assert publication.call_args.kwargs["originals"] == (
        {design: None} if initial else {design: originals[design]}
    )
    contexts = [(call.args[0], id(call.args[1])) for call in expand.call_args_list]
    assert contexts and len(contexts) == len(set(contexts)), expand.call_args_list
    print(
        "integrated write counts: Model once per input/permission context; generation=1, Change Validation=1, explicit quality checks after save"
    )
    change_check.assert_called_once()
    import_check.assert_not_called()
    impact.assert_not_called()
    assert values["desired.note.001.text"] in design.read_text()
    assert design.read_bytes() != originals[design]
    assert not artifact.exists()
    assert {path: path.read_bytes() for path in source_bytes} == source_bytes


def start_validator_repository(root):
    for name in ("AGENTS.md", "README.md", "docs/system-overview.md"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Independent fixture\n", encoding="utf-8")
    for name in (
        "infra/cloudformation/parameters/dev/123456789012",
        "tests/scenarios",
        "tests/results",
    ):
        (root / name).mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    commit(root, ["."], "Fixture")


@pytest.mark.parametrize("suffix", [".md", ".json"])
def check_view_only_migration(generated_policy, suffix):
    root, model, _, design, artifact, _ = generated_policy
    output = design if suffix == ".md" else artifact
    expected = design.read_bytes() if suffix == ".md" else None
    stale = expected + b"\n" if expected is not None else b"{}\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(stale)
    start_validator_repository(root)
    source_bytes = {path: path.read_bytes() for path in load_model(model).files}
    name = "tasks/view-refresh.md"
    relative = output.relative_to(root).as_posix()
    listed = f"- `{name}`\n- `{relative}`"
    tasks.start(
        root,
        name,
        "## Task contract\n- Task type: `migration`\n- Task status: `running`\n"
        "## Validation scope\n- `dev/123456789012/iam`\n"
        "## Required changes\n- [R1] Refresh saved View\n"
        f"## Acceptance checks\n- [R1] `{'absent' if suffix == '.json' else 'exists'}:{relative}`\n"
        f"## Modified files\n{listed}\n## Allowed paths\n{listed}\n",
    )
    scope = {("dev", "123456789012", "iam")}
    with tasks.selected_task(root, name):
        validator = validation_runner.Validator(root, scope, model_validation="change")
        assert validator.run() == 1
        assert any(
            f"is stale or missing: {relative}" in error for error in validator.errors
        )
        assert output.read_bytes() == stale

        validator = validation_runner.Validator(
            root, scope, model_validation="change", write=True
        )
        assert validator.run() == 0, validator.errors
        assert (output.read_bytes() if output.exists() else None) == expected

        validator = validation_runner.Validator(root, scope, model_validation="change")
        assert validator.run() == 0, validator.errors
        assert not validator.change_plan.views
    assert {path: path.read_bytes() for path in source_bytes} == source_bytes


def _callback_check_multiple_targets_barrier_validated(
    design,
    events,
    failure,
    log_design,
    log_model,
    original,
    validate,
    /,
    plan,
    **kwargs,
):
    TestCase().assertEqual(len(plan.generated), 1 if "none" == "candidate" else 2)
    assert design.read_bytes() == original and (not log_design.exists())
    validate(plan, **kwargs)
    events.append("validated")


def _callback_check_multiple_targets_barrier_read(
    _state_check_multiple_targets_barrier_1436, failure, read_bytes, root, /, path
):
    if (
        _state_check_multiple_targets_barrier_1436.published
        and "none" == "none"
        and path.is_relative_to(root)
    ):
        raise AssertionError("normal post-save input/output read: " + str(path))
    return read_bytes(path)


def _callback_check_multiple_targets_barrier_publish(
    _state_check_multiple_targets_barrier_1436,
    design,
    events,
    failure,
    log_design,
    transaction,
    /,
    *args,
    **kwargs,
):
    assert events == ["validated"]
    result = transaction(*args, **kwargs)
    _state_check_multiple_targets_barrier_1436.published = True
    return result


def check_multiple_targets_barrier(generated_policy):
    _state_check_multiple_targets_barrier_1436 = _CallbackState()
    root, model, values, design, artifact, register = generated_policy
    scope = {("dev", "123456789012", "iam"), ("stg", "123456789012", "logs")}
    project = json.loads((root / "project.json").read_text())
    project["targets"].append({**project["targets"][0], "environment": "stg"})
    (root / "project.json").write_text(json.dumps(project) + "\n")
    log_model = root / "model/stg/123456789012/logs.properties"
    log_values = {
        "desired.service.logs.serviceId": "logs",
        "desired.service.logs.ownedCatalogResourceTypes": "Logs.LogGroup",
        "display.service.title": "# Logs 詳細設計",
        "desired.resource.001.resourceType": "Logs.LogGroup",
        "display.resource.001.comment": "アプリケーションの実行ログ",
        "desired.row.001-001.property": "Logs.LogGroup.LogGroupName",
        "desired.row.001-001.value": "`cwlogs-app-stg`",
        "desired.row.001-001.comment": "ログを識別する名前",
    }
    log_values["desired.resource.001.cfn-logicalId"] = "cfn-stack-app-dev-iam-Log"
    write_model(
        log_model.with_name("cloudformation-stacks.properties"),
        dict(
            load_model(
                model.with_name("cloudformation-stacks.properties")
            ).authoritative
        ),
    )
    log_values.update(allocate(log_values, ["001"]))
    write_model(log_model, log_values)
    log_design = root / "docs/designs/stg/123456789012/logs.md"
    env = register([design, artifact, log_design])
    task = root / env["BLUEPRINT_TASK_FILE"]
    task.write_text(
        task.read_text().replace(
            "- `dev/123456789012/iam`\n",
            "- `dev/123456789012/iam`\n- `stg/123456789012/logs`\n",
            1,
        )
    )
    original = design.read_bytes()
    values["desired.note.001.text"] = "先行対象も後続の確認を待つ。"
    write_model(model, values)
    events = []
    validate, transaction = (
        sync_runtime.validate_generation,
        sync_runtime._publish_transaction,
    )
    validated = _bind_framework_callback(
        _callback_check_multiple_targets_barrier_validated,
        design,
        events,
        "none",
        log_design,
        log_model,
        original,
        validate,
    )
    _state_check_multiple_targets_barrier_1436.published = False
    read_bytes = Path.read_bytes
    read = _bind_framework_callback(
        _callback_check_multiple_targets_barrier_read,
        _state_check_multiple_targets_barrier_1436,
        "none",
        read_bytes,
        root,
    )
    publish = _bind_framework_callback(
        _callback_check_multiple_targets_barrier_publish,
        _state_check_multiple_targets_barrier_1436,
        design,
        events,
        "none",
        log_design,
        transaction,
    )
    with (
        patch.dict(os.environ, env),
        patch.object(sync_runtime, "validate_generation", side_effect=validated),
        patch.object(
            sync_runtime, "_publish_transaction", side_effect=publish
        ) as saved,
        patch.object(
            sync_runtime, "stage_inputs", wraps=sync_runtime.stage_inputs
        ) as stages,
        patch.object(Path, "read_bytes", read),
    ):
        assert sync_runtime.run_generation(root, scope) == 0
        assert saved.call_count == 2 and log_design.is_file()
        assert stages.call_count == 1


if __name__ == "__main__":
    raise SystemExit(main())
