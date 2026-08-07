#!/usr/bin/env python3
"""Deterministic local validator for a generic infrastructure blueprint."""

from __future__ import annotations

import argparse
import fnmatch
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
TOPOLOGY_HEADER = (
    "| Environment ID | Environment name | Purpose | AWS account ID | "
    "AWS account role | AWS region | IaC engine |"
)
TOPOLOGY_ALIGNMENT = "| --- | --- | --- | --- | --- | --- | --- |"
LOWER_KEBAB_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class Validator:
    def __init__(self, root: Path, task_id: str) -> None:
        self.root = root
        self.task_id = task_id
        self.errors: list[str] = []
        self.checks = 0
        self.changed_paths: set[str] = set()
        self.project_name = "UNSET"
        self.template_mode = True
        self.accounts: dict[tuple[str, str], dict[str, str]] = {}

    def check(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def run(self) -> int:
        self.check_structure()
        self.check_task_scope()
        self.check_system_overview()
        self.check_initialized_paths()
        self.check_catalog()
        self.check_designs()
        self.check_actuals()
        self.check_iac_selection()

        if self.errors:
            print(f"Blueprint local loop: FAIL ({len(self.errors)} errors)")
            for error in self.errors:
                print(f"- {error}")
            return 1

        print(f"Blueprint local loop: PASS ({self.checks} checks)")
        print(f"- task: {self.task_id}")
        print(f"- mode: {'template' if self.template_mode else 'project'}")
        print("- catalog integrity, task scope, design mirrors, and IaC selection: valid")
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
        prompt = self.root / "tasks" / self.task_id / "prompt.md"
        self.check(prompt.is_file(), f"active task prompt missing: {self.relative(prompt)}")
        if not prompt.is_file():
            return

        allowed: list[str] = []
        in_section = False
        for line in prompt.read_text(encoding="utf-8").splitlines():
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

    @staticmethod
    def table_cells(line: str) -> list[str]:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        return [cell[1:-1] if len(cell) >= 2 and cell.startswith("`") and cell.endswith("`") else cell for cell in cells]

    def check_system_overview(self) -> None:
        path = self.root / "docs" / "system-overview.md"
        if not path.is_file():
            return
        lines = path.read_text(encoding="utf-8").splitlines()

        project_lines = [line for line in lines if line.startswith("- Project name:")]
        self.check(len(project_lines) == 1, "System Overview must contain exactly one Project name")
        if project_lines:
            self.project_name = self.table_cells(project_lines[0].partition(":")[2].strip())[0]
        self.template_mode = self.project_name in {"", "UNSET"}

        header_indexes = [index for index, line in enumerate(lines) if line == TOPOLOGY_HEADER]
        self.check(len(header_indexes) == 1, "System Overview must contain exactly one Environment topology table")
        if not header_indexes:
            return
        index = header_indexes[0]
        self.check(index + 1 < len(lines) and lines[index + 1] == TOPOLOGY_ALIGNMENT, "invalid Environment topology table alignment")
        rows: list[list[str]] = []
        for line in lines[index + 2 :]:
            if not line.startswith("|"):
                break
            cells = self.table_cells(line)
            self.check(len(cells) == 7, f"Environment topology row must have seven cells: {line}")
            if len(cells) == 7:
                rows.append(cells)
        self.check(bool(rows), "Environment topology must contain at least one row")
        if self.template_mode:
            self.check(all(value == "UNSET" for row in rows for value in row), "template topology values must be UNSET")
            return

        environment_details: dict[str, tuple[str, str]] = {}
        for row in rows:
            environment, name, purpose, account, role, region, engine = row
            target = f"{environment}/{account}"
            self.check("UNSET" not in row and all(row), f"initialized topology contains unset value: {target}")
            self.check(LOWER_KEBAB_PATTERN.fullmatch(environment) is not None, f"invalid Environment ID: {environment}")
            self.check(re.fullmatch(r"\d{12}", account) is not None, f"invalid AWS account: {target}")
            self.check(region not in {"", "UNSET"}, f"AWS region is required: {target}")
            self.check(engine in {"cloudformation", "terraform"}, f"invalid IaC engine: {target}")
            previous = environment_details.setdefault(environment, (name, purpose))
            self.check(previous == (name, purpose), f"inconsistent environment name or purpose: {environment}")
            key = (environment, account)
            self.check(key not in self.accounts, f"duplicate AWS account in environment: {target}")
            self.accounts[key] = {
                "region": region,
                "engine": engine,
                "role": role,
            }

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
        self.check(target in self.accounts, f"target is not defined in System Overview: {self.relative(path)}")
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repository_root.resolve()
    if not (root / ".git").exists():
        print(f"repository root is invalid: {root}", file=sys.stderr)
        return 2
    return Validator(root, args.task_id).run()


if __name__ == "__main__":
    raise SystemExit(main())
