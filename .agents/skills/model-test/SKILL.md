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
[Issue gate](../../../framework/rules/issue-gate.md), [Model source authority](../../../framework/rules/model-templates.md),
[Project configuration](../../../framework/rules/project-configuration.md), and
[Validation policy](../../../framework/rules/loop-engineering.md#validation-policy).
Use the [worktree workflow](../worktree/SKILL.md) for repository changes.

Register a `migration` contract listing only this contract and
`tests/<environment>/<alias-or-account-id>/<service>.py`. Include the selected service
in Validation scope and apply its issue gate. For framework implementation tasks,
framework-only governance scope remains available under the existing rules.

Run from repository root with the managed Python launcher:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/model-test.py --environment dev --target cde --service vpc --task-file tasks/<task-name>.md
```

The generator expands templates/parameters/bindings using `model_files` and
`model_templates`, then embeds desired expectations, reference dependencies,
validated AWS Mapping, existing comparison/normalization code and selected read-only
adapters. `observed` only helps identify resources. It validates Python syntax before
atomic publication. It never executes the generated file or contacts AWS. Never
write Model, observed, design, IaC, a common runner, or cases.yaml; never generate
other environments/services automatically. Complete classified local validation.

Report the generated path, Model hash, and unsupported Mapping classifications/reasons.
Permissions Boundary uses a generation-only, SDK-shape-validated projection of the existing IAM get-role/get-user response; the existing AWS comparator is unchanged.
Identifier-only and unavailable properties remain explicit ERROR checks; returning a
lookup ID never proves configuration equality. Missing/ambiguous references and
unsupported expressions also produce ERROR, never guessed values or silent skips.
`GetAtt`/`Sub` resource attribute references support only the confirmed `Arn` identity projection; other attributes are explicit ERROR checks.
The standalone file uses only Python stdlib and AWS CLI; no repository imports are
needed at execution. If copied outside the generated directory layout, logs use the
current working directory's `tests/results/` tree. Expectations stay fixed until regeneration.

Human execution example (do not run this as part of this Skill):

```console
python tests/dev/cde/vpc.py --profile dev-profile
```

The test follows the embedded target's region and configured profile, rejects a
conflicting explicit profile before AWS, verifies STS against `awsExecutionAccountId`
(or `awsAccountId`), and never changes credentials after failure. Every selected
attribute receives OK/NG/ERROR. Structured differences include paths; secrets are
masked. The exact console text is saved under
`tests/results/<environment>/<alias>/<service>-YYYYMMDD-HHMMSS.log` (a microsecond
suffix prevents overwriting a same-second run). Exit codes: 0 all OK; 1 any NG;
2 any ERROR. Audit logs are human execution outputs, not generation/validation
artifacts; keep mock validation logs in temporary directories outside the repository.
