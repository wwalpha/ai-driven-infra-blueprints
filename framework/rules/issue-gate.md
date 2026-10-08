# Issue Gate Rules

## Unresolved issue gate

- The issue list is `issues/<environment>/<target-directory>/issues.md`. The target directory is the project.json alias, or the AWS account ID when no alias exists. A missing or empty file means no unresolved issues.
- Every numbered issue (`1. ...`) remaining in the list is unresolved. Remove only issues successfully repaired and revalidated within the explicit repair scope. Retain resolution history in Git; deletion/rewriting of the list alone does not mean repaired. If there are 0 issues, `未解決issueなし` may be written.
- Identify services by `### <service-id>`, `<!-- issue-service: <service-id> -->`, or an evidence link to the same target's model properties/detailed design Markdown. Do not infer them from AWS service display names alone. Issues with unidentified ownership or invalid lists without numbered issues/a zero-issue declaration stop the entire target.
- While unresolved issues exist for the target environment/target/service, do not start or continue other tasks such as design consultation, design saving, implement, deploy/apply, scenarios, or target migration. Do not stop other environments, targets, or services. When changing, implementing, or deploying multiple services, explicitly list every related service in Validation scope; stop the task if even one is blocked. Do not confuse overall validation with task targets.
- Permit only read-only issue investigation, issue repair explicitly requested by the human, and the save-only tasks below. Do not create new task types; retain existing task boundaries such as design/infrastructure and AWS execution authorization. Framework-only governance/catalog-maintenance are not service-targeted tasks, so consumer issues do not stop them.
- Issue investigation/saving and desired environment comparison/diff saving are `migration` tasks; only the explicit service Validation scope targets' `issues/<environment>/<target-directory>/issues.md` / `iac-issues.md` / `iac-issues.state.json` / `diff.md` and this task's `tasks/<task-name>.md` are Allowed paths and change targets. Save-only tasks meeting these conditions do not apply existing-issue stop decisions and continue investigation, comparison, AI classification, saving, and local validation. Items in iac-issues.md (non-blocking model → IaC comparison results) and diff.md (environment comparison) are not counted as unresolved issues and do not require repairing existing issues.md or adding Issue remediation. Retain issue gates for ordinary migration, design/model/IaC changes, model saving, and AWS mutation. Actual validation errors detected during investigation must still be reported as FAIL.
## Issue remediation

- Record the target issue, cause, and repair scope in the repair task's Goal and Required changes. Place the following section in the same active contract. Entries must be subsets of the explicit Validation scope only; repair exceptions using `all` / `framework` are prohibited. The exception applies only to that service's issue repair and revalidation; do not mix in feature additions, ordinary design, other issue repairs, etc. Do not automatically resume other suspended tasks after the repair task completes.

```md
## Issue remediation

- `dev/cde/ec2`
```

## Check timing

- Except for save-only tasks, check the latest issue list when targets are determined, before task start, on resume, before design saving, and before AWS mutation. Before starting, run the following check. This check does not use repair exceptions from old active contracts. For repair requests, confirm the stop reason and create a repair contract limited to the human's requested scope, then handle it with the existing workflow. An existing active contract does not lift issue stops for chat-only design consultation.

```text
python framework/scripts/issue_gate.py --environment <environment> --target-directory <alias-or-account-id> --service <service-id>
```

Repeat `--service` for every related service. The task validator, `sync-model.py --write`, and deploy context use the common issue decision. AWS read-only context may be used for issue investigation but does not authorize continuing ordinary tasks. In addition to existing preflight, rerun the same issue check immediately before deploy/apply execution. Add `--task` to that immediately-before-execution check and use Issue remediation from the same active contract. Ordinary tasks recheck without repair exceptions.
