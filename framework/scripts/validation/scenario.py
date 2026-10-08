"""Scenario definitions and current Result records; never execute scenarios."""


from datetime import datetime
from pathlib import Path
import re

from .project import LOWER_KEBAB_PATTERN
RESULT_STATUSES = {"PASS", "FAIL", "BLOCKED", "STALE", "NOT_EXECUTED"}
RESULT_METADATA = ("Scenario ID", "Environment", "AWS account ID", "AWS region", "Status", "Executed at")

def metadata_values(path: Path, label: str) -> list[str]:
    pattern = re.compile(rf"- {re.escape(label)}: `([^`]+)`")
    values: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith(f"- {label}:"):
            continue
        match = pattern.fullmatch(line)
        values.append(match.group(1) if match else "")
    return values


def is_rfc3339(value: str) -> bool:
    if value == "NOT_EXECUTED":
        return True
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def check_scenarios(root, findings, scenario_ids) -> None:
    root = root / "tests" / "scenarios"
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir()):
        if entry.name == ".gitkeep" and entry.is_file():
            continue
        findings.check(entry.is_dir(), f"tests/scenarios root may contain only .gitkeep or scenario directories: {findings.relative(entry)}")
        if not entry.is_dir():
            continue
        scenario_id = entry.name
        valid_id = LOWER_KEBAB_PATTERN.fullmatch(scenario_id) is not None
        findings.check(valid_id, f"invalid scenario ID: {scenario_id}")
        scenario_file = entry / "scenario.md"
        findings.check(scenario_file.is_file(), f"scenario.md missing: {findings.relative(entry)}")
        if not scenario_file.is_file():
            continue
        values = metadata_values(scenario_file, "Scenario ID")
        findings.check(len(values) == 1, f"Scenario ID must appear exactly once: {findings.relative(scenario_file)}")
        if values:
            findings.check(bool(values[0]), f"invalid Scenario ID metadata format: {findings.relative(scenario_file)}")
            if values[0]:
                findings.check(values[0] == scenario_id, f"Scenario ID does not match directory: {findings.relative(scenario_file)}")
        scenario_ids.add(scenario_id)


def check_result_metadata(path, scenario_id, environment, target_directory, accounts, findings) -> None:
    metadata: dict[str, str] = {}
    for label in RESULT_METADATA:
        values = metadata_values(path, label)
        findings.check(len(values) == 1, f"{label} must appear exactly once: {findings.relative(path)}")
        if values:
            findings.check(bool(values[0]), f"invalid {label} metadata format: {findings.relative(path)}")
            if values[0]:
                metadata[label] = values[0]

    target = (environment, target_directory)
    expected = {
        "Scenario ID": scenario_id,
        "Environment": environment,
        "AWS account ID": accounts.get(target, {}).get("account", ""),
    }
    for label, value in expected.items():
        if label in metadata:
            findings.check(metadata[label] == value, f"{label} does not match result path: {findings.relative(path)}")

    if "AWS region" in metadata and target in accounts:
        findings.check(metadata["AWS region"] == accounts[target]["region"], f"AWS region does not match project.json: {findings.relative(path)}")
    if "Status" in metadata:
        status = metadata["Status"]
        findings.check(status in RESULT_STATUSES, f"invalid result Status: {findings.relative(path)}: {status}")
        executed_at = metadata.get("Executed at", "")
        if executed_at:
            findings.check(is_rfc3339(executed_at), f"invalid Executed at: {findings.relative(path)}: {executed_at}")
        if status in {"PASS", "FAIL"}:
            findings.check(executed_at != "NOT_EXECUTED", f"{status} result must have execution timestamp: {findings.relative(path)}")
        if status == "NOT_EXECUTED":
            findings.check(executed_at == "NOT_EXECUTED", f"NOT_EXECUTED result must use NOT_EXECUTED timestamp: {findings.relative(path)}")


def check_results(repository, accounts, template_mode, result_files, findings) -> None:
    root = repository / "tests" / "results"
    if not root.is_dir():
        return
    for scenario_entry in sorted(root.iterdir()):
        if scenario_entry.name == ".gitkeep" and scenario_entry.is_file():
            continue
        findings.check(scenario_entry.is_dir(), f"tests/results root may contain only .gitkeep or scenario directories: {findings.relative(scenario_entry)}")
        if not scenario_entry.is_dir():
            continue
        scenario_id = scenario_entry.name
        findings.check(LOWER_KEBAB_PATTERN.fullmatch(scenario_id) is not None, f"invalid result scenario ID: {scenario_id}")
        scenario_file = repository / "tests" / "scenarios" / scenario_id / "scenario.md"
        findings.check(scenario_file.is_file(), f"orphan result without scenario: {findings.relative(scenario_entry)}")
        for environment_entry in sorted(scenario_entry.iterdir()):
            findings.check(environment_entry.is_dir(), f"result scenario directory may contain only environment directories: {findings.relative(environment_entry)}")
            if not environment_entry.is_dir():
                continue
            environment = environment_entry.name
            for target_entry in sorted(environment_entry.iterdir()):
                findings.check(target_entry.is_dir(), f"result environment directory may contain only target directories: {findings.relative(target_entry)}")
                if not target_entry.is_dir():
                    continue
                target_directory = target_entry.name
                target = (environment, target_directory)
                findings.check(target in accounts, f"result target is not defined in project.json: {findings.relative(target_entry)}")
                findings.check(not template_mode, f"template mode cannot contain scenario results: {findings.relative(target_entry)}")
                for child in sorted(target_entry.iterdir()):
                    findings.check(child.is_file(), f"result target directory cannot contain subdirectories: {findings.relative(child)}")
                    if child.is_file() and child.suffix.lower() == ".md":
                        findings.check(child.name == "result.md", f"result history copy is forbidden: {findings.relative(child)}")
                result_file = target_entry / "result.md"
                findings.check(result_file.is_file(), f"result.md missing: {findings.relative(target_entry)}")
                if result_file.is_file():
                    result_files.setdefault(scenario_id, []).append(result_file)
                    check_result_metadata(
                        result_file,
                        scenario_id,
                        environment,
                        target_directory, accounts, findings,
                    )


def check_scenario_changes(changed_paths, result_files, findings) -> None:
    changed_scenarios: set[str] = set()
    for changed in changed_paths:
        parts = Path(changed).parts
        if len(parts) >= 3 and parts[:2] == ("tests", "scenarios"):
            changed_scenarios.add(parts[2])
    for scenario_id in changed_scenarios:
        for result_file in result_files.get(scenario_id, []):
            path = findings.relative(result_file)
            findings.check(path in changed_paths, f"scenario changed without updating existing result: {path}")


