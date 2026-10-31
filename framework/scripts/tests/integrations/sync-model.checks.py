#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as _CallbackState

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
import model.core as _model_validation_core
import model.impact as model_impact
import model.render as model_design
import model.sources as _imports_model_sources
import model.sources as model_sources
import model.validations.full_inputs as _model_validation_full_inputs
import model.validations.identity as _model_validation_identity
import pytest
import support.sync_model_fixtures as _fixture_generated_policy
import sync_files as _imports_sync_files
import sync_progress as progress
import sync_runtime
import sync_views
import task_contract_core as tasks
import task_contract_runtime as task_runtime
from design.document import DesignIndex
from model.files import load_model, read_model
from support.model_reference_fixtures import reference, resource, save
from support.model_sources import allocate_fixture as allocate
from support.model_sources import write_model as write_model
from support.model_templates_fixtures import config_model, fixture, write_fixture
from support.pytest_cli import run
from support.sync_model_fixtures import MODULE
from support.validator import diagnostics, load
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
    originals = {p: p.read_bytes() for p in (design, artifact)}
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
    originals = {p: p.read_bytes() for p in (model, design, artifact)}
    with mapping_alias(root, stage):
        sync_runtime.stage_inputs(
            stage, root, {design: values}, [model], [design], ["iam"], False
        )
        write_model(
            stage / model.relative_to(root),
            values | {"desired.service.iam.serviceId": "s3"},
        )
        validator = sync_views.view_validator(stage, root)
        validator.scope = {("dev", "123456789012", "iam")}
        validator.check_project_topology()
        staged.write_text(
            staged.read_text(encoding="utf-8") + "\n[参照先](missing.md#missing)\n",
            encoding="utf-8",
        )
        metadata, *catalog = validator.check_design_service_ownership([staged])
        validator.check_resource_names(metadata, [staged])
        validator.check_design_tables(metadata, *catalog, [staged])
        validator.check_design_overviews([staged])
        validator.check_design_links(catalog[2], [staged])
        validator.check_policy_tables()
        errors = diagnostics(validator)
        assert any("model service" in error for error in errors), errors
        assert any("broken design link" in error for error in errors), errors
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
        # Only the staged stack authority changes; the saved stack remains valid.
        write_model(
            stage / stack_model.relative_to(root),
            stacks | {"desired.stack.001.name": "cfn-stack-other-dev-iam"},
        )
        with pytest.raises(ValueError, match="undeclared stack"):
            _model_validation_identity.validate_resource_identities(
                staged,
                values,
                stage,
                _model_validation_core.entries(values, "desired.resource."),
                definitions_root=definition_root(root),
            )
        validator = sync_views.view_validator(stage, root)
        validator.scope = {("dev", "123456789012", "cloudformation-stacks")}
        validator.check_project_topology()
        staged_stack.write_text(
            expected_stack.decode("utf-8").replace(
                "cfn-stack-app-dev-iam", "cfn-stack-other-dev-iam"
            ),
            encoding="utf-8",
        )
        validator.check_stack_designs([staged_stack])
        assert any("undeclared stack" in error for error in validator.errors), (
            validator.errors
        )
    assert (
        stack_design.read_bytes() == expected_stack
        and not (stage / "framework").exists()
    )


def _callback_check_publication_boundary_mutate_before_save(
    _state_check_publication_boundary_349, model, validate, /, *args, **kwargs
):
    result = validate(*args, **kwargs)
    target = model
    _state_check_publication_boundary_349.concurrent = (
        target,
        (target.read_bytes() if target.exists() else b"") + b"\n",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_state_check_publication_boundary_349.concurrent[1])
    return result


