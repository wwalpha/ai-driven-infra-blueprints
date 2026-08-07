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


def read_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key or key in values:
            raise ValueError(f"invalid properties line {path}:{number}")
        values[key] = value
    return values


class Validator:
    def __init__(self, root: Path, task_id: str) -> None:
        self.root = root
        self.task_id = task_id
        self.errors: list[str] = []
        self.checks = 0
        self.changed_paths: set[str] = set()
        self.project: dict[str, str] = {}

    def check(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def run(self) -> int:
        self.check_structure()
        self.check_task_scope()
        self.check_project()
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
        print(f"- mode: {self.project['blueprint.mode']}")
        print("- catalog integrity, task scope, design mirrors, and IaC selection: valid")
        return 0

    def check_structure(self) -> None:
        for filename in ("AGENTS.md", "README.md", "blueprint.properties"):
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

    def check_project(self) -> None:
        path = self.root / "blueprint.properties"
        if not path.is_file():
            return
        try:
            self.project = read_properties(path)
        except ValueError as error:
            self.errors.append(str(error))
            return

        mode = self.project.get("blueprint.mode")
        self.check(mode in {"template", "project"}, "blueprint.mode must be template or project")
        if mode == "template":
            for key, value in self.project.items():
                if key == "blueprint.mode":
                    continue
                self.check(value == "UNSET", f"template placeholder must be UNSET: {key}")
            return

        name = self.project.get("project.name", "")
        environments = [item for item in self.project.get("project.environments", "").split(",") if item]
        self.check(name not in {"", "UNSET"}, "project.name is required")
        self.check(bool(environments) and "UNSET" not in environments, "project.environments is required")
        self.check(len(environments) == len(set(environments)), "project.environments contains duplicates")
        for environment in environments:
            prefix = f"environment.{environment}."
            account = self.project.get(prefix + "awsAccountId", "")
            region = self.project.get(prefix + "awsRegion", "")
            engine = self.project.get(prefix + "iacEngine", "")
            self.check(re.fullmatch(r"\d{12}", account) is not None, f"invalid AWS account for {environment}")
            self.check(region not in {"", "UNSET"}, f"AWS region is required for {environment}")
            self.check(engine in {"cloudformation", "terraform"}, f"invalid IaC engine for {environment}")

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
        return sorted((self.root / "docs" / "designs").glob("*.md"))

    def check_designs(self) -> None:
        markdown = {path.stem for path in self.design_files()}
        properties = {path.stem for path in (self.root / "llm" / "designs").glob("*.properties")}
        self.check(markdown == properties, f"design/LLM group mismatch: markdown={sorted(markdown)}, llm={sorted(properties)}")
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
        definitions: set[str] = set()
        references: list[tuple[Path, str]] = []
        for path in sorted((self.root / "llm" / "designs").glob("*.properties")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith("#"):
                    continue
                match = PROPERTY_PATTERN.fullmatch(line)
                self.check(match is not None, f"invalid LLM property: {self.relative(path)}: {line}")
                if not match:
                    continue
                group, logical_id, property_name, value = match.groups()
                definitions.add(f"{group}.{logical_id}")
                if property_name.lower().endswith(("ref", "refs")):
                    references.extend((path, item) for item in value.split(",") if item)
        for path, reference in references:
            self.check(reference in definitions, f"unresolved LLM reference: {self.relative(path)}: {reference}")

    def check_actuals(self) -> None:
        for path in (self.root / "llm" / "actuals").rglob("*"):
            if path.is_file() and not path.name.startswith("."):
                text = path.read_text(encoding="utf-8")
                self.check(re.search(r"\barn:aws[a-z-]*:", text, re.IGNORECASE) is None, f"generated ARN persisted in {self.relative(path)}")

    def check_iac_selection(self) -> None:
        mode = self.project.get("blueprint.mode")
        active_engines = {
            value for key, value in self.project.items() if key.endswith(".iacEngine") and value != "UNSET"
        }
        for engine in ("cloudformation", "terraform"):
            files = [
                path
                for path in (self.root / "infra" / engine).rglob("*")
                if path.is_file() and not path.name.startswith(".")
            ]
            if mode == "template":
                self.check(not files, f"template mode contains {engine} implementation")
            elif engine not in active_engines:
                self.check(not files, f"unselected IaC engine contains implementation: {engine}")


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
