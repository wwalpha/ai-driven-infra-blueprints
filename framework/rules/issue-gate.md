# Issue Gate Rules

## Dedicated import boundary

For `/import`, [IMPORT configuration authority](model-information.md#import-configuration-authority)
replaces the design validation/completion rules below: source and display transactions
are separate, and issues runs only when explicitly requested. Other workflows retain these rules.


## Unresolved issue gate

- Every numbered issue (such as `1.`) in `issues/<environment>/<alias-or-account>/issues.md`
  is unresolved. A missing or empty file means there are no unresolved issues. Remove an
  item only when the Human explicitly requests its repair and revalidation provides
  evidence of resolution. Keep history in Git; deleting or rewriting the inventory does
  not resolve issues. When the count is zero, the report may state `未解決issueなし`.
- Identify the owning service from `### service-id`, an `issue-service` comment, or a
  link to Model properties or a detailed design for the same target. Do not infer it
  from an AWS display name. Unknown ownership or a malformed inventory with neither
  numbered issues nor a zero-issue declaration stops work for the entire target.
- An unresolved issue for an environment/target/service blocks the start or continuation
  of ordinary consultation, design/save, implement, deploy/apply, scenario and migration
  work. It does not block other targets or services. Explicitly list every affected
  service in Validation scope and stop if any is blocked. Distinguish the overall
  validation scope from the targets actually changed. Framework-only governance and
  catalog-maintenance tasks are not service tasks.
- Read-only investigation, Human-requested issue remediation, the Model deletion
  exception and the save-only exception are permitted. Retain the existing Task type,
  design boundaries and AWS permissions.
- Issue investigation and saving use `migration`. A save-only task whose Allowed paths
  and changes contain only the explicitly service-scoped `issues.md`/`iac-issues.md` and
  its own Task is not stopped by existing issues and needs no independent worktree.
  Report actual validation ERRORs as FAIL. `iac-issues.md` contains nonblocking
  Model-to-IaC comparisons, does not count as unresolved issues and needs no Issue
  remediation declaration. Do not save or delete IaC state. Other migration, Model,
  IaC, save and AWS mutation work retains the ordinary gate.
- Standalone `import-retarget` retains the ordinary pre-task, resume, Model save
  and final gates for all producer and consumer services. It does not inherit the
  deletion exception and must not change issues or mark them resolved.

## Model view generation

Model → Markdown/JSON generation does not use unresolved Issues as a start or save
condition, regardless of Issue count, classification or service ownership. This applies
to `sync-model.py --write`, `sync_runtime._sync()` and integrated validator generation.
Attempt all selected services through the existing candidate validation/publication APIs;
save valid services, restore failed services' saved artifacts, and report generation
failures separately from reference NOT_RUN. Either failure or NOT_RUN prevents a complete
generation PASS. Keep Import Guard, Task/Allowed paths/Validation scope, dependency and
Model checks, input snapshot comparison, publication lock, atomicity and rollback.
Common integrity violations still stop the whole publication. Never edit or resolve
`issues.md` as part of generation.

The integrated validator evaluates the Task Issue Gate after generation/publication,
independently of the generation result. Successful publications remain saved even when
Issues fail the Task. This exception grants no Model/IaC change authority and does not
waive pre-task/resume, Task completion/integration, remediation or deploy/AWS mutation gates.

## Issue and notice classification

Ordinary issue reading, Human review materials and Issue Gate use the same Markdown
classification. Matching `issues-notices:<scope>:start/end` ranges and the
`警告（非ブロッキング）` (nonblocking warnings) and `参照警告（非ブロッキング）`
(nonblocking reference warnings) sections are nonblocking. Headings, numbers and
markers inside code fences do not determine classification. Keep `### service` headings
and numbered items inside warning sections as warning content. Continue recognizing
legacy issues without markers outside warning sections.

To resume ordinary issues after a warning, use an explicit section boundary at the
same or a higher heading level, or a service section with an `issue-service` or
`issue-id` marker. Producers must explicitly identify the service and Issue ID and
keep ordinary issues out of warnings. Unmatched or nested scope markers, Issue markers
inside an explicit notice scope, and an Issue ID inside a warning without a service
boundary are ambiguous input: stop reading and saving. Before adding markers, confirm
the Human's intended ownership and boundaries; do not infer ordinary issues.

When saving, reuse the existing ordering: ordinary issues, information, unverified
scope, processing errors, warnings, then reference warnings. Preserve Issue IDs,
ownership and warning content across saving and reloading.

## Reference-only Issues

Apply [Reference diagnostics](model-information.md#reference-diagnostics) to all Model
operations. IaC comparisons unable to resolve a Model
report uncompared plus warnings, not match/verified or category error.

## Model deletion exception

For an explicit Human Model deletion request, do not stop at the ordinary pre-contract
issue check. First register and validate the design /update `import-delete` contract
with exact normalized deletion sources, forbidden AWS API execution and deploy/apply,
and explicit service Validation scope containing every source and repair consumer. Keep the same Task selector and managed
worktree ownership. Then use the common task-aware issue decision (`require_no_issues`,
or `issue_gate.py --task`) on its declared scope, including resume, source saves,
and final/integration validation. View generation follows Model view generation above.
Missing/invalid contracts, unknown operations,
scope mismatches and mismatched managed Tasks fail closed. The ordinary CLI without
`--task` retains its pre-contract gate.

Only the existing-issue stop decision for registered deletion source services is waived.
Other declared services retain their ordinary gate; do not expand the exception to
consumer-only repairs, unrelated services or other operation types. Do not require Issue remediation, delete issues.md or mark existing issues fixed.
Keep incoming-reference diagnostics and final verify_model_operation checks. Reference
analysis reports ambiguity/type mismatch/surviving links as warnings. The final candidate
guard rejects invalid surviving Resource references; intermediate leaves remain separate. Retain parse/Model/Bindings errors,
operation source existence/fixed identity, path/scope/worktree guards, AWS/deploy
prohibitions and non-reference generation/validation errors. `import-merge`, ordinary
updates, IaC/deploy and later ordinary Tasks retain the issue gate; completed deletion
contracts do not grant the exception.

## Issue remediation

- Record the target issue, cause, and repair scope in the repair task's Goal and Required changes. Place the following section in the same active contract. Entries must be subsets of the explicit Validation scope only; repair exceptions using `all` / `framework` are prohibited. The exception applies only to that service's issue repair and revalidation; do not mix in feature additions, ordinary design, other issue repairs, etc. Do not automatically resume other suspended tasks after the repair task completes. The explicitly preauthorized CloudFormation external-repair request permits only the supervising LLM to resume its matching original deploy Task through the existing helper; it does not waive Issue Gate, extend scope, or authorize unrelated phases.

```md
## Issue remediation

- `dev/cde/ec2`
```

## Check timing

Except for the explicit save-only and Model deletion exceptions, check the latest
inventory when the target is determined, before starting, on resume, before saving
Model/IaC changes and immediately before AWS mutation. Model view generation alone is
independent of this gate; integrated validation applies it to the Task after generation.
Before starting other work, run the following
command; repeat `--service` within the same process for multiple services. A previous
Task's remediation exception does not authorize ordinary consultation or execution.
For a repair request, confirm the reason work stopped, register a contract limited to
the Human-specified scope and proceed through the existing remediation workflow.

```text
python framework/scripts/issue_gate.py --environment <environment> --target-directory <alias-or-account-id> --service <service-id>
```

The Task validator and deploy context use the common decision.
AWS read-only context only verifies authentication for investigation; it does not
authorize continuation of another task. Immediately before mutation, run the same
gate with `--task` in addition to ordinary preflight, applying only that Task's Issue
remediation declaration. Recheck ordinary tasks without a remediation exception.