def check_publication_boundary(generated_policy):
    _state_check_publication_boundary_349 = _CallbackState()
    root, model, values, design, artifact, register = generated_policy
    values["desired.note.001.text"] = "保存前の一括照合を確認する。"
    write_model(model, values)
    env = register([design, artifact])
    originals = {file: file.read_bytes() for file in (design, artifact)}
    validate = sync_runtime.validate_generation
    _state_check_publication_boundary_349.concurrent = None

    mutate_before_save = _bind_framework_callback(
        _callback_check_publication_boundary_mutate_before_save,
        _state_check_publication_boundary_349,
        model,
        validate,
    )
    with (
        patch.dict(os.environ, env),
        patch.object(
            sync_runtime, "validate_generation", side_effect=mutate_before_save
        ),
        patch.object(
            sync_runtime,
            "_publish_transaction",
            side_effect=AssertionError("published before input comparison"),
        ),
    ):
        with pytest.raises(ValueError, match="inputs changed"):
            MODULE.sync(root, True, "dev", "123456789012", ["iam"])
    assert {file: file.read_bytes() for file in originals} == originals
    assert (
        _state_check_publication_boundary_349.concurrent[0].read_bytes()
        == _state_check_publication_boundary_349.concurrent[1]
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
    assert json.loads(artifact.read_text()) == json.loads(
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
    before = artifact.read_bytes(), artifact.stat().st_mtime_ns
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
    assert (artifact.read_bytes(), artifact.stat().st_mtime_ns) == before


def _fail_pending_write(original, target, /, path, *args, **kwargs):
    if path == target:
        raise OSError("injected pending Markdown write failure")
    return original(path, *args, **kwargs)


@pytest.mark.parametrize("failure", [None, "write", "artifact"])
def check_pending_artifact_transaction(generated_policy, failure):
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
    # This fixture uses dev, while the shared reference helper defaults to qa.
    producer = model_sources.Scope(root, "dev", "123456789012", "kms")
    save(producer, key)
    document["Statement"][0]["Resource"][1] = reference()
    values["desired.row.001-004.document"] = json.dumps(document)
    write_model(model, values)
    originals = {p: p.read_bytes() for p in (design, trust, artifact)}
    authority = {p: p.read_bytes() for p in (model, producer.path)}
    with patch.dict(os.environ, register({design, trust, artifact})):
        with sync_runtime.generation_context(root, True):
            plan = sync_runtime.prepare_generation(
                root, {("dev", "123456789012", "iam")}
            )
            try:
                assert not plan.failures and not plan.unavailable
                assert design in plan.generated
                sync_runtime.validate_generation(plan, jobs=1)
                metadata = sync_runtime.generation_metadata(plan)
                assert metadata["status"] == "PASS" and metadata["complete"]
                assert not metadata["unverified"]
                assert any(
                    warning.get("category") == "REFERENCE_PENDING_DEPLOY"
                    for warning in metadata["warnings"]
                )
                candidate = plan.expected_outputs[design]
                assert (
                    json.loads(candidate[artifact])["Statement"][0]["Resource"][1]
                    == "PENDING_DEPLOY"
                )
                assert "[KMS.Key](kms.md#saved-001)" in candidate[design]
                with ExitStack() as injections:
                    if failure:
                        injections.enter_context(
                            patch.object(
                                Path,
                                "write_text",
                                autospec=True,
                                side_effect=_bind_framework_callback(
                                    _fail_pending_write,
                                    Path.write_text,
                                    artifact if failure == "artifact" else design,
                                ),
                            )
                        )
                    sync_runtime.publish_generation(plan)
                if failure:
                    assert plan.failures and not plan.saved
                    assert {p: p.read_bytes() for p in originals} == originals
                else:
                    assert not plan.failures and design in plan.saved
                    assert artifact.read_text(encoding="utf-8") == candidate[artifact]
                    assert design.read_text(encoding="utf-8") == candidate[design]
                    assert trust.read_bytes() == originals[trust]
            finally:
                plan.close()
        assert {p: p.read_bytes() for p in authority} == authority
        originals = {p: p.read_bytes() for p in originals}
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
                assert not plan.failures and not plan.unavailable, plan.failures
                sync_runtime.validate_generation(plan, jobs=1)
                metadata = sync_runtime.generation_metadata(plan)
                assert metadata["status"] == "PASS" and metadata["complete"] is True
                assert not metadata["unverified"]
                candidate = plan.expected_outputs[design]
                assert (
                    json.loads(candidate[artifact]) == expected and trust in candidate
                )
                assert "iam/iam-role-001-pending.json" in candidate[design]
                assert (
                    "$modelRef" not in candidate[design]
                    and "confirmed-bucket" in candidate[design]
                )
                with ExitStack() as injections:
                    if failure == "artifact":
                        injections.enter_context(
                            patch.object(
                                Path,
                                "write_text",
                                autospec=True,
                                side_effect=_bind_framework_callback(
                                    _fail_pending_write, Path.write_text, artifact
                                ),
                            )
                        )
                    elif failure == "write":
                        injections.enter_context(
                            patch.object(
                                Path,
                                "write_text",
                                autospec=True,
                                side_effect=_bind_framework_callback(
                                    _fail_pending_write, Path.write_text, design
                                ),
                            )
                        )
                    sync_runtime.publish_generation(plan)
                if failure:
                    assert plan.failures and not plan.saved
                    assert {p: p.read_bytes() for p in originals} == originals
                else:
                    assert (
                        not plan.failures
                        and json.loads(artifact.read_bytes()) == expected
                    )
                    assert trust.read_bytes() == originals[trust]
                    assert design.read_text(encoding="utf-8") == candidate[design]
                    assert not list(root.glob(".model-publication*.json"))
            finally:
                plan.close()
        assert {p: p.read_bytes() for p in authority} == authority
        assert "$modelRef" in values["desired.row.001-004.document"]
        if not failure:
            assert "PENDING_DEPLOY" not in artifact.read_text(encoding="utf-8")


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
    assert publish.call_count == 1 and set(publish.call_args.args[1]) == {artifact}
    assert json.loads(artifact.read_text()) == json.loads(
        values["desired.row.001-002.document"]
    )
    assert design.read_bytes() == before, "sidecar-only change must preserve Markdown"


def _callback_check_publication_rechecks_excluded_outputs_mutate(
    changed, content, validate, /, *args, **kwargs
):
    result = validate(*args, **kwargs)
    changed.write_text(content, encoding="utf-8")
    return result


@pytest.mark.parametrize("note", [False, True])
def check_publication_rechecks_excluded_outputs(generated_policy, note):
    root, model, values, design, artifact, register = generated_policy
    if note:
        values["desired.note.001.text"] = "公開前に変更の競合を確認する。"
        write_model(model, values)
    env = register([design] if note else [])
    original = design.read_bytes()
    changed, content = artifact, "{}\n"
    validate = sync_runtime.validate_generation
    mutate = _bind_framework_callback(
        _callback_check_publication_rechecks_excluded_outputs_mutate,
        changed,
        content,
        validate,
    )
    with (
        patch.dict(os.environ, env),
        patch.object(sync_runtime, "validate_generation", side_effect=mutate),
    ):
        with pytest.raises(ValueError, match="inputs changed"):
            MODULE.sync(root, True, "dev", "123456789012", ["iam"])
    assert design.read_bytes() == original
    assert changed.read_text(encoding="utf-8") == content


def _callback_check_changed_sidecar_publication_rollback_fail_markdown(
    artifact, before, design, note, write, /, path, *args, **kwargs
):
    if path == design:
        if note:
            write(artifact, "{}\n", encoding="utf-8")
        else:
            assert artifact.read_bytes() != before[artifact]
        write(path, "partial Markdown", encoding="utf-8")
        raise OSError("injected Markdown publication failure")
    return write(path, *args, **kwargs)


@pytest.mark.parametrize("note", [False, True])
def check_changed_sidecar_publication_rollback(generated_policy, note):
    root, model, values, design, artifact, register = generated_policy
    before = {file: file.read_bytes() for file in (design, artifact)}
    if note:
        values["desired.note.001.text"] = "注記だけの公開もロールバックする。"
    else:
        document = json.loads(values["desired.row.001-002.document"])
        document["Statement"][0]["Sid"] = "Changed"
        values["desired.row.001-002.document"] = json.dumps(document)
    write_model(model, values)
    env = register([design] if note else [design, artifact])
    write = Path.write_text

    fail_markdown = _bind_framework_callback(
        _callback_check_changed_sidecar_publication_rollback_fail_markdown,
        artifact,
        before,
        design,
        note,
        write,
    )

    with patch.dict(os.environ, env), patch.object(Path, "write_text", fail_markdown):
        with pytest.raises(ValueError, match="injected Markdown publication failure"):
            MODULE.sync(root, True, "dev", "123456789012", ["iam"])
    assert design.read_bytes() == before[design]
    assert artifact.read_bytes() == (b"{}\n" if note else before[artifact])
    if note:
        artifact.write_bytes(before[artifact])
    with patch.dict(os.environ, env):
        assert MODULE.sync(root, True, "dev", "123456789012", ["iam"]) == 0


def check_unchanged_sidecar_validation(generated_policy):
    root, model, values, design, artifact, register = generated_policy
    env = register([])
    before = {file: file.read_bytes() for file in (design, artifact)}
    with (
        patch.dict(os.environ, env),
        patch.object(
            sync_runtime,
            "validate_generation",
            side_effect=ValueError("injected candidate generation failure"),
        ),
        patch.object(
            sync_runtime,
            "_publish_transaction",
            side_effect=AssertionError("invalid candidate published"),
        ),
    ):
        with pytest.raises(ValueError, match="injected candidate generation failure"):
            MODULE.sync(root, True, "dev", "123456789012", ["iam"])
    assert {file: file.read_bytes() for file in before} == before


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


def check_required_preflight(project_workspace) -> None:
    root = project_workspace
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
    model = root / "model/dev/123456789012/quicksight.properties"
    model.parent.mkdir(parents=True)
    values = {
        "desired.service.quicksight.serviceId": "quicksight",
        "desired.service.quicksight.ownedCatalogResourceTypes": "QuickSight.DataSource",
        "desired.resource.001.resourceType": "QuickSight.DataSource",
        "display.service.title": "# QuickSight 詳細設計",
        "display.resource.001.comment": "分析用データソース",
        "desired.row.001-001.property": "QuickSight.DataSource.Name",
        "desired.row.001-001.value": "`qs-app-dev-athena`",
        "desired.row.001-001.comment": "データソースの名前",
        "desired.row.001-002.property": "QuickSight.DataSource.Credentials.KeyPairCredentials",
        "desired.row.001-002.value": "[設定](quicksight/credentials.json)",
        "desired.row.001-002.document": '{"KeyPairUsername":"test","PrivateKey":"test"}',
        "desired.row.001-002.comment": "接続の認証設定",
    }
    values.update(allocate(values, ["001"]))
    source = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    write_model(model, source)
    source = read_model(model)
    design = root / "docs/designs/dev/123456789012/quicksight.md"
    artifact = design.with_suffix("") / "credentials.json"
    artifact.parent.mkdir(parents=True)
    design.write_text("existing Markdown\n")
    artifact.write_text("existing JSON\n")
    checked = _model_validation_full_inputs.check_model_inputs(
        model, load_model(model).values, root
    )
    assert any("QuickSight.DataSource.Type" in error for error in checked.errors), (
        checked.errors
    )
    assert (
        design.read_text() == "existing Markdown\n"
        and artifact.read_text() == "existing JSON\n"
    )
    with patch.object(
        _model_validation_full_inputs,
        "check_model_inputs",
        side_effect=AssertionError("generation ran Full quality validation"),
    ):
        assert MODULE.sync(root, True, "dev", "123456789012") == 0
    assert read_model(model) == source
    design.write_text("existing Markdown\n")
    artifact.write_text("existing JSON\n")
    invalid = dict(load_model(model).authoritative)
    del invalid["desired.row.001-002.document"]
    write_model(model, invalid)
    # An unrelated valid service still saves while the incomplete one fails.
    stack = model.with_name("cloudformation-stacks.properties")
    write_model(
        stack,
        "desired.stack.001.name=cfn-stack-app-dev-general-01\n"
        "desired.stack.001.template=app.yaml\n"
        "desired.stack.001.parameters=app.json\n"
        "desired.stack.001.deployOrder=10\n"
        "display.stack.001.comment=アプリケーションのstack\n",
    )
    with redirect_stdout(io.StringIO()):
        with pytest.raises(ValueError) as error:
            MODULE.sync(root, True, "dev", "123456789012")
        assert (
            "1 services succeeded; 1 services failed; 0 services unavailable; 1 diagnostics"
            in str(error.value)
        ), error.value
    assert design.with_name("cloudformation-stacks.md").is_file()
    assert (
        design.read_text() == "existing Markdown\n"
        and artifact.read_text() == "existing JSON\n"
    )
    print(
        "Required-property preflight: PASS (read/write preservation, partial success)"
    )


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
        artifact,
        root / "docs/designs/stg/123456789012/iam.md",
        root / "docs/designs/stg/123456789012/iam/iam-role-001-trust-policy.json",
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
        with patch.object(
            sys,
            "argv",
            [
                "sync-model.py",
                "--repository-root",
                str(root),
                "--scope",
                "prod/123456789012/iam",
            ],
        ):
            assert cli.main() == 1
    assert "sync-model progress:" not in stdout.getvalue()
    assert "stage=impact-scope" in stderr.getvalue()
    assert "completed=2/2" in stderr.getvalue()
    assert "state=failed" in stderr.getvalue()
    for document in (outputs[0], outputs[2]):
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
    jobs = 4
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


def check_internal_sync_real_diagnostics(internal_sync_project, capsys):
    runner = module("sync-model.py", "blueprint_sync_model")
    root = internal_sync_project
    scope = {(env, "team", "config") for env in ("dev", "stg")}
    args = [arg for entry in sorted(scope) for arg in ("--scope", "/".join(entry))]
    code, text = runner.run(["--scope", "dev/team/config"], repository_root=root)
    assert (
        code == 1
        and "include all affected Model services" in text
        and "stg/team/config" in text
    )
    design = root / "docs/designs/dev/team/config.md"
    saved = design.read_bytes()
    design.write_bytes(saved + b"old generated output\n")
    capsys.readouterr()
    code, text = runner.run(args, repository_root=root)
    assert code == 1 and "generated Markdown is stale or missing" in text
    assert "docs/designs/dev/team/config.md" in text
    validator = validation_runner.Validator(root, scope)
    validator.check_generated_service_models()
    assert any(
        "generated Markdown is stale or missing" in error
        and "dev/team/config.md" in error
        for error in validator.errors
    ), validator.errors
    design.write_bytes(saved)
    assert runner.run(args, repository_root=root)[0] == 0
    assert capsys.readouterr() == ("", "")


def _callback_check_integrated_validator_fail_write(
    design, write, /, path, *args, **kwargs
):
    if path == design:
        write(path, "partial output", encoding="utf-8")
        raise OSError("injected publication I/O")
    return write(path, *args, **kwargs)


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
    for name in ("AGENTS.md", "README.md", "docs/system-overview.md"):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# Independent fixture\n")
    for name in (
        "infra/cloudformation/parameters/dev/123456789012",
        "tests/scenarios",
        "tests/results",
    ):
        (root / name).mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Fixture",
        ],
        cwd=root,
        check=True,
    )
    originals = {path: path.read_bytes() for path in (design, artifact)}
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
        {design: None, artifact: None} if initial else {design: originals[design]}
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
    assert artifact.read_bytes() == originals[artifact]
    assert {path: path.read_bytes() for path in source_bytes} == source_bytes


