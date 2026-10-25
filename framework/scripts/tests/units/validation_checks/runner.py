"""Responsibility boundaries: dispatch, mutable findings, callbacks and import safety."""

import io
from contextlib import ExitStack, redirect_stdout
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState
from unittest.mock import patch

from support.validator import MODULE, SCRIPT, project, write
from utils.input_cache import input_context


def _callback_check_dispatch_run_check(_state_check_dispatch_13, /, name):
    _state_check_dispatch_13.invoked.append(name)
    if name == "check_task_scope":
        (
            _state_check_dispatch_13.validator.task_type,
            _state_check_dispatch_13.validator.infrastructure_phase,
        ) = _state_check_dispatch_13.task_type, _state_check_dispatch_13.phase
    if _state_check_dispatch_13.failed and name == "check_model_files":
        _state_check_dispatch_13.validator.check(False, "prior model error")


def check_dispatch():
    _state_check_dispatch_13 = _CallbackState()
    common = [
        "check_structure",
        "check_task_scope",
        "check_project_topology",
        "check_validation_scope",
        "check_model_files",
        "check_issue_gate",
        "check_initialized_paths",
        "check_catalog",
        "check_resource_layout",
    ]
    cases = [
        (
            None,
            "",
            "",
            False,
            [
                "check_designs",
                "check_observed_values",
                "check_iac_selection",
                "check_cloudformation_yaml_rules",
                "check_cloudformation_environment_parameters",
                "check_scenarios",
                "check_results",
                "check_scenario_changes",
            ],
        ),
        (set(), "governance", "", False, ["check_iac_selection"]),
        ({("dev", "target", "ec2")}, "design", "", True, ["check_iac_selection"]),
        (
            set(),
            "infrastructure",
            "implement",
            False,
            [
                "check_iac_selection",
                "check_cloudformation_yaml_rules",
                "check_cloudformation_environment_parameters",
            ],
        ),
        (set(), "infrastructure", "destroy", False, []),
        (
            set(),
            "scenario-test",
            "",
            False,
            [
                "check_iac_selection",
                "check_scenarios",
                "check_results",
                "check_scenario_changes",
            ],
        ),
    ]
    methods = set(common + ["check_task_type_requirements", "check_acceptance_checks"])
    methods.update(name for *_, tail in cases for name in tail)
    with project() as root:
        for (
            scope,
            _state_check_dispatch_13.task_type,
            _state_check_dispatch_13.phase,
            _state_check_dispatch_13.failed,
            tail,
        ) in cases:
            _state_check_dispatch_13.validator = MODULE.Validator(root, scope)
            _state_check_dispatch_13.invoked = []
            run_check = _bind_framework_callback(
                _callback_check_dispatch_run_check, _state_check_dispatch_13
            )
            with ExitStack() as stack, redirect_stdout(io.StringIO()):
                stack.enter_context(
                    patch.object(
                        _state_check_dispatch_13.validator.task,
                        "fix_baseline",
                        lambda *,
                        invoked=_state_check_dispatch_13.invoked: invoked.append(
                            "fix_baseline"
                        ),
                    )
                )
                for name in methods:
                    stack.enter_context(
                        patch.object(
                            _state_check_dispatch_13.validator,
                            name,
                            lambda name=name, run_check=run_check: run_check(name),
                        )
                    )
                assert _state_check_dispatch_13.validator.run() == int(
                    _state_check_dispatch_13.failed
                )
            assert _state_check_dispatch_13.invoked == [
                "fix_baseline"
            ] + common + tail + ["check_acceptance_checks"], (
                _state_check_dispatch_13.invoked
            )


