"""Framework entrypoint, rule, prompt and schema contracts."""

from __future__ import annotations

import re

from contracts.repository import DESIGNS_DIRECTORY
from task_contract_core import TASK_TYPES
from utils.aws_mappings import definition_root
from utils.cloudformation.schema import CloudFormationSchemaCatalog, snapshot_errors
from utils.input_cache import input_is_dir, input_is_file, input_select, input_text

REQUIRED_RULES = {
    "task-contract.md",
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
    DESIGNS_DIRECTORY,
    "infra",
    "tests/scenarios",
    "tests/results",
)
CODEX_PROMPT_FILENAME_PATTERN = re.compile(r"\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*\.md")


def check_structure(findings, root, *, consumer=True, definitions_root=None):
    definitions_root = definitions_root or definition_root(root)
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
        ".agents/skills/deploy/SKILL.md",
        "framework/prompts/codex/05_update.md",
        "framework/prompts/codex/06_scenario-test.md",
        "framework/prompts/codex/07_destroy.md",
        "framework/scripts/blueprint-loop.py",
        "framework/scripts/check-deploy-context.py",
        "framework/scripts/cloudformation_schema.py",
        "framework/scripts/sync-model.py",
    ):
        base = (
            definitions_root
            if filename.startswith(("framework/", ".agents/"))
            else root
        )
        findings.check(
            input_is_file(base / filename),
            f"required file missing: {filename}",
            cause_kind="input_invalid",
            source_path=base / filename,
        )
    for directory in REQUIRED_DIRECTORIES:
        findings.check(
            input_is_dir(root / directory),
            f"required directory missing: {directory}",
            cause_kind="input_invalid",
            source_path=root / directory,
        )
    if consumer:
        for directory in ("model",):
            findings.check(
                input_is_dir(root / directory),
                f"required directory missing: {directory}",
                cause_kind="input_invalid",
                source_path=root / directory,
            )
    codex_prompt_names = sorted(
        path.name
        for path in input_select(
            definitions_root / "framework" / "prompts" / "codex", "*"
        )
        if input_is_file(path)
    )
    invalid_prompt_names = [
        name
        for name in codex_prompt_names
        if name != "09_aws_pull.md" and not CODEX_PROMPT_FILENAME_PATTERN.fullmatch(name)
    ]
    findings.check(
        not invalid_prompt_names,
        f"invalid Codex prompt filenames: {invalid_prompt_names}",
        cause_kind="input_invalid",
        source_path=definitions_root / "framework/prompts/codex",
    )
    prompt_numbers = [name.split("_", 1)[0] for name in codex_prompt_names]
    findings.check(
        len(prompt_numbers) == len(set(prompt_numbers)),
        "Codex prompt numbers must be unique",
        cause_kind="input_invalid",
        source_path=definitions_root / "framework/prompts/codex",
    )
    actual_rules = {
        path.name
        for path in input_select(definitions_root / "framework" / "rules", "*.md")
    }
    findings.check(
        REQUIRED_RULES <= actual_rules,
        f"required rules missing: {sorted(REQUIRED_RULES - actual_rules)}",
        cause_kind="input_invalid",
        source_path=definitions_root / "framework/rules",
    )


def check_framework_task_type_dispatch(findings, task_type):
    findings.check(
        task_type in TASK_TYPES, "task type completion check was not dispatched"
    )
    findings.check(
        len(TASK_TYPES) == 7, "not every task type has a completion-check branch"
    )


def check_framework_focused_check_runner(findings, root):
    loop = input_text(
        root / "framework" / "scripts" / "validation" / "loop.py", encoding="utf-8"
    )
    findings.check(
        'glob("*.checks.py")' in loop,
        "local loop does not discover focused checks",
        cause_kind="input_invalid",
        source_path=root / "framework/scripts/validation/loop.py",
    )
    findings.check(
        "PYTHONDONTWRITEBYTECODE" in loop,
        "focused checks may write bytecode into the repository",
        cause_kind="input_invalid",
        source_path=root / "framework/scripts/validation/loop.py",
    )


def check_framework_cloudformation_schema_catalog(findings, root):
    errors = snapshot_errors(root)
    findings.check(
        not errors,
        "; ".join(errors) or "CloudFormation schema snapshot is invalid",
        cause_kind="input_invalid",
    )


def check_framework_schema_backed_design_validation(findings, root):
    catalog = CloudFormationSchemaCatalog(root)
    findings.check(
        bool(catalog.literal_errors("Logs.LogGroup", "KmsKeyId", "not-used")),
        "schema-backed literal validation is inactive",
    )
