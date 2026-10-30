"""Prompt and rule reading contracts."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from unittest.mock import patch

import utils.markdown_format as _imports_utils_markdown_format
from support.validator import MODULE, SCRIPT
from validation import framework_contracts


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
        "together in one response",
        "do not end the report at the first deficiency",
        "If deficiencies exist, do not implement",
        "without requiring additional approval",
        "Do not automatically expand change scope or all-service validation",
        "Japanese display Comments",
        "do not automatically translate/replace invalid values",
        "Do not repair designs/models/IaC here or automatically create/execute another task",
    ):
        assert required in preflight, required
    reading = text.split("## Read before changing files\n", 1)[1].split("\n## ", 1)[0]
    for required in (
        "Implement design inputs are only authoritative model properties",
        "Do not require the Agent to compare properties and generated Markdown twice in advance",
        "Do not read generated `docs/designs/<environment>/<target-directory>/*.md` bodies (including `cloudformation-stacks.md`) at Implement start, IaC generation, or reference resolution",
        "Retain Markdown/JSON generation/saving and local loop consistency validation as before",
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
        "saved Markdown Resource links",
        "common parser/resolver",
        "referenced Model groups",
        "parentReference",
        "Resolve through producer Model saved anchors, never names, cfn-logicalId or generated Markdown",
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
    comparison = text.split(
        "## Compare existing IaC before creating the contract\n", 1
    )[1].split("\n## ", 1)[0]
    assert (
        "If all portions match" in comparison
        and "does not create a new active contract" in comparison
    )
    assert "create it first under Create active task contract" not in reading

    root = SCRIPT.parents[2]
    transition = (root / "framework/rules/task-contract.md").read_text(encoding="utf-8")
    routing = transition.split("### Workflow selection\n", 1)[1].split("\n### ", 1)[0]
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
        "create, setup (when needed), normal Deploy checkpoint, finalize and cleanup",
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
        "Finalize/cleanup guards and the Python helper remain unchanged",
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
        "saved Markdown Resource links",
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
    deploy = sections["Preflight and deploy"]
    dependency = engine(deploy, "CloudFormation read-only dependency check")
    for token in (
        "--read-only",
        "describe-stacks",
        "list-exports",
        "ExportingStackId",
        "NOT_STARTED",
        "do not run it in ordinary CloudFormation update",
    ):
        assert token in dependency, token
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


def check_update_flow_prompt() -> None:
    text = (SCRIPT.parents[2] / "framework/prompts/codex/05_update.md").read_text(
        encoding="utf-8"
    )

    validate = _callback_check_update_flow_prompt_validate

    validate(text)
    # Prohibitions alone must not hide contradictory executable/read instructions.
    regressions = [
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


def check_rule_reading_contract() -> None:
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
