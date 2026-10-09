"""Prompt and rule reading contracts."""

from __future__ import annotations
import re
import shlex
from test_support.validator import MODULE, SCRIPT, project, write, load


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
    text = (SCRIPT.parents[2] / "framework/prompts/codex/03_implement.md").read_text(encoding="utf-8")
    preflight = text.split("## Read-only implementation preflight\n", 1)[1].split("\n## ", 1)[0]
    assert text.index("## Read-only implementation preflight") < text.index("## Create active task contract") < text.index("## Implement and validate")
    for required in (
        "before active contract creation or IaC generation", "Do not execute AWS APIs, IaC generation, or deploy",
        "model_design.validate_required_properties", "DesignSchemaCatalog.literal_errors",
        "necessary dependency properties", "authoritative stack registration", "template/parameter mappings", "dependency cycle",
        "対象file | resource（logical ID）/stack | property/parameter | 不足・違反理由",
        "together in one response", "do not end the report at the first deficiency", "If deficiencies exist, do not implement",
        "without requiring additional approval", "Do not automatically expand change scope or all-service validation",
        "Japanese display Comments", "do not automatically translate/replace invalid values", "Do not repair designs/models/IaC here or automatically create/execute another task",
    ):
        assert required in preflight, required
    reading = text.split("## Read before changing files\n", 1)[1].split("\n## ", 1)[0]
    for required in (
        "Implement design inputs are only authoritative model properties", "Do not require the Agent to compare properties and generated Markdown twice in advance",
        "Do not read generated `docs/designs/<environment>/<target-directory>/*.md` bodies (including `cloudformation-stacks.md`) at Implement start, IaC generation, or reference resolution", "Retain Markdown/JSON generation/saving and local loop consistency validation as before",
        "treat them as scope selectors", "Without reading bodies", "path/file stem", "If corresponding models cannot be uniquely identified, stop without guessing",
        "python framework/scripts/model_files.py model/<environment>/<target-directory>/<service>.properties --resource <resource-selector>",
        "resource number", "Selectors require exact matches for resource number (such as `001`), cfn-logicalId, legacy logical ID, or anchor", "single files and split entry indexes", "parents, children, and siblings in the same group required by existing specifications, and service metadata/notes",
        "Service-wide scope may use entire service properties", "対象accountの承認済み設計すべて", "Reading all target Markdown as fallback is prohibited",
        "desired values, resources, references, stack assignments, or human decisions", "stop because a design task is required",
    ):
        assert required in reading, required
    assert not any(line.startswith("5. Target `docs/designs/") for line in reading.splitlines())
    assert "generated designs" not in preflight and "model generation equality validation" not in preflight
    units = text.split("## Resolve implementation units\n", 1)[1].split("\n## ", 1)[0]
    for required in ("read only the target's authoritative `model/<environment>/<target-directory>/cloudformation-stacks.properties`", "desired.stack.*.name", "`.template`", "`.parameters`", "`.deployOrder`",
                     "desired.deployment.maxConcurrentStacks", "effective MaxConcurrentStacks remains 1 under the existing contract", "do not read it as Implement input"):
        assert required in units, required
    implementation = text.split("## Implement and validate\n", 1)[1].split("\n## ", 1)[0]
    for required in ("Use only authoritative model properties", "`desired.row.*`", "`.document`", "desired.resource.*.anchor", "desired.resource.*.logicalId",
                     "producer model properties", "parentReference", "do not read generated Markdown bodies", "Do not hardcode link display text `PENDING_DEPLOY` or physical IDs into IaC"):
        assert required in implementation, required
    finish = text.split("## Verify and finish\n", 1)[1]
    for required in ("blueprint-loop.py --mode task", "read-only `sync-model.py`", "mismatches are FAIL", "check_design_tables",
                     "check_design_links", "check_stack_designs", "do not omit/weaken these validations"):
        assert required in finish and required not in preflight, required


