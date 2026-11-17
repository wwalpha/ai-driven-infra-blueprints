---
name: model-test
description: Generate one standalone Python AWS audit test from the current Model for an explicit environment, target alias and service. Generation is offline; humans run the generated test separately.
---

# Model audit test generation

Require all three selectors, for example:

```text
/model-test --environment dev --target cde --service vpc
/model-test --environment dev --target cde --service iam
```

Apply [AGENTS](../../../AGENTS.md), [Task contract](../../../framework/rules/task-contract.md),
[Model source authority](../../../framework/rules/model-templates.md),
[Project configuration](../../../framework/rules/project-configuration.md), and
[Validation policy](../../../framework/rules/loop-engineering.md#validation-policy).
Use the [worktree workflow](../worktree/SKILL.md) for repository changes.

Before running the generation command, complete these steps in order:

1. From the current repository root, run
   `python3 -B framework/scripts/worktree-cli.py create --task-name <task-name>`
   under the [worktree workflow](../worktree/SKILL.md). Confirm that the returned
   `python_setup.status` is `ready`. If setup fails, report the error and retained
   Task/worktree and stop; do not continue generation with ordinary Python.
2. Set the working directory of every subsequent task command to the returned
   `worktree` root: the **managed worktree**, not the normally opened repository root.
   Clear `PYTHONHOME` and `PYTHONPATH` and invoke the absolute `python_setup.interpreter` from the successful Create/Setup JSON directly.
3. Use the returned `task_file` to register a `migration` contract through
   `python_setup.interpreter`, listing only that contract and
   `tests/<environment>/<alias-or-account-id>/<service>.py`. Include the selected
   service in Validation scope. Run contract registration, audit generation and
   Python local validation with the same executable from this Worktree root.
   For framework implementation tasks, framework-only governance scope remains
   available under the existing rules.

Substitute the returned absolute path for `<python_setup.interpreter>`. In PowerShell, invoke the quoted executable with `&`.
The following commands run from the returned `worktree`; replace `<task-file>`
with the exact returned `task_file` and use the requested service selectors:

```console
"<python_setup.interpreter>" -B framework/scripts/task_contract.py --task-file <task-file> --source <external-contract>
"<python_setup.interpreter>" -B framework/scripts/model/cli.py audit --environment dev --target cde --service vpc --task-file <task-file>
```

The generator loads the canonical properties snapshot through `model.sources`,
then embeds desired expectations, reference dependencies,
validated AWS Mapping, existing comparison/normalization code and selected read-only
adapters. `observed` identifies resources and supplies confirmed IDENTIFIER_OUTPUT values for audit comparisons. It validates Python syntax before
atomic publication. It never executes the generated file or contacts AWS. Never
write Model, observed, design, IaC, a common runner, or cases.yaml; never generate
other environments/services automatically. Complete classified local validation.

Report the generated path, Model hash, and unsupported Mapping classifications/reasons.
Permissions Boundary uses a generation-only, SDK-shape-validated projection of the existing IAM get-role/get-user response; the existing AWS comparator is unchanged.
Confirmed identifier outputs are compared with AWS; when AWS returns an identifier and observed is PENDING_DEPLOY, the check is NG. Missing, ambiguous, otherwise unresolved or unavailable identifiers remain explicit ERROR checks. Identifier equality does not prove configuration equality. Missing/ambiguous references and
unsupported expressions also produce ERROR, never guessed values or silent skips.
`GetAtt`/`Sub` resource attribute references support only the confirmed `Arn` identity projection; other attributes are explicit ERROR checks.
The standalone file uses only Python stdlib and AWS CLI; no repository imports are
needed at execution. If copied outside the generated directory layout, logs use the
current working directory's `tests/results/` tree. Expectations stay fixed until regeneration.

Human execution example using `python` in an activated virtual environment,
including PowerShell. The Human runs this command separately from generation.

```console
python tests/dev/cde/vpc.py --profile dev-profile
```

The test follows the embedded target's region and configured profile, rejects a
conflicting explicit profile before AWS, verifies STS against `awsExecutionAccountId`
(or `awsAccountId`), and never changes credentials after failure. Every selected
attribute receives OK/NG/ERROR. Structured differences include paths; secrets are
masked. The exact console text is saved under
`tests/results/<environment>/<alias>/<service>.log`, replacing the previous log for that service. Exit codes: 0 all OK; 1 any NG;
2 any ERROR. Audit logs are human execution outputs, not generation/validation
artifacts; keep mock validation logs in temporary directories outside the repository.
