"""Prompt and rule reading contracts."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from unittest.mock import patch

import utils.markdown_format as _imports_utils_markdown_format
from support.validator import MODULE, SCRIPT
from validation import framework_contracts
from validation.findings import Findings


def _task_completion_errors(root: Path, path: Path, text: str):
    findings = Findings(root)
    original = framework_contracts.input_text
    with patch.object(
        framework_contracts,
        "input_text",
        side_effect=lambda source, **kwargs: (
            text if source == path else original(source, **kwargs)
        ),
    ):
        framework_contracts.check_framework_task_completion_contract(findings, root)
    assert findings.checks == 6
    return findings.errors


def check_task_completion_contract() -> None:
    root = SCRIPT.parents[2]
    path = root / "framework/rules/task-contract.md"
    contract = path.read_text(encoding="utf-8")
    sections = _imports_utils_markdown_format.markdown_sections(contract)

    assert not _task_completion_errors(root, path, contract)
    for section, boundary in (
        ("common-transitions", "Suspension reason"),
        ("common-transitions", "--resume"),
        ("common-transitions", "--complete"),
        ("task-registration", "running"),
    ):
        original = sections[section]
        assert boundary in original
        misplaced = contract.replace(original, original.replace(boundary, ""), 1)
        misplaced += f"\n## Unrelated section\n\n{boundary}\n"
        assert f"Task transition safety boundary missing: {boundary}" in _task_completion_errors(root, path, misplaced)
    for section in ("common-transitions", "task-registration"):
        assert _task_completion_errors(root, path, contract.replace(sections[section], "", 1)), section


def check_optional_alias_contract() -> None:
    root = SCRIPT.parents[2]
    required = {
        "AGENTS.md": "target directory",
        "framework/prompts/codex/01_initialize.md": "optional `alias`",
        "framework/rules/cloudformation.md": "templates/<alias>/",
        "framework/rules/terraform.md": "infra/<target-directory>/terraform/modules/<module>/",
        "framework/rules/detailed-design.md": "<target-directory>",
        "framework/rules/scenario-testing.md": "<target-directory>",
    }
    for relative, literal in required.items():
        assert literal in (root / relative).read_text(encoding="utf-8"), (
            relative,
            literal,
        )


def check_implementation_preflight_prompt() -> None:
    text = (SCRIPT.parents[2] / "framework/prompts/codex/03_implement.md").read_text(
        encoding="utf-8"
    )
    preflight = text.split("## Read-only implementation preflight\n", 1)[1].split(
        "\n## ", 1
    )[0]
    assert (
        text.index("## Read-only implementation preflight")
        < text.index("## Create active task contract")
        < text.index("## Implement and validate")
    )
    for required in (
        "before active contract creation or IaC generation",
        "Do not execute AWS APIs, IaC generation, or deploy",
        "model.validations.schema.validate_required_properties",
        "DesignSchemaCatalog.literal_errors",
        "necessary dependency properties",
        "authoritative stack registration",
        "template/parameter mappings",
        "dependency cycle",
        "対象file | resource（logical ID）/stack | property/parameter | 不足・違反理由",
        "If deficiencies exist, do not implement",
        "Do not automatically expand change scope or all-service validation",
        "Do not repair designs/models/IaC here or automatically create/execute another task",
    ):
        assert required in preflight, required
    reading = text.split("## Read before changing files\n", 1)[1].split("\n## ", 1)[0]
    for required in (
        "Implement design inputs are only authoritative model properties",
        "Do not read generated `docs/designs/<environment>/<target-directory>/*.md` bodies (including `cloudformation-stacks.md`) at Implement start, IaC generation, or reference resolution",
        "treat them as scope selectors",
        "Without reading bodies",
        "path/file stem",
        "If corresponding models cannot be uniquely identified, stop without guessing",
        "python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py resource model/<environment>/<target-directory>/<service>.properties <resource-selector>",
        "resource number",
        "Selectors require exact matches for resource number (fixed entry, such as `001`) or immutable typed logicalId",
        "single files and split entry indexes",
        "parents, children, and siblings in the same group required by existing specifications, and service metadata/notes",
        "Service-wide scope may use entire service properties",
        "対象accountの承認済み設計すべて",
        "Reading all target Markdown as fallback is prohibited",
        "desired values, resources, references, stack assignments, or human decisions",
        "stop because a design task is required",
    ):
        assert required in reading, required
    assert not any(
        line.startswith("5. Target `docs/designs/") for line in reading.splitlines()
    )
    assert (
        "generated designs" not in preflight
        and "model generation equality validation" not in preflight
    )
    units = text.split("## Resolve implementation units\n", 1)[1].split("\n## ", 1)[0]
    for required in (
        "read only the target's runtime Model through the logical `model/<environment>/<target-directory>/cloudformation-stacks.properties`",
        "desired.stack.*.name",
        "`.template`",
        "`.parameters`",
        "`.deployOrder`",
        "desired.deployment.maxConcurrentStacks",
        "effective MaxConcurrentStacks remains 1 under the existing contract",
        "do not read it as Implement input",
    ):
        assert required in units, required
    implementation = text.split("## Implement and validate\n", 1)[1].split("\n## ", 1)[
        0
    ]
    for required in (
        "Use only authoritative model properties",
        "`desired.row.*`",
        "`.document`",
        "structured `$modelRef` Resource references",
        "common parser/resolver",
        "referenced Model groups",
        "parentReference",
        "Resolve through producer Model logicalId and explicit attribute, never display names, anchors or generated Markdown",
        "never emit an unresolved Resource link, PENDING_DEPLOY or an inferred physical value to IaC",
    ):
        assert required in implementation, required
    finish = text.split("## Verify and finish\n", 1)[1]
    for required in (
        "blueprint-loop.py --mode task",
        "read-only `sync-model.py`",
        "mismatches are FAIL",
        "check_design_tables",
        "check_design_links",
        "check_stack_designs",
        "do not omit/weaken these validations",
    ):
        assert required in finish and required not in preflight, required

    # Assert the reading boundary, not a copy of each engine's rule prose.
    for engine, anchors in {
        "cloudformation": (
            "common-rules",
            "template-implementation",
            "design-coverage-and-cloudformation-support",
            "resource-mode-boundary",
            "local-implementation-validation",
        ),
        "terraform": (
            "common-rules",
            "module-and-environment-inputs",
            "resource-mode-boundary",
            "local-static-validation",
        ),
        "observed-values": (
            "dedicated-import-boundary",
            "identifier-lifecycle",
            "compact-observation-persistence",
            "local-mapping-validation",
        ),
    }.items():
        assert f"../../rules/{engine}.md)" not in reading
        for anchor in anchors:
            assert f"../../rules/{engine}.md#{anchor}" in reading
    assert "introductory text before the first `##`" in reading
    numbered = reading.split("For naming rules", 1)[0]
    assert "#controlled-deploy-repair" not in numbered
    assert "#collection-and-propagation" not in numbered
    assert "#explicit-stack-destroy" not in numbered
    assert "For the selected engine only" in numbered
    assert "before this preflight" in preflight and "inside that Worktree" in preflight
    assert "first repository change only after" in preflight
    assert (
        "If all portions match" in preflight
        and "static validation once" in preflight
        and "finish without creating a Task" in preflight
        and "a no-diff confirmation alone does not complete it" in preflight
        and "Required changes, Acceptance checks, and Task completion contract"
        in preflight
    )
    assert "must not save or change Model or Observed" in text
    assert (
        "--cloudformation-type <catalog-resource-type> <another-catalog-resource-type>"
        in text
    )
    assert "<resource-selector> <another-resource-selector>" in reading
    assert "create it first under Create active task contract" not in reading

    root = SCRIPT.parents[2]
    transition = (root / "framework/rules/task-contract.md").read_text(encoding="utf-8")
    routing = transition.split("## Workflow selection\n", 1)[1].split("\n## ", 1)[0]
    assert "IaC-only work loads implement without reading `05_update.md`" in routing
    for request, skill in (
        ("Implement IaC from approved Model", "implement"),
        (
            "Correct IaC without changing Model, including Model/IaC mismatches on the IaC side",
            "implement",
        ),
        ("Change Model design values", "applicable update branch"),
        (
            "Reflect an explicitly requested Model change into IaC and AWS",
            "update infrastructure branch",
        ),
        ("Deploy only", "deploy"),
        (
            "Approved IaC repair after Deploy failure",
            "implement through the existing repair handoff",
        ),
    ):
        assert f"| {request} | {skill} |" in routing
    for relative in (
        "AGENTS.md",
        ".agents/skills/implement/SKILL.md",
        ".agents/skills/update/SKILL.md",
    ):
        assert "task-contract.md#workflow-selection" in (root / relative).read_text(
            encoding="utf-8"
        )

    sandbox = (
        (root / ".agents/skills/worktree/SKILL.md")
        .read_text(encoding="utf-8")
        .split("## Sandbox permission approval and continuation\n", 1)[1]
        .split("\n## ", 1)[0]
    )
    assert "git --no-optional-locks status --porcelain --untracked-files=all" in sandbox
    assert "git status --porcelain --untracked-files=all" not in sandbox
    for required in (
        "create, deploy-start, setup (when needed), normal Deploy checkpoint, base synchronization, finalize, PR operations, orphan branch deletion and cleanup",
        "effective Sandbox restrictions",
        "protected exceptions and symlinks",
        "prior denial is not required",
        "first invocation",
        "without an unnecessary approval",
        "infer a denial from ordinary filesystem permissions alone",
        "add no persistent permission-state file",
        'sandbox_permissions: "with_additional_permissions"',
        "additional_permissions.file_system.write",
        "Avoid granting the entire repository",
        'sandbox_permissions: "require_escalated"',
        "do not invent unsupported capabilities",
        "never use escalation to bypass them",
        "one escalated reexecution per denied invocation",
        "Never delete a lock",
        "Permission approval does not relax the Python helper's guards",
    ):
        assert required in sandbox, required


def _check_update_flow_prompt_validate_engine(body, heading):
    return body.split(f"### {heading}\n", 1)[1].split("\n### ", 1)[0]


def _check_update_flow_prompt_validate_commands(body):
    return [
        [token.strip("[]") for token in shlex.split(line)]
        for line in re.findall(
            "(?:^|`)(python\\s+framework/scripts/[^`\\n]+)", body, re.M
        )
    ]


# Check instruction/engine boundaries and executable examples, not a full prose snapshot.
def _callback_check_update_flow_prompt_validate(prompt):
    # Check instruction/engine boundaries and executable examples, not a full prose snapshot.
    sections = dict(re.findall(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", prompt, re.M | re.S))

    engine = _check_update_flow_prompt_validate_engine

    commands = _check_update_flow_prompt_validate_commands

    reading = sections["Read before changing files"]
    for token in (
        "authoritative model properties",
        "desired.row.*.document",
        "Do not read generated Markdown bodies or generated JSON artifacts as input",
        "model/cli.py resource",
        "parentReference",
        "structured `$modelRef` Resource references",
        "required parts",
    ):
        assert token in reading, token
    instructions = [line for line in reading.splitlines() if re.match(r"\d+\. ", line)]
    assert instructions and not any(
        re.search(
            r"docs/designs/|cloudformation-stacks\.md|0[34]_(?:implement|deploy)\.md",
            line,
        )
        for line in instructions
    ), "generated artifacts/full prompts returned to the input list"
    scope = sections["Resolve target and scope from repository state"]
    assert "only from authoritative `cloudformation-stacks.properties`" in scope
    assert "cloudformation-stacks.md" not in scope, "duplicate stack scope input"
    for token in (
        "desired.stack.*.name",
        ".template",
        ".parameters",
        ".deployOrder",
        "desired.deployment.maxConcurrentStacks",
        "workspace",
        "backend",
        "variable input",
    ):
        assert token in scope, token
    implementation = sections["Generate Markdown and implement IaC"]
    for token in (
        "Producer/Consumer relationship locally", "`!ImportValue`",
        "missing or ambiguous local prerequisites", "AWS Export lookup alone is not a prerequisite",
    ):
        assert token in implementation, token
    assert not re.search(r"AWS Export (?:confirmation|lookup) (?:is|must be) required", implementation, re.I)
    deploy = sections["Preflight and deploy"]
    dependency = engine(deploy, "CloudFormation read-only dependency check")
    for token in (
        "--read-only",
        "describe-stacks",
        "list-exports",
        "do not run it in ordinary CloudFormation update",
        "delegate AWS Export verification to the existing controller",
        "missing, changed, ambiguous or unavailable",
        "Producer-first order",
        "not added automatically",
        "Consumer-only deployment",
    ):
        assert token in dependency, token
    assert not re.search(r"(?:require|must)[^\n.]*ExportingStackId", dependency, re.I)
    assert not re.search(r"(?:require|must)[^\n.]*NOT_STARTED", dependency, re.I)
    cfn = engine(deploy, "CloudFormation controller")
    cfn_commands = commands(cfn)
    assert len(cfn_commands) == 1 and cfn_commands[0][1].endswith(
        "/cloudformation-deploy.py"
    )
    for option in ("--environment", "--alias", "--stack", "--profile", "--action"):
        assert option in cfn_commands[0], option
    for token in (
        "responsible for final preflight",
        "account",
        "region",
        "immutable input",
        "SDK",
        "validate-template",
        "MaxConcurrentStacks",
        "COMPLETE",
        "independent run",
        "task scope",
        "profiles, accounts, regions, engines",
        "Do not create consumer change sets before producer success",
    ):
        assert token in cfn, token
    assert "--state" not in cfn and "--resume" not in cfn
    terraform = engine(deploy, "Terraform preflight and apply")
    tf_commands = commands(terraform)
    assert len(tf_commands) == 2 and all(
        c[1].endswith("/check-deploy-context.py") for c in tf_commands
    )
    assert "--alias" in tf_commands[0] and "--aws-account-id" in tf_commands[1]
    assert commands(deploy) == cfn_commands + tf_commands, (
        "standalone normal CFn preflight was added"
    )
    for token in (
        "terraform fmt -check",
        "terraform validate",
        "terraform plan -out=",
        "terraform apply",
        "saved plan binary",
        "partial apply",
        "AWS_PROFILE",
    ):
        assert token in terraform, token

    post = sections["Post-deployment model sync"]
    cfn_post = engine(post, "CloudFormation")
    assert not commands(cfn_post), (
        "Agent must not run a second CFn observed/sync process"
    )
    for token in (
        "owned by the controller",
        "model.adapters.observed",
        "IDENTIFIER_OUTPUT",
        "PhysicalResourceId",
        "all references",
        "must not rerun",
        "AMBIGUOUS_OBSERVED_MAPPING",
    ):
        assert token in cfn_post, token
    assert all(
        "must not rerun" in line for line in cfn_post.splitlines() if "--write" in line
    )
    assert "--action status" in cfn_post and "same controller session" not in cfn_post
    tf_post = engine(post, "Terraform")
    for token in (
        "Terraform output",
        "state",
        "non-sensitive",
        "IDENTIFIER_OUTPUT",
        "all references",
        "PENDING_DEPLOY",
        "sync-model.py --write",
    ):
        assert token in tf_post, token
    approval = sections["Confirm unapproved delete/replacement"]
    for token in (
        "unexecuted",
        "wait for human confirmation",
        "--approve-change-set",
        "CREATE_COMPLETE/AVAILABLE",
        "fingerprint",
        "Do not execute with only partial approval",
        "Do not reuse prior approval",
    ):
        assert token in approval, token
    assert "--resume" not in approval and "independent invocation" in approval
    finish = sections["Verify and finish"]
    loop = commands(finish)
    assert len(loop) == 1 and loop[0][1].endswith("/blueprint-loop.py")
    assert loop[0][loop[0].index("--mode") + 1] == "task"
    assert "--task-file" in loop[0] and "--all" not in loop[0]
    for token in (
        "Validation scope",
        "Acceptance checks",
        "read-only",
        "mismatches are FAIL",
        "validation cache",
        "service parallelism",
        "do not add all framework regression",
    ):
        assert token in finish, token


def _validate_cross_stack(implement, rules):
    sections = _imports_utils_markdown_format.markdown_sections(rules)
    units = implement.split("## Resolve implementation units\n", 1)[1].split("\n## ", 1)[0]
    for token in (
        "local reference and dependency conditions", "`!ImportValue` without requiring AWS Export confirmation",
        "`PENDING_DEPLOY`", "never be embedded as a physical value",
        "Stop if ownership or the local reference cannot be resolved",
        "Do not execute AWS APIs, ChangeSets or deploy",
    ):
        assert token in units, token
    cross_stack = sections["cross-stack-references"]
    for token in (
        "formal Model resource and attribute", "unique owning Producer Stack", "Output/Export",
        "Consumer Export name locally", "dependencies and DeployOrder", "same account/region",
        "Stop without guessing", "ambiguous or unresolved", "not an Implement prerequisite",
        "Never embed `PENDING_DEPLOY` as a KeyId", "`!ImportValue`",
        "before ChangeSet creation", "immediately before execution", "Producer StackId",
        "successful status and Outputs", "Export name, value and owner",
        "missing, changed, ambiguous or unavailable evidence is BLOCKED",
        "do not create a Consumer ChangeSet before an in-scope Producer succeeds",
    ):
        assert token in cross_stack, token
    kms = sections["kms-key-and-alias"]
    for token in ("Model reference target and attribute", "Alias reference", "KeyId reference", "Key ARN", "S3 encryption", "Do not automatically convert among Alias, KeyId and ARN"):
        assert token in kms, token


def check_update_flow_prompt() -> None:
    text = (SCRIPT.parents[2] / "framework/prompts/codex/05_update.md").read_text(
        encoding="utf-8"
    )

    validate = _callback_check_update_flow_prompt_validate

    validate(text)
    root = SCRIPT.parents[2]
    implement = (root / "framework/prompts/codex/03_implement.md").read_text(encoding="utf-8")
    rules = (root / "framework/rules/cloudformation.md").read_text(encoding="utf-8")

    _validate_cross_stack(implement, rules)
    # Check each safety boundary in its own section, even if the text appears elsewhere.
    for document, phrase in (
        (implement, "`!ImportValue` without requiring AWS Export confirmation"),
        (rules, "not an Implement prerequisite"),
        (rules, "Never embed `PENDING_DEPLOY` as a KeyId"),
        (rules, "before ChangeSet creation"),
        (rules, "immediately before execution"),
        (rules, "missing, changed, ambiguous or unavailable evidence is BLOCKED"),
        (rules, "Export name, value and owner"),
        (rules, "same account/region"),
        (rules, "do not create a Consumer ChangeSet before an in-scope Producer succeeds"),
        (rules, "Do not automatically convert among Alias, KeyId and ARN"),
    ):
        assert phrase in document
        altered = document.replace(phrase, "", 1) + "\n## Unrelated section\n" + phrase
        try:
            _validate_cross_stack(altered if document == implement else implement, altered if document == rules else rules)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"Cross-stack regression accepted: {phrase}")
    # Prohibitions alone must not hide contradictory executable/read instructions.
    regressions = [
        text.replace("AWS Export lookup alone is not a prerequisite", "AWS Export lookup is required", 1),
        text.replace("### CloudFormation read-only dependency check\n", "### CloudFormation read-only dependency check\nRequire ExportingStackId and NOT_STARTED.\n", 1),
        text.replace("Producer-first order", "arbitrary order", 1),
        text.replace("task scope and immutable inputs", "immutable inputs", 1),
        text.replace("accounts, regions, engines", "engines", 1),
        text.replace("delegate AWS Export verification to the existing controller", "skip AWS Export verification", 1),
        text.replace("do not run it in ordinary CloudFormation update", "run it in ordinary CloudFormation update", 1),
        text.replace(
            "6. Authoritative Design scope",
            "6. Target `docs/designs/<environment>/<target-directory>/*.md` and related JSON artifacts\n7. Authoritative Design scope",
            1,
        ),
        text.replace(
            "only from authoritative `cloudformation-stacks.properties`",
            "from authoritative `cloudformation-stacks.properties` and generated `cloudformation-stacks.md`",
            1,
        ),
        text.replace(
            "### CloudFormation controller\n",
            "### CloudFormation controller\n\npython framework/scripts/check-deploy-context.py --environment <environment> --alias <alias>\n",
            1,
        ),
        text.replace(
            "### CloudFormation\n",
            "### CloudFormation\n\npython framework/scripts/sync-model.py --write --service <service-id>\n",
            1,
        ),
        text.replace(
            "python framework/scripts/blueprint-loop.py --mode task --task-file tasks/<task-name>.md",
            "Omit final validation",
            1,
        ),
    ]
    for index, regression in enumerate(regressions, 1):
        assert regression != text
        try:
            validate(regression)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"Update prompt regression {index} was accepted")


def check_design_handoff_prompt() -> None:
    validator = MODULE.Validator(SCRIPT.parents[2])
    validator.check_framework_design_handoff()
    assert not validator.errors, validator.errors
    prompt = (
        SCRIPT.parents[2] / "framework" / "prompts" / "chatbot" / "service-design.md"
    ).read_text(encoding="utf-8")
    assert "AWS::<Service>::<Resource>" in prompt
    assert "VPC-specific" not in prompt
    assert "Management owner" not in prompt
    for required in (
        "Do not persist reference-derived generated ARNs as concrete values in Model authority or `observed.*`",
        "Generated Markdown/JSON Views may persist ARNs resolved from formal Model references",
        "Their presence alone is not a storage-rule violation",
        "Do not display or save passwords, secrets, tokens, or credentials",
    ):
        assert required in prompt
        with patch.object(
            framework_contracts, "input_text", return_value=prompt.replace(required, "")
        ):
            invalid = MODULE.Validator(SCRIPT.parents[2])
            invalid.check_framework_design_handoff()
        assert invalid.errors, required


def _check_task_transition_routes(text, entrypoints):
    sections = _imports_utils_markdown_format.markdown_sections(text)
    common = {
        "selection-and-publication": (
            "publication lock",
            "per-service rollback",
            "stop all saves",
            "without automatic retry",
            "even for unchanged outputs",
            "selected contract",
        ),
        "workflow-selection": (
            "IaC-only work loads implement",
            "Model design changes cannot be performed by implement",
        ),
        "task-registration": (
            "first repository change",
            "Preserve other contracts",
            "No globs, directories or other Task contracts",
            "--source <external-contract-file>",
        ),
        "common-transitions": (
            "successful final validation",
            "all Requirement ID Acceptance checks",
            "--complete",
            "--suspend-reason",
            "--resume",
            "only the explicitly selected Task",
            "Staged status changes apply only to the snapshot",
            "do not repair unrelated failures",
            "While suspended, do not run generation, deploy or loops",
        ),
        "conditional-transitions": ("If applicability is unknown",),
        "task-boundary": (
            "IMPORT acquisition and acquired add/refresh/bind/replace remain exclusive to /import",
            "Do not proceed to IaC, AWS mutation or scenarios",
        ),
        "acceptance-contract": (
            "Only `changed:`, `exists:`, `absent:`",
            "validator-registered `check:`",
        ),
    }
    conditions = {
        "issues-report-publication": (
            "Any Issues report save",
            "read-only Human confirmations",
            "without updating or deleting it",
            "Do not collect/compare HEAD",
            "Acceptance",
            "whole-target Snapshot/Review integrity",
            "no stop, rescan or renewed review",
        ),
        "deploy-task-transitions": (
            "Independent Deploy or CloudFormation completion",
            "worktree_task.py deploy-start",
            "preserve AWS FAIL",
            "Active/uncertain AWS requests retain tracking",
            "No additional Human failure approval or force",
        ),
        "framework-final-candidates": (
            "Framework-only governance/catalog-maintenance/migration with `framework` Validation scope",
            "invoke finalize while running",
            "required dependency-selected UTs",
            "necessary IT",
            "no Consumer service tuple",
        ),
        "human-approved-validation-failures": (
            "Human-approved concrete validation failures for isolated Git integration",
            "--human-approved-validation-failure",
            "Keep `suspend`",
            "do not use `--complete`",
            "All requested work/inputs must otherwise be finished",
            "Git safety blocks and AWS permission boundaries still stop",
        ),
        "dedicated-import-boundary": (
            "IMPORT acquisition/publication/completion",
            "replaces the design validation/completion rules below",
            "issues runs only when explicitly requested",
        ),
        "self-recovery": (
            "Operation/check failure, retry or resume",
            "--check-resume-scope",
            "never discard Human or other Task changes",
            "all stopping causes were the LLM's own safely repairable operation errors",
        ),
        "retry-and-stop": (
            "Operation/check failure, retry or resume",
            "limited to 3 iterations",
            "same error occurs twice consecutively",
            "Do not suppress failing checks",
        ),
    }
    transition = sections["task-transition"]
    for anchor, required in common.items():
        assert f"](#{anchor})" in transition, anchor
        assert sections[anchor].startswith("## "), anchor
        for literal in required:
            assert literal in sections[anchor], (anchor, literal)
    for anchor, (condition, *required) in conditions.items():
        routing = sections["conditional-transitions"]
        row = next(line for line in routing.splitlines() if condition in line)
        assert f"](#{anchor})" in row, (condition, anchor)
        for literal in required:
            assert literal in sections[anchor], (anchor, literal)

    # Each real entrypoint reaches common rules; conditional reads are selected per route.
    routes = {
        "ordinary": (".agents/skills/worktree/SKILL.md", "read-before-execution", ()),
        "model": (
            "framework/prompts/codex/05_update.md",
            "common-update-authority",
            (),
        ),
        "issues": (
            ".agents/skills/issues/SKILL.md",
            "",
            ("issues-report-publication",),
        ),
        "deploy": (
            ".agents/skills/deploy/SKILL.md",
            "common-entry",
            ("deploy-task-transitions",),
        ),
        "import": (
            "framework/prompts/codex/08_import.md",
            "read-first",
            ("dedicated-import-boundary",),
        ),
        "recovery": (
            ".agents/skills/worktree/SKILL.md",
            "read-before-execution",
            ("self-recovery", "retry-and-stop"),
        ),
    }
    for route, (source, read_section, extra) in routes.items():
        entry = entrypoints[source]
        if read_section:
            entry = _imports_utils_markdown_format.markdown_sections(entry)[
                read_section
            ]
        assert re.search(r"task-contract\.md(?:#task-transition)?\)", entry), route
        if "task-contract.md#task-transition)" in entry:
            assert "including its required common and conditional reads" in entry, route
        reached = set(re.findall(r"task-contract\.md#([a-z-]+)\)", entry))
        if "task-contract.md)" in entry:
            reached.update(sections)
        if "task-transition" in reached:
            reached.update(re.findall(r"\]\(#([a-z-]+)\)", transition))
        for anchor in extra:
            assert f"](#{anchor})" in sections["conditional-transitions"], route
            reached.add(anchor)
        assert set(common) | set(extra) <= reached, route


def check_task_transition_readings():
    root = SCRIPT.parents[2]
    text = (root / "framework/rules/task-contract.md").read_text(encoding="utf-8")
    sources = [
        root / "AGENTS.md",
        root / "README.md",
        *sorted((root / "framework/prompts").rglob("*.md")),
        *sorted((root / "framework/rules").glob("*.md")),
        *sorted((root / ".agents/skills").glob("*/SKILL.md")),
    ]
    entrypoints = {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sources
    }
    for source, entry in entrypoints.items():
        if "task-contract.md#task-transition)" in entry:
            assert "including its required common and conditional reads" in entry, (
                source
            )
    _check_task_transition_routes(text, entrypoints)
    # Losing a formerly nested rule or a condition must fail, not silently shorten Read.
    for required in (
        "[Task registration](#task-registration)",
        "[Common transitions](#common-transitions)",
        "[Conditional transitions](#conditional-transitions)",
        "[Deploy task transitions](#deploy-task-transitions)",
        "--suspend-reason",
        "--human-approved-validation-failure",
        "If applicability is unknown",
        "preserve AWS FAIL",
    ):
        assert required in text
        try:
            _check_task_transition_routes(text.replace(required, ""), entrypoints)
        except (AssertionError, StopIteration):
            pass
        else:
            raise AssertionError(f"Lost Task reading contract was accepted: {required}")


def check_rule_reading_contract() -> None:
    check_task_transition_readings()
    validator = MODULE.Validator(SCRIPT.parents[2])
    validator.check_framework_rule_readings()
    assert not validator.errors, validator.errors
    # Required routes are checked in their execution section, including child rules.

    markdown_prose = _imports_utils_markdown_format.markdown_prose
    markdown_sections = _imports_utils_markdown_format.markdown_sections
    repository = SCRIPT.parents[2]
    sources = [
        repository / "AGENTS.md",
        repository / "README.md",
        *sorted((repository / "framework/prompts").rglob("*.md")),
        *sorted((repository / "framework/rules").glob("*.md")),
        *sorted((repository / ".agents/skills").glob("*/SKILL.md")),
    ]
    for source in sources:
        text = source.read_text(encoding="utf-8")
        prose = "".join(
            re.sub(r"(`+).*?\1", "", line) for _, line in markdown_prose(text)
        )
        for link in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", prose):
            if ":" in link:
                continue
            target, _, anchor = link.partition("#")
            if target and Path(target).suffix != ".md":
                continue
            path = (source.parent / target).resolve() if target else source
            assert path.is_file(), (source, link)
            if anchor:
                assert anchor in markdown_sections(path.read_text(encoding="utf-8")), (
                    source,
                    link,
                )
