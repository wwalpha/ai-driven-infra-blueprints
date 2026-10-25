#!/usr/bin/env python3
"""Deterministic local validator for a generic infrastructure blueprint."""

from __future__ import annotations

import argparse as argparse
import os as os
import subprocess as subprocess
import sys as sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, nullcontext
from dataclasses import replace
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

import deploy.inputs as _imports_deploy_inputs
import generation_inputs as _imports_generation_inputs
import model.core as _exports_model_core
import model.core as _imports_model_core
import model.sources as _imports_model_sources
import model.validation as _imports_model_validation
import sync_runtime as _imports_sync_runtime
import sync_views as _imports_sync_views
import task_contract_core as _imports_task_contract
import utils.aws_mappings as _imports_utils_aws_mappings
import validation.task as _dependency_validation_task
from design.catalog import DesignSchemaCatalog
from design.document import DesignIndex
from design.layout_schema import STACK_DESIGN
from design.policy_tables import artifact_id as artifact_id
from design.policy_tables import rendered_design
from task_contract_core import SELECTOR as SELECTOR
from task_contract_core import contract_reads as contract_reads
from task_contract_core import contract_snapshot, task_reads
from task_contract_core import verify_contract_reads as verify_contract_reads
from utils.input_cache import input_is_file, input_scope, input_text, recording_inputs
from validation import (
    cloudformation,
    design,
    design_links,
    design_tables,
    framework_contracts,
    iac,
    project,
    scenario,
    terraform,
)
from validation.design import REQUIRED_NAME_PROPERTIES as REQUIRED_NAME_PROPERTIES
from validation.design import TABLE_ALIGNMENT as TABLE_ALIGNMENT
from validation.design import TABLE_HEADER as TABLE_HEADER
from validation.diagnostics import ArtifactReferences
from validation.findings import Findings, check_metadata, finish_result
from validation.framework_contracts import (
    CODEX_PROMPT_FILENAME_PATTERN as CODEX_PROMPT_FILENAME_PATTERN,
)
from validation_cache import PassCache
from validation_scope import active_scope, scoped_files

# Preserve shared fixtures and compatibility exports under their historical names.
properties = _exports_model_core.properties


rendered_policy_design = rendered_design


def owned_field(owner, name):
    """Keep the used Validator attributes attached to their specific state owner."""
    return property(
        lambda validator: getattr(getattr(validator, owner), name),
        lambda validator, value: setattr(getattr(validator, owner), name, value),
    )


def _callback_Validator_generate_and_validate_generated(plan, self, snapshot, /):
    for diagnostic in plan.reference_warnings:
        self.findings.warn(diagnostic)
    for diagnostic in plan.failure_records:
        if diagnostic.code != "generation.reference":
            self.findings.add_diagnostic(diagnostic)
    for findings in plan.validation.values():
        if findings is not None:
            self.checks += findings.checks
            self.warnings.extend(findings.warnings)
    return {
        "inputs": snapshot,
        "candidates": plan.expected_outputs,
        "validation": plan.validation,
        "complete": not plan.unavailable and not plan.failures,
        "reference_unavailable": plan.unavailable,
    }


def _callback_Validator_generate_and_validate_policy_result(plan, self, /):
    common = plan.validation.get(None)
    actual = (
        None
        if common is None
        else common.result("framework.policy-tables", plan.generated_scope)
    )
    if actual is None and plan.unavailable and not plan.failures:
        ReferenceResolutionError = _imports_model_core.ReferenceResolutionError
        raise ReferenceResolutionError(
            "policy views unavailable because reference resolution failed"
        )
    self.check(
        actual is not None
        and actual.model_completion_allowed
        and (self.scope is None or actual.scope == frozenset(plan.generated_scope)),
        "candidate policy validation is FAIL or NOT_RUN for the required scope",
    )


def _callback_Validator_check_scoped_designs_validate(self, snapshot, /, scope):
    with task_reads(self.root, snapshot=snapshot):
        validator = Validator(
            self.root,
            scope,
            definitions_root=self.definitions_root,
            check_display=self.check_display,
        )
        validator.accounts = self.accounts
        validator.schema_catalog = self.schema_catalog or DesignSchemaCatalog(
            self.definitions_root
        )
        validator.generated_models_checked = True
        validator.unavailable_views = self.unavailable_views
        validator.view_reader = self.view_reader
        validator.findings.evaluate(
            "design.service", scope, validator.check_designs, isolate=True
        )
        if not self.check_display or validator.findings.processing_errors:
            validator.check_source_inputs(next(iter(scope)))
        validator.findings.evaluate(
            "design.observed-values",
            scope,
            lambda: validator.check_observed_values(
                scoped_files(self.root, "model", ".properties", scope)
            ),
            isolate=True,
        )
    return validator


