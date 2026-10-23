#!/usr/bin/env python3
"""Deterministic local validator for a generic infrastructure blueprint."""


from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys
from pathlib import Path
from validation_cache import PassCache, input_scope, recording_inputs, input_is_file
from validation import scenario, cloudformation, iac, terraform, design, design_tables, design_links, project, framework_contracts
from validation.task import TaskValidation
from validation.framework_contracts import CODEX_PROMPT_FILENAME_PATTERN
from validation.findings import Findings
from validation.design import TABLE_HEADER, TABLE_ALIGNMENT, REQUIRED_NAME_PROPERTIES
from policy_tables import artifact_id, rendered_design as rendered_policy_design
from design_catalog import DesignSchemaCatalog
from design_layout import STACK_DESIGN
from model.core import properties
from validation_scope import active_scope, scoped_files
from design_document import DesignIndex
from task_contract import SELECTOR, contract_reads, verify_contract_reads

def owned_field(owner, name):
    """Keep the used Validator attributes attached to their specific state owner."""
    return property(lambda validator: getattr(getattr(validator, owner), name),
                    lambda validator, value: setattr(getattr(validator, owner), name, value))


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

    def __init__(self, root: Path, scope=None, contract_scope=None, *, cache=False, fresh=False, workers=4, model_check=None, iac_paths=None, task_iac_paths=None, write=False, definitions_root: Path | None = None, final_candidate=None) -> None:
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
        self.service_cache_pending = []
        self.catalog_pending = None
        self.catalog_key = None
        self.model_check = model_check
        self.cache = PassCache(root, fresh, include_project=scope != set(), definitions_root=definitions_root) if cache else None
        self.relative_paths = self.findings.relative_paths
        self.scope = scope
        self.contract_scope = contract_scope
        self.generated_models_checked = False
        self.root = root
        from utils.aws_mappings import definition_root
        self.definitions_root = definitions_root or definition_root(root)
        self.task = TaskValidation(root, self.findings, final_candidate=final_candidate)
        self.template_mode = True
        self.accounts: dict[tuple[str, str], dict[str, str]] = {}
        self.scenario_ids: set[str] = set()
        self.result_files: dict[str, list[Path]] = {}
        self.markdown_design_artifacts: set[Path] = set()
        self.markdown_iam_policy_artifacts: dict[tuple[str, str, str, str], Path] = {}
        self.schema_catalog: DesignSchemaCatalog | None = None


    @input_scope
    def run(self) -> int:
        if not self.write:
            from contextlib import ExitStack
            from utils.aws_mappings import mapping_alias, definition_root
            with ExitStack() as lifetime:
                if self.scope != set() and self.definitions_root != self.root and definition_root(self.root) != self.definitions_root:
                    lifetime.enter_context(mapping_alias(self.definitions_root, self.root))
                self.task.fix_baseline()
                return self._run()
        if self.scope == set() or self.contract_scope == set():
            self.check(False, '--write requires service scope; framework scope cannot generate Models')
            return self.report()
        from generation_inputs import GenerationInputs
        from model.sources import publication_lock
        from contextlib import ExitStack
        from utils.aws_mappings import mapping_alias, definition_root
        with publication_lock(self.root):
            snapshot = GenerationInputs(self.root, self.definitions_root)
        with ExitStack() as lifetime:
            lifetime.callback(snapshot.close)
            lifetime.enter_context(recording_inputs(snapshot))
            if self.definitions_root != self.root and definition_root(self.root) != self.definitions_root:
                lifetime.enter_context(mapping_alias(self.definitions_root, self.root))
            self.task.fix_baseline()
            common = self.cache or PassCache(self.root, definitions_root=self.definitions_root)
            # Register the full cache dependency set before lookup; never derive it from
            # the growing subset of project inputs already consumed.
            common.common_inputs(snapshot)
            if self.cache:
                self.cache.common = self.cache.common_key(snapshot=snapshot)
                self.catalog_key = self.cache.key('catalog')
            return self._run(snapshot)

    def input_check(self, snapshot, handler):
        # Read boundaries use the invocation recorder; Task/Git/IaC stay on real root.
        return handler()

    def _run(self, snapshot=None) -> int:
        self.relative_paths.clear()
        if self.cache and snapshot is None:
            self.cache.common = None
        self.input_check(snapshot, self.check_structure)
        if snapshot is None:
            self.check_task_scope()
        else:
            self.task.check_task_scope(snapshot.expected_task[1])
        registered = self.registered_checks()
        for requirement, kind, value in self.acceptance_checks:
            if kind == 'check':
                self.check(value in registered, f'unknown registered Acceptance check: {requirement}: {value}')
                self.check(value in self.acceptance_stages, f'undefined Acceptance execution stage: {requirement}: {value}')
        self.input_check(snapshot, self.check_project_topology)
        self.check_validation_scope()
        if not self.write:
            self.check_model_files()
        self.input_check(snapshot, self.check_issue_gate)
        if self.changed_paths and not self.write:
            self.check_task_type_requirements()
        self.input_check(snapshot, self.check_initialized_paths)
        self.input_check(snapshot, self.check_catalog)
        self.findings.evaluate('framework.resource-layout', self.scope, lambda: self.input_check(snapshot, self.check_resource_layout))
        if self.write:
            for _, kind, value in self.acceptance_checks:
                if kind == 'check' and self.acceptance_stages.get(value) == 'common':
                    self.findings.evaluate(value, self.scope, lambda value=value: self.input_check(snapshot, registered[value]))
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
        if self.infrastructure_phase != "destroy" and (self.scope is None or self.task_type == "infrastructure"):
            self.check_cloudformation_yaml_rules()
            self.check_cloudformation_environment_parameters()
        if self.scope is None or self.task_type == "scenario-test":
            self.check_scenarios()
            self.check_results()
            self.check_scenario_changes()
        self.check_acceptance_checks()
        if self.cache and self.cache.common is not None:
            self.check(self.cache.common == self.cache.common_key(), "framework/project inputs changed during validation")

        return self.report()

    def report(self):
        return int(bool(self.errors))

    def display_report(self):
        if self.errors:
            print(f"Blueprint repository validation: FAIL ({len(self.errors)} errors)")
            for error in self.errors:
                print(f"- {error}")
            self.report_findings()
            return 1

        result = "PASS"
        print(f"Blueprint repository validation: {result} ({self.checks} checks)")
        if self.task_type:
            print(f"- task type: {self.task_type}")
        else:
            print("- task state: idle (no active task)")
        print(f"- task requirements: {', '.join(self.requirement_ids)}")
        print(f"- acceptance checks: {len(self.acceptance_results)}/{len(self.acceptance_checks)} passed")
        print(f"- mode: {'template' if self.template_mode else 'project'}")
        print(f"- validation scope: {'all' if self.scope is None else ', '.join('/'.join(item) for item in sorted(self.scope)) or 'framework'}")
        self.report_findings()
        return 0


    def generate_and_validate(self, snapshot, registered):
        from sync_runtime import prepare_generation, validate_generation, publish_generation, report_generation, planned_outputs
        from task_contract import paths_in, status
        name, text = snapshot.expected_task
        self.check(text is not None and status(text) == 'running',
                   '--write requires a running task contract')
        if self.errors:
            return
        plan = prepare_generation(self.root, self.scope, snapshot=snapshot, definitions_root=self.definitions_root)
        try:
            plan.accounts = self.accounts
            validate_generation(plan, jobs=self.workers)
            common_ids = {name for name, phase in self.acceptance_stages.items() if phase == 'common'}
            self.findings.bind_candidate(plan.candidate, common_ids)
            # Candidate validation is the content authority for this exact input/final stage.
            def generated():
                self.warnings.extend(plan.reference_warnings)
                for error in plan.failures:
                    self.check(False, error)
                for findings in plan.validation.values():
                    if findings is not None:
                        self.checks += findings.checks
                        self.warnings.extend(findings.warnings)
                return {"inputs": snapshot, "candidates": plan.expected_outputs, "validation": plan.validation,
                        "complete": not plan.unavailable, "reference_unavailable": plan.unavailable}
            self.findings.evaluate('framework.generated-service-model', self.scope, generated)
            # Reuse the actual scope-wide policy result, never infer it from generation.
            def policy_result():
                common = plan.validation.get(None)
                actual = None if common is None else common.result('framework.policy-tables', plan.generated_scope)
                if actual is None and plan.unavailable and not plan.failures:
                    from model.core import ReferenceResolutionError
                    raise ReferenceResolutionError('policy views unavailable because reference resolution failed')
                self.check(actual is not None and actual.model_completion_allowed and
                           (self.scope is None or actual.scope == frozenset(plan.generated_scope)),
                           'candidate policy validation is FAIL or NOT_RUN for the required scope')
            self.findings.evaluate('framework.policy-tables', self.scope, policy_result)
            candidate_error_count = len(self.errors)
            # Resolve every registered content handler before the first repository write.
            for _, kind, value in self.acceptance_checks:
                if kind == 'check':
                    self.findings.evaluate(value, self.scope, lambda value=value: self.input_check(snapshot, registered[value]))
            # Independent invalid candidates retain legacy partial success. Common/contract
            # failures prevent every save; candidate failures are reported after publication.
            if len(self.errors) != candidate_error_count:
                return
            if self.infrastructure_phase != 'destroy':
                self.input_check(snapshot, self.check_iac_selection)
            if self.infrastructure_phase != 'destroy' and (self.scope is None or self.task_type == 'infrastructure'):
                self.input_check(snapshot, self.check_cloudformation_yaml_rules)
                self.input_check(snapshot, lambda: self.check_cloudformation_environment_parameters(stack_definitions=self.candidate_stacks(plan)))
            if self.scope is None or self.task_type == 'scenario-test':
                self.input_check(snapshot, self.check_scenarios)
                self.input_check(snapshot, self.check_results)
                self.input_check(snapshot, self.check_scenario_changes)
            if len(self.errors) != candidate_error_count:
                return
            planned = planned_outputs(plan)
            allowed = paths_in(text, '## Allowed paths')
            modified = paths_in(text, '## Modified files')
            for path in planned:
                relative = path.relative_to(self.root).as_posix()
                self.check(relative in modified and any(self.task.matches(relative, pattern) for pattern in allowed),
                           f'generated path is outside task scope: {relative}')
                parts = path.relative_to(self.root / 'docs/designs').parts
                identity = (*parts[:2], Path(parts[2]).stem if len(parts) == 3 else parts[2])
                self.check(self.scope is None or identity in self.scope, f'generated path is outside Validation scope: {relative}')
            self.check_task_boundary(self.root / name, {p.relative_to(self.root).as_posix() for p in planned})
            if len(self.errors) != candidate_error_count:
                return
            before_publication = len(plan.failures)
            publish_generation(plan)
            publication_errors = plan.failures[before_publication:]
            if publication_errors:
                self.findings.bind_candidate(plan.candidate, common_ids)
                generation = self.findings.result('framework.generated-service-model', self.scope)
                generation.status = 'FAIL'
                generation.errors = tuple(plan.failures)
                for error in publication_errors:
                    self.check(False, error)
                # The original scope's policy/content result belongs to the old candidate.
                # Post-save Acceptance observes NOT_RUN/FAIL without invoking handlers.
            if self.cache and self.catalog_pending is not None and not self.warnings and not plan.unavailable:
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

    def check_scoped_designs(self, *, defer_cache=False) -> None:
        # These whole-scope checks must also run when individual services are reused.
        self.check_design_service_ownership(self.design_files())
        self.findings.evaluate('design.stacks', self.scope, lambda: {'stack_definitions': self.check_stack_designs()})
        keys = {}
        reused = {}
        for entry in sorted(self.scope):
            try:
                keys[entry] = self.cache.service_key(entry) if self.cache else None
            except (OSError, ValueError, KeyError, TypeError):
                keys[entry] = None
            checks = self.cache.load(keys[entry]) if self.cache else None
            if checks is not None:
                reused[entry] = checks
        self.service_keys = keys
        missing = self.scope - reused.keys()
        # Generation needs the whole selected consumer scope, even with partial cache hits.
        generator = Validator(self.root, self.scope, workers=self.workers, model_check=self.model_check, definitions_root=self.definitions_root)
        generator.accounts = self.accounts
        if missing:
            generator.check_generated_service_models()
            self.errors.extend(generator.errors)
            self.warnings.extend(generator.warnings)
        # Generated equality is covered by each service record; keep target counts stable.
        self.checks += len({entry[:2] for entry in self.scope})

        unavailable = generator.findings.result('framework.generated-service-model', self.scope).metadata.get('unverified', {})
        skipped = {tuple(entry.split('/')) for entry in unavailable}
        # Only View checks are unavailable; source checks remain independent.
        from model.validation import check_model_inputs
        from model.sources import load_model
        for entry in sorted(skipped):
            def source_checks():
                path = self.root / 'model' / entry[0] / entry[1] / (entry[2] + '.properties')
                analysis = load_model(path)
                independent = check_model_inputs(path, analysis.authoritative, self.root, definitions_root=self.definitions_root)
                self.errors.extend(independent.errors)
                self.warnings.extend((*analysis.warnings, *independent.warnings))
                self.checks += independent.checks
            self.findings.evaluate('design.model-inputs', {entry}, source_checks)
        missing -= skipped
        from task_contract import selected_task, task_revision
        selected_name, selected_text = task_revision(self.root)
        @selected_task(self.root, selected_name if selected_text is not None else None)
        @input_scope
        def validate(scope):
            with contract_reads(self.root):
                validator = Validator(self.root, scope, definitions_root=self.definitions_root)
                validator.accounts = self.accounts
                validator.schema_catalog = self.schema_catalog or DesignSchemaCatalog(self.definitions_root)
                validator.generated_models_checked = True
                validator.check_designs()
                validator.check_observed_values(scoped_files(self.root, "model", ".properties", scope))
            return validator

        with ThreadPoolExecutor(max_workers=min(self.workers, len(missing) or 1)) as executor:
            mapper = map if self.workers == 1 or len(missing) == 1 else executor.map
            results = dict(zip(sorted(missing), mapper(validate, [{entry} for entry in sorted(missing)])))
        verify_contract_reads(self.root)
        successful = []
        for entry in sorted(self.scope):
            if entry in skipped:
                result = self.findings.result('design.service', {entry})
                source = self.findings.result('design.model-inputs', {entry})
                result.errors, result.warnings = source.errors, source.warnings
                result.status = 'FAIL' if source.errors else 'NOT_RUN'
                result.metadata = {'complete': False, 'reason': 'reference', **unavailable['/'.join(entry)]}
                continue
            if entry in reused:
                self.checks += reused[entry]
            else:
                validator = results[entry]
                self.checks += validator.checks
                self.errors.extend(validator.errors)
                self.warnings.extend(validator.warnings)
            if self.cache and keys[entry] is not None:
                try:
                    unchanged = keys[entry] == self.cache.service_key(entry)
                except (OSError, ValueError, KeyError, TypeError):
                    unchanged = False
                self.check(unchanged, f"validation inputs changed during service validation: {'/'.join(entry)}")
                if unchanged and entry not in reused and not results[entry].errors and not generator.errors and not results[entry].warnings and not generator.warnings and not results[entry].findings.unverified and not unavailable:
                    successful.append((keys[entry], results[entry].checks))
        self.service_cache_pending = successful
        if not defer_cache and self.cache and self.cache.common is not None:
            self.finalize_service_cache(self.cache.common_key())
        if self.cache:
            print(f"Service validation: {len(missing)} executed, {len(reused)} reused; workers: {self.workers}")
        generation = self.findings.result('framework.generated-service-model', self.scope)
        generation.status = 'FAIL' if generator.errors else 'NOT_RUN' if unavailable else 'PASS'
        generation.errors = tuple(generator.errors)
        generation.warnings = tuple(generator.warnings)
        generation.metadata = generator.findings.result('framework.generated-service-model', self.scope).metadata
        policy = self.findings.result('framework.policy-tables', self.scope)
        policies = [validator.findings.result('framework.policy-tables', {entry})
                    for entry, validator in results.items()]
        policy.status = 'FAIL' if any(not p.model_completion_allowed for p in policies) else 'NOT_RUN' if skipped or any(p.status == 'NOT_RUN' for p in policies) else 'PASS'
        if policy.status == 'NOT_RUN':
            policy.metadata = {'complete': False, 'reason': 'reference', 'unverified': unavailable}
        policy.warnings = tuple(w for p in policies for w in p.warnings)
        policy.errors = tuple(error for p in policies for error in p.errors)
        self.generated_models_checked = True

    def finalize_service_cache(self, current_common_key):
        pending, self.service_cache_pending = self.service_cache_pending, []
        if self.cache and self.cache.common is not None:
            unchanged = self.cache.common == current_common_key
            self.check(unchanged, "framework/project inputs changed during service validation")
            if unchanged:
                for key, checks in pending:
                    self.cache.save(key, checks)

    def check_generated_service_models(self) -> None:
        return self.findings.evaluate('framework.generated-service-model', self.scope, self._check_generated_service_models)

    def _check_generated_service_models(self) -> None:
        if self.generated_models_checked:
            return
        self.generated_models_checked = True
        if self.scope == set():
            return
        if self.model_check is not None:
            errors = self.model_check(self.scope)
            self.check(not errors, "\n".join(errors) or "generated service models match")
            return
        from sync_runtime import compare_generation
        from sync_views import saved_design_validation
        from contextlib import nullcontext
        context = saved_design_validation(self.root, next(iter(self.scope))) if self.scope is not None and len(self.scope) == 1 else nullcontext()
        with context:
            errors = compare_generation(self.root, self.scope, jobs=self.workers, definitions_root=self.definitions_root, findings=self.findings)
        self.check(not errors, '\n'.join(errors) or 'generated service models match')
        return self.findings.result('framework.generated-service-model', self.scope).metadata


    def check_catalog(self) -> None:
        try:
            key = self.catalog_key if self.write else self.cache.key("catalog") if self.cache else None
        except (OSError, ValueError, KeyError, TypeError):
            key = None
        cached = self.cache.load(key) if self.cache else None
        if cached is not None:
            self.checks += cached
            for check_id in ('framework.cloudformation-schema-catalog', 'framework.api-design-catalog'):
                self.findings.evaluate(check_id, self.scope, lambda: None)
            self.schema_catalog = DesignSchemaCatalog(self.definitions_root)
            print("Catalog validation: reused (content hashes match)")
            if not self.write:
                self.check(self.cache.common == self.cache.common_key(), "framework/project inputs changed during catalog validation")
            return
        before, errors = self.checks, len(self.errors)
        self.check_catalog_inputs()
        if self.cache and key is not None and errors == len(self.errors):
            if self.write:
                self.catalog_pending = (key, self.checks - before)
            else:
                unchanged = self.cache.common == self.cache.common_key()
                self.check(unchanged, "framework/project inputs changed during catalog validation")
                if unchanged:
                    self.cache.save(key, self.checks - before - 1)


    def check_designs(self) -> None:
        self.check_generated_service_models()
        self.findings.evaluate('design.stacks', self.scope, lambda: {'stack_definitions': self.check_stack_designs()})
        markdown_paths = self.design_files()
        properties_paths = [path for path in scoped_files(self.root, "model", ".properties", self.scope) if path.stem != Path(STACK_DESIGN).stem]
        markdown = {
            path.relative_to(self.root / "docs" / "designs").with_suffix("").as_posix()
            for path in markdown_paths
        }
        properties = {
            path.relative_to(self.root / "model").with_suffix("").as_posix()
            for path in properties_paths
        }
        self.check(markdown == properties, f"design/model group mismatch: markdown={sorted(markdown)}, model={sorted(properties)}")
        for path in markdown_paths:
            self.check_target_file(path, self.root / "docs" / "designs")
        for path in properties_paths:
            self.check_target_file(path, self.root / "model")
        service_metadata, catalog_types, catalog_property_owners, identifier_outputs = self.check_design_service_ownership(markdown_paths)
        self.check_policy_tables()
        self.check_design_overviews()
        self.check_resource_names(service_metadata)
        self.check_design_tables(service_metadata, catalog_types, catalog_property_owners, identifier_outputs)
        self.check_design_links(identifier_outputs, markdown_paths)
        self.check_design_artifacts(None if self.scope is None else markdown_paths)


    def check_structure(self) -> None:
        return framework_contracts.check_structure(self.findings, self.root, consumer=self.scope != set(), definitions_root=self.definitions_root)

    def check_framework_active_task_transition(self) -> None:
        return framework_contracts.check_framework_active_task_transition(self.findings, self.definitions_root)

    def check_framework_rule_readings(self) -> None:
        return framework_contracts.check_framework_rule_readings(self.findings, self.definitions_root)

    def check_framework_design_handoff(self) -> None:
        return framework_contracts.check_framework_design_handoff(self.findings, self.definitions_root)

    def check_framework_task_completion_contract(self) -> None:
        return framework_contracts.check_framework_task_completion_contract(self.findings, self.definitions_root)

    def check_framework_task_type_dispatch(self) -> None:
        return framework_contracts.check_framework_task_type_dispatch(self.findings, self.task_type)

    def check_framework_focused_check_runner(self) -> None:
        return framework_contracts.check_framework_focused_check_runner(self.findings, self.definitions_root)

    def check_validation_scope(self) -> None:
        if self.task.final_candidate is not None:
            from import_guard import snapshots
            with snapshots(self.root, self.task.final_candidate.base_commit, {}, definitions_root=self.definitions_root) as (before, _):
                self.task.impact = project.check_validation_scope(self.accounts, self.task.scope_paths, self.contract_scope, self.findings, self.root, self.scope, self.task_iac_paths, candidates=False, before=before)
                self.task.design_impact = self.task.impact
        else:
            self.task.impact = project.check_validation_scope(self.accounts, self.task.scope_paths, self.contract_scope, self.findings, self.root, self.scope, self.task_iac_paths, candidates=self.write)
        if self.write and self.task_type == 'design':
            desired = {p for p in self.task.permission_paths if p.startswith('model/') and p.endswith('.properties')}
            if not desired:
                self.task.design_impact = set()
            elif desired:
                # Desired-source task requirements differ from all-source validation impact.
                from model.impact import affected
                self.task.design_impact = affected(self.root, desired)
            else:
                self.task.design_impact = self.task.impact


    def check_framework_cloudformation_schema_catalog(self) -> None:
        return framework_contracts.check_framework_cloudformation_schema_catalog(self.findings, self.definitions_root)

    def check_framework_schema_backed_design_validation(self) -> None:
        return framework_contracts.check_framework_schema_backed_design_validation(self.findings, self.definitions_root)

    def check_project_topology(self) -> None:
        if self.scope == set():
            return
        self.template_mode = not input_is_file(self.root / "project.json")
        project.check_project_topology(self.accounts, self.findings, self.root, self.template_mode)

    def check_initialized_paths(self) -> None:
        return project.check_initialized_paths(self.accounts, self.findings, self.root, self.scope, self.template_mode, candidates=self.write)

    def check_api_design_catalog(self) -> None:
        return design.check_api_design_catalog(self.findings, self.definitions_root)

    def check_catalog_inputs(self) -> None:
        design.check_catalog_inputs(self.findings, self.definitions_root, lambda catalog: setattr(self, "schema_catalog", catalog), self.scope)

    def check_task_scope(self) -> None:
        return self.task.check_task_scope()

    def check_task_boundary(self, prompt: Path, paths=None) -> None:
        return self.task.check_task_boundary(prompt, paths)

    def check_issue_gate(self) -> None:
        return self.task.check_issue_gate(self.scope) if self.write else self.task.check_issue_gate()

    def check_task_type_requirements(self) -> None:
        return self.task.check_task_type_requirements()


    acceptance_stages = {
        'framework.active-task-transition': 'common',
        'framework.rule-readings': 'common',
        'framework.design-handoff': 'common',
        'framework.task-completion-contract': 'common',
        'framework.task-type-dispatch': 'common',
        'framework.focused-check-runner': 'common',
        'framework.resource-layout': 'common',
        'framework.api-design-catalog': 'common',
        'framework.cloudformation-schema-catalog': 'common',
        'framework.schema-backed-design-validation': 'common',
        'framework.generated-service-model': 'candidate',
        'framework.policy-tables': 'candidate',
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
        self.task.check_acceptance_checks(self.registered_checks(), self.scope, results_only=self.write)

    def check_model_files(self) -> None:
        return design.check_model_files(findings=self.findings, root=self.root, scope=self.scope)

    def catalog_design_properties(
        self,
    ) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
        return design.catalog_design_properties(self.definitions_root)

    def check_service_file(self, path: Path, service_id: str, owned_types: tuple[str, ...]) -> None:
        return design.check_service_file(path, service_id, owned_types, findings=self.findings)

    def markdown_service_metadata(
        self, path: Path, catalog_types: set[str]
    ) -> tuple[str, tuple[str, ...]] | None:
        return design.markdown_service_metadata(path, catalog_types, findings=self.findings)

    def model_service_metadata(
        self, path: Path, catalog_types: set[str]
    ) -> tuple[str, tuple[str, ...]] | None:
        return design.model_service_metadata(path, catalog_types, findings=self.findings)

    def check_design_service_ownership(
        self, markdown_paths: list[Path]
    ) -> tuple[
        dict[Path, tuple[str, tuple[str, ...]]],
        set[str],
        dict[str, set[str]],
        dict[str, set[str]],
    ]:
        return design.check_design_service_ownership(markdown_paths, findings=self.findings, root=self.root, design_sources=getattr(self, "design_sources", {}), definitions_root=self.definitions_root)

    @staticmethod
    def is_policy_document_property(property_name: str) -> bool:
        return design.is_policy_document_property(property_name)

    def check_resource_layout(self) -> None:
        return design.check_resource_layout(findings=self.findings, root=self.definitions_root)

    def check_resource_names(self, service_metadata: dict[Path, tuple[str, tuple[str, ...]]], paths: list[Path] | None = None) -> None:
        return design.check_resource_names(service_metadata, self.design_files() if paths is None else paths, design_sources=getattr(self, "design_sources", {}), findings=self.findings, root=self.root, scope=self.scope, definitions_root=self.definitions_root)

    def check_policy_tables(self) -> None:
        return self.findings.evaluate('framework.policy-tables', self.scope, lambda: design.check_policy_tables(self.design_files(), self.findings, definitions_root=self.definitions_root))

    def check_observed_values(self, paths: list[Path] | None = None) -> None:
        return design.check_observed_values(paths, findings=self.findings, root=self.root, scope=self.scope, design_sources=getattr(self, "design_sources", {}))

    def design_files(self) -> list[Path]:
        return design.design_files(root=self.root, scope=self.scope)

    def stack_design_files(self) -> list[Path]:
        return design.stack_design_files(root=self.root, scope=self.scope)

    def check_cidr_value(self, path: Path, property_name: str, value: str) -> None:
        return design_tables.check_cidr_value(path, property_name, value, findings=self.findings)

    def check_generated_identifier(
        self,
        path: Path,
        resource_type: str,
        logical_id: str,
        rows: list[list[str]],
        identifier_outputs: dict[str, set[str]],
    ) -> None:
        return design_tables.check_generated_identifier(path, resource_type, logical_id, rows, identifier_outputs, findings=self.findings)

    def check_required_name_tag(
        self,
        path: Path,
        resource_type: str,
        logical_id: str,
        rows: list[list[str]],
        mode: str = "CREATE",
    ) -> None:
        return design_tables.check_required_name_tag(path, resource_type, logical_id, rows, mode, findings=self.findings, schema_catalog=self.schema_catalog)

    def check_markdown_iam_policy_artifacts(
        self, path: Path, logical_id: str, rows: list[list[str]]
    ) -> None:
        return design_tables.check_markdown_iam_policy_artifacts(path, logical_id, rows, design_sources=getattr(self, "design_sources", {}), findings=self.findings, markdown_iam_policy_artifacts=self.markdown_iam_policy_artifacts, root=self.root)

    def check_design_tables(
        self,
        service_metadata: dict[Path, tuple[str, tuple[str, ...]]],
        catalog_types: set[str],
        catalog_property_owners: dict[str, set[str]],
        identifier_outputs: dict[str, set[str]],
        paths: list[Path] | None = None,
    ) -> None:
        return design_tables.check_design_tables(service_metadata, catalog_types, catalog_property_owners, identifier_outputs, self.design_files() if paths is None else paths, design_sources=getattr(self, "design_sources", {}), findings=self.findings, markdown_design_artifacts=self.markdown_design_artifacts, markdown_iam_policy_artifacts=self.markdown_iam_policy_artifacts, root=self.root, schema_catalog=self.schema_catalog, scope=self.scope, definitions_root=self.definitions_root)

    def check_design_overviews(self, paths: list[Path] | None = None) -> None:
        return design_links.check_design_overviews(self.design_files() if paths is None else paths, findings=self.findings, root=self.root, scope=self.scope, definitions_root=self.definitions_root)

    def check_design_links(self, identifier_outputs: dict[str, set[str]], paths: list[Path] | None = None, *,
                           design_index: DesignIndex | None = None) -> None:
        return design_links.check_design_links(identifier_outputs, self.design_files() if paths is None else paths, design_index=design_index, design_sources=getattr(self, "design_sources", {}), findings=self.findings, root=self.root, scope=self.scope, definitions_root=self.definitions_root)

    def check_design_artifacts(self, paths: list[Path] | None = None) -> None:
        return design_links.check_design_artifacts(paths, accounts=self.accounts, findings=self.findings, markdown_design_artifacts=self.markdown_design_artifacts, root=self.root)

    def check_target_file(self, path: Path, base: Path) -> tuple[str, str] | None:
        return project.check_target_file(path, base, accounts=self.accounts, findings=self.findings)

    def check_stack_designs(self, paths: list[Path] | None = None) -> dict[Path, list[dict]]:
        return cloudformation.check_stack_designs(self.stack_design_files() if paths is None else paths, accounts=self.accounts, findings=self.findings, root=self.root, scope=self.scope, design_sources=getattr(self, "design_sources", {}), definitions_root=self.definitions_root)

    def check_iac_selection(self) -> None:
        if self.scope == set() and not self.accounts:
            return
        iac.check_iac_selection(self.root, self.scope, self.accounts, self.template_mode, self.findings)
        if self.scope is None or self.task_type == "infrastructure" or any(
                terraform.is_terraform_path(path) for path in self.task.scope_paths):
            terraform.check_configuration(self.root, self.scope, self.accounts, self.findings, self.task.scope_paths)

    def check_cloudformation_yaml_rules(self) -> None:
        cloudformation.check_cloudformation_yaml_rules(self.root, self.iac_paths, self.findings)

    def candidate_stacks(self, plan):
        findings = plan.validation.get(None)
        if findings is None:
            return {}
        result = findings.result('design.stacks', plan.generated_scope)
        return {self.root / path.relative_to(plan.stage): stacks
                for path, stacks in result.metadata.get('stack_definitions', {}).items()}

    def check_cloudformation_environment_parameters(self, stack_definitions=None) -> None:
        if stack_definitions is None:
            result = self.findings.result('design.stacks', self.scope)
            if result.status == 'PASS':
                stack_definitions = result.metadata.get('stack_definitions')
        cloudformation.check_cloudformation_environment_parameters(
            self.root, self.iac_paths, self.accounts, self.stack_design_files(), self.findings, stack_definitions=stack_definitions)

    def check_scenarios(self) -> None:
        scenario.check_scenarios(self.root, self.findings, self.scenario_ids)

    def check_results(self) -> None:
        scenario.check_results(self.root, self.accounts, self.template_mode, self.result_files, self.findings)

    def check_scenario_changes(self) -> None:
        scenario.check_scenario_changes(self.task.scope_paths, self.result_files, self.findings)



def run_validation(root: Path, options, *, final_candidate=None) -> Validator:
    """Run existing validation with explicit options; return findings, without final display.

    Final candidates fix the actual worktree and latest-base difference and are always
    read-only. Errors in inputs propagate to the CLI; validation findings stay ordered.
    """
    from task_contract import selected_task
    from deploy.inputs import task_deployment_input_paths
    if final_candidate is not None:
        if root.resolve() != final_candidate.root or options.write:
            raise ValueError('final validation requires the actual read-only candidate')
        task_file = final_candidate.task_file
    else:
        task_file = options.task_file
    with selected_task(root, task_file):
        scope = final_candidate.scope if final_candidate is not None else active_scope(root, options.all, task_file=task_file)
        contract_scope = active_scope(root, task_file=task_file) if options.contract_scope or options.write and options.all else None
        if options.write and (scope == set() or contract_scope == set()):
            raise ValueError('--write requires service scope; framework scope cannot generate Models')
        deployment_paths = task_deployment_input_paths(root)
        validator = Validator(root, scope, contract_scope, cache=True, fresh=options.fresh or options.all,
                              workers=options.jobs, iac_paths=None if options.all or options.repository_wide_iac else deployment_paths,
                              task_iac_paths=deployment_paths, write=options.write,
                              definitions_root=final_candidate.definitions_root if final_candidate is not None else None,
                              final_candidate=final_candidate)
        validator.run()
        return validator
