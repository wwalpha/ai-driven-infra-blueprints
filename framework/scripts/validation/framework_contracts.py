"""Framework entrypoint, rule, prompt and schema contracts."""


from __future__ import annotations
import re
from cloudformation_schema import CloudFormationSchemaCatalog, snapshot_errors
from .task import TASK_TYPES

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
CODEX_PROMPT_FILENAME_PATTERN = re.compile(r"\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*\.md")


def check_structure(findings, root):
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
        "framework/prompts/codex/07_destroy.md",
        "framework/scripts/blueprint-loop.py",
        "framework/scripts/check-deploy-context.py",
        "framework/scripts/cloudformation_schema.py",
        "framework/scripts/sync-model.py",
    ):
        findings.check((root / filename).is_file(), f"required file missing: {filename}")
    for directory in REQUIRED_DIRECTORIES:
        findings.check((root / directory).is_dir(), f"required directory missing: {directory}")
    codex_prompt_names = sorted(
        path.name
        for path in (root / "framework" / "prompts" / "codex").glob("*")
        if path.is_file()
    )
    invalid_prompt_names = [
        name for name in codex_prompt_names if not CODEX_PROMPT_FILENAME_PATTERN.fullmatch(name)
    ]
    findings.check(not invalid_prompt_names, f"invalid Codex prompt filenames: {invalid_prompt_names}")
    prompt_numbers = [name.split("_", 1)[0] for name in codex_prompt_names]
    findings.check(
        len(prompt_numbers) == len(set(prompt_numbers)),
        "Codex prompt numbers must be unique",
    )
    actual_rules = {
        path.name for path in (root / "framework" / "rules").glob("*.md")
    }
    findings.check(REQUIRED_RULES <= actual_rules, f"required rules missing: {sorted(REQUIRED_RULES - actual_rules)}")


def check_framework_active_task_transition(findings, root):
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    findings.check("## Task transition" in agents, "AGENTS.md lacks Task transition rules")
    findings.check("## Task transition" in readme, "README.md lacks Task transition workflow")
    findings.check("chat-only" in agents and "chat-only" in readme, "chat-only task handling is not defined")
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
        path = root / relative
        findings.check(path.is_file(), f"active task lifecycle file missing: {relative}")
        if path.is_file():
            findings.check(literal in path.read_text(encoding="utf-8"), f"active task lifecycle rule missing: {relative}")


def check_framework_rule_readings(findings, root):
    from deploy_preparation import markdown_sections, rule_readings
    sources = [root / "AGENTS.md", root / "README.md",
               *sorted((root / "framework/rules").glob("*.md")),
               *sorted((root / "framework/prompts").rglob("*.md")),
               *sorted((root / ".agents/skills").glob("*/SKILL.md"))]
    for source in sources:
        try:
            text = source.read_text(encoding="utf-8")
            rule_readings(root, source, text)
            if source.parent == root / "framework/prompts/codex":
                sections = markdown_sections(text)
                reading = sections.get("read-first", sections.get("read-before-changing-files", ""))
                required = {root / "framework/rules" / name for name in
                            ("task-contract.md", "issue-gate.md", "project-configuration.md")}
                findings.check(required <= rule_readings(root, source, reading).keys(),
                           f"workflow lacks canonical rule readings: {source.relative_to(root)}")
        except (OSError, ValueError) as error:
            findings.check(False, f"rule reading reference: {error}")


