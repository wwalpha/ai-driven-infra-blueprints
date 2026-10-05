#!/usr/bin/env python3
"""Deterministic local validator for a generic infrastructure blueprint."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from validation_cache import PassCache, input_scope, memoized

from policy_tables import (
    POLICY_FORMATS,
    artifact_id,
    iam_role_policy_artifact_filename,
    rendered_design as rendered_policy_design,
    without_policy_tables,
)

from cloudformation_schema import CloudFormationSchemaCatalog, snapshot_errors
from design_catalog import DesignSchemaCatalog, api_snapshot_errors, design_material_files, property_paths_with_parents
from macie_bucket_tables import job_bucket_tables
from design_layout import (
    CLOUDTRAIL_DATA_RESOURCE,
    CODEBUILD_FORMAL_VARIABLE,
    LINKED_LIST_PROPERTIES,
    SUBNET_LIST_PROPERTIES,
    linked_list_property,
    CODEPIPELINE_STAGE,
    DETAILS_HEADING,
    DISPLAY_PROPERTY_ALIASES,
    GROUPED,
    CHILD,
    HIDDEN_PROPERTIES,
    REQUIRED_NAME_TAG_TYPES,
    RESOURCE_REFERENCE_PROPERTIES,
    is_service_role_reference,
    SECURITY_GROUP_TYPES,
    GROUPED_RESOURCE_TYPES,
    IMPLICIT_GROUPED_PROPERTIES,
    RESOURCE as RESOURCE_HEADING_PATTERN,
    expanded_display_rows,
    expanded_design,
    resource_anchor,
    resource_display_name,
    resource_heading_lines,
    resource_has_name_property,
    resource_logical_ids,
    resource_modes,
    STACK_DESIGN,
    stack_design,
    stack_deployment_policy,
    layout_errors,
    catalog_order_errors,
)
from security_group_tables import security_group_table_lines
from model_design import entries, naming_errors, properties
from model_files import MAX_LINES, read_model, model_parts, service_model_path
from validation_scope import active_scope, reference_lines, scoped_files
from issue_gate import require_no_issues
from task_contract import task_path, task_changes, contracts, reservations, TASK_NAME, SELECTOR


REQUIRED_RULES = {
    "task-contract.md",
    "issue-gate.md",
    "project-configuration.md",
    "aws-resource-naming.md",
    "cloudformation.md",
    "detailed-design.md",
    "model-information.md",
    "loop-engineering.md",
    "observed-values.md",
    "scenario-testing.md",
    "terraform.md",
}
REQUIRED_DIRECTORIES = (
    "docs/designs",
    "model",
    "infra",
    "tests/scenarios",
    "tests/results",
)
TABLE_HEADER = "| No. | Property | Value | Source / Comment |"
TABLE_ALIGNMENT = "| ---: | --- | --- | --- |"
ANCHOR_PATTERN = re.compile(r'<a\s+id="([^"]+)"\s*></a>')
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
VALUE_LINK_PATTERN = re.compile(r"^\[[^\]]+\]\(([^)#]+)\)$")
RESOURCE_LINK_PATTERN = re.compile(r"^\[([^\]]+)\]\(([^)]*?)#([^)]+)\)$")
MARKDOWN_SERVICE_ID_PATTERN = re.compile(r"^- Design service ID: `([^`]+)`$")
MARKDOWN_OWNED_TYPES_PATTERN = re.compile(
    r"^- Owned catalog resource types: (`[^`]+`(?:, `[^`]+`)*)$"
)
MODEL_SERVICE_ID_PATTERN = re.compile(r"^desired\.service\.(.+)\.serviceId=(.*)$")
MODEL_OWNED_TYPES_PATTERN = re.compile(
    r"^desired\.service\.(.+)\.ownedCatalogResourceTypes=(.*)$"
)
OVERVIEW_HEADING = "## リソース一覧"
OVERVIEW_TYPE_HEADING_PATTERN = re.compile(
    r"^### ([A-Za-z0-9]+\.[A-Za-z0-9]+)$"
)
FORBIDDEN_DESIGN_METADATA_PATTERN = re.compile(
    r"^\s*-\s*(Environment|AWS account ID|AWS region|Purpose|Deployment state)\s*:",
    re.IGNORECASE,
)
FORBIDDEN_DESIGN_SECTION_PATTERN = re.compile(
    r"^#{1,6} +(Design decisions|Out of scope|Generated values|設計判断(?:事項)?|設計上の判断|設計上の決定|対象外|スコープ外|設計対象外|生成値|生成された値|デプロイ後生成値)(?:$|[:： -].*)",
    re.IGNORECASE,
)
JAPANESE_TEXT_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
MATERIAL_PATTERN = re.compile(
    r"^[A-Za-z0-9]+(?:\[\])?(?:\.[A-Za-z0-9]+(?:\[\])?)+=(?:IDENTIFIER_OUTPUT)?$"
)
LOWER_KEBAB_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
TASK_TYPES = {
    "initialization",
    "design",
    "infrastructure",
    "scenario-test",
    "governance",
    "catalog-maintenance",
    "migration",
}
REQUIRED_NAME_PROPERTIES = {
    "EC2.FlowLog": "EC2.FlowLog.Name",
    "EC2.RouteTable": "EC2.RouteTable.Name",
    "EC2.Subnet": "EC2.Subnet.Name",
    "EC2.VPC": "EC2.VPC.Name",
}
GROUPED_CHILD_RESOURCE_TYPES = set(GROUPED)
DESIGN_ONLY_PROPERTIES = {"S3.Bucket.Region": "S3.Bucket"}
S3_KMS_MASTER_KEY_ID = (
    "S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[]"
    ".ServerSideEncryptionByDefault.KMSMasterKeyID"
)
RESULT_STATUSES = {"PASS", "FAIL", "BLOCKED", "STALE", "NOT_EXECUTED"}
CODEX_PROMPT_FILENAME_PATTERN = re.compile(r"\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*\.md")
RESULT_METADATA = (
    "Scenario ID",
    "Environment",
    "AWS account ID",
    "AWS region",
    "Status",
    "Executed at",
)
SHORT_CF_INTRINSICS = (
    "Ref", "Fn::And", "Fn::Base64", "Fn::Cidr", "Fn::Equals", "Fn::FindInMap",
    "Fn::GetAtt", "Fn::GetAZs", "Fn::GetStackOutput", "Fn::If", "Fn::ImportValue",
    "Fn::Join", "Fn::Not", "Fn::Or", "Fn::Select", "Fn::Split", "Fn::Sub",
    "Fn::Transform",
)
_SHORT_CF_NAMES = "|".join(re.escape(name) for name in SHORT_CF_INTRINSICS)
LONG_CF_KEY = re.compile(rf"(?<![A-Za-z0-9_])(?:{_SHORT_CF_NAMES})\s*:")
QUOTED_LONG_CF_KEY = re.compile(
    rf"(?P<prefix>^|[{{,]|-\s)\s*(?P<quote>['\"])(?:{_SHORT_CF_NAMES})(?P=quote)\s*:"
)
YAML_REUSE = re.compile(r"(?<![A-Za-z0-9_-])(?:[&*][A-Za-z0-9_-]+|<<\s*:)")


class Validator:
    def __init__(self, root: Path, scope=None, contract_scope=None, *, cache=False, fresh=False, workers=4) -> None:
        self.workers = workers
        self.cache = PassCache(root, fresh) if cache else None
        self.relative_paths = {}
        self.canonical_root = root.resolve()
        self.scope = scope
        self.contract_scope = contract_scope
        self.generated_models_checked = False
        self.root = root
        self.errors: list[str] = []
        self.checks = 0
        self.changed_paths: set[str] = set()
        self.task_type = ""
        self.infrastructure_phase = ""
        self.requirement_ids: list[str] = []
        self.acceptance_checks: list[tuple[str, str, str]] = []
        self.acceptance_results: list[str] = []
        self.template_mode = True
        self.accounts: dict[tuple[str, str], dict[str, str]] = {}
        self.scenario_ids: set[str] = set()
        self.result_files: dict[str, list[Path]] = {}
        self.markdown_design_artifacts: set[Path] = set()
        self.markdown_iam_policy_artifacts: dict[tuple[str, str, str, str], Path] = {}
        self.schema_catalog: DesignSchemaCatalog | None = None

    def check(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)

    def relative(self, path: Path) -> str:
        if path not in self.relative_paths:
            self.relative_paths[path] = path.resolve().relative_to(self.canonical_root).as_posix()
        return self.relative_paths[path]

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
        self.check_task_type_requirements()
        self.check_initialized_paths()
        self.check_catalog()
        self.check_resource_layout()
        if self.scope is None:
            self.check_designs()
            self.check_observed_values()
        elif not self.errors:
            self.check_scoped_designs()
        self.check_iac_selection()
        if self.scope is None or self.task_type == "infrastructure":
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
            return 1

        print(f"Blueprint repository validation: PASS ({self.checks} checks)")
        if self.task_type:
            print(f"- task type: {self.task_type}")
        else:
            print("- task state: idle (no active task)")
        print(f"- task requirements: {', '.join(self.requirement_ids)}")
        print(f"- acceptance checks: {len(self.acceptance_results)}/{len(self.acceptance_checks)} passed")
        print(f"- mode: {'template' if self.template_mode else 'project'}")
        print(f"- validation scope: {'all' if self.scope is None else ', '.join('/'.join(item) for item in sorted(self.scope)) or 'framework'}")
        return 0

    def check_structure(self) -> None:
        for filename in (
            "AGENTS.md",
            "README.md",
            "framework/chatbot/personal-custom-instructions.md",
            "docs/system-overview.md",
            "framework/prompts/README.md",
            "framework/prompts/chatbot/service-design.md",
            "framework/prompts/codex/01_initialize.md",
            "framework/prompts/codex/02_add-target.md",
            "framework/prompts/codex/03_implement.md",
            "framework/prompts/codex/04_deploy.md",
            "framework/prompts/codex/05_update.md",
            "framework/prompts/codex/06_scenario-test.md",
            "framework/scripts/blueprint-loop.py",
            "framework/scripts/check-deploy-context.py",
            "framework/scripts/cloudformation_schema.py",
            "framework/scripts/sync-model.py",
        ):
            self.check((self.root / filename).is_file(), f"required file missing: {filename}")
        for directory in REQUIRED_DIRECTORIES:
            self.check((self.root / directory).is_dir(), f"required directory missing: {directory}")
        codex_prompt_names = sorted(
            path.name
            for path in (self.root / "framework" / "prompts" / "codex").glob("*")
            if path.is_file()
        )
        invalid_prompt_names = [
            name for name in codex_prompt_names if not CODEX_PROMPT_FILENAME_PATTERN.fullmatch(name)
        ]
        self.check(not invalid_prompt_names, f"invalid Codex prompt filenames: {invalid_prompt_names}")
        prompt_numbers = [name.split("_", 1)[0] for name in codex_prompt_names]
        self.check(
            len(prompt_numbers) == len(set(prompt_numbers)),
            "Codex prompt numbers must be unique",
        )
        actual_rules = {
            path.name for path in (self.root / "framework" / "rules").glob("*.md")
        }
        self.check(REQUIRED_RULES <= actual_rules, f"required rules missing: {sorted(REQUIRED_RULES - actual_rules)}")

    def git_paths(self, args: list[str]) -> set[str]:
        result = subprocess.run(
            ["git", *args], cwd=self.root, check=False, capture_output=True, text=True
        )
        self.check(result.returncode == 0, f"git {' '.join(args)} failed")
        return {path for path in result.stdout.split("\0") if path} if result.returncode == 0 else set()

    def check_task_scope(self) -> None:
        prompt = task_path(self.root)
        self.changed_paths = (
            self.git_paths(["diff", "--no-renames", "--name-only", "-z"])
            | self.git_paths(["diff", "--cached", "--no-renames", "--name-only", "-z"])
            | self.git_paths(["ls-files", "--others", "--exclude-standard", "-z"])
        ) - {".lock"}  # Per-repository password configuration is not a task artifact.
        if not self.changed_paths:
            return
        if not prompt.is_file():
            if contracts(self.root):
                self.changed_paths = task_changes(self.root, self.changed_paths)
                return
            self.check(
                not (self.changed_paths - {"tasks/active.md"}),
                f"active task prompt missing: {self.relative(prompt)} while repository has non-contract changes",
            )
            return

        self.changed_paths = task_changes(self.root, self.changed_paths, self.relative(prompt))
        if not self.changed_paths:
            return

        lines = prompt.read_text(encoding="utf-8").splitlines()
        contract: list[str] = []
        in_contract = False
        for line in lines:
            if line == "## Task contract":
                in_contract = True
                continue
            if in_contract and line.startswith("## "):
                break
            if in_contract:
                contract.append(line)
        task_types = []
        for line in contract:
            match = re.fullmatch(r"- Task type: `([^`]+)`", line)
            if match:
                task_types.append(match.group(1))
        self.check(len(task_types) == 1, f"Task type must appear exactly once in Task contract: {self.relative(prompt)}")
        if task_types:
            self.task_type = task_types[0]
            self.check(self.task_type in TASK_TYPES, f"unknown Task type: {self.task_type}")

        infrastructure_phases = []
        for line in contract:
            match = re.fullmatch(r"- Infrastructure phase: `([^`]+)`", line)
            if match:
                infrastructure_phases.append(match.group(1))
        expected_phase_count = 1 if self.task_type == "infrastructure" else 0
        self.check(
            len(infrastructure_phases) == expected_phase_count,
            f"Infrastructure phase must appear exactly once for infrastructure tasks only: {self.relative(prompt)}",
        )
        if infrastructure_phases:
            self.infrastructure_phase = infrastructure_phases[0]
            self.check(
                self.infrastructure_phase in {"implement", "deploy", "update"},
                f"unknown Infrastructure phase: {self.infrastructure_phase}",
            )

        requirement_ids: list[str] = []
        for line in self.section(lines, "## Required changes"):
            if not line.startswith("- "):
                continue
            match = re.fullmatch(r"- \[([A-Z][A-Z0-9-]*)\] .+", line)
            self.check(match is not None, f"invalid Required changes entry: {self.relative(prompt)}: {line}")
            if match:
                requirement_ids.append(match.group(1))
        self.check(bool(requirement_ids), f"Required changes section missing or empty: {self.relative(prompt)}")
        self.check(len(requirement_ids) == len(set(requirement_ids)), f"duplicate requirement ID: {self.relative(prompt)}")
        self.requirement_ids = requirement_ids

        acceptance_ids: set[str] = set()
        for line in self.section(lines, "## Acceptance checks"):
            if not line.startswith("- "):
                continue
            match = re.fullmatch(
                r"- \[([A-Z][A-Z0-9-]*)\] `(changed|exists|absent|check):([^`]+)`",
                line,
            )
            self.check(match is not None, f"invalid Acceptance checks entry: {self.relative(prompt)}: {line}")
            if not match:
                continue
            requirement_id, kind, value = match.groups()
            acceptance_ids.add(requirement_id)
            self.acceptance_checks.append((requirement_id, kind, value))
            self.check(requirement_id in requirement_ids, f"Acceptance check uses unknown requirement ID: {requirement_id}")
            if kind != "check":
                candidate = Path(value)
                self.check(not candidate.is_absolute() and ".." not in candidate.parts, f"unsafe Acceptance check path: {value}")
        for requirement_id in requirement_ids:
            self.check(requirement_id in acceptance_ids, f"requirement has no Acceptance check: {requirement_id}")

        allowed: list[str] = []
        in_section = False
        for line in lines:
            if line == "## Allowed paths":
                in_section = True
                continue
            if in_section and line.startswith("## "):
                break
            match = re.fullmatch(r"- `([^`]+)`", line) if in_section else None
            if match:
                allowed.append(match.group(1))
        self.check(bool(allowed), f"Allowed paths section missing or empty: {self.relative(prompt)}")

        for changed in sorted(self.changed_paths):
            permitted = any(self.matches(changed, pattern) for pattern in allowed)
            self.check(permitted, f"changed path is outside task scope: {changed}")
        self.check_task_boundary(prompt)

    @staticmethod
    def section(lines: list[str], heading: str) -> list[str]:
        content: list[str] = []
        in_section = False
        for line in lines:
            if line == heading:
                in_section = True
                continue
            if in_section and line.startswith("## "):
                break
            if in_section:
                content.append(line)
        return content

    @staticmethod
    def matches(path: str, pattern: str) -> bool:
        return path == pattern or (
            pattern.endswith("/**") and path.startswith(pattern[:-3] + "/")
        ) or fnmatch.fnmatchcase(path, pattern)

    @staticmethod
    def under(path: str, prefix: str) -> bool:
        return path == prefix or path.startswith(prefix + "/")

    def check_task_boundary(self, prompt: Path) -> None:
        if self.task_type not in TASK_TYPES:
            return
        prompt_path = self.relative(prompt)
        for changed in sorted(self.changed_paths):
            if self.task_type == "design":
                forbidden = self.under(changed, "infra") or self.under(changed, "tests")
                self.check(not forbidden, f"design task boundary violation: {changed}")
            elif self.task_type == "infrastructure":
                forbidden = self.under(changed, "tests")
                self.check(not forbidden, f"infrastructure task boundary violation: {changed}")
            elif self.task_type == "scenario-test":
                permitted = changed == prompt_path or self.under(changed, "tests/scenarios") or self.under(changed, "tests/results")
                self.check(permitted, f"scenario-test task boundary violation: {changed}")
            elif self.task_type in {"initialization", "governance", "catalog-maintenance", "migration"}:
                forbidden = self.under(changed, "tests/scenarios") or self.under(changed, "tests/results")
                self.check(not forbidden, f"{self.task_type} task boundary violation: {changed}")

    def check_issue_gate(self) -> None:
        if not self.task_type:
            return
        try:
            scope = active_scope(self.root)
            if self.task_type == "migration" and scope:
                reports = {f"issues/{env}/{target}/{name}" for env, target, _ in scope
                           for name in ("issues.md", "diff.md")}
                prompt = task_path(self.root)
                permitted = reports | {self.relative(prompt)}
                lines = prompt.read_text(encoding="utf-8").splitlines()
                allowed = self.section(lines, "## Allowed paths")
                allowed = {line[3:-1] for line in allowed if re.fullmatch(r"- `[^`]+`", line)}
                if allowed & reports and allowed <= permitted and self.changed_paths <= permitted:
                    return  # Report-only saves may continue; model saves and AWS guards still apply.
            service_changed = any(path.startswith(("model/", "docs/designs/", "infra/", "issues/")) for path in self.changed_paths)
            if self.task_type in {"governance", "catalog-maintenance"} and scope is None and not service_changed:
                scope = set()  # Framework-wide validation does not target consumer services.
            require_no_issues(self.root, scope)
        except (OSError, ValueError) as error:
            self.check(False, str(error))

    def check_task_type_requirements(self) -> None:
        changed = {path for path in self.changed_paths if not TASK_NAME.fullmatch(path)}
        if self.task_type == "initialization":
            self.check("project.json" in changed, "initialization task must change project.json")
        elif self.task_type == "design":
            markdown = {path for path in changed if path.startswith("docs/designs/") and path.endswith(".md")}
            artifacts = {path for path in changed if path.startswith("docs/designs/") and path.endswith(".json")}
            model_files = {path for path in changed if path.startswith("model/") and path.endswith(".properties")}
            models = {service_model_path(self.root / path, self.root / "model").relative_to(self.root).as_posix()
                      for path in model_files}
            self.check(bool(markdown or artifacts), "design task must change detailed-design Markdown or JSON artifacts")
            self.check(bool(models), "design task must change authoritative service properties")
            for path in markdown:
                expected = "model/" + path.removeprefix("docs/designs/").removesuffix(".md") + ".properties"
                self.check(expected in models, f"changed design Markdown lacks changed service model: {path}")
            for path in models:
                expected = "docs/designs/" + path.removeprefix("model/").removesuffix(".properties") + ".md"
                service = expected.removesuffix(".md") + "/"
                self.check(
                    expected in changed or any(artifact.startswith(service) for artifact in artifacts),
                    f"changed authoritative model lacks changed generated design: {path}",
                )
            for path in artifacts:
                parts = Path(path).parts
                if len(parts) >= 6:
                    expected = f"model/{parts[2]}/{parts[3]}/{parts[4]}.properties"
                    self.check(expected in models, f"changed design JSON lacks changed service model: {path}")
        elif self.task_type == "infrastructure":
            iac_changed = any(self.under(path, "infra") for path in changed)
            if self.infrastructure_phase == "implement":
                self.check(iac_changed, "infrastructure implement phase must change selected IaC")
            elif self.infrastructure_phase == "deploy":
                self.check(not iac_changed, "infrastructure deploy phase must not change IaC")
            elif self.infrastructure_phase == "update":
                self.check(iac_changed, "infrastructure update phase must change selected IaC")
                self.check(
                    any(path.startswith("docs/designs/") and path.endswith(".md") for path in changed),
                    "infrastructure update phase must include generated detailed-design Markdown",
                )
                self.check(
                    any(path.startswith("model/") and path.endswith(".properties") for path in changed),
                    "infrastructure update phase must include human-changed authoritative service properties",
                )
        elif self.task_type == "scenario-test":
            self.check(any(self.under(path, "tests/scenarios") for path in changed), "scenario-test task must change a scenario")
            self.check(any(self.under(path, "tests/results") for path in changed), "scenario-test task must change its current result")
        elif self.task_type == "governance":
            self.check(bool(changed), "governance task must change framework files")
        elif self.task_type == "catalog-maintenance":
            self.check(any(self.under(path, "framework/materials/aws") for path in changed), "catalog-maintenance task must change catalog files")
            self.check("framework/materials/catalog.sha256" in changed, "catalog-maintenance task must update framework/materials/catalog.sha256")
        elif self.task_type == "migration":
            self.check(bool(changed), "migration task must change its required outputs")

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
        for requirement_id, kind, value in self.acceptance_checks:
            before = len(self.errors)
            if kind == "changed":
                self.check(any(self.matches(path, value) for path in self.changed_paths), f"required changed path missing: {requirement_id}: {value}")
            elif kind == "exists":
                self.check(any(self.root.glob(value)), f"required path missing: {requirement_id}: {value}")
            elif kind == "absent":
                self.check(not any(self.root.glob(value)), f"forbidden path exists: {requirement_id}: {value}")
            else:
                handler = registered.get(value)
                self.check(handler is not None, f"unknown registered Acceptance check: {requirement_id}: {value}")
                if handler:
                    handler()
            if len(self.errors) == before:
                self.acceptance_results.append(f"{requirement_id}:{kind}:{value}")

    def check_framework_active_task_transition(self) -> None:
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        self.check("## Task transition" in agents, "AGENTS.md lacks Task transition rules")
        self.check("## Task transition" in readme, "README.md lacks Task transition workflow")
        self.check("chat-only" in agents and "chat-only" in readme, "chat-only task handling is not defined")
        required = {
            "AGENTS.md": "tasks/<task-name>.md",
            "README.md": "tasks/<task-name>.md",
            "framework/rules/task-contract.md": "## Modified files",
            "framework/prompts/chatbot/service-design.md": "tasks/<task-name>.md",
            "framework/prompts/codex/03_implement.md": "tasks/<task-name>.md",
            "framework/prompts/codex/04_deploy.md": "tasks/<task-name>.md",
            "framework/prompts/codex/05_update.md": "tasks/<task-name>.md",
        }
        for relative, literal in required.items():
            path = self.root / relative
            self.check(path.is_file(), f"active task lifecycle file missing: {relative}")
            if path.is_file():
                self.check(literal in path.read_text(encoding="utf-8"), f"active task lifecycle rule missing: {relative}")

    def check_framework_rule_readings(self) -> None:
        from deploy_preparation import markdown_sections, rule_readings
        sources = [self.root / "AGENTS.md", self.root / "README.md",
                   *sorted((self.root / "framework/rules").glob("*.md")),
                   *sorted((self.root / "framework/prompts").rglob("*.md")),
                   *sorted((self.root / ".agents/skills").glob("*/SKILL.md"))]
        for source in sources:
            try:
                text = source.read_text(encoding="utf-8")
                rule_readings(self.root, source, text)
                if source.parent == self.root / "framework/prompts/codex":
                    sections = markdown_sections(text)
                    reading = sections.get("read-first", sections.get("read-before-changing-files", ""))
                    required = {self.root / "framework/rules" / name for name in
                                ("task-contract.md", "issue-gate.md", "project-configuration.md")}
                    self.check(required <= rule_readings(self.root, source, reading).keys(),
                               f"workflow lacks canonical rule readings: {source.relative_to(self.root)}")
            except (OSError, ValueError) as error:
                self.check(False, f"rule reading reference: {error}")

    def check_framework_design_handoff(self) -> None:
        path = self.root / "framework" / "prompts" / "chatbot" / "service-design.md"
        self.check(path.is_file(), "service design prompt is missing")
        if not path.is_file():
            return
        prompt = path.read_text(encoding="utf-8")
        self.check("Task typeは`design`" in prompt, "service design prompt lacks design task contract")
        self.check("sync-model.py" in prompt, "service design prompt lacks properties-based Markdown generation")
        self.check("blueprint-loop.py --mode task" in prompt, "service design prompt lacks local validation")
        self.check("03_apply-design.md" not in prompt, "service design prompt still depends on apply-design")
        gate = "## Naming rule preflight（設計開始gate）"
        self.check(gate in prompt and "## Determine what to ask" in prompt
                   and prompt.index(gate) < prompt.index("## Determine what to ask"),
                   "service design prompt lacks naming preflight before design questions")
        self.check("check-design-naming.py --resource-type" in prompt,
                   "service design prompt lacks executable naming preflight")
        self.check("design契約登録前に`check-design-naming.py`" in prompt,
                   "service design handoff lacks naming preflight before task registration")
        required_existing_resource_contract = {
            "--read-only": "service design prompt lacks read-only AWS context preflight",
            "aws cloudcontrol list-resources": "service design prompt lacks generic existing-resource discovery",
            "aws cloudcontrol get-resource": "service design prompt lacks generic existing-resource read",
            "対象service固有のread-only APIへfallback": "service design prompt lacks service API fallback",
            "一件だけでもhumanが選択": "service design prompt may auto-select an existing resource",
            "logical IDを一回の応答につき一つ質問": "service design prompt may invent a logical ID for an existing resource",
            "直接差分反映": "service design prompt lacks direct existing-value synchronization",
            "存在しないoptional property rowは削除": "service design prompt lacks absent optional-property removal",
            "password、secret、token、credentialは表示または保存せず": "service design prompt lacks sensitive-value exclusion",
            "generated ARNはMarkdown、JSON artifact、modelへ保存しない": "service design prompt may persist generated ARNs",
            "resourceの作成者、管理者、外部作成済みという出自": "service design prompt persists or omits the no-provenance contract",
        }
        for literal, error in required_existing_resource_contract.items():
            self.check(literal in prompt, error)

    def check_framework_task_completion_contract(self) -> None:
        contract = (self.root / "framework/rules/task-contract.md").read_text(encoding="utf-8")
        rules = (self.root / "framework" / "rules" / "loop-engineering.md").read_text(encoding="utf-8")
        self.check("Requirement ID" in contract and "Acceptance checks" in contract, "task rules lack completion contract")
        self.check("task-contract.md#acceptance-contract" in rules, "loop lacks canonical completion contract reference")

    def check_framework_task_type_dispatch(self) -> None:
        self.check(self.task_type in TASK_TYPES, "task type completion check was not dispatched")
        self.check(len(TASK_TYPES) == 7, "not every task type has a completion-check branch")

    def check_framework_focused_check_runner(self) -> None:
        loop = (self.root / "framework" / "scripts" / "blueprint-loop.py").read_text(encoding="utf-8")
        self.check('glob("*.checks.py")' in loop, "local loop does not discover focused checks")
        self.check("PYTHONDONTWRITEBYTECODE" in loop, "focused checks may write bytecode into the repository")

    def check_validation_scope(self) -> None:
        scope = self.contract_scope if self.contract_scope is not None else self.scope
        if scope is None:
            return
        for environment, target, service in sorted(scope):
            self.check((environment, target) in self.accounts, f"validation target is not defined in project.json: {environment}/{target}")
            for base, suffix in (("model", ".properties"), ("docs/designs", ".md")):
                relative = f"{base}/{environment}/{target}/{service}{suffix}"
                self.check((self.root / relative).is_file(), f"validation input missing: {relative}")
        for changed in sorted(self.changed_paths):
            for base in ("model/", "docs/designs/"):
                if changed.startswith(base):
                    parts = Path(changed.removeprefix(base)).parts
                    identity = (parts[0], parts[1], Path(parts[2]).stem) if len(parts) >= 3 else None
                    self.check(identity in scope, f"changed design path is outside validation scope: {changed}")

    def check_model_files(self) -> None:
        base = self.root / "model"
        listed = set()
        for path in scoped_files(self.root, "model", ".properties", self.scope):
            try:
                read_model(path)
                for file in {path, *model_parts(path)}:
                    listed.add(file)
                    self.check(len(file.read_text(encoding="utf-8").splitlines()) <= MAX_LINES,
                               f"model file exceeds {MAX_LINES} lines; split with model_files.py: {self.relative(file)}")
            except (OSError, ValueError) as error:
                self.check(False, f"invalid service model: {self.relative(path)}: {error}")
        for path in base.rglob("*.properties"):
            parts = path.relative_to(base).parts
            if self.scope is not None and (len(parts) < 3 or (parts[0], parts[1], Path(parts[2]).stem) not in self.scope):
                continue
            self.check(path in listed, f"model properties must be a service entrance or its indexed part: {self.relative(path)}")

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
        missing = self.scope - reused.keys()
        generator = Validator(self.root, missing, workers=self.workers)
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
            validator.schema_catalog = DesignSchemaCatalog(self.root)
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

    def check_framework_cloudformation_schema_catalog(self) -> None:
        errors = snapshot_errors(self.root)
        self.check(not errors, "; ".join(errors) or "CloudFormation schema snapshot is invalid")

    def check_framework_schema_backed_design_validation(self) -> None:
        rules = (self.root / "framework" / "rules" / "detailed-design.md").read_text(encoding="utf-8")
        prompt = (
            self.root / "framework" / "prompts" / "chatbot" / "service-design.md"
        ).read_text(encoding="utf-8")
        self.check("CloudFormation provider schema" in rules, "detailed design rules do not apply provider schemas")
        self.check("CloudFormation provider schema" in prompt, "initial design prompt does not apply provider schemas")
        catalog = CloudFormationSchemaCatalog(self.root)
        self.check(bool(catalog.literal_errors("Logs.LogGroup", "KmsKeyId", "not-used")), "schema-backed literal validation is inactive")

    def check_framework_cfn_lint_validation(self) -> None:
        paths = (
            self.root / "framework" / "rules" / "cloudformation.md",
            self.root / "framework" / "prompts" / "codex" / "03_implement.md",
            self.root / "framework" / "prompts" / "codex" / "04_deploy.md",
            self.root / "framework" / "scripts" / "check-deploy-context.py",
        )
        for path in paths:
            self.check("cfn-lint" in path.read_text(encoding="utf-8"), f"cfn-lint requirement missing: {self.relative(path)}")

    def check_tasks(self) -> None:
        try:
            reservations(self.root, contracts(self.root))
        except (OSError, ValueError) as error:
            self.check(False, str(error))

    def check_project_topology(self) -> None:
        path = self.root / "project.json"
        self.template_mode = not path.is_file()
        if self.template_mode:
            return

        text = path.read_text(encoding="utf-8")
        self.check(text.endswith("\n"), "project.json must end with a newline")
        try:
            topology = json.loads(text)
        except json.JSONDecodeError as error:
            self.errors.append(f"invalid project.json: {error}")
            return

        self.check(isinstance(topology, dict), "project.json root must be an object")
        if not isinstance(topology, dict):
            return
        self.check(set(topology) == {"projectName", "targets"}, "project.json must contain only projectName and targets")

        project_name = topology.get("projectName")
        self.check(isinstance(project_name, str) and project_name not in {"", "UNSET"}, "projectName is required")

        targets = topology.get("targets")
        self.check(isinstance(targets, list) and bool(targets), "targets must be a non-empty array")
        if not isinstance(targets, list):
            return

        order: list[tuple[str, str]] = []
        environment_targets: dict[str, list[dict[str, str]]] = {}
        account_engines: dict[tuple[str, str], str] = {}
        execution_account_engines: dict[tuple[str, str], str] = {}
        required = {"environment", "awsAccountId", "awsRegion", "iacEngine"}
        allowed = required | {"alias", "awsProfile", "awsExecutionAccountId", "suffix"}
        for index, target_values in enumerate(targets, 1):
            self.check(isinstance(target_values, dict), f"target {index} must be an object")
            if not isinstance(target_values, dict):
                continue
            self.check(
                required <= set(target_values) <= allowed,
                f"target {index} must contain {sorted(required)} and optional alias/awsProfile/awsExecutionAccountId/suffix only",
            )
            if not required <= set(target_values):
                continue
            values = list(target_values.values())
            self.check(all(isinstance(value, str) for value in values), f"target {index} values must be strings")
            if not all(isinstance(value, str) for value in values):
                continue
            environment = target_values["environment"]
            account = target_values["awsAccountId"]
            region = target_values["awsRegion"]
            engine = target_values["iacEngine"]
            alias = target_values.get("alias", "")
            target_directory = alias or account
            target = f"{environment}/{target_directory}"
            execution_account = target_values.get("awsExecutionAccountId", account)
            self.check(
                re.fullmatch(r"[0-9]{12}", execution_account) is not None,
                f"invalid AWS execution account: {target}",
            )
            if "awsProfile" in target_values:
                profile = target_values["awsProfile"]
                self.check(
                    bool(profile) and profile == profile.strip() and profile != "UNSET"
                    and not any(char in profile for char in "\r\n\0"),
                    f"invalid AWS profile: {target}",
                )
            if "suffix" in target_values:
                self.check(
                    LOWER_KEBAB_PATTERN.fullmatch(target_values["suffix"]) is not None,
                    f"invalid naming suffix: {target}: expected a non-empty lower-kebab-case string",
                )
            self.check("UNSET" not in values and all(values), f"target contains unset value: {target}")
            self.check(LOWER_KEBAB_PATTERN.fullmatch(environment) is not None, f"invalid Environment ID: {environment}")
            self.check(re.fullmatch(r"\d{12}", account) is not None, f"invalid AWS account: {target}")
            if alias:
                self.check(
                    LOWER_KEBAB_PATTERN.fullmatch(alias) is not None
                    and re.fullmatch(r"\d{12}", alias) is None,
                    f"invalid target alias: {target}",
                )
            if region in {"", "UNSET"}:
                self.check(False, f"AWS region is required: {target}")
            else:
                self.check(
                    re.fullmatch(r"[a-z]{2,}(?:-[a-z0-9]+)+-[1-9][0-9]*", region) is not None,
                    f"invalid AWS region ID: {target}: {region}",
                )
            self.check(engine in {"cloudformation", "terraform"}, f"invalid IaC engine: {target}")
            key = (environment, target_directory)
            order.append(key)
            self.check(key not in self.accounts, f"duplicate target directory in environment: {target}")
            if key not in self.accounts:
                self.accounts[key] = {
                    "account": account,
                    "alias": alias,
                    "region": region,
                    "engine": engine,
                }
            environment_targets.setdefault(environment, []).append(target_values)
            account_key = (environment, account)
            previous_engine = account_engines.get(account_key)
            self.check(
                previous_engine in {None, engine},
                f"aliases for the same environment/AWS account must use one IaC engine: {environment}/{account}",
            )
            account_engines.setdefault(account_key, engine)
            execution_key = (environment, execution_account)
            self.check(
                execution_account_engines.get(execution_key) in {None, engine},
                f"targets for the same environment/AWS execution account must use one IaC engine: {environment}/{execution_account}",
            )
            execution_account_engines.setdefault(execution_key, engine)

        for environment, environment_values in environment_targets.items():
            aliases = [value.get("alias", "") for value in environment_values]
            if len(environment_values) == 1:
                self.check(not aliases[0], f"single-target environment must omit alias: {environment}")
            else:
                self.check(
                    all(aliases),
                    f"multi-target environment requires alias on every target: {environment}",
                )
                self.check(
                    len(aliases) == len(set(aliases)),
                    f"target aliases must be unique within environment: {environment}",
                )
        self.check(order == sorted(order), "targets must be sorted by environment and target directory")

    def check_initialized_paths(self) -> None:
        if self.template_mode:
            return
        for (environment, target_directory), values in self.accounts.items():
            if self.scope is not None and not any(item[:2] == (environment, target_directory) for item in self.scope):
                continue
            paths = [
                self.root / "docs" / "designs" / environment / target_directory,
                self.root / "model" / environment / target_directory,
            ]
            if values["engine"] == "cloudformation":
                paths.append(self.root / "infra" / "cloudformation" / "parameters" / environment / target_directory)
            else:
                paths.append(self.root / "infra" / "terraform" / "environments" / environment / target_directory)
            for path in paths:
                self.check(path.is_dir(), f"initialized target path missing: {self.relative(path)}")

    def check_api_design_catalog(self) -> None:
        errors = api_snapshot_errors(self.root)
        self.check(not errors, "; ".join(errors) or "API design catalog is invalid")

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

    def check_catalog_inputs(self) -> None:
        result = subprocess.run(
            [sys.executable, str(self.root / "framework" / "scripts" / "update-catalog-lock.py")],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.check(result.returncode == 0, result.stdout.strip() or "catalog lock check failed")

        schema_failures = snapshot_errors(self.root)
        self.check(not schema_failures, "; ".join(schema_failures) or "CloudFormation schema snapshot check failed")
        api_failures = api_snapshot_errors(self.root)
        self.check(not api_failures, "; ".join(api_failures) or "API design snapshot check failed")
        if not schema_failures and not api_failures:
            self.schema_catalog = DesignSchemaCatalog(self.root)

        for path in design_material_files(self.root):
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            prefix = path.stem.replace("_", ".", 1) + "."
            self.check(text.endswith("\n"), f"catalog file lacks final newline: {self.relative(path)}")
            self.check(len(lines) == len({line.partition("=")[0] for line in lines}), f"catalog properties must be unique; file order is display order: {self.relative(path)}")
            for index, line in enumerate(lines):
                self.check(MATERIAL_PATTERN.fullmatch(line) is not None, f"invalid catalog line: {self.relative(path)}: {line}")
                self.check(line.startswith(prefix), f"catalog prefix mismatch: {self.relative(path)}: {line}")

    def design_files(self) -> list[Path]:
        return [path for path in scoped_files(self.root, "docs/designs", ".md", self.scope) if path.name != STACK_DESIGN]

    def stack_design_files(self) -> list[Path]:
        return [path for path in scoped_files(self.root, "docs/designs", ".md", self.scope) if path.name == STACK_DESIGN]

    def check_target_file(self, path: Path, base: Path) -> tuple[str, str] | None:
        parts = path.relative_to(base).parts
        self.check(len(parts) == 3, f"target file must be <environment>/<target-directory>/<file>: {self.relative(path)}")
        if len(parts) != 3:
            return None
        target = (parts[0], parts[1])
        self.check(target in self.accounts, f"target is not defined in project.json: {self.relative(path)}")
        return target

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

    def check_stack_designs(self, paths: list[Path] | None = None) -> None:
        names: set[tuple[str, str, str]] = set()
        for path in self.stack_design_files() if paths is None else paths:
            target = self.check_target_file(path, self.root / "docs" / "designs")
            if target is None or target not in self.accounts:
                continue
            self.check(
                self.accounts[target]["engine"] == "cloudformation",
                f"stack design requires CloudFormation target: {self.relative(path)}",
            )
            try:
                from design_layout import stack_delivery
                from model_design import deployment_settings, deployment_bucket
                stack_deployment_policy(path)
                stacks = stack_design(path)
                from cloudformation_observed import validate_mapping_targets
                source = (self.root / "model" / path.relative_to(self.root / "docs" / "designs")).with_suffix(".properties")
                if source.is_file():
                    mapping_values = properties(read_model(source))
                    from model_design import stack_model
                    stack_model(mapping_values)
                    validate_mapping_targets(self.root, target[0], target[1], mapping_values)
                values = stack_delivery(path) | {f"desired.stack.{number:03d}.name": stack["name"]
                                               for number, stack in enumerate(stacks, 1)}
                settings, artifacts = deployment_settings(values)
                for reference in ([settings["templateBucket"]] if settings else []) + [a["bucket"] for _, a in artifacts]:
                    deployment_bucket(reference, path, self.root)
            except ValueError as error:
                self.check(False, f"invalid stack design: {self.relative(path)}: {error}")
                continue
            self.check(len({stack["name"] for stack in stacks}) == len(stacks), f"duplicate stack name in design: {self.relative(path)}")
            parameter_files: set[str] = set()
            for stack in stacks:
                name = stack["name"]
                self.check(
                    JAPANESE_TEXT_PATTERN.search(stack["comment"]) is not None,
                    f"stack Comment must describe its purpose in Japanese: {self.relative(path)}: {name}",
                )
                self.check(re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,127}", name) is not None, f"invalid stack name: {name}")
                identity = (self.accounts[target]["account"], self.accounts[target]["region"], name)
                self.check(identity not in names, f"duplicate stack in AWS account/region: {name}")
                names.add(identity)
                template = Path(stack["template"])
                self.check(
                    template.name == stack["template"] and template.suffix in {".yaml", ".yml"},
                    f"invalid stack template filename: {self.relative(path)}: {name}",
                )
                parameters = Path(stack["parameters"])
                self.check(
                    parameters.name == stack["parameters"] and parameters.suffix == ".json",
                    f"invalid stack parameter filename: {self.relative(path)}: {name}",
                )
                self.check(stack["parameters"] not in parameter_files, f"parameter file belongs to multiple stacks: {stack['parameters']}")
                parameter_files.add(stack["parameters"])

    @memoized
    def catalog_design_properties(
        self,
    ) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
        resource_types: set[str] = set()
        property_owners: dict[str, set[str]] = {}
        identifier_outputs: dict[str, set[str]] = {}
        for path in design_material_files(self.root):
            resource_type = path.stem.replace("_", ".", 1)
            prefix = f"{resource_type}."
            resource_types.add(resource_type)
            for line in path.read_text(encoding="utf-8").splitlines():
                property_name, separator, marker = line.partition("=")
                if not separator or not property_name.startswith(prefix):
                    continue
                property_path = property_name[len(prefix) :]
                property_owners.setdefault(property_path, set()).add(resource_type)
                property_owners.setdefault(property_name, set()).add(resource_type)
                if marker == "IDENTIFIER_OUTPUT" and property_name not in HIDDEN_PROPERTIES:
                    identifier_outputs.setdefault(resource_type, set()).add(property_name)
        for resource_type, property_name in REQUIRED_NAME_PROPERTIES.items():
            if resource_type in resource_types:
                property_owners.setdefault(property_name, set()).add(resource_type)
        for property_name, resource_type in DESIGN_ONLY_PROPERTIES.items():
            if resource_type in resource_types:
                property_owners.setdefault(property_name, set()).add(resource_type)
        return resource_types, property_owners, identifier_outputs

    def check_service_file(self, path: Path, service_id: str, owned_types: tuple[str, ...]) -> None:
        self.check(LOWER_KEBAB_PATTERN.fullmatch(service_id) is not None, f"invalid service ID: {self.relative(path)}: {service_id}")
        self.check(service_id == path.stem, f"service ID does not match file stem: {self.relative(path)}")
        for resource_type in owned_types:
            self.check(
                (resource_type in SECURITY_GROUP_TYPES) == (service_id == "security-group"),
                f"Security Group resources must belong only to security-group: {self.relative(path)}: {resource_type}",
            )

    def markdown_service_metadata(
        self, path: Path, catalog_types: set[str]
    ) -> tuple[str, tuple[str, ...]] | None:
        lines = path.read_text(encoding="utf-8").splitlines()
        service_lines = [line for line in lines if line.startswith("- Design service ID:")]
        owned_lines = [line for line in lines if line.startswith("- Owned catalog resource types:")]
        self.check(len(service_lines) == 1, f"Design service ID must appear exactly once: {self.relative(path)}")
        self.check(len(owned_lines) == 1, f"Owned catalog resource types must appear exactly once: {self.relative(path)}")
        if len(service_lines) != 1 or len(owned_lines) != 1:
            return None

        service_match = MARKDOWN_SERVICE_ID_PATTERN.fullmatch(service_lines[0])
        owned_match = MARKDOWN_OWNED_TYPES_PATTERN.fullmatch(owned_lines[0])
        self.check(service_match is not None, f"invalid Design service ID metadata: {self.relative(path)}")
        self.check(owned_match is not None, f"invalid Owned catalog resource types metadata: {self.relative(path)}")
        if service_match is None or owned_match is None:
            return None

        service_id = service_match.group(1)
        owned_types = tuple(re.findall(r"`([^`]+)`", owned_match.group(1)))
        self.check_service_file(path, service_id, owned_types)
        self.check(bool(owned_types), f"Owned catalog resource types must not be empty: {self.relative(path)}")
        self.check(len(owned_types) == len(set(owned_types)), f"duplicate owned catalog resource type: {self.relative(path)}")
        for resource_type in owned_types:
            self.check(resource_type in catalog_types, f"unknown owned catalog resource type: {self.relative(path)}: {resource_type}")
        return service_id, owned_types

    def model_service_metadata(
        self, path: Path, catalog_types: set[str]
    ) -> tuple[str, tuple[str, ...]] | None:
        try:
            lines = read_model(path).splitlines()
        except (OSError, ValueError) as error:
            self.check(False, f"invalid service model: {self.relative(path)}: {error}")
            return None
        service_matches = [match for line in lines if (match := MODEL_SERVICE_ID_PATTERN.fullmatch(line))]
        owned_matches = [match for line in lines if (match := MODEL_OWNED_TYPES_PATTERN.fullmatch(line))]
        self.check(len(service_matches) == 1, f"model service ID must appear exactly once: {self.relative(path)}")
        self.check(len(owned_matches) == 1, f"model owned catalog resource types must appear exactly once: {self.relative(path)}")
        if len(service_matches) != 1 or len(owned_matches) != 1:
            return None

        service_key, service_id = service_matches[0].groups()
        owned_key, owned_value = owned_matches[0].groups()
        owned_types = tuple(owned_value.split(",")) if owned_value else ()
        self.check_service_file(path, service_id, owned_types)
        self.check(service_key == service_id == owned_key, f"inconsistent model service metadata key: {self.relative(path)}")
        self.check(bool(owned_types), f"model owned catalog resource types must not be empty: {self.relative(path)}")
        self.check(len(owned_types) == len(set(owned_types)), f"duplicate model owned catalog resource type: {self.relative(path)}")
        for resource_type in owned_types:
            self.check(resource_type in catalog_types, f"unknown model owned catalog resource type: {self.relative(path)}: {resource_type}")
        return service_id, owned_types

    def check_design_service_ownership(
        self, markdown_paths: list[Path]
    ) -> tuple[
        dict[Path, tuple[str, tuple[str, ...]]],
        set[str],
        dict[str, set[str]],
        dict[str, set[str]],
    ]:
        catalog_types, catalog_property_owners, identifier_outputs = self.catalog_design_properties()
        metadata: dict[Path, tuple[str, tuple[str, ...]]] = {}
        owners: dict[tuple[str, str, str], Path] = {}
        docs_base = self.root / "docs" / "designs"
        model_base = self.root / "model"

        for markdown_path in markdown_paths:
            relative = markdown_path.relative_to(docs_base)
            model_path = (model_base / relative).with_suffix(".properties")
            markdown_metadata = self.markdown_service_metadata(markdown_path, catalog_types)
            model_metadata = self.model_service_metadata(model_path, catalog_types) if model_path.is_file() else None
            if markdown_metadata is None or model_metadata is None:
                continue
            self.check(markdown_metadata == model_metadata, f"Markdown/model service metadata mismatch: {self.relative(markdown_path)}")
            metadata[markdown_path] = markdown_metadata

            target = relative.parts[:2]
            if len(target) != 2:
                continue
            for resource_type in markdown_metadata[1]:
                owner_key = (target[0], target[1], resource_type)
                previous = owners.get(owner_key)
                self.check(previous is None, f"duplicate catalog resource type ownership: {resource_type}: {self.relative(previous) if previous else self.relative(markdown_path)} and {self.relative(markdown_path)}")
                owners.setdefault(owner_key, markdown_path)

        return metadata, catalog_types, catalog_property_owners, identifier_outputs

    @staticmethod
    def normalized(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    @staticmethod
    def unquoted(value: str) -> str:
        value = value.strip()
        return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == "`" else value

    @staticmethod
    def resource_property_path(resource_type: str, property_name: str) -> str:
        prefix = resource_type + "."
        return property_name[len(prefix) :] if property_name.startswith(prefix) else property_name

    def check_cidr_value(self, path: Path, property_name: str, value: str) -> None:
        self.check(
            not ("cidr" in property_name.lower() and "PENDING_DEPLOY" in value.upper()),
            f"CIDR must not use PENDING_DEPLOY: {self.relative(path)}: {property_name}",
        )

    def check_generated_identifier(
        self,
        path: Path,
        resource_type: str,
        logical_id: str,
        rows: list[list[str]],
        identifier_outputs: dict[str, set[str]],
    ) -> None:
        expected_properties = sorted(identifier_outputs.get(resource_type, set()))
        for property_name in expected_properties:
            generated_rows = [row for row in rows if row[1] == property_name]
            self.check(
                len(generated_rows) == 1,
                f"identifier output row must appear exactly once: {self.relative(path)}: {property_name}",
            )
            if len(generated_rows) != 1:
                continue
            value = self.unquoted(generated_rows[0][2])
            self.check(bool(value), f"identifier output value is empty: {self.relative(path)}: {property_name}")
            self.check(value != "NOT_DEPLOYED", f"identifier output must use PENDING_DEPLOY after destroy: {self.relative(path)}: {property_name}")
            self.check(
                value == "PENDING_DEPLOY" or value != logical_id,
                f"identifier output must use a physical value, not the logical ID: {self.relative(path)}: {property_name}",
            )
            self.check(
                re.search(r"\barn:aws[a-z-]*:", value, re.IGNORECASE) is None,
                f"generated ARN is forbidden in design: {self.relative(path)}: {property_name}",
            )
        if resource_type != "EC2.SecurityGroup" and resource_type not in {"EC2.SecurityGroupIngress", "EC2.SecurityGroupEgress"}:
            for error in catalog_order_errors(resource_type, rows):
                self.check(False, f"{self.relative(path)}: {error}")

    def check_required_name_tag(
        self,
        path: Path,
        resource_type: str,
        logical_id: str,
        rows: list[list[str]],
        mode: str = "CREATE",
    ) -> None:
        if resource_type in REQUIRED_NAME_TAG_TYPES:
            try:
                name = resource_display_name(resource_type, rows, mode=mode)
            except ValueError as error:
                self.check(False, f"{self.relative(path)}: {error}")
                return
            if name is not None:
                self.check(logical_id == name, f"resource heading identifier must match Name tag value: {self.relative(path)}: {resource_type}")
            return
        property_name = REQUIRED_NAME_PROPERTIES.get(resource_type)
        if property_name is None:
            return
        name_rows = [row for row in rows if row[1] == property_name]
        self.check(
            len(name_rows) == 1 or (mode == "IMPORT" and not name_rows),
            f"required Name property must appear exactly once: {self.relative(path)}: {property_name}",
        )
        legacy_name_rows = [
            row
            for row in rows
            if self.resource_property_path(resource_type, row[1])
            in {"Tags[].Key", "HostedZoneTags[].Key"}
            and self.unquoted(row[2]) == "Name"
        ]
        self.check(
            not legacy_name_rows,
            f"Name tag must use one-row property {property_name}: {self.relative(path)}: {resource_type}",
        )
        if len(name_rows) != 1:
            return
        self.check(rows[0] == name_rows[0], f"design-only Name must be the first row: {self.relative(path)}: {property_name}")
        value = self.unquoted(name_rows[0][2]).strip()
        self.check(bool(value), f"required Name value must not be empty: {self.relative(path)}: {property_name}")
        if mode == "IMPORT" and self.schema_catalog is not None:
            for error in self.schema_catalog.literal_errors(resource_type, "Tags[].Value", self.unquoted(name_rows[0][2])):
                self.check(False, f"provider schema violation: {self.relative(path)}: {property_name}: {error}")
        self.check(
            mode == "IMPORT" or LOWER_KEBAB_PATTERN.fullmatch(value) is not None,
            f"required Name value must be lower-kebab-case: {self.relative(path)}: {property_name}: {value}",
        )
        self.check(
            logical_id == value,
            f"resource heading identifier must match Name value: {self.relative(path)}: {resource_type}: {logical_id} != {value}",
        )

    @staticmethod
    def is_policy_document_property(property_name: str) -> bool:
        return property_name in POLICY_FORMATS

    def design_model_values(self, path: Path) -> dict[str, str] | None:
        from design_layout import design_model_values
        sources = getattr(self, "design_sources", {})
        return sources[path] if path in sources else design_model_values(path, self.root)

    def check_markdown_iam_policy_artifacts(
        self, path: Path, logical_id: str, rows: list[list[str]]
    ) -> None:
        relative = path.relative_to(self.root / "docs" / "designs")
        if len(relative.parts) < 3:
            return
        target = (relative.parts[0], relative.parts[1])
        from design_layout import resource_identity_metadata
        entry_numbers, _ = resource_identity_metadata(path.read_text(encoding="utf-8").splitlines(), values=self.design_model_values(path)) if path.is_file() else ({}, {})
        legacy = logical_id not in entry_numbers.values()
        properties = [row[1].removeprefix("IAM.Role.") for row in rows]

        for index, row in enumerate(rows):
            property_name = properties[index]
            link = VALUE_LINK_PATTERN.fullmatch(row[2])
            if property_name == "AssumeRolePolicyDocument" and link:
                artifact = (path.parent / link.group(1)).resolve()
                expected = iam_role_policy_artifact_filename(logical_id)
                self.check(not legacy or artifact.name == expected, f"invalid IAM trust policy artifact name: {self.relative(path)}: expected {expected}")
                key = (*target, logical_id, "trust")
                self.check(key not in self.markdown_iam_policy_artifacts, f"duplicate IAM trust policy artifact: {self.relative(path)}: {logical_id}")
                self.markdown_iam_policy_artifacts.setdefault(key, artifact)

            if property_name == "Policies[].PolicyName":
                paired = index + 1 < len(rows) and properties[index + 1] == "Policies[].PolicyDocument"
                self.check(paired, f"IAM inline PolicyName must immediately precede PolicyDocument: {self.relative(path)}: {logical_id}")
            if property_name != "Policies[].PolicyDocument":
                continue

            paired = index > 0 and properties[index - 1] == "Policies[].PolicyName"
            self.check(paired, f"IAM inline PolicyDocument requires a preceding PolicyName: {self.relative(path)}: {logical_id}")
            if not paired or not link:
                continue
            policy_name = self.unquoted(rows[index - 1][2])
            self.check(policy_name not in {"", "UNSET", "PENDING_DEPLOY"}, f"IAM inline PolicyName is required: {self.relative(path)}: {logical_id}")
            if policy_name in {"", "UNSET", "PENDING_DEPLOY"}:
                continue
            artifact = (path.parent / link.group(1)).resolve()
            expected = iam_role_policy_artifact_filename(logical_id, policy_name)
            self.check(not legacy or artifact.name == expected, f"invalid IAM inline policy artifact name: {self.relative(path)}: expected {expected}")
            key = (*target, logical_id, f"inline:{policy_name}")
            self.check(key not in self.markdown_iam_policy_artifacts, f"duplicate IAM inline PolicyName: {self.relative(path)}: {logical_id}: {policy_name}")
            self.markdown_iam_policy_artifacts.setdefault(key, artifact)

    def check_resource_layout(self) -> None:
        errors = layout_errors(self.root)
        self.check(not errors, "; ".join(errors) or "resource layout decisions are invalid")

    def check_resource_names(self, service_metadata: dict[Path, tuple[str, tuple[str, ...]]], paths: list[Path] | None = None) -> None:
        for path in self.design_files() if paths is None else paths:
            lines = resource_heading_lines(without_policy_tables(path.read_text(encoding="utf-8").splitlines()))
            try:
                identities = resource_logical_ids(lines)
                values = self.design_model_values(path)
                modes = resource_modes(lines, values)
                lines = security_group_table_lines(lines)
                lines = expanded_display_rows(lines)
                values = values or {}
                labels = {
                    (resource.get("resourceType"), resource.get("logicalId"), label)
                    for identity, resource in entries(values, "desired.resource.")
                    if (label := values.get(f"display.resource.{identity}.label"))
                    and label not in {"UNSET", "PENDING_DEPLOY"}
                }
            except (OSError, ValueError) as error:
                self.check(False, f"invalid resource identity: {self.relative(path)}: {error}")
                continue
            anchor = ""
            current = None
            rows = []
            counts = Counter(match.group(1) for line in lines if (match := RESOURCE_HEADING_PATTERN.fullmatch(line)))

            def check_name() -> None:
                if current is None:
                    return
                resource_type, display = current
                mode = modes.get(anchor, "CREATE")
                try:
                    name = resource_display_name(resource_type, rows, display, mode)
                except ValueError as error:
                    self.check(False, f"{self.relative(path)}: {error}")
                    return
                for error in naming_errors(self.root, resource_type, rows, mode):
                    self.check(False, f"{self.relative(path)}: {error}")
                self.check(name is None or name not in {"", "UNSET", "PENDING_DEPLOY"}, f"resource display name must be confirmed: {self.relative(path)}: {resource_type}")
                self.check(name is None or display == name, f"resource heading must display resource name: {self.relative(path)}: {resource_type}: {display} != {name}")
                if name is None:
                    if display == resource_type:
                        self.check(counts[resource_type] == 1 and resource_type not in GROUPED and not resource_has_name_property(self.root, resource_type, mode), f"resource type display requires a single nameless independent resource: {self.relative(path)}: {resource_type}")
                    confirmed_label = (resource_type, identities.get(current), display) in labels and not resource_has_name_property(self.root, resource_type, mode)
                    self.check(current in identities and (display == resource_type or display != identities[current] or confirmed_label), f"resource without a name requires a display label or resource type and hidden logical ID: {self.relative(path)}: {display}")
                if path in service_metadata:
                    expected = resource_anchor(service_metadata[path][0], display, resource_type)
                    self.check(anchor == expected, f"resource anchor must use display name: {self.relative(path)}: expected {expected}")

            for line in [*lines, "### end"]:
                if heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                    check_name()
                    current, rows = heading.groups(), []
                elif line.startswith("### "):
                    check_name()
                    current = None
                elif match := ANCHOR_PATTERN.fullmatch(line):
                    check_name()
                    current, anchor = None, match.group(1)
                elif current and line.startswith("| "):
                    cells = [cell.strip() for cell in line.strip("|").split("|")]
                    if len(cells) == 4 and cells[0].isdigit():
                        rows.append(cells)
                        if cells[1] == "KMS.Alias.AliasName" and path in service_metadata:
                            marker = CHILD.match(cells[3])
                            expected = resource_anchor(service_metadata[path][0], self.unquoted(cells[2]), "KMS.Alias")
                            self.check(bool(marker and marker.group(1) == expected), f"KMS Alias anchor must use AliasName: {self.relative(path)}: expected {expected}")

    def check_design_tables(
        self,
        service_metadata: dict[Path, tuple[str, tuple[str, ...]]],
        catalog_types: set[str],
        catalog_property_owners: dict[str, set[str]],
        identifier_outputs: dict[str, set[str]],
        paths: list[Path] | None = None,
    ) -> None:
        for path in self.design_files() if paths is None else paths:
            lines = resource_heading_lines(path.read_text(encoding="utf-8").splitlines())
            try:
                identities = resource_logical_ids(lines)
                modes = resource_modes(lines, self.design_model_values(path))
                heading_modes = {}
                anchor = ""
                for line in lines:
                    if match := ANCHOR_PATTERN.fullmatch(line):
                        anchor = match.group(1)
                    elif match := RESOURCE_HEADING_PATTERN.fullmatch(line):
                        heading_modes[match.groups()] = modes.get(anchor, "CREATE")
            except ValueError as error:
                self.check(False, f"invalid resource identity: {self.relative(path)}: {error}")
                identities = {}
                heading_modes = {}
            resource_type = ""
            for index, line in enumerate(lines):
                if heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                    resource_type = heading.group(1)
                    self.check(
                        (resource_type in SECURITY_GROUP_TYPES) == (path.stem == "security-group"),
                        f"Security Group resources must belong only to security-group: {self.relative(path)}: {resource_type}",
                    )
                elif line.startswith("#"):
                    resource_type = ""
                if line != TABLE_HEADER or not resource_type:
                    continue
                cursor = index + 2
                while cursor < len(lines) and lines[cursor].startswith("|"):
                    cells = [cell.strip() for cell in lines[cursor].strip("|").split("|")]
                    if len(cells) == 4 and cells[1].startswith(resource_type + "."):
                        self.check(False, f"resource table Property must omit heading resource type: {self.relative(path)}:{cursor + 1}: {cells[1]}")
                    cursor += 1
            try:
                lines = security_group_table_lines(lines)
                _, children = expanded_design(lines, normalized=True)
                lines = expanded_display_rows(lines)
            except ValueError as error:
                self.check(False, f"invalid grouped design: {self.relative(path)}: {error}")
                children = {}
            for child in children.values():
                resource_type = child["resourceType"]
                if self.schema_catalog is not None:
                    present = {
                        self.resource_property_path(resource_type, prop)
                        for prop in [*(row[1] for row in child["rows"]), child["parentProperty"]]
                    }
                    for required in self.schema_catalog.required_properties(resource_type):
                        if resource_type in catalog_property_owners.get(required, set()):
                            self.check(required in present, f"required grouped property missing: {self.relative(path)}: {child['logicalId']}: {required}")
                self.check_generated_identifier(path, resource_type, child["logicalId"], child["rows"], identifier_outputs)
            self.check(
                len([line for line in lines if re.fullmatch(r"# [^#].+", line)]) == 1,
                f"design must contain exactly one H1 title: {self.relative(path)}",
            )
            for line in lines:
                self.check(
                    FORBIDDEN_DESIGN_METADATA_PATTERN.match(line) is None,
                    f"forbidden design file metadata: {self.relative(path)}: {line}",
                )
                self.check(
                    FORBIDDEN_DESIGN_SECTION_PATTERN.fullmatch(line) is None,
                    f"forbidden design section: {self.relative(path)}: {line}",
                )
            table_count = 0
            index = 0
            current_resource_type = ""
            current_logical_id = ""
            while index < len(lines):
                heading_match = RESOURCE_HEADING_PATTERN.fullmatch(lines[index])
                if heading_match:
                    current_resource_type = heading_match.group(1)
                    current_logical_id = heading_match.group(2)
                    self.check(
                        current_resource_type in catalog_types,
                        f"unknown catalog resource type in heading: {self.relative(path)}: {current_resource_type}",
                    )
                    if current_resource_type in catalog_types and path in service_metadata:
                        self.check(
                            current_resource_type in service_metadata[path][1],
                            f"catalog resource type is outside declared service ownership: {self.relative(path)}: {current_resource_type}",
                        )
                    self.check(
                        current_resource_type not in GROUPED_CHILD_RESOURCE_TYPES,
                        f"grouped resource type must not have an independent heading: {self.relative(path)}: {current_resource_type}",
                    )
                elif lines[index].startswith("#"):
                    current_resource_type = ""
                    current_logical_id = ""
                if not lines[index].startswith("|"):
                    index += 1
                    continue
                if not current_resource_type:
                    while index < len(lines) and lines[index].startswith("|"):
                        index += 1
                    continue
                table_count += 1
                table = []
                while index < len(lines) and lines[index].startswith("|"):
                    table.append(lines[index])
                    index += 1
                self.check(len(table) >= 3, f"incomplete table: {self.relative(path)}")
                if len(table) < 3:
                    continue
                self.check(table[0] == TABLE_HEADER, f"invalid table header: {self.relative(path)}")
                self.check(table[1] == TABLE_ALIGNMENT, f"invalid table alignment: {self.relative(path)}")
                rows: list[list[str]] = []
                for number, row in enumerate(table[2:], 1):
                    cells = [cell.strip() for cell in row.strip("|").split("|")]
                    self.check(len(cells) == 4, f"table row must have four cells: {self.relative(path)}")
                    if len(cells) == 4:
                        display_property = cells[1]
                        cells[1] = DISPLAY_PROPERTY_ALIASES.get(display_property, display_property)
                        if cells[1] in DISPLAY_PROPERTY_ALIASES.values():
                            self.check(
                                display_property in DISPLAY_PROPERTY_ALIASES,
                                f"formal property must use its Markdown display alias: {self.relative(path)}: {display_property}",
                            )
                        rows.append(cells)
                        self.check_cidr_value(path, cells[1], cells[2])
                        self.check(cells[0] == str(number), f"table numbering error: {self.relative(path)}")
                        self.check(
                            JAPANESE_TEXT_PATTERN.search(cells[3]) is not None,
                            f"Source / Comment must be Japanese: {self.relative(path)}: {cells[3]}",
                        )
                        property_owners = catalog_property_owners.get(cells[1], set())
                        allowed_types = {
                            current_resource_type,
                            *GROUPED_RESOURCE_TYPES.get(current_resource_type, set()),
                        }
                        row_types = property_owners & allowed_types
                        if current_resource_type in catalog_types:
                            self.check(
                                bool(row_types),
                                f"resource table property is not selected by design catalog: {self.relative(path)}: {current_resource_type}: {cells[1]}",
                            )
                        if property_owners and path in service_metadata:
                            owned_types = set(service_metadata[path][1])
                            self.check(bool(property_owners & owned_types), f"catalog property is outside declared service ownership: {self.relative(path)}: {cells[1]}")
                            if current_resource_type:
                                self.check(bool(row_types), f"catalog property does not belong to resource table: {self.relative(path)}: {current_resource_type}: {cells[1]}")
                        schema_type = (
                            current_resource_type
                            if current_resource_type in row_types
                            else min(row_types, default="")
                        )
                        if schema_type in GROUPED:
                            self.check(
                                cells[1].startswith(schema_type + "."),
                                f"grouped property must use its full catalog name: {self.relative(path)}: {cells[1]}",
                            )
                        if (
                            self.schema_catalog is not None
                            and schema_type
                            and schema_type not in self.schema_catalog.api_schemas
                            and cells[1] != REQUIRED_NAME_PROPERTIES.get(schema_type)
                            and cells[1] not in DESIGN_ONLY_PROPERTIES
                            and LINK_PATTERN.fullmatch(cells[2]) is None
                        ):
                            property_path = self.resource_property_path(schema_type, cells[1])
                            raw_value = self.unquoted(cells[2])
                            if cells[1] in SUBNET_LIST_PROPERTIES and raw_value.lstrip().startswith("["):
                                property_path = property_path.removesuffix("[]")
                            errors = [] if is_service_role_reference(cells[1], cells[2]) or (
                                cells[1] in identifier_outputs.get(schema_type, set())
                                and raw_value == "PENDING_DEPLOY"
                            ) else self.schema_catalog.literal_errors(schema_type, property_path, raw_value)
                            for error in errors:
                                self.check(
                                    False,
                                    f"provider schema violation: {self.relative(path)}: {identities.get((current_resource_type, current_logical_id), current_logical_id)}: {schema_type}.{property_path}: {raw_value!r} {error}",
                                )
                        link_match = VALUE_LINK_PATTERN.fullmatch(cells[2])
                        artifact_link = link_match.group(1) if link_match else ""
                        is_json_link = artifact_link.endswith(".json")
                        if self.is_policy_document_property(cells[1]):
                            self.check(is_json_link, f"policy property must link to a JSON artifact: {self.relative(path)}: {cells[1]}")
                        if cells[1] == S3_KMS_MASTER_KEY_ID:
                            self.check(
                                RESOURCE_LINK_PATTERN.fullmatch(cells[2]) is not None,
                                f"S3 KMSMasterKeyID must link to a KMS.Alias: {self.relative(path)}: {current_logical_id}",
                            )
                        if cells[1] == "EC2.SecurityGroup.VpcId":
                            self.check(
                                RESOURCE_LINK_PATTERN.fullmatch(cells[2]) is not None,
                                f"Security Group VpcId must link to its VPC: {self.relative(path)}: {current_logical_id}",
                            )
                        if is_json_link:
                            artifact = (path.parent / artifact_link).resolve()
                            expected_directory = path.with_suffix("").resolve()
                            self.check(artifact.parent == expected_directory, f"design JSON artifact must be stored under owning service: {self.relative(path)}: {artifact_link}")
                            self.check(LOWER_KEBAB_PATTERN.fullmatch(artifact.stem) is not None, f"invalid design JSON artifact path: {self.relative(path)}: {artifact_link}")
                            self.markdown_design_artifacts.add(artifact)
                if current_resource_type in catalog_types:
                    if self.schema_catalog is not None and current_resource_type in self.schema_catalog.api_schemas:
                        self.check_api_design_rows(path, current_resource_type, current_logical_id, rows)
                    if current_resource_type == "Events.Rule":
                        for property_name in ("Events.Rule.Name", "Events.Rule.State"):
                            selected = [row for row in rows if row[1] == property_name]
                            self.check(
                                len(selected) == 1,
                                f"{property_name} must appear exactly once: {self.relative(path)}: {current_logical_id}",
                            )
                            if len(selected) == 1:
                                value = self.unquoted(selected[0][2]).strip()
                                self.check(
                                    value not in {"", "UNSET", "PENDING_DEPLOY"},
                                    f"{property_name} must have a confirmed value: {self.relative(path)}: {current_logical_id}",
                                )
                    if current_resource_type == "S3.Bucket":
                        bucket_name_rows = [
                            row for row in rows if row[1] == "S3.Bucket.BucketName"
                        ]
                        self.check(
                            len(bucket_name_rows) == 1 and rows[0][1] == "S3.Bucket.BucketName",
                            f"S3.Bucket.BucketName must be the first row: {self.relative(path)}: {current_logical_id}",
                        )
                        if len(bucket_name_rows) == 1:
                            self.check(
                                current_logical_id == self.unquoted(bucket_name_rows[0][2]),
                                f"S3.Bucket heading identifier must match BucketName: {self.relative(path)}: {current_logical_id}",
                            )
                        region_rows = [
                            row for row in rows if row[1] == "S3.Bucket.Region"
                        ]
                        self.check(
                            len(region_rows) == 1
                            and len(rows) > 1
                            and rows[1][1] == "S3.Bucket.Region",
                            f"S3.Bucket.Region must be the second row: {self.relative(path)}: {current_logical_id}",
                        )
                        if len(region_rows) == 1:
                            region = self.unquoted(region_rows[0][2])
                            self.check(
                                LOWER_KEBAB_PATTERN.fullmatch(region) is not None
                                and region != "UNSET",
                                f"S3.Bucket.Region must be a confirmed AWS region ID: {self.relative(path)}: {current_logical_id}",
                            )
                    if self.schema_catalog is not None:
                        schema_types = {current_resource_type} | {
                            resource_type
                            for resource_type in GROUPED_RESOURCE_TYPES.get(
                                current_resource_type, set()
                            )
                            if any(
                                resource_type
                                in catalog_property_owners.get(row[1], set())
                                for row in rows
                            )
                        }
                        for resource_type in schema_types:
                            present = property_paths_with_parents({
                                self.resource_property_path(resource_type, row[1])
                                for row in rows
                                if resource_type
                                in catalog_property_owners.get(row[1], set())
                            })
                            selected_required = self.schema_catalog.required_design_properties(resource_type)
                            missing = (
                                selected_required
                                - present
                                - IMPLICIT_GROUPED_PROPERTIES.get(resource_type, set())
                            )
                            for property_name in sorted(missing):
                                self.check(
                                    False,
                                    f"required provider schema property missing: {self.relative(path)}: {resource_type}.{property_name}",
                                )
                    self.check_generated_identifier(
                        path, current_resource_type, identities.get((current_resource_type, current_logical_id), current_logical_id), rows, identifier_outputs
                    )
                    self.check_required_name_tag(
                        path, current_resource_type, current_logical_id, rows,
                        heading_modes.get((current_resource_type, current_logical_id), "CREATE"),
                    )
                if current_resource_type == "IAM.Role":
                    self.check_markdown_iam_policy_artifacts(path, identities.get((current_resource_type, current_logical_id), current_logical_id), rows)
            self.check(table_count > 0, f"resource design has no table: {self.relative(path)}")

            previous = ""
            for line in lines:
                heading_match = RESOURCE_HEADING_PATTERN.fullmatch(line)
                if heading_match:
                    anchor_match = ANCHOR_PATTERN.fullmatch(previous)
                    self.check(anchor_match is not None, f"resource heading lacks explicit anchor: {self.relative(path)}: {line}")
                    if path in service_metadata:
                        logical_id = heading_match.group(2)
                        if anchor_match is not None:
                            expected = resource_anchor(service_metadata[path][0], logical_id, heading_match.group(1))
                            self.check(anchor_match.group(1) == expected, f"resource anchor does not match service ID/logical ID: {self.relative(path)}: expected {expected}")
                if line.strip():
                    previous = line.strip()

    def check_api_design_rows(self, path: Path, resource_type: str, logical_id: str, rows: list[list[str]]) -> None:
        catalog = self.schema_catalog
        schema = catalog.schema(resource_type)
        values = {}
        before = len(self.errors)
        for row in rows:
            prop = self.resource_property_path(resource_type, row[1])
            if prop not in schema["properties"]:
                continue  # The common catalog check reports unselected properties.
            self.check(prop not in values, f"duplicate API design property: {self.relative(path)}: {prop}")
            raw = self.unquoted(row[2])
            node = catalog.property_schema(resource_type, prop)
            link = VALUE_LINK_PATTERN.fullmatch(raw)
            try:
                if link and link.group(1).endswith(".json") and node["type"] == "object":
                    artifact = (path.parent / link.group(1)).resolve()
                    if artifact.parent != path.with_suffix("").resolve():
                        raise ValueError("API JSON artifact must belong to this service")
                    value = json.loads(artifact.read_text(encoding="utf-8"))
                else:
                    if LINK_PATTERN.fullmatch(raw):
                        raise ValueError("API root property requires a literal or an object JSON artifact")
                    value = raw if node["type"] == "string" else json.loads(raw)
                values[prop] = value
                if prop == "jobId" and value == "PENDING_DEPLOY":
                    continue
                for error in catalog.api_value_errors(resource_type, node, value, prop):
                    self.check(False, f"API schema violation: {self.relative(path)}: {error}")
            except (OSError, ValueError) as error:
                self.check(False, f"invalid API design value: {self.relative(path)}: {prop}: {error}")
        if len(self.errors) == before:
            for error in catalog.job_errors(values):
                self.check(False, f"API design constraint: {self.relative(path)}: {error}")
        if resource_type == "Macie.ClassificationJob":
            try:
                tables = job_bucket_tables(path)
            except (OSError, ValueError) as error:
                self.check(False, f"invalid Macie bucket table: {self.relative(path)}: {error}")
                return
            scope = values.get("s3JobDefinition", {})
            if isinstance(scope, dict) and "bucketDefinitions" in scope:
                self.check(logical_id in tables, f"Macie bucketDefinitions requires a Markdown mapping table and JSON artifact: {self.relative(path)}: {logical_id}")
                if logical_id in tables:
                    self.check(scope["bucketDefinitions"] == tables[logical_id][1], f"Macie bucket mapping differs from JSON artifact: {self.relative(path)}: {logical_id}")
            else:
                self.check(logical_id not in tables, f"Macie bucket table requires bucketDefinitions, not bucketCriteria: {self.relative(path)}: {logical_id}")

    def check_policy_tables(self) -> None:
        for path in self.design_files():
            try:
                self.check(
                    rendered_policy_design(path) == path.read_text(encoding="utf-8"),
                    f"Policy tables or overview differ from design JSON/properties: {self.relative(path)}",
                )
            except (OSError, ValueError) as error:
                self.check(False, f"invalid policy tables: {self.relative(path)}: {error}")

    def check_design_overviews(self, paths: list[Path] | None = None) -> None:
        for path in self.design_files() if paths is None else paths:
            lines = resource_heading_lines(path.read_text(encoding="utf-8").splitlines())
            try:
                lines = security_group_table_lines(lines)
            except ValueError:
                pass
            overview_indices = [
                index for index, line in enumerate(lines) if line == OVERVIEW_HEADING
            ]
            self.check(
                len(overview_indices) == 1,
                f"resource overview must appear exactly once: {self.relative(path)}",
            )
            details_indices = [index for index, line in enumerate(lines) if line == DETAILS_HEADING]
            self.check(
                len(details_indices) == 1,
                f"resource details heading must appear exactly once: {self.relative(path)}",
            )
            resources: dict[str, tuple[str, str]] = {}
            resource_indices: list[int] = []
            previous = ""
            for index, line in enumerate(lines):
                if re.match(r"^#{1,6} [A-Za-z0-9]+\.[A-Za-z0-9]+: ", line):
                    self.check(
                        RESOURCE_HEADING_PATTERN.fullmatch(line) is not None,
                        f"resource detail heading must use H3: {self.relative(path)}: {line}",
                    )
                if heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                    anchor = ANCHOR_PATTERN.fullmatch(previous)
                    if anchor:
                        resources[anchor.group(1)] = heading.groups()
                    resource_indices.append(index)
                if line.strip():
                    previous = line.strip()
            if len(overview_indices) != 1 or len(details_indices) != 1 or not resource_indices:
                continue

            overview_index = overview_indices[0]
            details_index = details_indices[0]
            first_resource_index = min(resource_indices)
            self.check(
                overview_index < details_index < first_resource_index
                and all(
                    not line.startswith(("## ", "### ")) or RESOURCE_HEADING_PATTERN.fullmatch(line)
                    for line in lines[details_index + 1:]
                ),
                f"resource details must follow the overview and contain every resource: {self.relative(path)}",
            )
            if not overview_index < details_index < first_resource_index:
                continue
            self.check(
                not any(ANCHOR_PATTERN.fullmatch(line) for line in lines[overview_index:details_index]),
                f"resource anchors must be inside resource details: {self.relative(path)}",
            )

            listed: list[str] = []
            overview_types: list[str] = []
            current_type = ""
            index = overview_index + 1
            while index < details_index:
                line = lines[index]
                if heading := OVERVIEW_TYPE_HEADING_PATTERN.fullmatch(line):
                    current_type = heading.group(1)
                    overview_types.append(current_type)
                    index += 1
                    continue
                if not line.startswith("|"):
                    index += 1
                    continue
                table: list[str] = []
                while index < details_index and lines[index].startswith("|"):
                    table.append(lines[index])
                    index += 1
                self.check(bool(current_type), f"resource overview table lacks a resource type heading: {self.relative(path)}")
                self.check(len(table) >= 3, f"resource overview table is incomplete: {self.relative(path)}: {current_type}")
                if not current_type or len(table) < 3:
                    continue
                headers = [cell.strip() for cell in table[0].strip("|").split("|")]
                alignment = [cell.strip() for cell in table[1].strip("|").split("|")]
                self.check(
                    headers == ["No.", "ResourceName", "Comment"],
                    f"resource overview must use No., ResourceName, Comment: {self.relative(path)}: {current_type}",
                )
                self.check(
                    len(alignment) == len(headers)
                    and all(re.fullmatch(r":?---+:?", cell) for cell in alignment),
                    f"invalid resource overview table alignment: {self.relative(path)}: {current_type}",
                )
                for number, row in enumerate(table[2:], 1):
                    cells = [cell.strip() for cell in row.strip("|").split("|")]
                    self.check(
                        len(cells) == len(headers),
                        f"resource overview row width mismatch: {self.relative(path)}: {current_type}",
                    )
                    if len(cells) != len(headers):
                        continue
                    self.check(cells[0] == str(number), f"resource overview numbering error: {self.relative(path)}: {current_type}")
                    self.check(
                        JAPANESE_TEXT_PATTERN.search(cells[-1]) is not None,
                        f"resource overview Comment must describe the resource in Japanese: {self.relative(path)}: {current_type}",
                    )
                    link = RESOURCE_LINK_PATTERN.fullmatch(cells[1])
                    self.check(
                        bool(link and not link.group(2)),
                        f"resource overview resource column must link to a same-file detail block: {self.relative(path)}: {current_type}",
                    )
                    if not link or link.group(2):
                        continue
                    label, _, anchor = link.groups()
                    self.check(
                        not re.fullmatch(
                            rf".*[（(]\s*{re.escape(label)}\s*[）)]\s*の(?:設定|説明|用途|役割)",
                            cells[-1],
                        )
                        and cells[-1] not in {f"{label}の設定", f"{current_type}の設定", "セキュリティグループの設定"},
                        f"resource overview Comment must state a distinct purpose or role: {self.relative(path)}: {current_type}: {label}",
                    )
                    resource = resources.get(anchor)
                    self.check(
                        bool(
                            resource and resource[0] == current_type
                            and label == resource[1]
                        ),
                        f"resource overview link must match its detail block: {self.relative(path)}: {current_type}: {label}",
                    )
                    listed.append(anchor)

            detail_types = [resource_type for resource_type, _ in resources.values()]
            self.check(
                len(overview_types) == len(set(overview_types))
                and set(overview_types) == set(detail_types),
                f"resource overview types must match detail resource types: {self.relative(path)}",
            )
            self.check(
                len(listed) == len(set(listed)) and set(listed) == set(resources),
                f"resource overview must list every detail resource exactly once: {self.relative(path)}",
            )

    def check_design_links(self, identifier_outputs: dict[str, set[str]], paths: list[Path] | None = None) -> None:
        sources = self.design_files() if paths is None else paths
        references = {path.resolve() for path in sources}
        fragments = {}
        visible_text = {source: re.sub(r"<!--.*?-->", "", source.read_text(encoding="utf-8"), flags=re.DOTALL) for source in sources}
        for source in sources:
            for raw in LINK_PATTERN.findall(visible_text[source]):
                target, separator, fragment = raw.partition("#")
                if separator and not raw.startswith(("http://", "https://", "mailto:")):
                    linked = (source.parent / target if target else source).resolve()
                    if linked.is_file() and linked.suffix == ".md" and linked.is_relative_to(self.root / "docs/designs"):
                        references.add(linked)
                        fragments.setdefault(linked, set()).add(fragment)
        anchors = {
            path: set(ANCHOR_PATTERN.findall(path.read_text(encoding="utf-8")))
            for path in references
        }
        resources: dict[tuple[Path, str], tuple[str, dict[str, str]]] = {}
        configured_names: dict[tuple[Path, str], dict[str, str]] = {}
        hidden_ids: dict[tuple[Path, str], str] = {}
        tagged_names: dict[tuple[Path, str], tuple[str, str]] = {}
        type_names: dict[tuple[Path, str], str] = {}
        name_properties = {"CodeCommit.Repository.RepositoryName", "CodeBuild.Project.Name"}
        name_properties.update(kind + "." + field for kind, field in RESOURCE_REFERENCE_PROPERTIES.values())
        source_paths = {path.resolve() for path in sources}
        for path in sorted(references):
            source_lines = resource_heading_lines(path.read_text(encoding="utf-8").splitlines()) if path in source_paths else reference_lines(path, fragments.get(path, set()))
            try:
                identities = resource_logical_ids(source_lines)
            except ValueError:
                identities = {}
            pending_anchor = ""
            for line in source_lines:
                if match := ANCHOR_PATTERN.fullmatch(line):
                    pending_anchor = match.group(1)
                elif heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                    if heading.group(1) in REQUIRED_NAME_TAG_TYPES:
                        tagged_names[path.resolve(), pending_anchor] = heading.groups()
                    if heading.group(1) == heading.group(2):
                        type_names[path.resolve(), pending_anchor] = heading.group(1)
                    if heading.groups() in identities and identities[heading.groups()] != heading.group(2):
                        hidden_ids[path.resolve(), pending_anchor] = identities[heading.groups()]
            pending_anchor = ""
            current: tuple[Path, str] | None = None
            lines = source_lines
            try:
                lines, children = expanded_design(lines)
                for anchor, child in children.items():
                    identity = GROUPED[child["resourceType"]]["identityProperty"]
                    if identity != "Id":
                        value = self.unquoted(child["rows"][0][2])
                        if value != child["logicalId"]:
                            hidden_ids[path.resolve(), anchor] = child["logicalId"]
            except ValueError as error:
                if path in source_paths:
                    self.check(False, f"invalid grouped design: {self.relative(path)}: {error}")
            for line in lines:
                if anchor := ANCHOR_PATTERN.fullmatch(line):
                    pending_anchor = anchor.group(1)
                elif heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                    current = (path.resolve(), pending_anchor)
                    resources[current] = (heading.group(1), {})
                    configured_names[current] = {}
                    pending_anchor = ""
                elif current and line.startswith("|") and line not in {TABLE_HEADER, TABLE_ALIGNMENT}:
                    cells = [cell.strip() for cell in line.strip("|").split("|")]
                    if len(cells) == 4 and cells[1] in name_properties:
                        configured_names[current][cells[1]] = self.unquoted(cells[2])
                    if len(cells) == 4 and (
                        cells[1]
                        in identifier_outputs.get(resources[current][0], set())
                        or cells[1] == "KMS.Alias.AliasName"
                        or cells[1] == "SecretsManager.Secret.Name"
                    ):
                        resources[current][1][cells[1]] = self.unquoted(cells[2])
        for source in sources:
            for line in visible_text[source].splitlines():
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                for link in re.finditer(r"\[([^\]]+)\]\(([^)]*?)#([^)]+)\)", line):
                    label, target_text, fragment = link.groups()
                    target = (source if not target_text else source.parent / target_text).resolve()
                    self.check(label != hidden_ids.get((target, fragment)), f"design link must not display internal logical ID: {self.relative(source)}: {label}")
                    if role_name := configured_names.get((target, fragment), {}).get("IAM.Role.RoleName"):
                        self.check(label == role_name, f"IAM Role link must display RoleName: {self.relative(source)}: {label}")
                    if tagged := tagged_names.get((target, fragment)):
                        kind, name = tagged
                        observed = resources.get((target, fragment), ("", {}))[1].values()
                        identifier_reference = len(cells) == 4 and RESOURCE_LINK_PATTERN.fullmatch(cells[2]) and label in observed
                        resource = "Endpoint" if kind == "EC2.VPCEndpoint" else "Instance"
                        self.check(label == name or identifier_reference, f"{resource} link must display Name tag value or observed identifier: {self.relative(source)}: {label}")
                    if name := type_names.get((target, fragment)):
                        observed = resources.get((target, fragment), ("", {}))[1].values()
                        identifier_reference = len(cells) == 4 and RESOURCE_LINK_PATTERN.fullmatch(cells[2]) and label in observed
                        self.check(label == name or identifier_reference, f"nameless resource link must display resource type or observed identifier: {self.relative(source)}: {label}")
            for raw in LINK_PATTERN.findall(visible_text[source]):
                if raw.startswith(("http://", "https://", "mailto:")):
                    continue
                target_text, separator, fragment = raw.partition("#")
                self.check(not Path(target_text).is_absolute(), f"design link must be relative: {self.relative(source)}: {raw}")
                target = (source if not target_text else source.parent / target_text).resolve()
                self.check(target.is_file(), f"broken design link: {self.relative(source)}: {raw}")
                if separator and target.is_file():
                    self.check(fragment in anchors.get(target, set()), f"missing design anchor: {self.relative(source)}: {raw}")
            source_lines = source.read_text(encoding="utf-8").splitlines()
            pipeline_rows = []
            pipeline_id = ""
            providers = {}
            for line in source_lines:
                if heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                    pipeline_id = heading.group(2) if heading.group(1) == "CodePipeline.Pipeline" else ""
                elif line.startswith("#"):
                    pipeline_id = ""
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                match = CODEPIPELINE_STAGE.fullmatch(cells[1]) if pipeline_id and len(cells) == 4 else None
                if match:
                    identity = pipeline_id, match.group(1), match.group(2) or "1"
                    pipeline_rows.append((identity, match.group(3), cells[2]))
                    if match.group(3) == "ActionTypeId.Provider":
                        providers[identity] = self.unquoted(cells[2])
            for identity, field, value in pipeline_rows:
                if not field.startswith("Configuration."):
                    continue
                key = field.removeprefix("Configuration.")
                expected = {
                    ("CodeCommit", "RepositoryName"): ("CodeCommit.Repository", "RepositoryName"),
                    ("CodeBuild", "ProjectName"): ("CodeBuild.Project", "Name"),
                }.get((providers.get(identity), key))
                link = RESOURCE_LINK_PATTERN.fullmatch(value)
                if expected:
                    self.check(bool(link), f"CodePipeline Configuration.{key} must link to its resource: {self.relative(source)}")
                if not link:
                    continue
                label, target_text, fragment = link.groups()
                target = (source if not target_text else source.parent / target_text).resolve()
                resource = resources.get((target, fragment))
                self.check(
                    bool(resource and target.parent == source.parent.resolve()),
                    f"CodePipeline Configuration must link to a resource in the same target: {self.relative(source)}: {value}",
                )
                if expected:
                    self.check(
                        bool(resource and resource[0] == expected[0] and configured_names.get((target, fragment), {}).get(expected[0] + "." + expected[1]) == label),
                        f"CodePipeline Configuration.{key} must display the referenced {expected[0]} name: {self.relative(source)}: {value}",
                    )
            list_resource_type = ""
            for line in resource_heading_lines(source_lines):
                if heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                    list_resource_type = heading.group(1)
                elif line.startswith("#"):
                    list_resource_type = ""
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if len(cells) != 4:
                    continue
                cloudtrail = CLOUDTRAIL_DATA_RESOURCE.fullmatch(cells[1])
                linked_list = linked_list_property(cells[1], list_resource_type)
                if not cloudtrail and not linked_list:
                    continue
                link = RESOURCE_LINK_PATTERN.fullmatch(cells[2])
                if not link:
                    continue  # The display-row parser reports the missing resource link.
                _, target_text, fragment = link.groups()
                target = (source if not target_text else source.parent / target_text).resolve()
                resource = resources.get((target, fragment))
                expected = (
                    {"S3": "S3.Bucket", "Lambda": "Lambda.Function"}[cloudtrail.group(2)]
                    if cloudtrail else
                    LINKED_LIST_PROPERTIES[linked_list[0]]
                )
                self.check(
                    bool(resource and resource[0] == expected and target.parent == source.parent.resolve()),
                    f"{('CloudTrail DataResources' if cloudtrail else 'Subnet/Security Group list')} must link to a {expected} in the same target: {self.relative(source)}: {cells[2]}",
                )
            try:
                source_lines = expanded_display_rows(security_group_table_lines(source_lines))
            except ValueError as error:
                self.check(False, f"invalid Security Group tables: {self.relative(source)}: {error}")
            variable_type = ""
            for line in source_lines:
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if len(cells) == 4:
                    cells[1] = DISPLAY_PROPERTY_ALIASES.get(cells[1], cells[1])
                    if cells[1] == CODEBUILD_FORMAL_VARIABLE + "Type":
                        variable_type = self.unquoted(cells[2])
                link = RESOURCE_LINK_PATTERN.fullmatch(cells[2]) if len(cells) == 4 else None
                if not link:
                    continue
                label, target_text, fragment = link.groups()
                target = (source if not target_text else source.parent / target_text).resolve()
                resource = resources.get((target, fragment))
                if expected := RESOURCE_REFERENCE_PROPERTIES.get(cells[1]):
                    self.check(
                        bool(resource and resource[0] == expected[0] and target.parent == source.parent.resolve()),
                        f"{cells[1]} must link to a {expected[0]} in the same target: {self.relative(source)}: {cells[2]}",
                    )
                    self.check(
                        configured_names.get((target, fragment), {}).get(expected[0] + "." + expected[1]) == label,
                        f"{cells[1]} must display the referenced {expected[0]}.{expected[1]}: {self.relative(source)}: {label}",
                    )
                    continue
                if cells[1] == CODEBUILD_FORMAL_VARIABLE + "Value":
                    expected_type = {"SECRETS_MANAGER": "SecretsManager.Secret", "PARAMETER_STORE": "SSM.Parameter"}.get(variable_type)
                    self.check(
                        bool(resource and target.parent == source.parent.resolve() and (not expected_type or resource[0] == expected_type)),
                        f"CodeBuild environment variable must link to a {expected_type or 'resource'} in the same target: {self.relative(source)}: {label}",
                    )
                    if variable_type == "SECRETS_MANAGER" and resource:
                        secret_name = resource[1].get("SecretsManager.Secret.Name", "")
                        self.check(
                            bool(secret_name and (label == secret_name or label.startswith(secret_name + ":"))),
                            f"CodeBuild secret reference must display its configured name and optional selector: {self.relative(source)}: {label}",
                        )
                    continue
                if cells[1] == "EC2.SecurityGroup.VpcId":
                    self.check(
                        bool(resource and resource[0] == "EC2.VPC" and target.parent == source.parent.resolve()),
                        f"Security Group VpcId must link to a VPC in the same target: {self.relative(source)}: {label}",
                    )
                if cells[1] == S3_KMS_MASTER_KEY_ID:
                    alias_name = (
                        resource[1].get("KMS.Alias.AliasName") if resource else None
                    )
                    self.check(
                        bool(
                            resource
                            and resource[0] == "KMS.Alias"
                            and alias_name == label
                            and label.startswith("alias/")
                        ),
                        f"S3 KMSMasterKeyID must display the referenced KMS alias name: {self.relative(source)}: {label}",
                    )
                    continue
                if not resource or not resource[1]:
                    continue
                source_leaf = self.normalized(cells[1].split(".")[-1].replace("[]", ""))
                exact = [
                    value
                    for property_name, value in resource[1].items()
                    if self.normalized(property_name.split(".")[-1]) == source_leaf
                ]
                expected = exact or list(resource[1].values())
                self.check(
                    label in expected,
                    f"identifier reference does not match observed target: {self.relative(source)}: {cells[1]}: {label}",
                )

    def check_design_artifacts(self, paths: list[Path] | None = None) -> None:
        base = self.root / "docs" / "designs"
        artifacts = {path.resolve() for path in base.rglob("*.json")} if paths is None else {
            artifact.resolve() for path in paths for artifact in path.with_suffix("").rglob("*.json")
        }
        for artifact in sorted(artifacts):
            relative = artifact.relative_to(base)
            self.check(len(relative.parts) == 4, f"design JSON artifact must be <environment>/<target-directory>/<service-id>/<file>: {self.relative(artifact)}")
            if len(relative.parts) != 4:
                continue
            target = (relative.parts[0], relative.parts[1])
            self.check(target in self.accounts, f"design JSON artifact target is not defined: {self.relative(artifact)}")
            self.check(LOWER_KEBAB_PATTERN.fullmatch(relative.parts[2]) is not None, f"invalid design JSON service ID: {self.relative(artifact)}")
            self.check(LOWER_KEBAB_PATTERN.fullmatch(artifact.stem) is not None, f"invalid design JSON artifact ID: {self.relative(artifact)}")
            self.check((artifact.parent.parent / f"{relative.parts[2]}.md").is_file(), f"design JSON artifact has no owning service Markdown: {self.relative(artifact)}")
            try:
                content = json.loads(artifact.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                self.errors.append(f"invalid design JSON artifact: {self.relative(artifact)}: {error}")
                continue
            self.check(isinstance(content, dict), f"design JSON artifact root must be an object: {self.relative(artifact)}")
        self.check(artifacts == self.markdown_design_artifacts, "design JSON artifacts must match Markdown links")

    def check_observed_values(self, paths: list[Path] | None = None) -> None:
        for path in scoped_files(self.root, "model", ".properties", self.scope) if paths is None else paths:
            if not path.is_file():
                continue
            try:
                lines = read_model(path).splitlines()
            except (OSError, ValueError) as error:
                self.check(False, f"invalid service model: {self.relative(path)}: {error}")
                continue
            for line in lines:
                if line.startswith("observed."):
                    self.check(
                        re.search(r"\barn:aws[a-z-]*:", line, re.IGNORECASE) is None,
                        f"generated ARN persisted in observed model value: {self.relative(path)}",
                    )

    def check_iac_selection(self) -> None:
        active_engines = {values["engine"] for values in self.accounts.values()}
        for engine in ("cloudformation", "terraform"):
            engine_root = self.root / "infra" / engine
            files = [
                path
                for path in engine_root.rglob("*")
                if path.is_file() and not path.name.startswith(".")
            ]
            if self.template_mode:
                self.check(not files, f"template mode contains {engine} implementation")
            elif engine in active_engines:
                self.check(engine_root.is_dir(), f"selected IaC engine directory missing: {engine}")
            else:
                self.check(not engine_root.exists(), f"unselected IaC engine directory remains: {engine}")

        cloudformation_base = self.root / "infra" / "cloudformation" / "parameters"
        for path in cloudformation_base.rglob("*"):
            if not path.is_file() or path.name.startswith("."):
                continue
            parts = path.relative_to(cloudformation_base).parts
            self.check(len(parts) >= 3, f"CloudFormation parameter must be scoped by environment/target directory: {self.relative(path)}")
            if len(parts) >= 3:
                target = (parts[0], parts[1])
                if self.scope is not None and not any(item[:2] == target for item in self.scope):
                    continue
                self.check(target in self.accounts, f"CloudFormation target is not defined: {self.relative(path)}")
                if target in self.accounts:
                    self.check(self.accounts[target]["engine"] == "cloudformation", f"CloudFormation is not selected: {self.relative(path)}")

        terraform_base = self.root / "infra" / "terraform" / "environments"
        if terraform_base.exists():
            for path in terraform_base.rglob("*"):
                if not path.is_file() or path.name.startswith("."):
                    continue
                parts = path.relative_to(terraform_base).parts
                self.check(len(parts) >= 3, f"Terraform composition must be scoped by environment/target directory: {self.relative(path)}")
                if len(parts) >= 3:
                    target = (parts[0], parts[1])
                    if self.scope is not None and not any(item[:2] == target for item in self.scope):
                        continue
                    self.check(target in self.accounts, f"Terraform target is not defined: {self.relative(path)}")
                    if target in self.accounts:
                        self.check(self.accounts[target]["engine"] == "terraform", f"Terraform is not selected: {self.relative(path)}")

    @staticmethod
    def unquoted_yaml(line: str) -> str:
        code: list[str] = []
        quote = ""
        index = 0
        while index < len(line):
            char = line[index]
            if quote:
                if quote == '"' and char == "\\" and index + 1 < len(line):
                    code.extend("  ")
                    index += 2
                    continue
                if quote == "'" and char == "'" and index + 1 < len(line) and line[index + 1] == "'":
                    code.extend("  ")
                    index += 2
                    continue
                if char == quote:
                    quote = ""
                code.append(" ")
            elif char in "'\"":
                quote = char
                code.append(" ")
            elif char == "#":
                break
            else:
                code.append(char)
            index += 1
        return "".join(code)

    def check_cloudformation_yaml_rules(self) -> None:
        base = self.root / "infra" / "cloudformation" / "templates"
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            scalar_indent: int | None = None
            for index, line in enumerate(lines):
                indent = len(line) - len(line.lstrip(" "))
                if scalar_indent is not None:
                    if not line.strip() or indent > scalar_indent:
                        continue
                    scalar_indent = None
                code = self.unquoted_yaml(line)
                if YAML_REUSE.search(code):
                    self.check(False, f"CloudFormation YAML anchor/alias/merge is forbidden: {self.relative(path)}:{index + 1}")
                quoted_long = any(
                    match.group("prefix") == code[match.start("prefix"):match.end("prefix")]
                    for match in QUOTED_LONG_CF_KEY.finditer(line)
                )
                if LONG_CF_KEY.search(code) or quoted_long:
                    self.check(False, f"CloudFormation intrinsic must use YAML short form: {self.relative(path)}:{index + 1}")

                tag = re.search(r"![A-Za-z][A-Za-z0-9]*\s*$", code)
                if tag and re.fullmatch(r"![A-Za-z][A-Za-z0-9]*\s*(?:#.*)?", line[tag.start():]):
                    for later in lines[index + 1:]:
                        if not later.strip() or later.lstrip().startswith("#"):
                            continue
                        if len(later) - len(later.lstrip(" ")) > indent and later.lstrip().startswith("- "):
                            self.check(False, f"CloudFormation intrinsic array must use YAML flow form: {self.relative(path)}:{index + 1}")
                        break

                if re.search(r":\s*(?:![A-Za-z][A-Za-z0-9]*\s*)?[>|][+-]?\s*$", code):
                    scalar_indent = indent
                    continue

            resource_types: set[str] = set()
            in_metadata = False
            standalone_marker = False
            in_resources = False
            resource_indent: int | None = None
            property_indent: int | None = None
            seen_resource = False
            for index, line in enumerate(lines):
                code = self.unquoted_yaml(line)
                if not code.strip():
                    continue
                indent = len(code) - len(code.lstrip(" "))
                if indent == 0:
                    in_metadata = code.strip() == "Metadata:"
                    in_resources = code.startswith("Resources:")
                    resource_indent = property_indent = None
                    continue
                if in_metadata and indent == 2 and code.strip() == "RolePlacement: standalone":
                    standalone_marker = True
                if not in_resources:
                    continue
                resource = re.fullmatch(r"( +)[A-Za-z0-9]+:\s*", code)
                if resource and (resource_indent is None or indent <= resource_indent):
                    if seen_resource:
                        self.check(not lines[index - 1].strip(), f"CloudFormation resources must be separated by a blank line: {self.relative(path)}:{index + 1}")
                    seen_resource = True
                    resource_indent, property_indent = indent, None
                    continue
                if resource_indent is None or indent <= resource_indent:
                    continue
                if property_indent is None:
                    property_indent = indent
                if indent == property_indent:
                    resource_type = re.fullmatch(r"\s*Type:\s*(AWS::[A-Za-z0-9:]+)\s*", code)
                    if resource_type:
                        resource_types.add(resource_type.group(1))

            support_types = {
                "AWS::IAM::Role", "AWS::IAM::Policy", "AWS::IAM::ManagedPolicy",
                "AWS::IAM::InstanceProfile",
            }
            is_security_group = lambda kind: kind.startswith("AWS::EC2::SecurityGroup")
            requires_consumer = (
                "AWS::IAM::Role" in resource_types
                or any(kind.startswith("AWS::Logs::") for kind in resource_types)
                or any(is_security_group(kind) for kind in resource_types)
            )
            role_only = "AWS::IAM::Role" in resource_types and resource_types <= {
                "AWS::IAM::Role", "AWS::IAM::Policy", "AWS::IAM::ManagedPolicy",
            }
            if role_only:
                self.check(standalone_marker, f"Role-only template requires Metadata.RolePlacement: standalone: {self.relative(path)}")
            elif standalone_marker:
                self.check(False, f"Metadata.RolePlacement: standalone requires a Role-only template: {self.relative(path)}")
            if requires_consumer and not role_only:
                self.check(
                    any(
                        not kind.startswith("AWS::Logs::")
                        and kind not in support_types
                        and not is_security_group(kind)
                        for kind in resource_types
                    ),
                    f"CloudWatch Logs, IAM Role, and Security Group must share the consuming resource template: {self.relative(path)}",
                )

    def check_cloudformation_environment_parameters(self) -> None:
        templates = self.root / "infra" / "cloudformation" / "templates"
        parameters = self.root / "infra" / "cloudformation" / "parameters"
        stack_parameters: dict[Path, Path] = {}
        designed_targets: set[tuple[str, str]] = set()
        for design in self.stack_design_files():
            target_parts = design.relative_to(self.root / "docs" / "designs").parts
            if len(target_parts) != 3:
                continue
            designed_targets.add((target_parts[0], target_parts[1]))
            try:
                stacks = stack_design(design)
            except ValueError:
                continue
            for stack in stacks:
                parameter_path = parameters / target_parts[0] / target_parts[1] / stack["parameters"]
                self.check(parameter_path not in stack_parameters, f"parameter file belongs to multiple stacks: {stack['parameters']}")
                alias = self.accounts.get((target_parts[0], target_parts[1]), {}).get("alias", "")
                stack_parameters[parameter_path] = templates / alias / stack["template"]
        environment_templates: set[Path] = set()
        for path in sorted(templates.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
                continue
            section = ""
            parameter_keys: dict[int, set[str]] = {}
            used = False
            for line in path.read_text(encoding="utf-8").splitlines():
                if re.match(r"^[A-Za-z][A-Za-z0-9]*:\s*(?:#.*)?$", line):
                    section = line.split(":", 1)[0]
                    continue
                if section == "Parameters":
                    key = re.match(r"^( +)([A-Za-z][A-Za-z0-9]*):", line)
                    if key:
                        parameter_keys.setdefault(len(key.group(1)), set()).add(key.group(2))
                if section == "Resources" and not line.lstrip().startswith("#"):
                    used |= bool(re.search(r"!Ref\s+Environment\b|\$\{Environment\}", line))
            if used:
                environment_templates.add(path)
                declared = bool(parameter_keys) and "Environment" in parameter_keys[min(parameter_keys)]
                self.check(declared, f"CloudFormation resource uses Environment without Parameters.Environment: {self.relative(path)}")

        for path in sorted(parameters.rglob("*.json")):
            parts = path.relative_to(parameters).parts
            if len(parts) < 3:
                continue
            environment, target_directory = parts[:2]
            candidates = [
                templates / target_directory / f"{path.stem}{suffix}"
                for suffix in (".yaml", ".yml")
            ] + [templates / f"{path.stem}{suffix}" for suffix in (".yaml", ".yml")]
            matching_template = stack_parameters.get(path) or next((candidate for candidate in candidates if candidate.is_file()), None)
            self.check(
                (environment, target_directory) not in designed_targets or path in stack_parameters,
                f"parameter file is absent from stack design: {self.relative(path)}",
            )
            requires_environment = matching_template in environment_templates
            try:
                entries = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                self.check(False, f"invalid CloudFormation parameter JSON: {self.relative(path)}: {error}")
                continue
            if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
                self.check(False, f"CloudFormation parameter file must be a parameter array: {self.relative(path)}")
                continue
            environment_values = [entry.get("ParameterValue") for entry in entries if entry.get("ParameterKey") == "Environment"]
            if requires_environment or environment_values:
                self.check(
                    environment_values == [environment],
                    f"CloudFormation Environment parameter must equal target environment: {self.relative(path)}",
                )
            component = re.compile(rf"(?<![a-z0-9]){re.escape(environment)}(?![a-z0-9])", re.IGNORECASE)
            for entry in entries:
                value = entry.get("ParameterValue")
                if entry.get("ParameterKey") != "Environment" and isinstance(value, str):
                    self.check(
                        component.search(value) is None,
                        f"CloudFormation parameter value contains Environment component: {self.relative(path)}: {entry.get('ParameterKey')}",
                    )

    @staticmethod
    def metadata_values(path: Path, label: str) -> list[str]:
        pattern = re.compile(rf"- {re.escape(label)}: `([^`]+)`")
        values: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith(f"- {label}:"):
                continue
            match = pattern.fullmatch(line)
            values.append(match.group(1) if match else "")
        return values

    @staticmethod
    def is_rfc3339(value: str) -> bool:
        if value == "NOT_EXECUTED":
            return True
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed.tzinfo is not None

    def check_scenarios(self) -> None:
        root = self.root / "tests" / "scenarios"
        if not root.is_dir():
            return
        for entry in sorted(root.iterdir()):
            if entry.name == ".gitkeep" and entry.is_file():
                continue
            self.check(entry.is_dir(), f"tests/scenarios root may contain only .gitkeep or scenario directories: {self.relative(entry)}")
            if not entry.is_dir():
                continue
            scenario_id = entry.name
            valid_id = LOWER_KEBAB_PATTERN.fullmatch(scenario_id) is not None
            self.check(valid_id, f"invalid scenario ID: {scenario_id}")
            scenario_file = entry / "scenario.md"
            self.check(scenario_file.is_file(), f"scenario.md missing: {self.relative(entry)}")
            if not scenario_file.is_file():
                continue
            values = self.metadata_values(scenario_file, "Scenario ID")
            self.check(len(values) == 1, f"Scenario ID must appear exactly once: {self.relative(scenario_file)}")
            if values:
                self.check(bool(values[0]), f"invalid Scenario ID metadata format: {self.relative(scenario_file)}")
                if values[0]:
                    self.check(values[0] == scenario_id, f"Scenario ID does not match directory: {self.relative(scenario_file)}")
            self.scenario_ids.add(scenario_id)

    def check_result_metadata(
        self,
        path: Path,
        scenario_id: str,
        environment: str,
        target_directory: str,
    ) -> None:
        metadata: dict[str, str] = {}
        for label in RESULT_METADATA:
            values = self.metadata_values(path, label)
            self.check(len(values) == 1, f"{label} must appear exactly once: {self.relative(path)}")
            if values:
                self.check(bool(values[0]), f"invalid {label} metadata format: {self.relative(path)}")
                if values[0]:
                    metadata[label] = values[0]

        target = (environment, target_directory)
        expected = {
            "Scenario ID": scenario_id,
            "Environment": environment,
            "AWS account ID": self.accounts.get(target, {}).get("account", ""),
        }
        for label, value in expected.items():
            if label in metadata:
                self.check(metadata[label] == value, f"{label} does not match result path: {self.relative(path)}")

        if "AWS region" in metadata and target in self.accounts:
            self.check(metadata["AWS region"] == self.accounts[target]["region"], f"AWS region does not match project.json: {self.relative(path)}")
        if "Status" in metadata:
            status = metadata["Status"]
            self.check(status in RESULT_STATUSES, f"invalid result Status: {self.relative(path)}: {status}")
            executed_at = metadata.get("Executed at", "")
            if executed_at:
                self.check(self.is_rfc3339(executed_at), f"invalid Executed at: {self.relative(path)}: {executed_at}")
            if status in {"PASS", "FAIL"}:
                self.check(executed_at != "NOT_EXECUTED", f"{status} result must have execution timestamp: {self.relative(path)}")
            if status == "NOT_EXECUTED":
                self.check(executed_at == "NOT_EXECUTED", f"NOT_EXECUTED result must use NOT_EXECUTED timestamp: {self.relative(path)}")
    def check_results(self) -> None:
        root = self.root / "tests" / "results"
        if not root.is_dir():
            return
        for scenario_entry in sorted(root.iterdir()):
            if scenario_entry.name == ".gitkeep" and scenario_entry.is_file():
                continue
            self.check(scenario_entry.is_dir(), f"tests/results root may contain only .gitkeep or scenario directories: {self.relative(scenario_entry)}")
            if not scenario_entry.is_dir():
                continue
            scenario_id = scenario_entry.name
            self.check(LOWER_KEBAB_PATTERN.fullmatch(scenario_id) is not None, f"invalid result scenario ID: {scenario_id}")
            scenario_file = self.root / "tests" / "scenarios" / scenario_id / "scenario.md"
            self.check(scenario_file.is_file(), f"orphan result without scenario: {self.relative(scenario_entry)}")
            for environment_entry in sorted(scenario_entry.iterdir()):
                self.check(environment_entry.is_dir(), f"result scenario directory may contain only environment directories: {self.relative(environment_entry)}")
                if not environment_entry.is_dir():
                    continue
                environment = environment_entry.name
                for target_entry in sorted(environment_entry.iterdir()):
                    self.check(target_entry.is_dir(), f"result environment directory may contain only target directories: {self.relative(target_entry)}")
                    if not target_entry.is_dir():
                        continue
                    target_directory = target_entry.name
                    target = (environment, target_directory)
                    self.check(target in self.accounts, f"result target is not defined in project.json: {self.relative(target_entry)}")
                    self.check(not self.template_mode, f"template mode cannot contain scenario results: {self.relative(target_entry)}")
                    for child in sorted(target_entry.iterdir()):
                        self.check(child.is_file(), f"result target directory cannot contain subdirectories: {self.relative(child)}")
                        if child.is_file() and child.suffix.lower() == ".md":
                            self.check(child.name == "result.md", f"result history copy is forbidden: {self.relative(child)}")
                    result_file = target_entry / "result.md"
                    self.check(result_file.is_file(), f"result.md missing: {self.relative(target_entry)}")
                    if result_file.is_file():
                        self.result_files.setdefault(scenario_id, []).append(result_file)
                        self.check_result_metadata(
                            result_file,
                            scenario_id,
                            environment,
                            target_directory,
                        )

    def check_scenario_changes(self) -> None:
        changed_scenarios: set[str] = set()
        for changed in self.changed_paths:
            parts = Path(changed).parts
            if len(parts) >= 3 and parts[:2] == ("tests", "scenarios"):
                changed_scenarios.add(parts[2])
        for scenario_id in changed_scenarios:
            for result_file in self.result_files.get(scenario_id, []):
                relative = self.relative(result_file)
                self.check(relative in self.changed_paths, f"scenario changed without updating existing result: {relative}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--task-file", help="Selected tasks/<task-name>.md contract")
    parser.add_argument("--all", action="store_true", help="Explicit repository-wide validation")
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
        validator = Validator(root, active_scope(root, args.all),
                              active_scope(root) if args.contract_scope else None,
                              cache=True, fresh=args.fresh or args.all, workers=args.jobs)
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
