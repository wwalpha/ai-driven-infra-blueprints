"""Framework entrypoint, rule, prompt and schema contracts."""


from __future__ import annotations
from validation_cache import input_is_dir, input_is_file, input_select, input_text
import re
from utils.aws_mappings import definition_root
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
        "framework/prompts/codex/04_deploy.md",
        "framework/prompts/codex/05_update.md",
        "framework/prompts/codex/06_scenario-test.md",
        "framework/prompts/codex/07_destroy.md",
        "framework/scripts/blueprint-loop.py",
        "framework/scripts/check-deploy-context.py",
        "framework/scripts/cloudformation_schema.py",
        "framework/scripts/sync-model.py",
    ):
        base = definitions_root if filename.startswith('framework/') else root
        findings.check(input_is_file(base / filename), f"required file missing: {filename}")
    for directory in REQUIRED_DIRECTORIES:
        findings.check(input_is_dir(root / directory), f"required directory missing: {directory}")
    if consumer:
        for directory in ("model",):
            findings.check(input_is_dir(root / directory), f"required directory missing: {directory}")
    codex_prompt_names = sorted(
        path.name
        for path in input_select(definitions_root / "framework" / "prompts" / "codex", "*")
        if input_is_file(path)
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
        path.name for path in input_select(definitions_root / "framework" / "rules", "*.md")
    }
    findings.check(REQUIRED_RULES <= actual_rules, f"required rules missing: {sorted(REQUIRED_RULES - actual_rules)}")


def check_framework_active_task_transition(findings, root):
    agents = input_text(root / "AGENTS.md", encoding="utf-8")
    readme = input_text(root / "README.md", encoding="utf-8")
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
        findings.check(input_is_file(path), f"active task lifecycle file missing: {relative}")
        if input_is_file(path):
            findings.check(literal in input_text(path, encoding="utf-8"), f"active task lifecycle rule missing: {relative}")


def check_framework_rule_readings(findings, root):
    from utils.markdown_format import markdown_sections, rule_readings
    # These entry sections must direct execution to the existing authorities.
    routes = {
        ("README.md", "task-transition"): {
            "task-contract.md": {"task-transition"}},
        ("framework/rules/loop-engineering.md", "local-loop"): {
            "task-contract.md": {"task-transition", "acceptance-contract"}},
        (".agents/skills/worktree/SKILL.md", "read-before-execution"): {
            "task-contract.md": {"task-transition", "task-boundary", "acceptance-contract", "retry-and-stop"},
            "loop-engineering.md": {"local-loop", "validation-scope", "framework-regression",
                                    "conflict-resolution-and-reproducible-validation", "retry-and-stop"}},
    }
    sources = [root / "AGENTS.md", root / "README.md",
               *sorted(input_select(root / "framework/rules", "*.md")),
               *sorted(input_select(root / "framework/prompts", "*.md", recursive=True)),
               *sorted(input_select(root / ".agents/skills", "*/SKILL.md"))]
    for source in sources:
        try:
            text = input_text(source, encoding="utf-8")
            rule_readings(root, source, text)
            sections = markdown_sections(text)
            for (relative, heading), required in routes.items():
                if source != root / relative:
                    continue
                if heading not in sections:
                    findings.check(False, f"mandatory reading entry missing: {relative}#{heading}")
                    continue
                readings = rule_readings(root, source, sections[heading])
                for filename, anchors in required.items():
                    entry = readings.get((root / "framework/rules" / filename).resolve())
                    covered = set(entry["sections"]) if entry else set()
                    findings.check("" in covered or anchors <= covered,
                                   f"mandatory rule readings missing: {relative}#{heading} -> {filename}")
            if source.parent == root / "framework/prompts/codex":
                reading = sections.get("read-first", sections.get("read-before-changing-files", ""))
                required = {root / "framework/rules" / name for name in
                            ("task-contract.md", "issue-gate.md", "project-configuration.md")}
                readings = rule_readings(root, source, reading)
                if source.name == "08_import.md":
                    required.remove(root / "framework/rules/issue-gate.md")
                    worktree = root / ".agents/skills/worktree/SKILL.md"
                    if worktree in readings:
                        delegated = markdown_sections(readings[worktree]["text"]).get("read-before-execution", "")
                        task = root / "framework/rules/task-contract.md"
                        inherited = rule_readings(root, worktree, delegated)
                        if task in inherited:
                            readings[task] = inherited[task]
                findings.check(required <= readings.keys(),
                           f"workflow lacks canonical rule readings: {source.relative_to(root)}")
        except (OSError, ValueError) as error:
            findings.check(False, f"rule reading reference: {error}")