def check_framework_design_handoff(findings, root):
    path = root / "framework" / "prompts" / "chatbot" / "service-design.md"
    findings.check(path.is_file(), "service design prompt is missing")
    if not path.is_file():
        return
    prompt = path.read_text(encoding="utf-8")
    findings.check("Task type is `design`" in prompt, "service design prompt lacks design task contract")
    findings.check("sync-model.py" in prompt, "service design prompt lacks properties-based Markdown generation")
    findings.check("blueprint-loop.py --mode task" in prompt, "service design prompt lacks local validation")
    findings.check("03_apply-design.md" not in prompt, "service design prompt still depends on apply-design")
    gate = "## Naming rule preflight (design start gate)"
    findings.check(gate in prompt and "## Determine what to ask" in prompt
               and prompt.index(gate) < prompt.index("## Determine what to ask"),
               "service design prompt lacks naming preflight before design questions")
    findings.check("check-design-naming.py --resource-type" in prompt,
               "service design prompt lacks executable naming preflight")
    findings.check("Before design contract registration, execute `check-design-naming.py`" in prompt,
               "service design handoff lacks naming preflight before task registration")
    required_existing_resource_contract = {
        "--read-only": "service design prompt lacks read-only AWS context preflight",
        "aws cloudcontrol list-resources": "service design prompt lacks generic existing-resource discovery",
        "aws cloudcontrol get-resource": "service design prompt lacks generic existing-resource read",
        "Fall back to target-service-specific read-only APIs only when Cloud Control API does not support List/Read": "service design prompt lacks service API fallback",
        "stop until humans select, even for a single candidate": "service design prompt may auto-select an existing resource",
        "ask one logical ID per response": "service design prompt may invent a logical ID for an existing resource",
        "Directly apply differences to model properties": "service design prompt lacks direct existing-value synchronization",
        "delete optional property rows absent from AWS current values": "service design prompt lacks absent optional-property removal",
        "Do not display or save passwords, secrets, tokens, or credentials": "service design prompt lacks sensitive-value exclusion",
        "do not save generated ARNs in Markdown, JSON artifacts, or models": "service design prompt may persist generated ARNs",
        "Do not add resource creator, administrator, or externally created provenance to artifacts": "service design prompt persists or omits the no-provenance contract",
    }
    for literal, error in required_existing_resource_contract.items():
        findings.check(literal in prompt, error)


def check_framework_task_completion_contract(findings, root):
    contract = (root / "framework/rules/task-contract.md").read_text(encoding="utf-8")
    rules = (root / "framework" / "rules" / "loop-engineering.md").read_text(encoding="utf-8")
    findings.check("Requirement ID" in contract and "Acceptance checks" in contract, "task rules lack completion contract")
    findings.check("task-contract.md#acceptance-contract" in rules, "loop lacks canonical completion contract reference")


def check_framework_task_type_dispatch(findings, task_type):
    findings.check(task_type in TASK_TYPES, "task type completion check was not dispatched")
    findings.check(len(TASK_TYPES) == 7, "not every task type has a completion-check branch")


def check_framework_focused_check_runner(findings, root):
    loop = (root / "framework" / "scripts" / "blueprint-loop.py").read_text(encoding="utf-8")
    findings.check('glob("*.checks.py")' in loop, "local loop does not discover focused checks")
    findings.check("PYTHONDONTWRITEBYTECODE" in loop, "focused checks may write bytecode into the repository")


def check_framework_cloudformation_schema_catalog(findings, root):
    errors = snapshot_errors(root)
    findings.check(not errors, "; ".join(errors) or "CloudFormation schema snapshot is invalid")


def check_framework_schema_backed_design_validation(findings, root):
    rules = (root / "framework" / "rules" / "detailed-design.md").read_text(encoding="utf-8")
    prompt = (
        root / "framework" / "prompts" / "chatbot" / "service-design.md"
    ).read_text(encoding="utf-8")
    findings.check("CloudFormation provider schema" in rules, "detailed design rules do not apply provider schemas")
    findings.check("CloudFormation provider schema" in prompt, "initial design prompt does not apply provider schemas")
    catalog = CloudFormationSchemaCatalog(root)
    findings.check(bool(catalog.literal_errors("Logs.LogGroup", "KmsKeyId", "not-used")), "schema-backed literal validation is inactive")


def check_framework_cfn_lint_validation(findings, root):
    paths = (
        root / "framework" / "rules" / "cloudformation.md",
        root / "framework" / "prompts" / "codex" / "03_implement.md",
        root / "framework" / "prompts" / "codex" / "04_deploy.md",
        root / "framework" / "scripts" / "check-deploy-context.py",
    )
    for path in paths:
        findings.check("cfn-lint" in path.read_text(encoding="utf-8"), f"cfn-lint requirement missing: {findings.relative(path)}")