def _callback_Validator_check_unavailable_design(self, entry, info, /):
    scope = {entry}
    self.check_source_inputs(entry)
    self.findings.evaluate(
        "design.observed-values",
        scope,
        lambda: self.check_observed_values(
            scoped_files(self.root, "model", ".properties", scope)
        ),
        isolate=True,
    )
    path = self.root / "docs/designs" / entry[0] / entry[1] / (entry[2] + ".md")
    try:
        if path in self.unavailable_views:
            raise OSError(str(self.unavailable_views[path]))
        input_text(path, encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raw = self.findings.result("design.tables.raw", scope)
        raw.metadata = dict(complete=False, reason="view-read", message=str(error))
        self.findings.unverified.append(
            dict(
                code="design.tables.raw",
                reason="view-read",
                complete=False,
                path=self.findings.relative(path),
                message=str(error),
                scope=["/".join(entry)],
            )
        )
    else:
        self.findings.evaluate(
            "design.tables",
            scope,
            lambda: self.check_design_tables(
                *self.check_design_service_ownership([path]), paths=[path]
            ),
            isolate=True,
        )
    reason = info.get("reason", "expansion")
    source = self.findings.result("design.model-inputs", scope)
    if source.errors:
        reason = "expansion"
    semantic = self.findings.result("design.tables.semantic", scope)
    if semantic.metadata.get("reason") == "expansion":
        reason = "expansion"
    entry_info = dict(
        code="design.tables.dependency",
        phase="generation" if self.check_display else "saved-view",
        reason=reason,
        scope=["/".join(entry)],
        path=self.findings.relative(path),
        resource="document",
        message="generated View unavailable"
        if self.check_display
        else "saved View unavailable",
        checks=(["generated View equality"] if self.check_display else [])
        + ["cross-resource reference integrity"],
        complete=False,
    )
    self.findings.unverified.append(entry_info)
    semantic.metadata.update(complete=False, reason=reason)
    semantic.metadata.setdefault("unverified", []).append(entry_info)
    for check_id in ("framework.policy-tables", "design.links"):
        result = self.findings.result(check_id, scope)
        result.metadata.update(complete=False, reason=reason, unverified=[entry_info])
    return dict(complete=False, reason=reason)


def unavailable_service_result(parent, entry, info):
    validator = Validator(
        parent.root,
        {entry},
        definitions_root=parent.definitions_root,
        check_display=parent.check_display,
    )
    validator.accounts = parent.accounts
    validator.schema_catalog = parent.schema_catalog or DesignSchemaCatalog(
        parent.definitions_root
    )
    validator.generated_models_checked = True
    validator.unavailable_views = parent.unavailable_views
    validator.findings.evaluate(
        "design.service",
        {entry},
        _bind_framework_callback(
            _callback_Validator_check_unavailable_design, validator, entry, info
        ),
        isolate=True,
    )
    return validator


def _callback_Validator_check_scoped_designs_source_checks(
    _state_check_scoped_designs_351, check_model_inputs, load_model, self, /
):
    path = (
        self.root
        / "model"
        / _state_check_scoped_designs_351.entry[0]
        / _state_check_scoped_designs_351.entry[1]
        / (_state_check_scoped_designs_351.entry[2] + ".properties")
    )
    try:
        analysis = load_model(path)
    except _imports_model_core.ReferenceDiagnosticError as error:
        self.findings.warn(error, model=str(path))
        return
    independent = check_model_inputs(
        path, analysis.authoritative, self.root, definitions_root=self.definitions_root
    )
    # Generation may already contain these source diagnostics in its aggregate error.
    self.errors.extend(
        error
        for error in independent.errors
        if not any(error in existing for existing in self.errors)
    )
    self.findings.include_diagnostics(independent)
    self.findings.reference_errors.extend(independent.reference_errors)
    for diagnostic in (*analysis.warnings, *independent.warnings):
        self.findings.warn(diagnostic)
    self.checks += independent.checks


def service_result(parent, entry, handler):
    try:
        return handler()
    except Exception as error:
        validator = Validator(
            parent.root,
            {entry},
            definitions_root=parent.definitions_root,
            check_display=parent.check_display,
        )
        validator.accounts = parent.accounts
        validator.schema_catalog = parent.schema_catalog
        validator.findings.processing_failure("design.worker", {entry}, error)
        validator.check_source_inputs(entry)
        validator.findings.evaluate(
            "design.observed-values",
            {entry},
            validator.check_observed_values,
            isolate=True,
        )
        return validator


class Validator:
    changed_paths = owned_field("task", "changed_paths")
    task_type = owned_field("task", "task_type")
    infrastructure_phase = owned_field("task", "infrastructure_phase")
    requirement_ids = owned_field("task", "requirement_ids")
    acceptance_checks = owned_field("task", "acceptance_checks")
    acceptance_results = owned_field("task", "acceptance_results")

    checks = owned_field("findings", "checks")
    errors = owned_field("findings", "errors")
    warnings = owned_field("findings", "warnings")

    def __init__(
        self,
        root: Path,
        scope=None,
        contract_scope=None,
        *,
        cache=False,
        fresh=False,
        workers=4,
        iac_paths=None,
        task_iac_paths=None,
        write=False,
        definitions_root: Path | None = None,
        final_candidate=None,
        check_display=True,
    ) -> None:
        definition_root = _imports_utils_aws_mappings.definition_root
        self.findings = Findings(root)
        self.warn = self.findings.warn
        self.check = self.findings.check
        self.check_file = self.findings.check_file
        self.relative = self.findings.relative
        self.report_findings = self.findings.report_findings
        self.iac_paths = iac_paths
        self.task_iac_paths = task_iac_paths
        self.workers = workers
        self.write = write
        self.check_display = check_display
        self.service_cache_pending = []
        self.catalog_pending = None
        self.catalog_key = None
        self.unavailable_views = {}
        self.view_reader = None
        self.cache = (
            PassCache(
                root,
                fresh,
                include_project=scope != set(),
                definitions_root=definitions_root,
            )
            if cache and check_display
            else None
        )
        self.relative_paths = self.findings.relative_paths
        self.scope = scope
        self.contract_scope = contract_scope
        self.generated_models_checked = False
        self.root = root
        self.definitions_root = definitions_root or definition_root(root)
        self.task = _dependency_validation_task.TaskValidation(
            root, self.findings, final_candidate=final_candidate
        )
        self.template_mode = True
        self.accounts: dict[tuple[str, str], dict[str, str]] = {}
        self.scenario_ids: set[str] = set()
        self.result_files: dict[str, list[Path]] = {}
        self.markdown_design_artifacts = ArtifactReferences()
        self.markdown_iam_policy_artifacts: dict[tuple[str, str, str, str], Path] = {}
        self.schema_catalog: DesignSchemaCatalog | None = None

    @input_scope
    def run(self) -> int:
        with contract_reads(self.root, verify=False):
            result = self._run_with_contracts()
            return result

    def _run_with_contracts(self) -> int:
        GenerationInputs = _imports_generation_inputs.GenerationInputs
        publication_lock = _imports_model_sources.publication_lock
        definition_root = _imports_utils_aws_mappings.definition_root
        mapping_alias = _imports_utils_aws_mappings.mapping_alias
        if not self.write:
            with ExitStack() as lifetime:
                if (
                    self.scope != set()
                    and self.definitions_root != self.root
                    and definition_root(self.root) != self.definitions_root
                ):
                    lifetime.enter_context(
                        mapping_alias(self.definitions_root, self.root)
                    )
                self.task.fix_baseline()
                return self._run()
        if self.scope == set() or self.contract_scope == set():
            self.check(
                False,
                "--write requires service scope; framework scope cannot generate Models",
            )
            return self.report()

        with publication_lock(self.root):
            snapshot = GenerationInputs(self.root, self.definitions_root)
        with ExitStack() as lifetime:
            lifetime.callback(snapshot.close)
            lifetime.enter_context(recording_inputs(snapshot))
            if (
                self.definitions_root != self.root
                and definition_root(self.root) != self.definitions_root
            ):
                lifetime.enter_context(mapping_alias(self.definitions_root, self.root))
            self.task.fix_baseline()
            common = self.cache or PassCache(
                self.root, definitions_root=self.definitions_root
            )
            # Register mutable common inputs once, before any cache lookup.
            if self.cache:
                self.cache.common = self.cache.common_key(snapshot=snapshot)
                self.catalog_key = self.cache.key("catalog")
            else:
                common.common_inputs(snapshot)
            return self._run(snapshot)

    def input_check(self, snapshot, handler):
        # Read boundaries use the invocation recorder; Task/Git/IaC stay on real root.
        return handler()

    def _run(self, snapshot=None) -> int:
        self.relative_paths.clear()
        if self.task.issues_only:
            self.cache = None
        if self.cache and snapshot is None:
            self.cache.common = None
        self.input_check(snapshot, self.check_structure)
        if snapshot is None:
            self.check_task_scope()
        else:
            self.task.check_task_scope(snapshot.expected_task[1])
        registered = self.registered_checks()
        for requirement, kind, value in self.acceptance_checks:
            if kind == "check":
                self.check(
                    value in registered,
                    f"unknown registered Acceptance check: {requirement}: {value}",
                )
                self.check(
                    value in self.acceptance_stages,
                    f"undefined Acceptance execution stage: {requirement}: {value}",
                )
        self.input_check(snapshot, self.check_project_topology)
        self.check_validation_scope()
        if not self.write:
            self.check_model_files()
        if self.changed_paths and not self.write:
            self.check_task_type_requirements()
        self.input_check(snapshot, self.check_initialized_paths)
        self.input_check(snapshot, self.check_catalog)
        self.findings.evaluate(
            "framework.resource-layout",
            self.scope,
            lambda: self.input_check(snapshot, self.check_resource_layout),
        )
        if self.write:
            for _, kind, value in self.acceptance_checks:
                if kind == "check" and self.acceptance_stages.get(value) == "common":
                    self.findings.evaluate(
                        value,
                        self.scope,
                        lambda value=value: self.input_check(
                            snapshot, registered[value]
                        ),
                    )
            if not self.errors:
                self.generate_and_validate(snapshot, registered)
            return self.report()
        if self.scope is None:
            self.check_designs()
            self.check_observed_values()
        elif self.scope and not self.errors:
            self.check_scoped_designs()
        if self.infrastructure_phase != "destroy":
            self.check_iac_selection()
        if self.infrastructure_phase != "destroy" and (
            self.scope is None or self.task_type == "infrastructure"
        ):
            self.check_cloudformation_yaml_rules()
            self.check_cloudformation_environment_parameters()
        if self.scope is None or self.task_type == "scenario-test":
            self.check_scenarios()
            self.check_results()
            self.check_scenario_changes()
        self.check_acceptance_checks()
        current_common = None
        if self.cache and self.cache.common is not None:
            current_common = self.cache.common_key()
            self.check(
                self.cache.common == current_common,
                "project inputs changed during validation",
            )

        if not self.task.issues_only:
            verify_contract_reads(self.root)
        if self.cache and not self.errors:
            if self.catalog_pending is not None:
                self.cache.save(*self.catalog_pending)
                self.catalog_pending = None
            self.finalize_service_cache(current_common)
        return self.report()

    def report(self):
        return int(self.findings.status != "PASS")

    def display_report(self):
        if self.errors:
            print(f"Blueprint repository validation: FAIL ({len(self.errors)} errors)")
            for error in self.errors:
                print(f"- {error}")
            self.report_findings()
            return 1

        result = self.findings.status
        print(f"Blueprint repository validation: {result} ({self.checks} checks)")
        if self.task_type:
            print(f"- task type: {self.task_type}")
        else:
            print("- task state: idle (no active task)")
        print(f"- task requirements: {', '.join(self.requirement_ids)}")
        print(
            f"- acceptance checks: {len(self.acceptance_results)}/{len(self.acceptance_checks)} passed"
        )
        print(f"- mode: {'template' if self.template_mode else 'project'}")
        print(
            f"- validation scope: {'all' if self.scope is None else ', '.join('/'.join(item) for item in sorted(self.scope)) or 'framework'}"
        )
        self.report_findings()
        return self.report()

    def generate_and_validate(self, snapshot, registered):
        planned_outputs = _imports_sync_runtime.planned_outputs
        prepare_generation = _imports_sync_runtime.prepare_generation
        publish_generation = _imports_sync_runtime.publish_generation
        report_generation = _imports_sync_runtime.report_generation
        validate_generation = _imports_sync_runtime.validate_generation
        paths_in = _imports_task_contract.paths_in
        status = _imports_task_contract.status
        name, text = snapshot.expected_task
        self.check(
            text is not None and status(text) == "running",
            "--write requires a running task contract",
        )
        if self.errors:
            return
        plan = prepare_generation(
            self.root,
            self.scope,
            snapshot=snapshot,
            definitions_root=self.definitions_root,
        )
        try:
            plan.accounts = self.accounts
            validate_generation(plan, jobs=self.workers)
            common_ids = {
                name
                for name, phase in self.acceptance_stages.items()
                if phase == "common"
            }
            self.findings.bind_candidate(plan.candidate, common_ids)
            # Candidate validation is the content authority for this exact input/final stage.
            generated = _bind_framework_callback(
                _callback_Validator_generate_and_validate_generated,
                plan,
                self,
                snapshot,
            )
            self.findings.evaluate(
                "framework.generated-service-model", self.scope, generated
            )
            # Reuse the actual scope-wide policy result, never infer it from generation.
            policy_result = _bind_framework_callback(
                _callback_Validator_generate_and_validate_policy_result, plan, self
            )
            self.findings.evaluate("framework.policy-tables", self.scope, policy_result)
            candidate_error_count = len(self.errors)
            # Resolve every registered content handler before the first repository write.
            for _, kind, value in self.acceptance_checks:
                if kind == "check":
                    self.findings.evaluate(
                        value,
                        self.scope,
                        lambda value=value: self.input_check(
                            snapshot, registered[value]
                        ),
                    )
            # Independent invalid candidates retain partial success. Common/contract
            # failures prevent every save; candidate failures are reported after publication.
            if len(self.errors) != candidate_error_count:
                return
            if self.infrastructure_phase != "destroy":
                self.input_check(snapshot, self.check_iac_selection)
            if self.infrastructure_phase != "destroy" and (
                self.scope is None or self.task_type == "infrastructure"
            ):
                self.input_check(snapshot, self.check_cloudformation_yaml_rules)
                self.input_check(
                    snapshot,
                    lambda: self.check_cloudformation_environment_parameters(
                        stack_definitions=self.candidate_stacks(plan)
                    ),
                )
            if self.scope is None or self.task_type == "scenario-test":
                self.input_check(snapshot, self.check_scenarios)
                self.input_check(snapshot, self.check_results)
                self.input_check(snapshot, self.check_scenario_changes)
            if len(self.errors) != candidate_error_count:
                return
            planned = planned_outputs(plan)
            allowed = paths_in(text, "## Allowed paths")
            modified = paths_in(text, "## Modified files")
            for path in planned:
                relative = path.relative_to(self.root).as_posix()
                self.check(
                    relative in modified
                    and any(
                        self.task.matches(relative, pattern) for pattern in allowed
                    ),
                    f"generated path is outside task scope: {relative}",
                )
                parts = path.relative_to(self.root / "docs/designs").parts
                identity = (
                    *parts[:2],
                    Path(parts[2]).stem if len(parts) == 3 else parts[2],
                )
                self.check(
                    self.scope is None or identity in self.scope,
                    f"generated path is outside Validation scope: {relative}",
                )
            self.check_task_boundary(
                self.root / name, {p.relative_to(self.root).as_posix() for p in planned}
            )
            if len(self.errors) != candidate_error_count:
                return
            before_publication = len(plan.failures)
            publish_generation(plan)
            publication_errors = plan.failures[before_publication:]
            if publication_errors:
                self.findings.bind_candidate(plan.candidate, common_ids)
                generation = self.findings.result(
                    "framework.generated-service-model", self.scope
                )
                generation.status = "FAIL"
                generation.errors = tuple(plan.failures)
                for diagnostic in plan.failure_records[before_publication:]:
                    self.findings.add_diagnostic(diagnostic)
                generation.metadata.update(complete=False, status="FAIL")
                # The original scope's policy/content result belongs to the old candidate.
                # Post-save Acceptance observes NOT_RUN/FAIL without invoking handlers.
            if (
                self.cache
                and self.catalog_pending is not None
                and not self.warnings
                and not plan.unavailable
                and not publication_errors
            ):
                self.cache.save(*self.catalog_pending)
            self.task.changed_paths = self.task.final_paths()
            self.check_task_type_requirements()
            self.check_acceptance_checks()
            try:
                report_generation(plan)
            except ValueError as error:
                if not self.errors:
                    self.check(False, str(error))
        finally:
            plan.close()

    def check_source_inputs(self, entry):
        return self.findings.evaluate(
            "design.model-inputs",
            {entry},
            _bind_framework_callback(
                _callback_Validator_check_scoped_designs_source_checks,
                _CallbackState(entry=entry),
                _imports_model_validation.check_model_inputs,
                _imports_model_sources.load_model,
                self,
            ),
            isolate=True,
        )

    def check_scoped_designs(self, *, view_errors=None, view_reader=None) -> None:
        _state_check_scoped_designs_351 = _CallbackState()
        selected_task = _imports_task_contract.selected_task
        task_revision = _imports_task_contract.task_revision
        self.unavailable_views = view_errors if view_errors is not None else {}
        self.view_reader = view_reader
        unreadable = {
            (*path.relative_to(self.root / "docs/designs").parts[:2], path.stem)
            for path in self.unavailable_views
        }
        if unreadable:
            self.findings.unverified.append(
                dict(
                    code="design.ownership_incomplete",
                    scope=sorted("/".join(e) for e in self.scope),
                    message="selected saved Views unavailable",
                )
            )
        # These whole-scope checks must also run when individual services are reused.
        self.findings.evaluate(
            "design.ownership",
            self.scope,
            lambda: self.check_design_service_ownership(
                [p for p in self.design_files() if p not in self.unavailable_views]
            ),
            isolate=True,
        )
        self.findings.evaluate(
            "design.stacks",
            self.scope,
            lambda: {"stack_definitions": self.check_stack_designs()},
            isolate=True,
        )
        keys = {}
        reused = {}
        for _state_check_scoped_designs_351.entry in sorted(self.scope):
            try:
                keys[_state_check_scoped_designs_351.entry] = (
                    self.cache.service_key(_state_check_scoped_designs_351.entry)
                    if self.cache
                    else None
                )
            except (OSError, ValueError, KeyError, TypeError):
                keys[_state_check_scoped_designs_351.entry] = None
            checks = (
                self.cache.load(keys[_state_check_scoped_designs_351.entry])
                if self.cache and not unreadable
                else None
            )
            if checks is not None:
                reused[_state_check_scoped_designs_351.entry] = checks
        self.service_keys = keys
        missing = self.scope - reused.keys()
        # Generation needs the whole selected consumer scope, even with partial cache hits.
        generation_scope = self.scope - unreadable
        generator = Validator(
            self.root,
            generation_scope,
            workers=self.workers,
            definitions_root=self.definitions_root,
        )
        generator.accounts = self.accounts
        if self.check_display and missing - unreadable:
            generator.findings.evaluate(
                "design.generation",
                generation_scope,
                generator.check_generated_service_models,
                isolate=True,
            )
            self.findings.include_diagnostics(generator.findings)
            self.findings.reference_errors.extend(generator.findings.reference_errors)
            self.errors.extend(generator.errors)
            self.warnings.extend(generator.warnings)
            self.findings.processing_errors.extend(generator.findings.processing_errors)
            self.findings.unverified.extend(generator.findings.unverified)
        # Generated equality is covered by each service record; keep target counts stable.
        if self.check_display:
            self.checks += len({entry[:2] for entry in generation_scope})

        generation_info = generator.findings.result(
            "framework.generated-service-model", generation_scope
        ).metadata
        check_metadata(generation_info)
        unavailable = generation_info.get("unavailable_services", {}).copy()
        unavailable.update(
            {
                "/".join(entry): dict(reason="view-read", complete=False)
                for entry in unreadable
            }
        )
        skipped = {tuple(entry.split("/")) for entry in unavailable}
        failed = set()
        if "generated" in generation_info:
            generated = {
                tuple(entry.split("/")) for entry in generation_info["generated"]
            }
            failed = generation_scope - generated - skipped
        skipped.update(failed)
        missing -= skipped
        captured = contract_snapshot(self.root)
        selected_name, selected_text = task_revision(self.root)
        validate = (
            selected_task(
                self.root, selected_name if selected_text is not None else None
            )
        )(
            (input_scope)(
                _bind_framework_callback(
                    _callback_Validator_check_scoped_designs_validate, self, captured
                )
            )
        )

        with ThreadPoolExecutor(
            max_workers=min(self.workers, len(missing) or 1)
        ) as executor:
            if self.workers == 1 or len(missing) == 1:
                results = {
                    entry: service_result(
                        self, entry, _bind_framework_callback(validate, {entry})
                    )
                    for entry in sorted(missing)
                }
            else:
                futures = {
                    entry: executor.submit(validate, {entry})
                    for entry in sorted(missing)
                }
                results = {
                    entry: service_result(self, entry, future.result)
                    for entry, future in futures.items()
                }
        for entry in sorted(skipped):
            results[entry] = service_result(
                self,
                entry,
                _bind_framework_callback(
                    unavailable_service_result,
                    self,
                    entry,
                    unavailable.get(
                        "/".join(entry), dict(reason="expansion", complete=False)
                    ),
                ),
            )
        successful = []
        for _state_check_scoped_designs_351.entry in sorted(self.scope):
            if _state_check_scoped_designs_351.entry in reused:
                self.checks += reused[_state_check_scoped_designs_351.entry]
            else:
                validator = results[_state_check_scoped_designs_351.entry]
                self.checks += validator.checks
                self.findings.include_diagnostics(validator.findings)
                self.findings.reference_errors.extend(
                    validator.findings.reference_errors
                )
                self.errors.extend(validator.errors)
                self.warnings.extend(validator.warnings)
                self.findings.unverified.extend(validator.findings.unverified)
                self.findings.processing_errors.extend(
                    validator.findings.processing_errors
                )
                for result in validator.findings.results.values():
                    self.findings.results[
                        result.check_id, result.scope, self.findings.candidate
                    ] = replace(result, candidate=self.findings.candidate)
            if (
                _state_check_scoped_designs_351.entry not in skipped
                and self.cache
                and keys[_state_check_scoped_designs_351.entry] is not None
            ):
                try:
                    unchanged = keys[
                        _state_check_scoped_designs_351.entry
                    ] == self.cache.service_key(_state_check_scoped_designs_351.entry)
                except (OSError, ValueError, KeyError, TypeError):
                    unchanged = False
                self.check(
                    unchanged,
                    f"validation inputs changed during service validation: {'/'.join(_state_check_scoped_designs_351.entry)}",
                )
                if (
                    unchanged
                    and _state_check_scoped_designs_351.entry not in reused
                    and not results[_state_check_scoped_designs_351.entry].errors
                    and not generator.errors
                    and not results[_state_check_scoped_designs_351.entry].warnings
                    and not generator.warnings
                    and not results[
                        _state_check_scoped_designs_351.entry
                    ].findings.unverified
                    and not unavailable
                    and not (view_errors is not None and self.findings.unverified)
                ):
                    successful.append(
                        (
                            keys[_state_check_scoped_designs_351.entry],
                            results[_state_check_scoped_designs_351.entry].checks,
                        )
                    )
        self.service_cache_pending = successful
        if self.cache:
            print(
                f"Service validation: {len(missing)} executed, {len(reused)} reused; workers: {self.workers}"
            )
        if self.check_display:
            generation = self.findings.result(
                "framework.generated-service-model", self.scope
            )
            generation.status = (
                "FAIL" if generator.errors else "NOT_RUN" if unavailable else "PASS"
            )
            generation.errors = tuple(generator.errors)
            generation.warnings = tuple(generator.warnings)
            generation.metadata = dict(
                generator.findings.result(
                    "framework.generated-service-model", generation_scope
                ).metadata,
                unavailable_services=unavailable,
            )
            finish_result(generation)
        policy = self.findings.result("framework.policy-tables", self.scope)
        policies = [
            validator.findings.result("framework.policy-tables", {entry})
            for entry, validator in results.items()
        ]
        policy.status = (
            "FAIL"
            if any(p.status == "FAIL" for p in policies)
            else "NOT_RUN"
            if skipped or any(p.status == "NOT_RUN" for p in policies)
            else "PASS"
        )
        policy_unavailable = unavailable.copy()
        for result in policies:
            check_metadata(result.metadata)
            policy_unavailable.update(result.metadata.get("unavailable_services", {}))
        incomplete_policy = bool(skipped) or any(
            p.status == "NOT_RUN"
            or p.metadata.get("complete") is False
            or p.metadata.get("unverified")
            or p.metadata.get("unavailable_services")
            for p in policies
        )
        if incomplete_policy:
            reason = "reference"
            if failed or any(
                info.get("reason") != "reference" for info in unavailable.values()
            ):
                reason = "dependency"
            if unreadable:
                reason = "view-read"
            if self.findings.processing_errors:
                reason = "processing"
            policy.metadata = {
                "complete": False,
                "reason": reason,
                "unavailable_services": policy_unavailable,
                "unverified": [
                    item for p in policies for item in p.metadata.get("unverified", [])
                ],
            }
        policy.warnings = tuple(w for p in policies for w in p.warnings)
        policy.errors = tuple(error for p in policies for error in p.errors)
        finish_result(policy)
        self.generated_models_checked = True

    def finalize_service_cache(self, current_common_key):
        pending, self.service_cache_pending = self.service_cache_pending, []
        if self.cache and self.cache.common is not None:
            unchanged = self.cache.common == current_common_key
            self.check(
                unchanged, "framework/project inputs changed during service validation"
            )
            if unchanged:
                for key, checks in pending:
                    self.cache.save(key, checks)

    def check_generated_service_models(self) -> None:
        return self.findings.evaluate(
            "framework.generated-service-model",
            self.scope,
            self._check_generated_service_models,
        )

    def _check_generated_service_models(self) -> None:
        compare_generation = _imports_sync_runtime.compare_generation
        saved_design_validation = _imports_sync_views.saved_design_validation
        if self.generated_models_checked:
            return
        self.generated_models_checked = True
        if self.scope == set():
            return

        context = (
            saved_design_validation(self.root, next(iter(self.scope)))
            if self.scope is not None and len(self.scope) == 1
            else nullcontext()
        )
        with context:
            errors = compare_generation(
                self.root,
                self.scope,
                jobs=self.workers,
                definitions_root=self.definitions_root,
                findings=self.findings,
            )
        self.checks += 1
        for error in errors:
            if error not in self.errors:
                self.check(False, error)
        return self.findings.result(
            "framework.generated-service-model", self.scope
        ).metadata

    def check_catalog(self) -> None:
        try:
            key = (
                self.catalog_key
                if self.write
                else self.cache.key("catalog")
                if self.cache
                else None
            )
        except (OSError, ValueError, KeyError, TypeError):
            key = None
        cached = self.cache.load(key) if self.cache else None
        if cached is not None:
            self.checks += cached
            for check_id in (
                "framework.cloudformation-schema-catalog",
                "framework.api-design-catalog",
            ):
                self.findings.evaluate(check_id, self.scope, lambda: None)
            self.schema_catalog = DesignSchemaCatalog(self.definitions_root)
            print("Catalog validation: reused (content hashes match)")
            return
        before, errors = self.checks, len(self.errors)
        self.check_catalog_inputs()
        if self.cache and key is not None and errors == len(self.errors):
            # Save only after the invocation's final Project input comparison.
            self.catalog_pending = (key, self.checks - before)

    def check_designs(self) -> None:
        if self.check_display:
            self.check_generated_service_models()
        self.findings.evaluate(
            "design.stacks",
            self.scope,
            lambda: {"stack_definitions": self.check_stack_designs()},
        )
        markdown_paths = self.design_files()
        properties_paths = [
            path
            for path in scoped_files(self.root, "model", ".properties", self.scope)
            if path.stem != Path(STACK_DESIGN).stem
        ]
        markdown = {
            path.relative_to(self.root / "docs" / "designs").with_suffix("").as_posix()
            for path in markdown_paths
        }
        properties = {
            path.relative_to(self.root / "model").with_suffix("").as_posix()
            for path in properties_paths
        }
        self.check(
            markdown == properties,
            f"design/model group mismatch: markdown={sorted(markdown)}, model={sorted(properties)}",
        )
        for path in markdown_paths:
            self.check_target_file(path, self.root / "docs" / "designs")
        for path in properties_paths:
            self.check_target_file(path, self.root / "model")
        service_metadata, catalog_types, catalog_property_owners, identifier_outputs = (
            self.check_design_service_ownership(markdown_paths)
        )
        self.check_policy_tables()
        self.check_design_overviews()
        self.check_resource_names(service_metadata)
        self.check_design_tables(
            service_metadata, catalog_types, catalog_property_owners, identifier_outputs
        )
        self.check_design_links(identifier_outputs, markdown_paths)
        self.check_design_artifacts(None if self.scope is None else markdown_paths)

    def check_structure(self) -> None:
        return framework_contracts.check_structure(
            self.findings,
            self.root,
            consumer=self.scope != set(),
            definitions_root=self.definitions_root,
        )

    def check_framework_active_task_transition(self) -> None:
        return framework_contracts.check_framework_active_task_transition(
            self.findings, self.definitions_root
        )

    def check_framework_rule_readings(self) -> None:
        return framework_contracts.check_framework_rule_readings(
            self.findings, self.definitions_root
        )

    def check_framework_design_handoff(self) -> None:
        return framework_contracts.check_framework_design_handoff(
            self.findings, self.definitions_root
        )

    def check_framework_task_completion_contract(self) -> None:
        return framework_contracts.check_framework_task_completion_contract(
            self.findings, self.definitions_root
        )

    def check_framework_task_type_dispatch(self) -> None:
        return framework_contracts.check_framework_task_type_dispatch(
            self.findings, self.task_type
        )

    def check_framework_focused_check_runner(self) -> None:
        return framework_contracts.check_framework_focused_check_runner(
            self.findings, self.definitions_root
        )

    def check_validation_scope(self) -> None:
        if self.task.final_candidate is not None or (self.root / ".git").exists():
            self.task.fix_baseline()
        self.task.impact = project.check_validation_scope(
            self.accounts,
            self.task.scope_paths,
            self.contract_scope,
            self.findings,
            self.root,
            self.scope,
            self.task_iac_paths,
            candidates=self.write,
            base=self.task.baseline,
        )
        # Design requirements and scope validation consume the same source set and snapshot.
        self.task.design_impact = self.task.impact

    def check_framework_cloudformation_schema_catalog(self) -> None:
        return framework_contracts.check_framework_cloudformation_schema_catalog(
            self.findings, self.definitions_root
        )

    def check_framework_schema_backed_design_validation(self) -> None:
        return framework_contracts.check_framework_schema_backed_design_validation(
            self.findings, self.definitions_root
        )

    def check_project_topology(self) -> None:
        if self.scope == set():
            return
        self.template_mode = not input_is_file(self.root / "project.json")
        project.check_project_topology(
            self.accounts, self.findings, self.root, self.template_mode
        )

    def check_initialized_paths(self) -> None:
        return project.check_initialized_paths(
            self.accounts,
            self.findings,
            self.root,
            self.scope,
            self.template_mode,
            candidates=self.write,
        )

    def check_api_design_catalog(self) -> None:
        return design.check_api_design_catalog(self.findings, self.definitions_root)

    def check_catalog_inputs(self) -> None:
        design.check_catalog_inputs(
            self.findings,
            self.definitions_root,
            lambda catalog: setattr(self, "schema_catalog", catalog),
            self.scope,
        )

    def check_task_scope(self) -> None:
        return self.task.check_task_scope()

    def check_task_boundary(self, prompt: Path, paths=None) -> None:
        return self.task.check_task_boundary(prompt, paths)

    def check_task_type_requirements(self) -> None:
        return self.task.check_task_type_requirements()

    acceptance_stages = {
        "framework.active-task-transition": "common",
        "framework.rule-readings": "common",
        "framework.design-handoff": "common",
        "framework.task-completion-contract": "common",
        "framework.task-type-dispatch": "common",
        "framework.focused-check-runner": "common",
        "framework.resource-layout": "common",
        "framework.api-design-catalog": "common",
        "framework.cloudformation-schema-catalog": "common",
        "framework.schema-backed-design-validation": "common",
        "framework.generated-service-model": "candidate",
        "framework.policy-tables": "candidate",
    }

    def registered_checks(self):
        return {
            "framework.active-task-transition": self.check_framework_active_task_transition,
            "framework.rule-readings": self.check_framework_rule_readings,
            "framework.design-handoff": self.check_framework_design_handoff,
            "framework.task-completion-contract": self.check_framework_task_completion_contract,
            "framework.task-type-dispatch": self.check_framework_task_type_dispatch,
            "framework.focused-check-runner": self.check_framework_focused_check_runner,
            "framework.generated-service-model": self.check_generated_service_models,
            "framework.resource-layout": self.check_resource_layout,
            "framework.policy-tables": self.check_policy_tables,
            "framework.api-design-catalog": self.check_api_design_catalog,
            "framework.cloudformation-schema-catalog": self.check_framework_cloudformation_schema_catalog,
            "framework.schema-backed-design-validation": self.check_framework_schema_backed_design_validation,
        }

    def check_acceptance_checks(self) -> None:
        self.task.check_acceptance_checks(
            self.registered_checks(), self.scope, results_only=self.write
        )

    def check_model_files(self) -> None:
        return design.check_model_files(
            findings=self.findings, root=self.root, scope=self.scope
        )

    def catalog_design_properties(
        self,
    ) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
        return design.catalog_design_properties(self.definitions_root)

    def check_service_file(
        self, path: Path, service_id: str, owned_types: tuple[str, ...]
    ) -> None:
        return design.check_service_file(
            path, service_id, owned_types, findings=self.findings
        )

    def markdown_service_metadata(
        self, path: Path, catalog_types: set[str]
    ) -> tuple[str, tuple[str, ...]] | None:
        return design.markdown_service_metadata(
            path, catalog_types, findings=self.findings
        )

    def model_service_metadata(
        self, path: Path, catalog_types: set[str]
    ) -> tuple[str, tuple[str, ...]] | None:
        return design.model_service_metadata(
            path, catalog_types, findings=self.findings
        )

    def check_design_service_ownership(
        self, markdown_paths: list[Path]
    ) -> tuple[
        dict[Path, tuple[str, tuple[str, ...]]],
        set[str],
        dict[str, set[str]],
        dict[str, set[str]],
    ]:
        return design.check_design_service_ownership(
            markdown_paths,
            findings=self.findings,
            root=self.root,
            design_sources=getattr(self, "design_sources", {}),
            definitions_root=self.definitions_root,
        )

    @staticmethod
    def is_policy_document_property(property_name: str) -> bool:
        return design.is_policy_document_property(property_name)

    def check_resource_layout(self) -> None:
        return design.check_resource_layout(
            findings=self.findings, root=self.definitions_root
        )

    def check_resource_names(
        self,
        service_metadata: dict[Path, tuple[str, tuple[str, ...]]],
        paths: list[Path] | None = None,
    ) -> None:
        return design.check_resource_names(
            service_metadata,
            self.design_files() if paths is None else paths,
            design_sources=getattr(self, "design_sources", {}),
            findings=self.findings,
            root=self.root,
            scope=self.scope,
            definitions_root=self.definitions_root,
            check_display=self.check_display,
        )

    def check_policy_tables(self) -> None:
        return self.findings.evaluate(
            "framework.policy-tables",
            self.scope,
            lambda: design.check_policy_tables(
                self.design_files(),
                self.findings,
                definitions_root=self.definitions_root,
            ),
        )

    def check_observed_values(self, paths: list[Path] | None = None) -> None:
        return design.check_observed_values(
            paths,
            findings=self.findings,
            root=self.root,
            scope=self.scope,
            design_sources=getattr(self, "design_sources", {}),
        )

    def design_files(self) -> list[Path]:
        return design.design_files(root=self.root, scope=self.scope)

    def stack_design_files(self) -> list[Path]:
        return design.stack_design_files(root=self.root, scope=self.scope)

    def check_cidr_value(self, path: Path, property_name: str, value: str) -> None:
        return design_tables.check_cidr_value(
            path, property_name, value, findings=self.findings
        )

    def check_generated_identifier(
        self,
        path: Path,
        resource_type: str,
        logical_id: str,
        rows: list[list[str]],
        identifier_outputs: dict[str, set[str]],
    ) -> None:
        return design_tables.check_generated_identifier(
            path,
            resource_type,
            logical_id,
            rows,
            identifier_outputs,
            findings=self.findings,
        )

    def check_required_name_tag(
        self,
        path: Path,
        resource_type: str,
        logical_id: str,
        rows: list[list[str]],
        mode: str = "CREATE",
    ) -> None:
        return design_tables.check_required_name_tag(
            path,
            resource_type,
            logical_id,
            rows,
            mode,
            findings=self.findings,
            schema_catalog=self.schema_catalog,
        )

    def check_markdown_iam_policy_artifacts(
        self, path: Path, logical_id: str, rows: list[list[str]]
    ) -> None:
        return design_tables.check_markdown_iam_policy_artifacts(
            path,
            logical_id,
            rows,
            design_sources=getattr(self, "design_sources", {}),
            findings=self.findings,
            markdown_iam_policy_artifacts=self.markdown_iam_policy_artifacts,
            root=self.root,
        )

    def check_design_tables(
        self,
        service_metadata: dict[Path, tuple[str, tuple[str, ...]]],
        catalog_types: set[str],
        catalog_property_owners: dict[str, set[str]],
        identifier_outputs: dict[str, set[str]],
        paths: list[Path] | None = None,
    ) -> None:
        return design_tables.check_design_tables(
            service_metadata,
            catalog_types,
            catalog_property_owners,
            identifier_outputs,
            self.design_files() if paths is None else paths,
            design_sources=getattr(self, "design_sources", {}),
            findings=self.findings,
            markdown_design_artifacts=self.markdown_design_artifacts,
            markdown_iam_policy_artifacts=self.markdown_iam_policy_artifacts,
            root=self.root,
            schema_catalog=self.schema_catalog,
            scope=self.scope,
            definitions_root=self.definitions_root,
            check_display=self.check_display,
        )

    def check_design_overviews(self, paths: list[Path] | None = None) -> None:
        return design_links.check_design_overviews(
            self.design_files() if paths is None else paths,
            findings=self.findings,
            root=self.root,
            scope=self.scope,
            definitions_root=self.definitions_root,
        )

    def check_design_links(
        self,
        identifier_outputs: dict[str, set[str]],
        paths: list[Path] | None = None,
        *,
        design_index: DesignIndex | None = None,
        candidate_paths=None,
    ) -> None:
        return design_links.check_design_links(
            identifier_outputs,
            self.design_files() if paths is None else paths,
            design_index=design_index,
            design_sources=getattr(self, "design_sources", {}),
            findings=self.findings,
            root=self.root,
            scope=self.scope,
            definitions_root=self.definitions_root,
            check_display=self.check_display,
            view_reader=self.view_reader,
            unavailable_views=self.unavailable_views,
            candidate_paths=candidate_paths,
        )

    def check_design_artifacts(self, paths: list[Path] | None = None) -> None:
        return design_links.check_design_artifacts(
            paths,
            accounts=self.accounts,
            findings=self.findings,
            markdown_design_artifacts=self.markdown_design_artifacts,
            root=self.root,
        )

    def check_target_file(self, path: Path, base: Path) -> tuple[str, str] | None:
        return project.check_target_file(
            path, base, accounts=self.accounts, findings=self.findings
        )

    def check_stack_designs(
        self, paths: list[Path] | None = None
    ) -> dict[Path, list[dict]]:
        return cloudformation.check_stack_designs(
            self.stack_design_files() if paths is None else paths,
            accounts=self.accounts,
            findings=self.findings,
            root=self.root,
            scope=self.scope,
            design_sources=getattr(self, "design_sources", {}),
            definitions_root=self.definitions_root,
        )

    def check_iac_selection(self) -> None:
        if self.scope == set() and not self.accounts:
            return
        iac.check_iac_selection(
            self.root, self.scope, self.accounts, self.template_mode, self.findings
        )
        if (
            self.scope is None
            or self.task_type == "infrastructure"
            or any(terraform.is_terraform_path(path) for path in self.task.scope_paths)
        ):
            terraform.check_configuration(
                self.root,
                self.scope,
                self.accounts,
                self.findings,
                self.task.scope_paths,
            )

    def check_cloudformation_yaml_rules(self) -> None:
        cloudformation.check_cloudformation_yaml_rules(
            self.root, self.iac_paths, self.findings
        )

    def candidate_stacks(self, plan):
        findings = plan.validation.get(None)
        if findings is None:
            return {}
        result = findings.result("design.stacks", plan.generated_scope)
        return {
            self.root / path.relative_to(plan.stage): stacks
            for path, stacks in result.metadata.get("stack_definitions", {}).items()
        }

    def check_cloudformation_environment_parameters(
        self, stack_definitions=None
    ) -> None:
        if stack_definitions is None:
            result = self.findings.result("design.stacks", self.scope)
            if result.status == "PASS":
                stack_definitions = result.metadata.get("stack_definitions")
        cloudformation.check_cloudformation_environment_parameters(
            self.root,
            self.iac_paths,
            self.accounts,
            self.stack_design_files(),
            self.findings,
            stack_definitions=stack_definitions,
        )

    def check_scenarios(self) -> None:
        scenario.check_scenarios(self.root, self.findings, self.scenario_ids)

    def check_results(self) -> None:
        scenario.check_results(
            self.root,
            self.accounts,
            self.template_mode,
            self.result_files,
            self.findings,
        )

    def check_scenario_changes(self) -> None:
        scenario.check_scenario_changes(
            self.task.scope_paths, self.result_files, self.findings
        )


def run_validation(root: Path, options, *, final_candidate=None) -> Validator:
    """Run existing validation with explicit options; return findings, without final display.

    Final candidates fix the actual worktree and latest-base difference and are always
    read-only. Errors in inputs propagate to the CLI; validation findings stay ordered.
    """
    task_deployment_input_paths = _imports_deploy_inputs.task_deployment_input_paths
    selected_task = _imports_task_contract.selected_task
    if final_candidate is not None:
        if root.resolve() != final_candidate.root or options.write:
            raise ValueError("final validation requires the actual read-only candidate")
        task_file = final_candidate.task_file
    else:
        task_file = options.task_file
    with selected_task(root, task_file), contract_reads(root, verify=False):
        scope = (
            final_candidate.scope
            if final_candidate is not None
            else active_scope(root, options.all, task_file=task_file)
        )
        contract_scope = (
            active_scope(root, task_file=task_file)
            if options.contract_scope or options.write and options.all
            else None
        )
        if options.write and (scope == set() or contract_scope == set()):
            raise ValueError(
                "--write requires service scope; framework scope cannot generate Models"
            )
        deployment_paths = task_deployment_input_paths(root)
        validator = Validator(
            root,
            scope,
            contract_scope,
            cache=True,
            fresh=options.fresh or options.all,
            workers=options.jobs,
            iac_paths=None
            if options.all or options.repository_wide_iac
            else deployment_paths,
            task_iac_paths=deployment_paths,
            write=options.write,
            definitions_root=final_candidate.definitions_root
            if final_candidate is not None
            else None,
            final_candidate=final_candidate,
        )
        validator.run()
        return validator