def check_integrated_validator_publication_failure(generated_policy):
    root, model, values, design, artifact, register = generated_policy
    env = register([design, artifact])
    task = root / env[tasks.SELECTOR]
    task.write_text(
        task.read_text().replace(
            "## Required changes\n- [R1] Apply synthetic Model candidate\n## Acceptance checks\n- [R1] `exists:project.json`\n",
            "## Required changes\n- [R1] Publish the service.\n"
            "## Acceptance checks\n- [R1] `check:framework.policy-tables`\n",
        )
    )
    originals = {p: p.read_bytes() for p in (design, artifact)}
    validator_module = validation_runner
    fail_write = _bind_framework_callback(
        _callback_check_integrated_validator_fail_write, design, Path.write_text
    )
    candidate_policy_check = _bind_framework_callback(
        _callback_check_integrated_validator_candidate_policy_check,
        validator_module.Validator.check_policy_tables,
        root,
    )
    for name in ("AGENTS.md", "README.md", "docs/system-overview.md"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Independent fixture\n")
    for name in (
        "infra/cloudformation/parameters/dev/123456789012",
        "tests/scenarios",
        "tests/results",
    ):
        (root / name).mkdir(parents=True, exist_ok=True)
    # A normal Git baseline is needed by the real Validator's Task boundary.
    for arguments in [
        ("init", "-q"),
        ("add", "."),
        (
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Fixture",
        ),
    ]:
        subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)
    values["desired.note.001.text"] = "保存失敗時にもModel入力を保持する。"
    write_model(model, values)
    with (
        patch.dict(os.environ, env),
        patch.object(Path, "write_text", fail_write),
        patch.object(
            validator_module.Validator, "check_policy_tables", candidate_policy_check
        ),
    ):
        failed = validator_module.Validator(
            root,
            {("dev", "123456789012", "iam")},
            write=True,
            model_validation="change",
        )
        assert failed.run() == 1
    assert originals == {p: p.read_bytes() for p in originals}
    assert any("injected publication I/O" in error for error in failed.errors)
    assert not any(
        "framework.policy-tables" in result for result in failed.acceptance_results
    )
    assert (
        load_model(model).values["desired.note.001.text"]
        == values["desired.note.001.text"]
    )


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
    assert len(plan.generated) == (1 if failure == "candidate" else 2)
    assert design.read_bytes() == original and not log_design.exists()
    validate(plan, **kwargs)
    events.append("validated")
    if failure == "input":
        source = log_model
        source.write_bytes(source.read_bytes() + b"\n")


