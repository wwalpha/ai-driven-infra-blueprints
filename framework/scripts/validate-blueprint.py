#!/usr/bin/env python3
"""Deterministic local validator for a generic infrastructure blueprint."""


from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys
from pathlib import Path
from validation_cache import PassCache, input_scope
from validation import scenario, cloudformation, iac, terraform, design, design_tables, design_links, project, framework_contracts
from validation.task import TaskValidation
from validation.framework_contracts import CODEX_PROMPT_FILENAME_PATTERN
from validation.findings import Findings
from validation.design import TABLE_HEADER, TABLE_ALIGNMENT, REQUIRED_NAME_PROPERTIES
from policy_tables import artifact_id, rendered_design as rendered_policy_design
from design_catalog import DesignSchemaCatalog
from design_layout import STACK_DESIGN
from model_core import properties
from validation_scope import active_scope, scoped_files
from design_document import DesignIndex
from task_contract import SELECTOR

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
    deferred_files = owned_field("task", "deferred_files")
    deferred_acceptance = owned_field("task", "deferred_acceptance")

    checks = owned_field("findings", "checks")
    file_gate_paths = owned_field("findings", "file_gate_paths")
    repository_wide_gate = owned_field("findings", "repository_wide_gate")
    errors = owned_field("findings", "errors")
    non_blocking_findings = owned_field("findings", "non_blocking_findings")

    def __init__(self, root: Path, scope=None, contract_scope=None, *, cache=False, fresh=False, workers=4, model_check=None, iac_paths=None, task_iac_paths=None, repository_wide_gate=False) -> None:
        self.findings = Findings(root, repository_wide_gate or scope is None)
        self.check = self.findings.check
        self.check_file = self.findings.check_file
        self.relative = self.findings.relative
        self.report_findings = self.findings.report_findings
        self.iac_paths = iac_paths
        self.task_iac_paths = task_iac_paths
        self.workers = workers
        self.model_check = model_check
        self.cache = PassCache(root, fresh) if cache else None
        self.relative_paths = self.findings.relative_paths
        self.scope = scope
        self.contract_scope = contract_scope
        self.generated_models_checked = False
        self.root = root
        self.task = TaskValidation(root, self.findings)
        self.template_mode = True
        self.accounts: dict[tuple[str, str], dict[str, str]] = {}
        self.scenario_ids: set[str] = set()
        self.result_files: dict[str, list[Path]] = {}
        self.markdown_design_artifacts: set[Path] = set()
        self.markdown_iam_policy_artifacts: dict[tuple[str, str, str, str], Path] = {}
        self.schema_catalog: DesignSchemaCatalog | None = None


    @input_scope
    def run(self) -> int:
        self.relative_paths.clear()
        if self.cache:
            self.cache.common = None
        self.check_structure()
        self.check_task_scope()
        self.check_tasks()
        self.check_project_topology()
        self.check_validation_scope()
        self.check_model_files()
        self.check_issue_gate()
        if self.changed_paths:
            self.check_task_type_requirements()
        self.check_initialized_paths()
        self.check_catalog()
        self.check_resource_layout()
        if self.scope is None:
            self.check_designs()
            self.check_observed_values()
        elif not self.errors:
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

        if self.errors:
            print(f"Blueprint repository validation: FAIL ({len(self.errors)} errors)")
            for error in self.errors:
                print(f"- {error}")
            self.report_findings()
            return 1

        result = "DEFERRED (Active checks passed; task remains running)" if self.deferred_files else "PASS"
        print(f"Blueprint repository validation: {result} ({self.checks} checks)")
        if self.task_type:
            print(f"- task type: {self.task_type}")
        else:
            print("- task state: idle (no active task)")
        print(f"- task requirements: {', '.join(self.requirement_ids)}")
        print(f"- acceptance checks: {len(self.acceptance_results)}/{len(self.acceptance_checks)} passed")
        if self.deferred_files:
            print(f"- Deferred files: {', '.join(sorted(self.deferred_files))}")
            print(f"- deferred acceptance: {', '.join(self.deferred_acceptance)}")
        print(f"- mode: {'template' if self.template_mode else 'project'}")
        print(f"- validation scope: {'all' if self.scope is None else ', '.join('/'.join(item) for item in sorted(self.scope)) or 'framework'}")
        self.report_findings()
        return 0


    def check_scoped_designs(self) -> None:
        # These whole-scope checks must also run when individual services are reused.
        self.check_design_service_ownership(self.design_files())
        self.check_stack_designs()
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
        generator = Validator(self.root, missing, workers=self.workers, model_check=self.model_check)
        generator.accounts = self.accounts
        if missing:
            generator.check_generated_service_models()
            self.errors.extend(generator.errors)
        # Generated equality is covered by each service record; keep target counts stable.
        self.checks += len({entry[:2] for entry in self.scope})

        @input_scope
        def validate(scope):
            validator = Validator(self.root, scope)
            validator.accounts = self.accounts
            validator.schema_catalog = self.schema_catalog or DesignSchemaCatalog(self.root)
            validator.generated_models_checked = True
            validator.check_designs()
            validator.check_observed_values(scoped_files(self.root, "model", ".properties", scope))
            return validator

        with ThreadPoolExecutor(max_workers=min(self.workers, len(missing) or 1)) as executor:
            mapper = map if self.workers == 1 else executor.map
            results = dict(zip(sorted(missing), mapper(validate, [{entry} for entry in sorted(missing)])))
        successful = []
        for entry in sorted(self.scope):
            if entry in reused:
                self.checks += reused[entry]
            else:
                validator = results[entry]
                self.checks += validator.checks
                self.errors.extend(validator.errors)
            if self.cache and keys[entry] is not None:
                try:
                    unchanged = keys[entry] == self.cache.service_key(entry)
                except (OSError, ValueError, KeyError, TypeError):
                    unchanged = False
                self.check(unchanged, f"validation inputs changed during service validation: {'/'.join(entry)}")
                if unchanged and entry not in reused and not results[entry].errors and not generator.errors:
                    successful.append((keys[entry], results[entry].checks))
        if self.cache and self.cache.common is not None:
            unchanged = self.cache.common == self.cache.common_key()
            self.check(unchanged, "framework/project inputs changed during service validation")
            if unchanged:
                for key, checks in successful:
                    self.cache.save(key, checks)
        if self.cache:
            print(f"Service validation: {len(missing)} executed, {len(reused)} reused; workers: {self.workers}")
        self.generated_models_checked = True

    def check_generated_service_models(self) -> None:
        if self.generated_models_checked:
            return
        self.generated_models_checked = True
        if self.scope == set():
            return
        if self.model_check is not None:
            errors = self.model_check(self.scope)
            self.check(not errors, "\n".join(errors) or "generated service models match")
            return
        command = [sys.executable, str(self.root / "framework/scripts/sync-model.py"), "--repository-root", str(self.root),
                   "--jobs", str(self.workers)]
        commands = []
        if self.scope is None:
            commands.append([*command, "--all"])
        else:
            groups = {}
            for environment, target, service in sorted(self.scope):
                groups.setdefault((environment, target), []).append(service)
            for (environment, target), services in groups.items():
                selector = "--alias" if self.accounts[environment, target]["alias"] else "--aws-account-id"
                commands.append([*command, "--environment", environment, selector, target,
                                 *(arg for service in services for arg in ("--service", service))])
        for command in commands:
            result = subprocess.run(command, cwd=self.root, check=False, capture_output=True, text=True)
            self.check(result.returncode == 0, result.stdout.strip() + "\n" + result.stderr.strip() or "generated service model check failed")


    def check_catalog(self) -> None:
        try:
            key = self.cache.key("catalog") if self.cache else None
        except (OSError, ValueError, KeyError, TypeError):
            key = None
        cached = self.cache.load(key) if self.cache else None
        if cached is not None:
            self.checks += cached
            self.schema_catalog = DesignSchemaCatalog(self.root)
            print("Catalog validation: reused (content hashes match)")
            self.check(self.cache.common == self.cache.common_key(), "framework/project inputs changed during catalog validation")
            return
        before, errors = self.checks, len(self.errors)
        self.check_catalog_inputs()
        if self.cache and key is not None and errors == len(self.errors):
            unchanged = self.cache.common == self.cache.common_key()
            self.check(unchanged, "framework/project inputs changed during catalog validation")
            if unchanged:
                self.cache.save(key, self.checks - before - 1)


    def check_designs(self) -> None:
        self.check_generated_service_models()
        self.check_stack_designs()
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
        return framework_contracts.check_structure(self.findings, self.root)

    def check_framework_active_task_transition(self) -> None:
        return framework_contracts.check_framework_active_task_transition(self.findings, self.root)

    def check_framework_rule_readings(self) -> None:
        return framework_contracts.check_framework_rule_readings(self.findings, self.root)

    def check_framework_design_handoff(self) -> None:
        return framework_contracts.check_framework_design_handoff(self.findings, self.root)

    def check_framework_task_completion_contract(self) -> None:
        return framework_contracts.check_framework_task_completion_contract(self.findings, self.root)

    def check_framework_task_type_dispatch(self) -> None:
        return framework_contracts.check_framework_task_type_dispatch(self.findings, self.task_type)

    def check_framework_focused_check_runner(self) -> None:
        return framework_contracts.check_framework_focused_check_runner(self.findings, self.root)

    def check_validation_scope(self) -> None:
        return project.check_validation_scope(self.accounts, self.changed_paths, self.contract_scope, self.findings, self.root, self.scope, self.task_iac_paths)

    def check_framework_cloudformation_schema_catalog(self) -> None:
        return framework_contracts.check_framework_cloudformation_schema_catalog(self.findings, self.root)

    def check_framework_schema_backed_design_validation(self) -> None:
        return framework_contracts.check_framework_schema_backed_design_validation(self.findings, self.root)

    def check_framework_cfn_lint_validation(self) -> None:
        return framework_contracts.check_framework_cfn_lint_validation(self.findings, self.root)

    def check_project_topology(self) -> None:
        self.template_mode = not (self.root / "project.json").is_file()
        project.check_project_topology(self.accounts, self.findings, self.root, self.template_mode)

    def check_initialized_paths(self) -> None:
        return project.check_initialized_paths(self.accounts, self.findings, self.root, self.scope, self.template_mode)

    def check_api_design_catalog(self) -> None:
        return design.check_api_design_catalog(self.findings, self.root)

    def check_catalog_inputs(self) -> None:
        design.check_catalog_inputs(self.findings, self.root, lambda catalog: setattr(self, "schema_catalog", catalog))

    def check_task_scope(self) -> None:
        return self.task.check_task_scope()

    def check_task_boundary(self, prompt: Path) -> None:
        return self.task.check_task_boundary(prompt)

    def check_issue_gate(self) -> None:
        return self.task.check_issue_gate()

    def check_task_type_requirements(self) -> None:
        return self.task.check_task_type_requirements()

    def check_tasks(self) -> None:
        return self.task.check_tasks()

    def check_acceptance_checks(self) -> None:
        registered = {
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
            "framework.cfn-lint-validation": self.check_framework_cfn_lint_validation,
        }
        self.task.check_acceptance_checks(registered)

    def check_model_files(self) -> None:
        return design.check_model_files(findings=self.findings, root=self.root, scope=self.scope)

    def catalog_design_properties(
        self,
    ) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
        return design.catalog_design_properties(self.root)

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
        return design.check_design_service_ownership(markdown_paths, findings=self.findings, root=self.root)

    @staticmethod
    def is_policy_document_property(property_name: str) -> bool:
        return design.is_policy_document_property(property_name)

    def check_resource_layout(self) -> None:
        return design.check_resource_layout(findings=self.findings, root=self.root)

    def check_resource_names(self, service_metadata: dict[Path, tuple[str, tuple[str, ...]]], paths: list[Path] | None = None) -> None:
        return design.check_resource_names(service_metadata, self.design_files() if paths is None else paths, design_sources=getattr(self, "design_sources", {}), findings=self.findings, root=self.root, scope=self.scope)

    def check_policy_tables(self) -> None:
        return design.check_policy_tables(self.design_files(), self.findings)

    def check_observed_values(self, paths: list[Path] | None = None) -> None:
        return design.check_observed_values(paths, findings=self.findings, root=self.root, scope=self.scope)

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
        return design_tables.check_design_tables(service_metadata, catalog_types, catalog_property_owners, identifier_outputs, self.design_files() if paths is None else paths, design_sources=getattr(self, "design_sources", {}), findings=self.findings, markdown_design_artifacts=self.markdown_design_artifacts, markdown_iam_policy_artifacts=self.markdown_iam_policy_artifacts, root=self.root, schema_catalog=self.schema_catalog, scope=self.scope)

    def check_design_overviews(self, paths: list[Path] | None = None) -> None:
        return design_links.check_design_overviews(self.design_files() if paths is None else paths, findings=self.findings, root=self.root, scope=self.scope)

    def check_design_links(self, identifier_outputs: dict[str, set[str]], paths: list[Path] | None = None, *,
                           design_index: DesignIndex | None = None) -> None:
        return design_links.check_design_links(identifier_outputs, self.design_files() if paths is None else paths, design_index=design_index, findings=self.findings, root=self.root, scope=self.scope)

    def check_design_artifacts(self, paths: list[Path] | None = None) -> None:
        return design_links.check_design_artifacts(paths, accounts=self.accounts, findings=self.findings, markdown_design_artifacts=self.markdown_design_artifacts, root=self.root)

    def check_target_file(self, path: Path, base: Path) -> tuple[str, str] | None:
        return project.check_target_file(path, base, accounts=self.accounts, findings=self.findings)

    def check_stack_designs(self, paths: list[Path] | None = None) -> None:
        return cloudformation.check_stack_designs(self.stack_design_files() if paths is None else paths, accounts=self.accounts, findings=self.findings, root=self.root, scope=self.scope)

    def check_iac_selection(self) -> None:
        iac.check_iac_selection(self.root, self.scope, self.accounts, self.template_mode, self.findings)
        if self.scope is None or self.task_type == "infrastructure" or any(
                terraform.is_terraform_path(path) for path in self.changed_paths):
            terraform.check_configuration(self.root, self.scope, self.accounts, self.findings, self.changed_paths)

    def check_cloudformation_yaml_rules(self) -> None:
        cloudformation.check_cloudformation_yaml_rules(self.root, self.iac_paths, self.findings)

    def check_cloudformation_environment_parameters(self) -> None:
        cloudformation.check_cloudformation_environment_parameters(
            self.root, self.iac_paths, self.accounts, self.stack_design_files(), self.findings)

    def check_scenarios(self) -> None:
        scenario.check_scenarios(self.root, self.findings, self.scenario_ids)

    def check_results(self) -> None:
        scenario.check_results(self.root, self.accounts, self.template_mode, self.result_files, self.findings)

    def check_scenario_changes(self) -> None:
        scenario.check_scenario_changes(self.changed_paths, self.result_files, self.findings)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--task-file", help="Selected tasks/<task-name>.md contract")
    parser.add_argument("--all", action="store_true", help="Explicit repository-wide validation")
    parser.add_argument("--repository-wide-iac", action="store_true", help="Retain whole-IaC checks for full/framework regression")
    parser.add_argument("--contract-scope", action="store_true", help="Also enforce the active generation scope while validating all services")
    parser.add_argument("--fresh", action="store_true", help="Revalidate instead of reusing successful content-addressed checks")
    parser.add_argument("--jobs", type=int, choices=(1, 2, 4), default=4, help="Service validation workers")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.task_file:
        os.environ[SELECTOR] = args.task_file
    root = args.repository_root.resolve()
    if not (root / ".git").exists():
        print(f"repository root is invalid: {root}", file=sys.stderr)
        return 2
    try:
        from deploy_preparation import task_deployment_input_paths
        deployment_paths = task_deployment_input_paths(root)
        validator = Validator(root, active_scope(root, args.all),
                              active_scope(root) if args.contract_scope else None,
                              cache=True, fresh=args.fresh or args.all, workers=args.jobs,
                              iac_paths=None if args.all or args.repository_wide_iac else deployment_paths,
                              task_iac_paths=deployment_paths,
                              repository_wide_gate=args.all or args.repository_wide_iac)
        if directory := os.environ.get("BLUEPRINT_PROFILE_DIR"):
            import cProfile
            import pstats
            profile = cProfile.Profile()
            try:
                return profile.runcall(validator.run)
            finally:
                profile.dump_stats(str(Path(directory) / "validate-blueprint.prof"))
                pstats.Stats(profile).strip_dirs().sort_stats("cumulative").print_stats(25)
        return validator.run()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Blueprint repository validation: FAIL\n- {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
