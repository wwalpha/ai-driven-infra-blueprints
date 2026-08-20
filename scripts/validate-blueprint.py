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


REQUIRED_RULES = {
    "cloudformation.md",
    "detailed-design.md",
    "llm-design-information.md",
    "loop-engineering.md",
    "post-deploy-actuals.md",
    "scenario-testing.md",
    "terraform.md",
}
REQUIRED_DIRECTORIES = (
    "docs/designs",
    "llm/designs",
    "llm/actuals",
    "infra/cloudformation/templates",
    "infra/cloudformation/parameters",
    "infra/terraform",
    "tasks",
    "tests/scenarios",
    "tests/results",
)
TABLE_HEADER = "| No. | Property | Value | Source / Comment |"
TABLE_ALIGNMENT = "| ---: | --- | --- | --- |"
ANCHOR_PATTERN = re.compile(r'<a\s+id="([^"]+)"\s*></a>')
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
PROPERTY_PATTERN = re.compile(r"^([^.]+)\.([^.]+)\.([^=]+)=(.*)$")
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


class Validator:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.errors: list[str] = []
        self.checks = 0
        self.changed_paths: set[str] = set()
        self.task_type = ""
        self.template_mode = True
        self.accounts: dict[tuple[str, str], dict[str, str]] = {}
        self.scenario_ids: set[str] = set()
        self.result_files: dict[str, list[Path]] = {}

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
        self.check_initialized_paths()
        self.check_catalog()
        self.check_designs()
        self.check_actuals()
        self.check_iac_selection()
        self.check_scenarios()
        self.check_results()
        self.check_scenario_changes()

        if self.errors:
            print(f"Blueprint local loop: FAIL ({len(self.errors)} errors)")
            for error in self.errors:
                print(f"- {error}")
            return 1

        print(f"Blueprint local loop: PASS ({self.checks} checks)")
        print(f"- task type: {self.task_type}")
        print(f"- mode: {'template' if self.template_mode else 'project'}")
        print("- task scope, catalog integrity, design mirrors, IaC selection, and scenario/result structure: valid")
        return 0

    def check_structure(self) -> None:
        for filename in (
            "AGENTS.md",
            "README.md",
            "copilot/personal-custom-instructions.md",
            "docs/system-overview.md",
            "prompts/chatbot/initial-service-design.md",
            "prompts/codex/initialize-repository.md",
        ):
            self.check((self.root / filename).is_file(), f"required file missing: {filename}")
        for directory in REQUIRED_DIRECTORIES:
            self.check((self.root / directory).is_dir(), f"required directory missing: {directory}")
        actual_rules = {path.name for path in (self.root / "rules").glob("*.md")}
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
            permitted = any(
                changed == pattern
                or (pattern.endswith("/**") and changed.startswith(pattern[:-3] + "/"))
                or fnmatch.fnmatchcase(changed, pattern)
                for pattern in allowed
            )
            self.check(permitted, f"changed path is outside task scope: {changed}")
        self.check_task_boundary(prompt)

    @staticmethod
    def under(path: str, prefix: str) -> bool:
        return path == prefix or path.startswith(prefix + "/")

    def check_task_boundary(self, prompt: Path) -> None:
        if self.task_type not in TASK_TYPES:
            return
        prompt_path = self.relative(prompt)
        for changed in sorted(self.changed_paths):
            if self.task_type == "design":
                forbidden = self.under(changed, "infra") or self.under(changed, "llm/actuals") or self.under(changed, "tests")
                self.check(not forbidden, f"design task boundary violation: {changed}")
            elif self.task_type == "infrastructure":
                forbidden = self.under(changed, "llm/designs") or self.under(changed, "tests")
                self.check(not forbidden, f"infrastructure task boundary violation: {changed}")
            elif self.task_type == "scenario-test":
                permitted = changed == prompt_path or self.under(changed, "tests/scenarios") or self.under(changed, "tests/results")
                self.check(permitted, f"scenario-test task boundary violation: {changed}")
            elif self.task_type in {"initialization", "governance", "catalog-maintenance"}:
                forbidden = self.under(changed, "tests/scenarios") or self.under(changed, "tests/results")
                self.check(not forbidden, f"{self.task_type} task boundary violation: {changed}")

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
        path = self.root / "project-topology.json"
        self.template_mode = not path.is_file()
        if self.template_mode:
            return

        text = path.read_text(encoding="utf-8")
        self.check(text.endswith("\n"), "project-topology.json must end with a newline")
        try:
            topology = json.loads(text)
        except json.JSONDecodeError as error:
            self.errors.append(f"invalid project-topology.json: {error}")
            return

        self.check(isinstance(topology, dict), "project-topology.json root must be an object")
        if not isinstance(topology, dict):
            return
        self.check(set(topology) == {"projectName", "targets"}, "project-topology.json must contain only projectName and targets")

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
                self.root / "llm" / "designs" / environment / account,
                self.root / "llm" / "actuals" / environment / account,
            ]
            if values["engine"] == "cloudformation":
                paths.append(self.root / "infra" / "cloudformation" / "parameters" / environment / account)
            else:
                paths.append(self.root / "infra" / "terraform" / "environments" / environment / account)
            for path in paths:
                self.check(path.is_dir(), f"initialized target path missing: {self.relative(path)}")

    def check_catalog(self) -> None:
        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "update-catalog-lock.py")],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.check(result.returncode == 0, result.stdout.strip() or "catalog lock check failed")

        for path in sorted((self.root / "materials" / "aws").glob("*.properties")):
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
        self.check(target in self.accounts, f"target is not defined in project-topology.json: {self.relative(path)}")
        return target

    def check_designs(self) -> None:
        markdown_paths = self.design_files()
        properties_paths = sorted((self.root / "llm" / "designs").rglob("*.properties"))
        markdown = {
            path.relative_to(self.root / "docs" / "designs").with_suffix("").as_posix()
            for path in markdown_paths
        }
        properties = {
            path.relative_to(self.root / "llm" / "designs").with_suffix("").as_posix()
            for path in properties_paths
        }
        self.check(markdown == properties, f"design/LLM group mismatch: markdown={sorted(markdown)}, llm={sorted(properties)}")
        for path in markdown_paths:
            self.check_target_file(path, self.root / "docs" / "designs")
        for path in properties_paths:
            self.check_target_file(path, self.root / "llm" / "designs")
        self.check_design_tables()
        self.check_design_links()
        self.check_llm_references()

    def check_design_tables(self) -> None:
        for path in self.design_files():
            lines = path.read_text(encoding="utf-8").splitlines()
            table_count = 0
            index = 0
            while index < len(lines):
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
                for number, row in enumerate(table[2:], 1):
                    cells = [cell.strip() for cell in row.strip("|").split("|")]
                    self.check(len(cells) == 4, f"table row must have four cells: {self.relative(path)}")
                    if len(cells) == 4:
                        self.check(cells[0] == str(number), f"table numbering error: {self.relative(path)}")
            self.check(table_count > 0, f"resource design has no table: {self.relative(path)}")

            previous = ""
            for line in lines:
                if line.startswith("##") and ":" in line:
                    self.check(ANCHOR_PATTERN.fullmatch(previous) is not None, f"resource heading lacks explicit anchor: {self.relative(path)}: {line}")
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
                target = (source if not target_text else source.parent / target_text).resolve()
                self.check(target.is_file(), f"broken design link: {self.relative(source)}: {raw}")
                if separator and target.is_file():
                    self.check(fragment in anchors.get(target, set()), f"missing design anchor: {self.relative(source)}: {raw}")

    def check_llm_references(self) -> None:
        definitions: dict[tuple[str, str], set[str]] = {}
        references: list[tuple[Path, tuple[str, str], str]] = []
        base = self.root / "llm" / "designs"
        for path in sorted(base.rglob("*.properties")):
            target = self.check_target_file(path, base)
            if target is None:
                continue
            target_definitions = definitions.setdefault(target, set())
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith("#"):
                    continue
                match = PROPERTY_PATTERN.fullmatch(line)
                self.check(match is not None, f"invalid LLM property: {self.relative(path)}: {line}")
                if not match:
                    continue
                group, logical_id, property_name, value = match.groups()
                target_definitions.add(f"{group}.{logical_id}")
                if property_name.lower().endswith(("ref", "refs")):
                    references.extend((path, target, item) for item in value.split(",") if item)
        for path, target, reference in references:
            self.check(reference in definitions.get(target, set()), f"unresolved LLM reference: {self.relative(path)}: {reference}")

    def check_actuals(self) -> None:
        for path in (self.root / "llm" / "actuals").rglob("*"):
            if path.is_file() and not path.name.startswith("."):
                self.check_target_file(path, self.root / "llm" / "actuals")
                text = path.read_text(encoding="utf-8")
                self.check(re.search(r"\barn:aws[a-z-]*:", text, re.IGNORECASE) is None, f"generated ARN persisted in {self.relative(path)}")

    def check_iac_selection(self) -> None:
        active_engines = {values["engine"] for values in self.accounts.values()}
        for engine in ("cloudformation", "terraform"):
            files = [
                path
                for path in (self.root / "infra" / engine).rglob("*")
                if path.is_file() and not path.name.startswith(".")
            ]
            if self.template_mode:
                self.check(not files, f"template mode contains {engine} implementation")
            elif engine not in active_engines:
                self.check(not files, f"unselected IaC engine contains implementation: {engine}")

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
            self.check(metadata["AWS region"] == self.accounts[target]["region"], f"AWS region does not match project-topology.json: {self.relative(path)}")
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
                    self.check(target in self.accounts, f"result target is not defined in project-topology.json: {self.relative(account_entry)}")
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