def _callback_check_multiple_targets_barrier_publish_failed_write(
    design, write, /, path, *a, **kw
):
    if path == design:
        write(path, "partial output", encoding="utf-8")
        raise OSError("injected write failure")
    return write(path, *a, **kw)


def _callback_check_multiple_targets_barrier_read(
    _state_check_multiple_targets_barrier_1436, failure, read_bytes, root, /, path
):
    if (
        _state_check_multiple_targets_barrier_1436.published
        and failure == "none"
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
    if failure == "io" and log_design in args[1]:
        raise OSError("injected late target I/O")
    if failure == "rollback":
        _state_check_multiple_targets_barrier_1436.journal = args[3]
        sync_files = _imports_sync_files
        write = Path.write_text
        failed_write = _bind_framework_callback(
            _callback_check_multiple_targets_barrier_publish_failed_write, design, write
        )
        with (
            patch.object(Path, "write_text", failed_write),
            patch.object(
                sync_files,
                "restore_files",
                side_effect=OSError("injected restore failure"),
            ),
        ):
            return transaction(*args, **kwargs)
    result = transaction(*args, **kwargs)
    _state_check_multiple_targets_barrier_1436.published = True
    return result


@pytest.mark.parametrize("failure", ["none", "input", "candidate", "io", "rollback"])
def check_multiple_targets_barrier(generated_policy, failure):
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
    if failure == "candidate":
        del log_values["desired.row.001-001.value"]
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
        failure,
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
        failure,
        read_bytes,
        root,
    )
    publish = _bind_framework_callback(
        _callback_check_multiple_targets_barrier_publish,
        _state_check_multiple_targets_barrier_1436,
        design,
        events,
        failure,
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
        if failure == "input":
            with pytest.raises(ValueError, match="inputs changed"):
                sync_runtime.run_generation(root, scope)
            assert (
                not saved.called
                and design.read_bytes() == original
                and not log_design.exists()
            )
        elif failure == "rollback":
            with pytest.raises(
                ValueError, match="rollback incomplete; recovery journal retained"
            ):
                sync_runtime.run_generation(root, scope)
            assert saved.call_count == 1 and not log_design.exists()
            assert _state_check_multiple_targets_barrier_1436.journal.is_file()
            record = json.loads(
                _state_check_multiple_targets_barrier_1436.journal.read_text()
            )
            assert record["root"] == str(root.resolve()) and record["originals"]
            publication_lock = _imports_model_sources.publication_lock
            with publication_lock(root) as journal:
                assert not journal.exists() and design.read_bytes() == original
        elif failure in {"candidate", "io"}:
            with pytest.raises(
                ValueError, match="1 services succeeded; 1 services failed"
            ):
                sync_runtime.run_generation(root, scope)
            assert (
                not log_design.exists()
                and values["desired.note.001.text"] in design.read_text()
            )
        else:
            assert sync_runtime.run_generation(root, scope) == 0
            assert saved.call_count == 2 and log_design.is_file()
        assert stages.call_count == 1


if __name__ == "__main__":
    raise SystemExit(main())