def check_update_flow_prompt() -> None:
    text = (SCRIPT.parents[2] / "framework/prompts/codex/05_update.md").read_text(encoding="utf-8")

    def validate(prompt):
        # Check instruction/engine boundaries and executable examples, not a full prose snapshot.
        sections = dict(re.findall(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", prompt, re.M | re.S))

        def engine(body, heading):
            return body.split(f"### {heading}\n", 1)[1].split("\n### ", 1)[0]

        def commands(body):
            return [[token.strip("[]") for token in shlex.split(line)] for line in re.findall(
                r"(?:^|`)(python\s+framework/scripts/[^`\n]+)", body, re.M)]

        reading = sections["Read before changing files"]
        for token in ("authoritative model properties", "desired.row.*.document", "Do not read generated Markdown bodies or generated JSON artifacts as input",
                      "--resource <resource-selector>", "parentReference", "path/file stem", "required parts"):
            assert token in reading, token
        instructions = [line for line in reading.splitlines() if re.match(r"\d+\. ", line)]
        assert instructions and not any(re.search(
            r"docs/designs/|cloudformation-stacks\.md|0[34]_(?:implement|deploy)\.md", line
        ) for line in instructions), "generated artifacts/full prompts returned to the input list"
        scope = sections["Resolve target and scope from repository state"]
        assert "only from authoritative `cloudformation-stacks.properties`" in scope
        assert "cloudformation-stacks.md" not in scope, "duplicate stack scope input"
        for token in ("desired.stack.*.name", ".template", ".parameters", ".deployOrder",
                      "desired.deployment.maxConcurrentStacks", "workspace", "backend", "variable input"):
            assert token in scope, token
        issue = commands(sections["Unresolved issue gate"])
        assert len(issue) == 1 and issue[0][1].endswith("/issue_gate.py")
        assert issue[0].count("--service") == 2, "repeatable services must share one process example"
        assert "--task" in sections["Unresolved issue gate"]

        deploy = sections["Preflight and deploy"]
        dependency = engine(deploy, "CloudFormation read-only dependency check")
        for token in ("--read-only", "describe-stacks", "list-exports", "ExportingStackId",
                      "NOT_STARTED", "--pause-after-group", "do not run it in ordinary CloudFormation update"):
            assert token in dependency, token
        cfn = engine(deploy, "CloudFormation controller")
        cfn_commands = commands(cfn)
        assert len(cfn_commands) == 1 and cfn_commands[0][1].endswith("/cloudformation-deploy.py")
        for option in ("--environment", "--alias", "--stack", "--state", "--profile"):
            assert option in cfn_commands[0], option
        for token in ("responsible for final preflight", "account", "region", "issue gate", "immutable input",
                      "cfn-lint", "validate-template", "MaxConcurrentStacks", "COMPLETE", "--resume"):
            assert token in cfn, token
        terraform = engine(deploy, "Terraform preflight and apply")
        tf_commands = commands(terraform)
        assert len(tf_commands) == 2 and all(c[1].endswith("/check-deploy-context.py") for c in tf_commands)
        assert "--alias" in tf_commands[0] and "--aws-account-id" in tf_commands[1]
        assert commands(deploy) == cfn_commands + tf_commands, "standalone normal CFn preflight was added"
        for token in ("terraform fmt -check", "terraform validate", "terraform plan -out=",
                      "terraform apply", "saved plan binary", "partial apply", "AWS_PROFILE"):
            assert token in terraform, token

        post = sections["Post-deployment model sync"]
        cfn_post = engine(post, "CloudFormation")
        assert not commands(cfn_post), "Agent must not run a second CFn observed/sync process"
        for token in ("owned by the controller", "cloudformation_observed.py", "IDENTIFIER_OUTPUT",
                      "PhysicalResourceId", "all references", "must not rerun", "AMBIGUOUS_OBSERVED_MAPPING"):
            assert token in cfn_post, token
        assert all("must not rerun" in line for line in cfn_post.splitlines() if "--write" in line)
        tf_post = engine(post, "Terraform")
        for token in ("Terraform output", "state", "non-sensitive", "IDENTIFIER_OUTPUT", "all references",
                      "PENDING_DEPLOY", "sync-model.py --write"):
            assert token in tf_post, token
        approval = sections["Confirm unapproved delete/replacement"]
        for token in ("unexecuted", "wait for human confirmation", "--approve-change-set", "CREATE_COMPLETE/AVAILABLE",
                      "fingerprint", "Do not execute with only partial approval", "Do not reuse prior approval"):
            assert token in approval, token
        finish = sections["Verify and finish"]
        loop = commands(finish)
        assert len(loop) == 1 and loop[0][1].endswith("/blueprint-loop.py")
        assert loop[0][loop[0].index("--mode") + 1] == "task"
        assert "--task-file" in loop[0] and "--all" not in loop[0]
        for token in ("Validation scope", "Acceptance checks", "read-only", "mismatches are FAIL",
                      "validation cache", "service parallelism", "do not add all framework regression"):
            assert token in finish, token

    validate(text)
    # Prohibitions alone must not hide contradictory executable/read instructions.
    regressions = [
        text.replace("6. Authoritative Design scope", "6. Target `docs/designs/<environment>/<target-directory>/*.md` and related JSON artifacts\n7. Authoritative Design scope", 1),
        text.replace("only from authoritative `cloudformation-stacks.properties`", "from authoritative `cloudformation-stacks.properties` and generated `cloudformation-stacks.md`", 1),
        text.replace("### CloudFormation controller\n", "### CloudFormation controller\n\npython framework/scripts/check-deploy-context.py --environment <environment> --alias <alias>\n", 1),
        text.replace("### CloudFormation\n", "### CloudFormation\n\npython framework/scripts/sync-model.py --write --service <service-id>\n", 1),
        text.replace("python framework/scripts/blueprint-loop.py --mode task --task-file tasks/<task-name>.md", "Omit final validation", 1),
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
    with project() as root:
        path = root / "framework/prompts/chatbot/service-design.md"
        path.parent.mkdir(parents=True)
        for original, replacement, expected in (
            ("## Naming rule preflight (design start gate)", "## Removed gate", "before design questions"),
            ("check-design-naming.py --resource-type", "removed-preflight", "executable naming preflight"),
            ("Before design contract registration, execute `check-design-naming.py`", "removed-handoff", "before task registration"),
        ):
            assert original in prompt
            mutated = prompt.replace(original, replacement)
            assert mutated != prompt
            write(path, mutated)
            validator = MODULE.Validator(root)
            validator.check_framework_design_handoff()
            assert any(expected in error for error in validator.errors), validator.errors


def check_rule_reading_contract() -> None:
    validator = MODULE.Validator(SCRIPT.parents[2])
    validator.check_framework_rule_readings()
    assert not validator.errors, validator.errors
    with project() as root:
        write(root / "README.md", "## Task transition\n[Task](framework/rules/task-contract.md#task-transition)\n")
        task_rule = root / "framework/rules/task-contract.md"
        task_rule.parent.mkdir(parents=True)
        write(task_rule, "## Task transition\nfixture\n")
        rule = root / "framework/rules/fixture.md"
        rule.parent.mkdir(parents=True, exist_ok=True)
        write(rule, "## Present\nrequired rule\n")
        agents = root / "AGENTS.md"
        write(agents, "[rule](framework/rules/fixture.md#missing)\n")
        validator = MODULE.Validator(root)
        validator.check_framework_rule_readings()
        assert len(validator.errors) == 1 and "missing rule section" in validator.errors[0], validator.errors
        write(agents, "[rule](framework/rules/fixture.md#present)\n")
        validator = MODULE.Validator(root)
        validator.check_framework_rule_readings()
        assert not validator.errors, validator.errors

    # Required routes are checked in their execution section, including child rules.
    from deploy_preparation import markdown_sections, rule_readings, markdown_prose
    from pathlib import Path
    repository = SCRIPT.parents[2]
    sources = [repository / "AGENTS.md", repository / "README.md",
               *sorted((repository / "framework/prompts").rglob("*.md")),
               *sorted((repository / "framework/rules").glob("*.md")),
               *sorted((repository / ".agents/skills").glob("*/SKILL.md"))]
    for source in sources:
        text = source.read_text(encoding="utf-8")
        prose = "".join(re.sub(r"(`+).*?\1", "", line) for _, line in markdown_prose(text))
        for link in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", prose):
            if ":" in link:
                continue
            target, _, anchor = link.partition("#")
            if target and Path(target).suffix != ".md":
                continue
            path = (source.parent / target).resolve() if target else source
            assert path.is_file(), (source, link)
            if anchor:
                assert anchor in markdown_sections(path.read_text(encoding="utf-8")), (source, link)
    for relative, heading, link in (
        ("README.md", "task-transition", "framework/rules/task-contract.md#task-transition"),
        ("framework/rules/loop-engineering.md", "local-loop", "task-contract.md#task-transition"),
        (".agents/skills/worktree/SKILL.md", "read-before-execution", "../../../framework/rules/task-contract.md#task-transition"),
    ):
        with project() as root:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            original = (repository / relative).read_text(encoding="utf-8")
            # Copy only authorities required by this entry, never live contracts/state.
            pending = list(rule_readings(repository, repository / relative, original))
            copied = set()
            while pending:
                source = pending.pop()
                if source in copied:
                    continue
                copied.add(source)
                body = source.read_text(encoding="utf-8")
                path = root / source.relative_to(repository)
                path.parent.mkdir(parents=True, exist_ok=True)
                write(path, body)
                pending.extend(rule_readings(repository, source, body))
            if relative != "README.md":
                write(root / "README.md", "## Task transition\n[Task](framework/rules/task-contract.md#task-transition)\n")
            write(root / "AGENTS.md", "fixture\n")
            write(destination, original)
            validator = MODULE.Validator(root)
            validator.check_framework_rule_readings()
            assert not validator.errors, validator.errors
            # A link outside the mandatory section does not repair its removal.
            assert link in markdown_sections(original)[heading]
            write(destination, original.replace(link, "https://example.invalid/rule", 1) + f"\n## Background\n[Task]({link})\n")
            validator = MODULE.Validator(root)
            validator.check_framework_rule_readings()
            assert any("mandatory rule readings missing" in error for error in validator.errors), validator.errors

    # Removing an authority's stop condition must fail even with valid links/headings.
    with project() as root:
        rules = root / "framework/rules"
        rules.mkdir(parents=True)
        contract = (repository / "framework/rules/task-contract.md").read_text(encoding="utf-8")
        loop = (repository / "framework/rules/loop-engineering.md").read_text(encoding="utf-8")
        write(rules / "task-contract.md", contract)
        write(rules / "loop-engineering.md", loop)
        validator = MODULE.Validator(root)
        validator.check_framework_task_completion_contract()
        assert not validator.errors, validator.errors
        for boundary in ("Never forcibly steal", "20 waiting attempts", "Deferred path-based Acceptance"):
            assert boundary in contract
            write(rules / "task-contract.md", contract.replace(boundary, "REMOVED", 1))
            validator = MODULE.Validator(root)
            validator.check_framework_task_completion_contract()
            assert any("safety boundary missing" in error for error in validator.errors), validator.errors

    loop = load("blueprint-loop")
    all_checks = sorted((SCRIPT.parent).glob("*.checks.py"))
    for path in ("framework/scripts/deploy_preparation.py", "framework/scripts/validation_cache.py",
                 "framework/scripts/validation/framework_contracts.py", "README.md",
                 ".agents/skills/worktree/SKILL.md", "framework/rules/loop-engineering.md"):
        selected, reason = loop.select_checks(repository, {path}, True)
        assert selected == all_checks, (path, selected, reason)
