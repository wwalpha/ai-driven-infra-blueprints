# Import current AWS inventory

`/import --environment dev --target cde --service vpc`

AWS CLI → selected Model source transaction → selected Markdown/JSON transaction.
This is a design task with `Workflow: import`. Design validation belongs to an explicit
later `/issues` invocation and is never run before or after import, even for warnings.

## Read before changing files

Read AGENTS.md, [Task transition](../../rules/task-contract.md#task-transition),
[Import issue-gate boundary](../../rules/issue-gate.md#dedicated-import-boundary),
[project-configuration](../../rules/project-configuration.md),
[IMPORT configuration authority](../../rules/model-information.md#import-configuration-authority),
[Model templates](../../rules/model-templates.md), and
[Identifier lifecycle](../../rules/observed-values.md#identifier-lifecycle).
Use [worktree](../../../.agents/skills/worktree/SKILL.md) and its Task transition,
Task boundary, Acceptance and retry reads. Reuse unchanged rules already read.
For this workflow, the unresolved issue gate, naming preflight, candidate validation,
generated equality, local loop and general final design validation do not apply.
This exception does not relax ordinary design, deploy or framework implementation tests.

## Execution

1. Require one explicit Environment and Service. Resolve exactly one project.json Target
   by Alias, or Account ID without an Alias; omission is allowed only when unambiguous.
2. Run IMPORT in the worktree selected by the Human. Register a separate contract
   there; this does not itself authorize commit.
   Register a `design` contract with `Workflow: import`, exact `IMPORT target` and
   initial target scope. Preserve other tasks and declare exact source/view paths. Do not run issues or validation to determine permission.
3. Invoke import-model.py once. Its first AWS call is STS get-caller-identity. Every call
   uses project.json awsRegion and configured awsProfile. Explicit `--no-profile` omits
   only the configured profile for this invocation; retain AWS_PROFILE/default credential
   chain and account checks. Compare STS Account to awsExecutionAccountId, or awsAccountId
   when absent. Never retry authentication with another profile or infer an override.
4. Enumerate the selected service's supported AWS resource types using the existing
   read-only adapters and model.include. Never filter inventory by Model names/settings.
   Distinguish failed retrieval from a successful empty collection. Preserve CREATE and
   unselected settings; reuse confirmed IDs/Row IDs and reject ambiguous ownership.
   Existing main-vpc slot behavior remains; do not acquire another service/environment.
5. Read only editable template/parameter/binding/observed inputs. Do not expand external
   references or check input design constraints. Preserve existing logical references;
   store their acquired values separately as observations even when they disagree.
   Keep acquired non-secret IDs/ARNs; never store guessed/generated ARNs, credentials,
   raw AWS responses or new snapshot files. Report every unreflected item.
6. Reuse independent parameter inversion when safe. Otherwise parameterize only the
   changed Property. Read only that Property's old inputs for direct Definition users,
   preserve their values and apply AWS values to selected IMPORT instances. No recursive
   consumer traversal, whole-Model preservation comparison or unrelated parameter cleanup.
7. Build an in-memory source plan. Bind acquisition, Task, selected target,
   permitted source changes and source hashes in ignored `.blueprint/import/<task-name>.json` evidence under the execution root.
   Under publication_lock, recheck concurrent source changes, then save
   Model sources through the existing journal/rollback transaction. Source-save failure
   restores that transaction. Contract flags alone never authorize IMPORT edits.
8. Generate only selected-service Markdown/JSON from saved sources. Keep the existing
   display formats and lossless JSON fallback for policies that cannot form tables.
   Recheck source/output snapshots, ownership and collisions, then save views as a second
   transaction. Roll back only that view transaction on failure; retain saved Model.
   Preserve unowned JSON. A stale view may be updated even when Model is unchanged.
9. Report Model and display statuses separately. Design validation is always `not-run`.
   Do not run issues, sync validation, local loop or whole-repository validation.
   Complete Model reflection only with matching, complete acquisition/source evidence.
   Display failure does not undo reflection. Complete the authorized worktree lifecycle;
   never push. Report display failure explicitly and do not automatically reacquire AWS.

## CLI and recovery

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/import-model.py --environment dev --target cde --service vpc
python3 -B framework/scripts/run-python.py -B framework/scripts/import-model.py --environment dev --target cde --service config --dry-run
```

Dry-run retrieves and plans without persistent Model, view, contract or evidence writes.
It is not a prerequisite for normal import. There is no --all, named profile override,
mutation, deploy or extra preview/apply mode. For an explicit current-checkout request,
use the installed Python with `BLUEPRINT_TASK_FILE=tasks/<task-name>.md`.

For display recovery after Model reflection, without AWS reacquisition:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/sync-model.py --write --environment dev --alias cde --service vpc
```

Use --aws-account-id without Alias. The selected import contract/evidence remains required;
ordinary sync/design validation retains its existing safety checks.

## Result

- Model: `reflected` / `unchanged` / `failed`.
- Markdown/JSON: `generated` / `unchanged` / `failed` / `not-run`.
- Design validation: `not-run`; Human explicitly runs issues later.
- Exit 0: Model and display complete, including no changes.
- Exit 2: acquisition/reflection failed or items remain unreflected; report saved and pending scope.
- Exit 3: Model complete, display generation/publication failed; old displays may remain.

Report command/scope, connection and STS, resource counts, saved sources, CREATE protection,
unreflected items and display status. Do not describe partial coverage as full reflection.
Adapters remain VPC, Config, Data Firehose, QuickSight DataSource/VPCConnection,
Security Hub, Transit Gateway VPC attachments and CloudWatch Logs. No new service coverage.
Tests use Mock CLI and minimal fixtures; no live-AWS verification is implied.