def check_boundaries():
    with project() as root:
        template = root / "infra/cloudformation/templates/existing.yaml"
        write(template, "Resources: {}\n")
        framework = MODULE.Validator(root, set())
        with patch.object(MODULE.iac, "check_iac_selection") as selection:
            framework.check_iac_selection()
            selection.assert_not_called()
        assert not framework.errors
        overall = MODULE.Validator(root, None)
        overall.check_iac_selection()
        assert "template mode contains cloudformation implementation" in overall.errors
        consumer = MODULE.Validator(root, {("dev", "cde", "ec2")})
        consumer.template_mode = False
        consumer.accounts = {("dev", "cde"): {"engine": "terraform", "alias": "cde"}}
        consumer.check_iac_selection()
        assert (
            "unselected IaC engine directory remains: cloudformation" in consumer.errors
        )
    with project() as root:
        path = root / "own.yaml"
        first, second = MODULE.Validator(root, set()), MODULE.Validator(root, set())
        first.check_file(False, path, "unresolved")
        first.check_file(False, path, "file failure")
        first.check(False, "global")
        assert first.errors == ["unresolved", "file failure", "global"]
        assert first.checks == 3
        assert first.errors is first.findings.errors
        first.errors = list(first.errors)
        assert first.errors is first.findings.errors
        assert not second.errors and second.checks == 0
        first.task.changed_paths.add("own.yaml")
        assert first.changed_paths == {"own.yaml"} and not second.changed_paths
        first.acceptance_checks = [
            ("R1", "check", "framework.resource-layout"),
            ("R2", "check", "unknown"),
            ("R3", "changed", "pending.md"),
        ]
        with patch.object(
            first,
            "check_resource_layout",
            side_effect=lambda: first.check(False, "handler failed"),
        ) as handler:
            first.check_acceptance_checks()
            handler.assert_called_once_with()
        assert first.errors[-4:] == [
            "handler failed",
            "Acceptance check is FAIL: R1: framework.resource-layout",
            "unknown registered Acceptance check: R2: unknown",
            "required changed path missing: R3: pending.md",
        ]
        assert not first.acceptance_results
        # A failed read keeps Project's already-determined mode and propagates failure.
        write(root / "project.json", "{}\n")
        second.scope = None
        with patch.object(
            Path, "read_text", side_effect=OSError("cannot read")
        ) as read:
            try:
                second.check_project_topology()
            except OSError as error:
                assert str(error) == "cannot read" and not second.template_mode
            else:
                raise AssertionError("read failure was hidden")
            read.assert_called_once_with(encoding="utf-8", errors=None)
        scope = {("dev", "target", "ec2")}
        first.schema_catalog = MODULE.DesignSchemaCatalog(SCRIPT.parents[2])
        with (
            patch.object(first, "check_design_service_ownership") as ownership,
            patch.object(first, "check_stack_designs") as stacks,
            patch.object(
                MODULE.Validator,
                "check_designs",
                side_effect=RuntimeError("child failed"),
            ) as child,
        ):
            first.scope = scope
            first.check_scoped_designs()
            assert any(
                error["exception"] == "RuntimeError"
                and "child failed" in error["message"]
                for error in first.findings.processing_errors
            )
            assert first.findings.result("design.service", scope).status == "FAIL"
            ownership.assert_called_once()
            stacks.assert_called_once()
            child.assert_called_once_with()


def check_common_cache_guard():
    state = _CallbackState(task_type="governance", phase="", failed=False, invoked=[])
    methods = (
        "check_structure",
        "check_task_scope",
        "check_project_topology",
        "check_validation_scope",
        "check_model_files",
        "check_issue_gate",
        "check_initialized_paths",
        "check_resource_layout",
        "check_iac_selection",
        "check_acceptance_checks",
    )
    with (
        project() as root,
        input_context(),
        ExitStack() as lifetime,
        redirect_stdout(io.StringIO()),
    ):
        state.validator = MODULE.Validator(root, set(), cache=True)
        validator = state.validator
        run_check = _bind_framework_callback(_callback_check_dispatch_run_check, state)
        for name in methods:
            lifetime.enter_context(
                patch.object(validator, name, _bind_framework_callback(run_check, name))
            )
        lifetime.enter_context(patch.object(validator.task, "fix_baseline"))
        common = lifetime.enter_context(
            patch.object(
                validator.cache, "common_key", wraps=validator.cache.common_key
            )
        )
        catalog = lifetime.enter_context(
            patch.object(
                validator,
                "check_catalog_inputs",
                side_effect=_bind_framework_callback(validator.check, True, "catalog"),
            )
        )
        assert validator.run() == 0
        assert validator.run() == 0
        assert common.call_count == 4  # One initial key and one final guard per run.
        catalog.assert_called_once()
