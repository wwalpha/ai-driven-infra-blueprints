#!/usr/bin/env python3
"""Deterministic local validator for a generic infrastructure blueprint."""

from __future__ import annotations

import argparse
from datetime import datetime
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

from cloudformation_schema import CloudFormationSchemaCatalog, snapshot_errors


REQUIRED_RULES = {
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
    "tasks",
    "tests/scenarios",
    "tests/results",
)
TABLE_HEADER = "| No. | Property | Value | Source / Comment |"
TABLE_ALIGNMENT = "| ---: | --- | --- | --- |"
ANCHOR_PATTERN = re.compile(r'<a\s+id="([^"]+)"\s*></a>')
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
VALUE_LINK_PATTERN = re.compile(r"^\[[^\]]+\]\(([^)#]+)\)$")
MARKDOWN_SERVICE_ID_PATTERN = re.compile(r"^- Design service ID: `([^`]+)`$")
MARKDOWN_OWNED_TYPES_PATTERN = re.compile(
    r"^- Owned catalog resource types: (`[^`]+`(?:, `[^`]+`)*)$"
)
MODEL_SERVICE_ID_PATTERN = re.compile(r"^desired\.service\.(.+)\.serviceId=(.*)$")
MODEL_OWNED_TYPES_PATTERN = re.compile(
    r"^desired\.service\.(.+)\.ownedCatalogResourceTypes=(.*)$"
)
RESOURCE_HEADING_PATTERN = re.compile(
    r"^## ([A-Za-z0-9]+\.[A-Za-z0-9]+): ([A-Za-z0-9][A-Za-z0-9_-]*)$"
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
    r"^[A-Za-z0-9]+(?:\[\])?(?:\.[A-Za-z0-9]+(?:\[\])?)+=$"
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
RESULT_STATUSES = {"PASS", "FAIL", "BLOCKED", "STALE", "NOT_EXECUTED"}
RESULT_METADATA = (
    "Scenario ID",
    "Environment",
    "AWS account ID",
    "AWS region",
    "Status",
    "Executed at",
)


def artifact_id(value: str) -> str:
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).lower()
    return re.sub(r"-+", "-", value).strip("-")


def iam_role_policy_artifact_filename(role_logical_id: str, policy_name: str | None = None) -> str:
    suffix = "trust-policy" if policy_name is None else artifact_id(policy_name)
    return f"{artifact_id(role_logical_id)}-{suffix}.json"


