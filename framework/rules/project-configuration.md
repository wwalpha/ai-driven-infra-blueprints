# Project Configuration Rules

## Topology

- After initialization, the machine-readable source of truth is `project.json`. The target directory is the alias if present, otherwise `awsAccountId`.

- Do not include `project.json` in the uninitialized distribution state.
- `framework/prompts/codex/01_initialize.md` may be used regardless of whether `docs/system-overview.md` has been created or filled in. Codex asks for necessary confirmed values and creates `project.json` and target paths.
- Initialization registers only targets whose required values are currently confirmed. Do not register not-yet-created targets or targets with unconfirmed required values using guesses or placeholders; add them after confirmation via migration using `framework/prompts/codex/02_add-target.md`.
- Do not fix the number or names of environments or the number of AWS accounts.
- Do not assign an alias when an environment has only one target. If there are multiple targets, human-confirmed aliases are mandatory for all targets; the same AWS account ID may be assigned to multiple aliases. Aliases must be unique lower-kebab-case within the same environment; values consisting only of 12 digits are prohibited.
- The `IaC engine` for 1 environment/AWS account must be exactly one of `cloudformation` or `terraform`, consistent across aliases with the same AWS account ID.
- Do not require the human to directly edit `project.json`. Codex performs topology changes in explicit initialization or migration tasks.
- Each `project.json` target may have an optional `suffix`. It must be a confirmed non-empty lower-kebab-case string; different values may be configured per environment/alias. Use the selected target's value only when the naming pattern contains `{{suffix}}`; do not automatically append it to patterns without it. It may be confirmed during initialization/target addition; adding/changing/removing it on an existing target requires a human-explicit `migration` task. Do not automatically change existing names.

## Credentials and account

- Each `project.json` target may have an optional `awsProfile`. When configured, use that profile for the target's AWS CLI/SDK and Terraform provider/AWS backend. When unset, retain the explicit profile, or the default credential chain if that is also absent. Reject explicit profiles differing from the configured value before execution; do not fall back to another profile after authentication failure.

- `awsProfile` must be a confirmed non-empty string; leading/trailing whitespace, newlines, NUL, and `UNSET` are prohibited. If unspecified, omit the key itself; do not save credential values. Profiles may be configured per target and do not change alias/account/region/IaC engine constraints.
- `awsAccountId` is the authority for explicit account ID settings/name components when creating resources and for target identity. Target directories, selectors, and task scope continue to use aliases, or `awsAccountId` when no alias exists.
- Values in policies that match actual owner/source accounts of resources created in the same target must be distinguished from name/ID settings at resource creation and use `awsExecutionAccountId` (`awsAccountId` when unset). Both `aws:SourceAccount` and the account portion of `aws:SourceArn` in VPC Flow Logs trust policies apply. Match accounts in permission policy `Resource` ARNs and `Principal` to the reference target's actual owning account as well. Retain human-explicit cross-account references; do not bulk-replace accounts in policies.
- Each target may have an optional `awsExecutionAccountId`. If specified, it must be a string of 12 ASCII digits; otherwise omit the key and use `awsAccountId` as the execution account. Use the execution account for caller account validation in AWS CLI/SDK, CloudFormation, Terraform, existing-resource retrieval, observed value retrieval, model-to-AWS comparison, and scenarios; stop before AWS operations on mismatch or authentication failure. Setting IDs alone does not switch credentials: use the existing `awsProfile` / explicit profile / default credential chain, and do not automatically add AssumeRole or fallback to another account.
- AWS API implicit account context/owner validation and CloudFormation `AWS::AccountId` use the execution account. Do not rewrite explicit account properties or cross-account references in the design. If names, etc. require `awsAccountId` and the two IDs differ, pass it as an independent explicit parameter/setting rather than replacing it with `AWS::AccountId`. Ordinary resource membership is determined by the actual AWS execution destination and cannot be changed merely by setting `awsAccountId`.
- Also keep IaC engines consistent for targets with the same environment/execution account. Confirm the optional execution account ID at initialization/target addition; Codex adds/changes/removes it on existing targets only in human-explicit `migration` tasks. Do not implicitly change `awsAccountId`, aliases, paths, designs, or IaC; perform local validation without AWS connections.
- Local loops must reject paths/IaC implementations inconsistent with `project.json`.
