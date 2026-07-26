#!/usr/bin/env python3
"""Deterministic local validator for the infrastructure blueprint."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path


RULE_FILES = {
    "cloudformation.md",
    "detailed-design.md",
    "llm-design-information.md",
    "loop-engineering.md",
    "post-deploy-actuals.md",
    "terraform.md",
}

GROUPS = {
    "vpc",
    "internet-gateway",
    "elastic-ip",
    "nat-gateway",
    "subnet",
    "route-table",
    "security-group",
    "iam-role",
    "instance-profile",
    "ec2",
    "load-balancer",
}

TABLE_HEADER = "| No. | Property | Value | Source / Comment |"
TABLE_ALIGNMENT = "| ---: | --- | --- | --- |"
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
ANCHOR_PATTERN = re.compile(r'<a\s+id="([^"]+)"\s*></a>')
PROPERTY_PATTERN = re.compile(r"^([^.]+)\.([^.]+)\.([^=]+)=(.*)$")
ACTIVE_FORBIDDEN = (
    ".github/",
    "docs/designs/_llm/",
    "docs/test-results/",
    "REVIEW_PENDING",
    "Copilot",
)


class Validator:
    def __init__(self, root: Path, task_id: str) -> None:
        self.root = root
        self.task_id = task_id
        self.errors: list[str] = []
        self.checks = 0

    def check(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def run(self) -> int:
        self.check_structure()
        self.check_changed_paths()
        self.check_manifests()
        self.check_design_tables_and_anchors()
        self.check_links()
        self.check_design_llm_groups_and_references()
        self.check_active_obsolete_terms()
        self.check_actuals()

        if self.errors:
            print(f"Blueprint local loop: FAIL ({len(self.errors)} errors)")
            for error in self.errors:
                print(f"- {error}")
            return 1

        print(f"Blueprint local loop: PASS ({self.checks} checks)")
        print(f"- task: {self.task_id}")
        print("- materials and implementation baselines: unchanged")
        print("- design tables, numbering, anchors, links, and LLM references: valid")
        return 0

    def check_structure(self) -> None:
        prompt = self.root / "tasks" / self.task_id / "prompt.md"
        self.check(prompt.is_file(), f"active task prompt missing: {self.relative(prompt)}")

        actual_rules = {
            path.name for path in (self.root / "rules").glob("*.md") if path.is_file()
        }
        self.check(
            actual_rules == RULE_FILES,
            f"rules/*.md must be exactly {sorted(RULE_FILES)}; got {sorted(actual_rules)}",
        )
        self.check(not (self.root / ".github").exists(), "legacy GitHub workflow directory exists")
        self.check(
            not (self.root / "docs" / "designs" / "_llm").exists(),
            "obsolete design LLM helper directory exists",
        )

        required_directories = (
            "docs/designs",
            "llm/designs",
            "llm/actuals/dev",
            "infra/cloudformation",
            "infra/terraform",
            "tests/scenarios",
            f"tests/results/{self.task_id}",
        )
        for directory in required_directories:
            self.check((self.root / directory).is_dir(), f"required directory missing: {directory}")

    def check_changed_paths(self) -> None:
        completed = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.check(completed.returncode == 0, "git status failed")
        if completed.returncode != 0:
            return

        allowed_roots = (
            ".github/",
            "docs/designs/",
            "infra/terraform/",
            "llm/",
            "rules/",
            "scripts/",
            f"tasks/{self.task_id}/",
            "tasks/task-20260327-web-nginx/",
            f"tests/results/{self.task_id}/",
        )
        allowed_files = {"AGENTS.md", "README.md", "CMD.md"}

        for line in completed.stdout.splitlines():
            path_text = line[3:]
            paths = path_text.split(" -> ")
            for changed in paths:
                allowed = changed in allowed_files or changed.startswith(allowed_roots)
                self.check(allowed, f"changed path is outside task scope: {changed}")

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def check_manifest(self, name: str) -> None:
        manifest = self.root / "tests" / "results" / self.task_id / name
        self.check(manifest.is_file(), f"baseline manifest missing: {self.relative(manifest)}")
        if not manifest.is_file():
            return

        for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            self.check(match is not None, f"invalid manifest line {name}:{line_number}")
            if match is None:
                continue
            expected, relative_path = match.groups()
            target = self.root / relative_path
            self.check(target.is_file(), f"baseline target missing: {relative_path}")
            if target.is_file():
                self.check(
                    self.sha256(target) == expected,
                    f"baseline mismatch: {relative_path}",
                )

    def check_manifests(self) -> None:
        for manifest in (
            "materials-baseline.sha256",
            "cloudformation-templates-baseline.sha256",
            "cloudformation-parameters-baseline.sha256",
            "scenarios-baseline.sha256",
        ):
            self.check_manifest(manifest)

    def resource_design_files(self) -> list[Path]:
        return sorted(
            path
            for path in (self.root / "docs" / "designs").glob("*.md")
            if path.name != "naming-rules.md"
        )

    def check_design_tables_and_anchors(self) -> None:
        expected_designs = {f"{group}.md" for group in GROUPS} | {"naming-rules.md"}
        actual_designs = {
            path.name for path in (self.root / "docs" / "designs").glob("*.md")
        }
        self.check(
            actual_designs == expected_designs,
            f"detailed-design grouping mismatch; got {sorted(actual_designs)}",
        )

        for path in self.resource_design_files():
            lines = path.read_text(encoding="utf-8").splitlines()
            table_count = 0
            index = 0
            while index < len(lines):
                if not lines[index].startswith("|"):
                    index += 1
                    continue
                table_count += 1
                table_lines: list[str] = []
                while index < len(lines) and lines[index].startswith("|"):
                    table_lines.append(lines[index])
                    index += 1
                self.check(
                    len(table_lines) >= 3,
                    f"{self.relative(path)} contains an incomplete table",
                )
                if len(table_lines) < 3:
                    continue
                self.check(
                    table_lines[0] == TABLE_HEADER,
                    f"{self.relative(path)} table {table_count} has invalid header",
                )
                self.check(
                    table_lines[1] == TABLE_ALIGNMENT,
                    f"{self.relative(path)} table {table_count} has invalid alignment row",
                )
                expected_number = 1
                for row in table_lines[2:]:
                    cells = [cell.strip() for cell in row.strip("|").split("|")]
                    self.check(
                        len(cells) == 4,
                        f"{self.relative(path)} table {table_count} row has {len(cells)} cells",
                    )
                    if len(cells) != 4:
                        continue
                    self.check(
                        cells[0] == str(expected_number),
                        f"{self.relative(path)} table {table_count} expected No. {expected_number}, got {cells[0]}",
                    )
                    expected_number += 1
            self.check(table_count > 0, f"{self.relative(path)} has no resource table")

            previous_nonblank = ""
            for line in lines:
                if line.startswith("##") and ":" in line:
                    self.check(
                        ANCHOR_PATTERN.fullmatch(previous_nonblank) is not None,
                        f"{self.relative(path)} resource heading lacks explicit anchor: {line}",
                    )
                if line.strip():
                    previous_nonblank = line.strip()

    def check_links(self) -> None:
        anchor_cache: dict[Path, set[str]] = {}
        for path in (self.root / "docs" / "designs").glob("*.md"):
            text = path.read_text(encoding="utf-8")
            anchor_cache[path.resolve()] = set(ANCHOR_PATTERN.findall(text))

        for source in (self.root / "docs" / "designs").glob("*.md"):
            text = source.read_text(encoding="utf-8")
            for raw_target in LINK_PATTERN.findall(text):
                if raw_target.startswith(("http://", "https://", "mailto:")):
                    continue
                target_text, separator, fragment = raw_target.partition("#")
                target = source if not target_text else (source.parent / target_text)
                target = target.resolve()
                self.check(target.is_file(), f"broken link in {self.relative(source)}: {raw_target}")
                if separator and target.is_file():
                    anchors = anchor_cache.get(target)
                    if anchors is None:
                        anchors = set(
                            ANCHOR_PATTERN.findall(target.read_text(encoding="utf-8"))
                        )
                        anchor_cache[target] = anchors
                    self.check(
                        fragment in anchors,
                        f"missing explicit anchor in {self.relative(source)}: {raw_target}",
                    )

    def check_design_llm_groups_and_references(self) -> None:
        expected_llm = {f"{group}.properties" for group in GROUPS} | {
            "naming-rules.properties"
        }
        actual_llm = {
            path.name for path in (self.root / "llm" / "designs").glob("*.properties")
        }
        self.check(
            actual_llm == expected_llm,
            f"LLM design grouping mismatch; got {sorted(actual_llm)}",
        )

        definitions: set[str] = set()
        references: list[tuple[Path, str]] = []
        for path in (self.root / "llm" / "designs").glob("*.properties"):
            if path.name == "naming-rules.properties":
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith("#"):
                    continue
                match = PROPERTY_PATTERN.fullmatch(line)
                self.check(match is not None, f"invalid properties line in {self.relative(path)}: {line}")
                if match is None:
                    continue
                group, logical_id, property_name, value = match.groups()
                definitions.add(f"{group}.{logical_id}")
                if property_name.lower().endswith(("ref", "refs")):
                    references.extend((path, item) for item in value.split(",") if item)

        for path, reference in references:
            self.check(
                reference in definitions,
                f"unresolved LLM logical reference in {self.relative(path)}: {reference}",
            )

    def active_files(self) -> list[Path]:
        files = [self.root / "AGENTS.md", self.root / "README.md"]
        for directory in ("rules", "docs/designs", "llm", "infra/terraform"):
            files.extend(path for path in (self.root / directory).rglob("*") if path.is_file())
        return files

    def check_active_obsolete_terms(self) -> None:
        for path in self.active_files():
            text = path.read_text(encoding="utf-8")
            for forbidden in ACTIVE_FORBIDDEN:
                self.check(
                    forbidden not in text,
                    f"active obsolete dependency '{forbidden}' in {self.relative(path)}",
                )

    def check_actuals(self) -> None:
        actual_files = [
            path for path in (self.root / "llm" / "actuals").rglob("*") if path.is_file()
        ]
        self.check(bool(actual_files), "llm/actuals contains no current-state file")
        for path in actual_files:
            text = path.read_text(encoding="utf-8")
            self.check(
                re.search(r"\barn:aws[a-z-]*:", text, re.IGNORECASE) is None,
                f"generated ARN persisted in {self.relative(path)}",
            )


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