class Validator:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.errors: list[str] = []
        self.checks = 0
        self.changed_paths: set[str] = set()
        self.task_type = ""
        self.requirement_ids: list[str] = []
        self.acceptance_checks: list[tuple[str, str, str]] = []
        self.acceptance_results: list[str] = []
        self.template_mode = True
        self.accounts: dict[tuple[str, str], dict[str, str]] = {}
        self.scenario_ids: set[str] = set()
        self.result_files: dict[str, list[Path]] = {}
        self.markdown_design_artifacts: set[Path] = set()
        self.markdown_iam_policy_artifacts: dict[tuple[str, str, str, str], Path] = {}
        self.schema_catalog: CloudFormationSchemaCatalog | None = None

    def check(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def run(self) -> int:
        self.check_structure()
        self.check_task_scope()
        self.check_tasks()
        self.check_project_topology()
        self.check_task_type_requirements()
        self.check_initialized_paths()
        self.check_catalog()
        self.check_designs()
        self.check_observed_values()
        self.check_iac_selection()
        self.check_scenarios()
        self.check_results()
        self.check_scenario_changes()
        self.check_acceptance_checks()

        if self.errors:
            print(f"Blueprint repository validation: FAIL ({len(self.errors)} errors)")
            for error in self.errors:
                print(f"- {error}")
            return 1

        print(f"Blueprint repository validation: PASS ({self.checks} checks)")
        print(f"- task type: {self.task_type}")
        print(f"- task requirements: {', '.join(self.requirement_ids)}")
        print(f"- acceptance checks: {len(self.acceptance_results)}/{len(self.acceptance_checks)} passed")
        print(f"- mode: {'template' if self.template_mode else 'project'}")
        print("- task scope, catalog integrity, service models, IaC selection, and scenario/result structure: valid")
        return 0

    def check_structure(self) -> None:
        for filename in (
            "AGENTS.md",
            "README.md",
            "framework/chatbot/personal-custom-instructions.md",
            "docs/system-overview.md",
            "framework/prompts/chatbot/initial-service-design.md",
            "framework/prompts/codex/add-project-target.md",
            "framework/prompts/codex/apply-design.md",
            "framework/prompts/codex/initialize-repository.md",
            "framework/prompts/codex/implement-infrastructure.md",
            "framework/prompts/codex/run-scenario-test.md",
            "framework/scripts/blueprint-loop.py",
            "framework/scripts/check-deploy-context.py",
            "framework/scripts/cloudformation_schema.py",
            "framework/scripts/sync-model.py",
        ):
            self.check((self.root / filename).is_file(), f"required file missing: {filename}")
        for directory in REQUIRED_DIRECTORIES:
            self.check((self.root / directory).is_dir(), f"required directory missing: {directory}")
        actual_rules = {
            path.name for path in (self.root / "framework" / "rules").glob("*.md")
        }
        self.check(REQUIRED_RULES <= actual_rules, f"required rules missing: {sorted(REQUIRED_RULES - actual_rules)}")

    def git_paths(self, args: list[str]) -> set[str]:
        result = subprocess.run(
            ["git", *args], cwd=self.root, check=False, capture_output=True, text=True
        )
        self.check(result.returncode == 0, f"git {' '.join(args)} failed")
        return set(result.stdout.splitlines()) if result.returncode == 0 else set()

    def check_task_scope(self) -> None:
        prompt = self.root / "tasks" / "active.md"
        self.check(prompt.is_file(), f"active task prompt missing: {self.relative(prompt)}")
        if not prompt.is_file():
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

        self.changed_paths = (
            self.git_paths(["diff", "--name-only"])
            | self.git_paths(["diff", "--cached", "--name-only"])
            | self.git_paths(["ls-files", "--others", "--exclude-standard"])
        )
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

    def check_task_type_requirements(self) -> None:
        changed = self.changed_paths - {"tasks/active.md"}
        if self.task_type == "initialization":
            self.check("project.json" in changed, "initialization task must change project.json")
        elif self.task_type == "design":
            markdown = {path for path in changed if path.startswith("docs/designs/") and path.endswith(".md")}
            artifacts = {path for path in changed if path.startswith("docs/designs/") and path.endswith(".json")}
            models = {path for path in changed if path.startswith("model/") and path.endswith(".properties")}
            self.check(bool(markdown or artifacts), "design task must change detailed-design Markdown or JSON artifacts")
            self.check(bool(models), "design task must change generated service models")
            for path in markdown:
                expected = "model/" + path.removeprefix("docs/designs/").removesuffix(".md") + ".properties"
                self.check(expected in changed, f"changed design Markdown lacks changed service model: {path}")
            for path in models:
                expected = "docs/designs/" + path.removeprefix("model/").removesuffix(".properties") + ".md"
                service = expected.removesuffix(".md") + "/"
                self.check(
                    expected in changed or any(artifact.startswith(service) for artifact in artifacts),
                    f"changed service model lacks changed design source: {path}",
                )
            for path in artifacts:
                parts = Path(path).parts
                if len(parts) >= 6:
                    expected = f"model/{parts[2]}/{parts[3]}/{parts[4]}.properties"
                    self.check(expected in changed, f"changed design JSON lacks changed service model: {path}")
        elif self.task_type == "infrastructure":
            self.check(any(self.under(path, "infra") for path in changed), "infrastructure task must change selected IaC")
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
            "framework.design-handoff": self.check_framework_design_handoff,
            "framework.task-completion-contract": self.check_framework_task_completion_contract,
            "framework.task-type-dispatch": self.check_framework_task_type_dispatch,
            "framework.focused-check-runner": self.check_framework_focused_check_runner,
            "framework.generated-service-model": self.check_generated_service_models,
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

    def check_framework_design_handoff(self) -> None:
        prompt = self.root / "framework" / "prompts" / "codex" / "apply-design.md"
        chatbot = (
            self.root / "framework" / "prompts" / "chatbot" / "initial-service-design.md"
        ).read_text(encoding="utf-8")
        self.check(prompt.is_file(), "design application prompt is missing")
        if prompt.is_file():
            text = prompt.read_text(encoding="utf-8")
            self.check("Task typeは`design`" in text, "design application prompt lacks design task contract")
            self.check("sync-model.py" in text, "design application prompt does not generate the service model")
        self.check("framework/prompts/codex/apply-design.md" in chatbot, "chatbot prompt lacks Codex design handoff")

    def check_framework_task_completion_contract(self) -> None:
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        rules = (self.root / "framework" / "rules" / "loop-engineering.md").read_text(encoding="utf-8")
        self.check("Requirement ID" in agents and "Acceptance checks" in agents, "AGENTS.md lacks completion contract")
        self.check("Requirement ID" in rules and "Acceptance checks" in rules, "loop rules lack completion contract")

    def check_framework_task_type_dispatch(self) -> None:
        self.check(self.task_type in TASK_TYPES, "task type completion check was not dispatched")
        self.check(len(TASK_TYPES) == 7, "not every task type has a completion-check branch")

    def check_framework_focused_check_runner(self) -> None:
        loop = (self.root / "framework" / "scripts" / "blueprint-loop.py").read_text(encoding="utf-8")
        self.check('glob("*.checks.py")' in loop, "local loop does not discover focused checks")
        self.check("PYTHONDONTWRITEBYTECODE" in loop, "focused checks may write bytecode into the repository")

    def check_generated_service_models(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(self.root / "framework" / "scripts" / "sync-model.py"),
                "--repository-root",
                str(self.root),
            ],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.check(result.returncode == 0, result.stdout.strip() or result.stderr.strip() or "generated service model check failed")

    def check_framework_cloudformation_schema_catalog(self) -> None:
        errors = snapshot_errors(self.root)
        self.check(not errors, "; ".join(errors) or "CloudFormation schema snapshot is invalid")

    def check_framework_schema_backed_design_validation(self) -> None:
        rules = (self.root / "framework" / "rules" / "detailed-design.md").read_text(encoding="utf-8")
        prompt = (
            self.root / "framework" / "prompts" / "chatbot" / "initial-service-design.md"
        ).read_text(encoding="utf-8")
        self.check("CloudFormation provider schema" in rules, "detailed design rules do not apply provider schemas")
        self.check("CloudFormation provider schema" in prompt, "initial design prompt does not apply provider schemas")
        catalog = CloudFormationSchemaCatalog(self.root)
        self.check(bool(catalog.literal_errors("Logs.LogGroup", "KmsKeyId", "not-used")), "schema-backed literal validation is inactive")

    def check_framework_cfn_lint_validation(self) -> None:
        paths = (
            self.root / "framework" / "rules" / "cloudformation.md",
            self.root / "framework" / "prompts" / "codex" / "implement-infrastructure.md",
            self.root / "framework" / "scripts" / "check-deploy-context.py",
        )
        for path in paths:
            self.check("cfn-lint" in path.read_text(encoding="utf-8"), f"cfn-lint requirement missing: {self.relative(path)}")

    def check_tasks(self) -> None:
        tasks = self.root / "tasks"
        if not tasks.is_dir():
            return
        entries = sorted(tasks.iterdir())
        self.check(
            len(entries) == 1 and entries[0].is_file() and entries[0].name == "active.md",
            "tasks directory must contain only tasks/active.md",
        )

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
        required = {"environment", "awsAccountId", "awsRegion", "iacEngine"}
        for index, target_values in enumerate(targets, 1):
            self.check(isinstance(target_values, dict), f"target {index} must be an object")
            if not isinstance(target_values, dict):
                continue
            self.check(set(target_values) == required, f"target {index} must contain only {sorted(required)}")
            if not required <= set(target_values):
                continue
            values = [target_values[key] for key in required]
            self.check(all(isinstance(value, str) for value in values), f"target {index} values must be strings")
            if not all(isinstance(value, str) for value in values):
                continue
            environment = target_values["environment"]
            account = target_values["awsAccountId"]
            region = target_values["awsRegion"]
            engine = target_values["iacEngine"]
            target = f"{environment}/{account}"
            self.check("UNSET" not in values and all(values), f"target contains unset value: {target}")
            self.check(LOWER_KEBAB_PATTERN.fullmatch(environment) is not None, f"invalid Environment ID: {environment}")
            self.check(re.fullmatch(r"\d{12}", account) is not None, f"invalid AWS account: {target}")
            self.check(region not in {"", "UNSET"}, f"AWS region is required: {target}")
            self.check(engine in {"cloudformation", "terraform"}, f"invalid IaC engine: {target}")
            key = (environment, account)
            order.append(key)
            self.check(key not in self.accounts, f"duplicate AWS account in environment: {target}")
            if key not in self.accounts:
                self.accounts[key] = {"region": region, "engine": engine}
        self.check(order == sorted(order), "targets must be sorted by environment and AWS account ID")

    def check_initialized_paths(self) -> None:
        if self.template_mode:
            return
        for (environment, account), values in self.accounts.items():
            paths = [
                self.root / "docs" / "designs" / environment / account,
                self.root / "model" / environment / account,
            ]
            if values["engine"] == "cloudformation":
                paths.append(self.root / "infra" / "cloudformation" / "parameters" / environment / account)
            else:
                paths.append(self.root / "infra" / "terraform" / "environments" / environment / account)
            for path in paths:
                self.check(path.is_dir(), f"initialized target path missing: {self.relative(path)}")

    def check_catalog(self) -> None:
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
        if not schema_failures:
            self.schema_catalog = CloudFormationSchemaCatalog(self.root)

        for path in sorted((self.root / "framework" / "materials" / "aws").glob("*.properties")):
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            prefix = path.stem.replace("_", ".", 1) + "."
            self.check(text.endswith("\n"), f"catalog file lacks final newline: {self.relative(path)}")
            self.check(lines == sorted(set(lines)), f"catalog lines must be sorted and unique: {self.relative(path)}")
            for line in lines:
                self.check(MATERIAL_PATTERN.fullmatch(line) is not None, f"invalid catalog line: {self.relative(path)}: {line}")
                self.check(line.startswith(prefix), f"catalog prefix mismatch: {self.relative(path)}: {line}")

    def design_files(self) -> list[Path]:
        return sorted((self.root / "docs" / "designs").rglob("*.md"))

    def check_target_file(self, path: Path, base: Path) -> tuple[str, str] | None:
        parts = path.relative_to(base).parts
        self.check(len(parts) == 3, f"target file must be <environment>/<aws-account-id>/<file>: {self.relative(path)}")
        if len(parts) != 3:
            return None
        target = (parts[0], parts[1])
        self.check(target in self.accounts, f"target is not defined in project.json: {self.relative(path)}")
        return target

    def check_designs(self) -> None:
        self.check_generated_service_models()
        markdown_paths = self.design_files()
        properties_paths = sorted((self.root / "model").rglob("*.properties"))
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
        service_metadata, catalog_types, catalog_property_owners = self.check_design_service_ownership(markdown_paths)
        self.check_design_tables(service_metadata, catalog_types, catalog_property_owners)
        self.check_design_links()
        self.check_design_artifacts()

    def catalog_design_properties(self) -> tuple[set[str], dict[str, set[str]]]:
        resource_types: set[str] = set()
        property_owners: dict[str, set[str]] = {}
        for path in sorted((self.root / "framework" / "materials" / "aws").glob("*.properties")):
            resource_type = path.stem.replace("_", ".", 1)
            prefix = f"{resource_type}."
            resource_types.add(resource_type)
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.startswith(prefix) or not line.endswith("="):
                    continue
                property_path = line[len(prefix) : -1]
                property_owners.setdefault(property_path, set()).add(resource_type)
                property_owners.setdefault(f"{resource_type}.{property_path}", set()).add(resource_type)
        return resource_types, property_owners

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
        self.check(LOWER_KEBAB_PATTERN.fullmatch(service_id) is not None, f"invalid Design service ID: {self.relative(path)}: {service_id}")
        self.check(service_id == path.stem, f"Design service ID does not match file stem: {self.relative(path)}")
        self.check(bool(owned_types), f"Owned catalog resource types must not be empty: {self.relative(path)}")
        self.check(len(owned_types) == len(set(owned_types)), f"duplicate owned catalog resource type: {self.relative(path)}")
        for resource_type in owned_types:
            self.check(resource_type in catalog_types, f"unknown owned catalog resource type: {self.relative(path)}: {resource_type}")
        return service_id, owned_types

    def model_service_metadata(
        self, path: Path, catalog_types: set[str]
    ) -> tuple[str, tuple[str, ...]] | None:
        lines = path.read_text(encoding="utf-8").splitlines()
        service_matches = [match for line in lines if (match := MODEL_SERVICE_ID_PATTERN.fullmatch(line))]
        owned_matches = [match for line in lines if (match := MODEL_OWNED_TYPES_PATTERN.fullmatch(line))]
        self.check(len(service_matches) == 1, f"model service ID must appear exactly once: {self.relative(path)}")
        self.check(len(owned_matches) == 1, f"model owned catalog resource types must appear exactly once: {self.relative(path)}")
        if len(service_matches) != 1 or len(owned_matches) != 1:
            return None

        service_key, service_id = service_matches[0].groups()
        owned_key, owned_value = owned_matches[0].groups()
        owned_types = tuple(owned_value.split(",")) if owned_value else ()
        self.check(LOWER_KEBAB_PATTERN.fullmatch(service_id) is not None, f"invalid model service ID: {self.relative(path)}: {service_id}")
        self.check(service_key == service_id == owned_key, f"inconsistent model service metadata key: {self.relative(path)}")
        self.check(service_id == path.stem, f"model service ID does not match file stem: {self.relative(path)}")
        self.check(bool(owned_types), f"model owned catalog resource types must not be empty: {self.relative(path)}")
        self.check(len(owned_types) == len(set(owned_types)), f"duplicate model owned catalog resource type: {self.relative(path)}")
        for resource_type in owned_types:
            self.check(resource_type in catalog_types, f"unknown model owned catalog resource type: {self.relative(path)}: {resource_type}")
        return service_id, owned_types

    def check_design_service_ownership(
        self, markdown_paths: list[Path]
    ) -> tuple[dict[Path, tuple[str, tuple[str, ...]]], set[str], dict[str, set[str]]]:
        catalog_types, catalog_property_owners = self.catalog_design_properties()
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

        return metadata, catalog_types, catalog_property_owners

    @staticmethod
    def normalized(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    @staticmethod
    def unquoted(value: str) -> str:
        value = value.strip()
        return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == "`" else value

    @staticmethod
    def resource_label(resource_type: str) -> str:
        name = resource_type.split(".", 1)[1]
        words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+", name)
        return " ".join(words)

    def is_generated_identifier_property(self, resource_type: str, property_name: str) -> bool:
        return self.normalized(property_name) == self.normalized(
            f"{self.resource_label(resource_type)} ID"
        )

    @staticmethod
    def resource_property_path(resource_type: str, property_name: str) -> str:
        prefix = resource_type + "."
        return property_name[len(prefix) :] if property_name.startswith(prefix) else property_name

    def check_generated_identifier(
        self, path: Path, resource_type: str, rows: list[list[str]]
    ) -> None:
        resource_name = resource_type.split(".", 1)[1]
        identifier_properties = {
            self.normalized(resource_name + "Name"),
            self.normalized(resource_name + "Identifier"),
        }
        has_selected_identifier = any(
            self.normalized(row[1].split(".")[-1]) in identifier_properties
            and self.unquoted(row[2]) not in {"", "UNSET", "PENDING_DEPLOY"}
            for row in rows
        )
        identifier_label = f"{self.resource_label(resource_type)} ID"
        generated_rows = [
            row for row in rows if self.normalized(row[1]) == self.normalized(identifier_label)
        ]
        if has_selected_identifier:
            self.check(
                not generated_rows,
                f"redundant generated identifier row: {self.relative(path)}: {identifier_label}",
            )
            return

        self.check(
            len(generated_rows) == 1,
            f"generated identifier row must appear exactly once: {self.relative(path)}: {identifier_label}",
        )
        if len(generated_rows) != 1:
            return
        value = self.unquoted(generated_rows[0][2])
        self.check(bool(value), f"generated identifier value is empty: {self.relative(path)}: {identifier_label}")
        self.check(value != "NOT_DEPLOYED", f"generated identifier must use PENDING_DEPLOY after destroy: {self.relative(path)}: {identifier_label}")
        self.check(
            re.search(r"\barn:aws[a-z-]*:", value, re.IGNORECASE) is None,
            f"generated ARN is forbidden in design: {self.relative(path)}: {identifier_label}",
        )
        self.check(
            generated_rows[0][3].startswith("デプロイ後生成値"),
            f"invalid generated identifier source: {self.relative(path)}: {identifier_label}",
        )

    @staticmethod
    def is_policy_document_property(property_name: str) -> bool:
        leaf = property_name.split(".")[-1].replace("[]", "")
        return leaf.endswith("PolicyDocument") or (
            leaf.endswith("Policy")
            and leaf not in {"BlockPublicPolicy", "StreamExceptionPolicy"}
        )

    def check_markdown_iam_policy_artifacts(
        self, path: Path, logical_id: str, rows: list[list[str]]
    ) -> None:
        relative = path.relative_to(self.root / "docs" / "designs")
        if len(relative.parts) < 3:
            return
        target = (relative.parts[0], relative.parts[1])
        properties = [row[1].removeprefix("IAM.Role.") for row in rows]

        for index, row in enumerate(rows):
            property_name = properties[index]
            link = VALUE_LINK_PATTERN.fullmatch(row[2])
            if property_name == "AssumeRolePolicyDocument" and link:
                artifact = (path.parent / link.group(1)).resolve()
                expected = iam_role_policy_artifact_filename(logical_id)
                self.check(artifact.name == expected, f"invalid IAM trust policy artifact name: {self.relative(path)}: expected {expected}")
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
            self.check(artifact.name == expected, f"invalid IAM inline policy artifact name: {self.relative(path)}: expected {expected}")
            key = (*target, logical_id, f"inline:{policy_name}")
            self.check(key not in self.markdown_iam_policy_artifacts, f"duplicate IAM inline PolicyName: {self.relative(path)}: {logical_id}: {policy_name}")
            self.markdown_iam_policy_artifacts.setdefault(key, artifact)

    def check_design_tables(
        self,
        service_metadata: dict[Path, tuple[str, tuple[str, ...]]],
        catalog_types: set[str],
        catalog_property_owners: dict[str, set[str]],
    ) -> None:
        for path in self.design_files():
            lines = path.read_text(encoding="utf-8").splitlines()
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
                elif lines[index].startswith("#"):
                    current_resource_type = ""
                    current_logical_id = ""
                if not lines[index].startswith("|"):
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
                        rows.append(cells)
                        self.check(cells[0] == str(number), f"table numbering error: {self.relative(path)}")
                        self.check(
                            JAPANESE_TEXT_PATTERN.search(cells[3]) is not None,
                            f"Source / Comment must be Japanese: {self.relative(path)}: {cells[3]}",
                        )
                        property_owners = catalog_property_owners.get(cells[1], set())
                        generated_identifier = bool(current_resource_type) and self.is_generated_identifier_property(
                            current_resource_type, cells[1]
                        )
                        if current_resource_type in catalog_types and not generated_identifier:
                            self.check(
                                current_resource_type in property_owners,
                                f"resource table property is not selected by framework/materials/aws: {self.relative(path)}: {current_resource_type}: {cells[1]}",
                            )
                        if property_owners and path in service_metadata:
                            owned_types = set(service_metadata[path][1])
                            self.check(bool(property_owners & owned_types), f"catalog property is outside declared service ownership: {self.relative(path)}: {cells[1]}")
                            if current_resource_type:
                                self.check(current_resource_type in property_owners, f"catalog property does not belong to resource table: {self.relative(path)}: {current_resource_type}: {cells[1]}")
                        if (
                            self.schema_catalog is not None
                            and current_resource_type in property_owners
                            and LINK_PATTERN.fullmatch(cells[2]) is None
                        ):
                            property_path = self.resource_property_path(current_resource_type, cells[1])
                            raw_value = self.unquoted(cells[2])
                            for error in self.schema_catalog.literal_errors(
                                current_resource_type, property_path, raw_value
                            ):
                                self.check(
                                    False,
                                    f"provider schema violation: {self.relative(path)}: {current_resource_type}.{property_path}: {raw_value!r} {error}",
                                )
                        link_match = VALUE_LINK_PATTERN.fullmatch(cells[2])
                        artifact_link = link_match.group(1) if link_match else ""
                        is_json_link = artifact_link.endswith(".json")
                        if self.is_policy_document_property(cells[1]):
                            self.check(is_json_link, f"policy property must link to a JSON artifact: {self.relative(path)}: {cells[1]}")
                        if is_json_link:
                            artifact = (path.parent / artifact_link).resolve()
                            expected_directory = path.with_suffix("").resolve()
                            self.check(artifact.parent == expected_directory, f"design JSON artifact must be stored under owning service: {self.relative(path)}: {artifact_link}")
                            self.check(LOWER_KEBAB_PATTERN.fullmatch(artifact.stem) is not None, f"invalid design JSON artifact path: {self.relative(path)}: {artifact_link}")
                            self.markdown_design_artifacts.add(artifact)
                if current_resource_type in catalog_types:
                    if self.schema_catalog is not None:
                        present = {
                            self.resource_property_path(current_resource_type, row[1])
                            for row in rows
                            if current_resource_type in catalog_property_owners.get(row[1], set())
                        }
                        selected_required = {
                            property_name
                            for property_name in self.schema_catalog.required_properties(current_resource_type)
                            if current_resource_type
                            in catalog_property_owners.get(property_name, set())
                        }
                        for property_name in sorted(selected_required - present):
                            self.check(
                                False,
                                f"required provider schema property missing: {self.relative(path)}: {current_resource_type}.{property_name}",
                            )
                    self.check_generated_identifier(path, current_resource_type, rows)
                if current_resource_type == "IAM.Role":
                    self.check_markdown_iam_policy_artifacts(path, current_logical_id, rows)
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
                            expected = f"{service_metadata[path][0]}-{logical_id.lower()}"
                            self.check(anchor_match.group(1) == expected, f"resource anchor does not match service ID/logical ID: {self.relative(path)}: expected {expected}")
                if line.strip():
                    previous = line.strip()

    def check_design_links(self) -> None:
        anchors = {
            path.resolve(): set(ANCHOR_PATTERN.findall(path.read_text(encoding="utf-8")))
            for path in self.design_files()
        }
        for source in self.design_files():
            for raw in LINK_PATTERN.findall(source.read_text(encoding="utf-8")):
                if raw.startswith(("http://", "https://", "mailto:")):
                    continue
                target_text, separator, fragment = raw.partition("#")
                self.check(not Path(target_text).is_absolute(), f"design link must be relative: {self.relative(source)}: {raw}")
                target = (source if not target_text else source.parent / target_text).resolve()
                self.check(target.is_file(), f"broken design link: {self.relative(source)}: {raw}")
                if separator and target.is_file():
                    self.check(fragment in anchors.get(target, set()), f"missing design anchor: {self.relative(source)}: {raw}")

    def check_design_artifacts(self) -> None:
        base = self.root / "docs" / "designs"
        artifacts = {path.resolve() for path in base.rglob("*.json")}
        for artifact in sorted(artifacts):
            relative = artifact.relative_to(base)
            self.check(len(relative.parts) == 4, f"design JSON artifact must be <environment>/<aws-account-id>/<service-id>/<file>: {self.relative(artifact)}")
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

    def check_observed_values(self) -> None:
        for path in (self.root / "model").rglob("*.properties"):
            for line in path.read_text(encoding="utf-8").splitlines():
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
            self.check(len(parts) >= 3, f"CloudFormation parameter must be scoped by environment/AWS account: {self.relative(path)}")
            if len(parts) >= 3:
                target = (parts[0], parts[1])
                self.check(target in self.accounts, f"CloudFormation target is not defined: {self.relative(path)}")
                if target in self.accounts:
                    self.check(self.accounts[target]["engine"] == "cloudformation", f"CloudFormation is not selected: {self.relative(path)}")

        terraform_base = self.root / "infra" / "terraform" / "environments"
        if terraform_base.exists():
            for path in terraform_base.rglob("*"):
                if not path.is_file() or path.name.startswith("."):
                    continue
                parts = path.relative_to(terraform_base).parts
                self.check(len(parts) >= 3, f"Terraform composition must be scoped by environment/AWS account: {self.relative(path)}")
                if len(parts) >= 3:
                    target = (parts[0], parts[1])
                    self.check(target in self.accounts, f"Terraform target is not defined: {self.relative(path)}")
                    if target in self.accounts:
                        self.check(self.accounts[target]["engine"] == "terraform", f"Terraform is not selected: {self.relative(path)}")

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

    def check_result_metadata(self, path: Path, scenario_id: str, environment: str, account: str) -> None:
        metadata: dict[str, str] = {}
        for label in RESULT_METADATA:
            values = self.metadata_values(path, label)
            self.check(len(values) == 1, f"{label} must appear exactly once: {self.relative(path)}")
            if values:
                self.check(bool(values[0]), f"invalid {label} metadata format: {self.relative(path)}")
                if values[0]:
                    metadata[label] = values[0]

        expected = {
            "Scenario ID": scenario_id,
            "Environment": environment,
            "AWS account ID": account,
        }
        for label, value in expected.items():
            if label in metadata:
                self.check(metadata[label] == value, f"{label} does not match result path: {self.relative(path)}")

        target = (environment, account)
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
                for account_entry in sorted(environment_entry.iterdir()):
                    self.check(account_entry.is_dir(), f"result environment directory may contain only AWS account directories: {self.relative(account_entry)}")
                    if not account_entry.is_dir():
                        continue
                    account = account_entry.name
                    self.check(re.fullmatch(r"\d{12}", account) is not None, f"invalid result AWS account ID: {self.relative(account_entry)}")
                    target = (environment, account)
                    self.check(target in self.accounts, f"result target is not defined in project.json: {self.relative(account_entry)}")
                    self.check(not self.template_mode, f"template mode cannot contain scenario results: {self.relative(account_entry)}")
                    for child in sorted(account_entry.iterdir()):
                        self.check(child.is_file(), f"result account directory cannot contain subdirectories: {self.relative(child)}")
                        if child.is_file() and child.suffix.lower() == ".md":
                            self.check(child.name == "result.md", f"result history copy is forbidden: {self.relative(child)}")
                    result_file = account_entry / "result.md"
                    self.check(result_file.is_file(), f"result.md missing: {self.relative(account_entry)}")
                    if result_file.is_file():
                        self.result_files.setdefault(scenario_id, []).append(result_file)
                        self.check_result_metadata(result_file, scenario_id, environment, account)

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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repository_root.resolve()
    if not (root / ".git").exists():
        print(f"repository root is invalid: {root}", file=sys.stderr)
        return 2
    return Validator(root).run()


if __name__ == "__main__":
    raise SystemExit(main())