def check_framework_design_handoff(findings, root):
    path = root / "framework" / "prompts" / "chatbot" / "service-design.md"
    findings.check(input_is_file(path), "service design prompt is missing")
    if not input_is_file(path):
        return
    prompt = input_text(path, encoding="utf-8")
    findings.check("Task type is `design`" in prompt, "service design prompt lacks design task contract")
    findings.check("blueprint-loop.py --mode task --write --task-file tasks/<task-name>.md" in prompt, "service design prompt lacks integrated Model generation/validation")
    from utils.markdown_format import markdown_prose, markdown_sections, rule_readings
    try:
        completion = markdown_sections(prompt).get("completion", "")
        validation = next((line for _, line in markdown_prose(completion) if re.match(
            r"^\d+\. Select development checks and final validation under ", line)), "")
        readings = rule_readings(root, path, validation)
        policy = readings.get((root / "framework/rules/loop-engineering.md").resolve(), {})
        findings.check("validation-policy" in policy.get("sections", []),
                       "service design handoff lacks canonical Validation policy reference")
        for required in (
            ". Validate in-scope service designs/models, generated Markdown/JSON, schemas, naming, "
            "references, active task contracts, and task-specific checks.",
            ". Do not add entire-scope validation “just in case” after scoped validation.",
            ". Report executed checks and diff-check results,",
        ):
            findings.check(required in validation,
                           f"service design handoff lacks required validation instruction: {required}")
    except (OSError, ValueError) as error:
        findings.check(False, f"service design handoff Validation policy reference: {error}")
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
        "Allocate new selected Resources through the shared allocator; preserve existing logicalIds": "service design prompt lacks fixed Resource identity allocation",
        "For CREATE only, directly apply differences to model properties": "service design prompt lacks CREATE-only existing-value synchronization",
        "[/import](../../../.agents/skills/import/SKILL.md)": "service design prompt lacks IMPORT delegation",
        "The retrieval/copy steps below apply\nto CREATE only": "service design prompt lacks IMPORT delegation boundary",
        "delete optional property rows absent from AWS current values": "service design prompt lacks absent optional-property removal",
        "Do not display or save passwords, secrets, tokens, or credentials": "service design prompt lacks sensitive-value exclusion",
        "do not save generated ARNs in Markdown, JSON artifacts, or models": "service design prompt may persist generated ARNs",
        "Do not add resource creator, administrator, or externally created provenance to artifacts": "service design prompt persists or omits the no-provenance contract",
    }
    for literal, error in required_existing_resource_contract.items():
        findings.check(literal in prompt, error)


def check_framework_task_completion_contract(findings, root):
    contract = input_text(root / "framework/rules/task-contract.md", encoding="utf-8")
    rules = input_text(root / "framework" / "rules" / "loop-engineering.md", encoding="utf-8")
    findings.check("Requirement ID" in contract and "Acceptance checks" in contract, "task rules lack completion contract")
    findings.check("task-contract.md#acceptance-contract" in rules, "loop lacks canonical completion contract reference")
    from utils.markdown_format import markdown_sections
    transition = markdown_sections(contract).get("task-transition", "")
    for boundary in ("Suspension reason", "--resume", "--complete", "running"):
        findings.check(boundary in transition, f"Task transition safety boundary missing: {boundary}")


def check_framework_task_type_dispatch(findings, task_type):
    findings.check(task_type in TASK_TYPES, "task type completion check was not dispatched")
    findings.check(len(TASK_TYPES) == 7, "not every task type has a completion-check branch")


def check_framework_focused_check_runner(findings, root):
    loop = input_text(root / "framework" / "scripts" / "validation" / "loop.py", encoding="utf-8")
    findings.check('glob("*.checks.py")' in loop, "local loop does not discover focused checks")
    findings.check("PYTHONDONTWRITEBYTECODE" in loop, "focused checks may write bytecode into the repository")


def check_framework_cloudformation_schema_catalog(findings, root):
    errors = snapshot_errors(root)
    findings.check(not errors, "; ".join(errors) or "CloudFormation schema snapshot is invalid")


def check_framework_schema_backed_design_validation(findings, root):
    rules = input_text(root / "framework" / "rules" / "detailed-design.md", encoding="utf-8")
    prompt = input_text(root / "framework" / "prompts" / "chatbot" / "service-design.md", encoding="utf-8")
    findings.check("CloudFormation provider schema" in rules, "detailed design rules do not apply provider schemas")
    findings.check("CloudFormation provider schema" in prompt, "initial design prompt does not apply provider schemas")
    catalog = CloudFormationSchemaCatalog(root)
    findings.check(bool(catalog.literal_errors("Logs.LogGroup", "KmsKeyId", "not-used")), "schema-backed literal validation is inactive")
