# Scenario Testing Rules

- Follow [Credentials and account](project-configuration.md#credentials-and-account) for account/profile/target selection.

## Task boundary

- Create, change, implement, and execute scenario tests only in independent `scenario-test` tasks.
- Do not automatically create or execute scenario-test tasks after infrastructure task completion or behavior changes.
- Scenario-test tasks must not change `docs/**`, `model/**`, or `infra/**`.
- After test failure, do not proceed to design changes, IaC repair, redeploy, or remediation task creation/execution.
- Scenario results must not be the authority for current observed values.

## Scenario definition

- Scenario IDs must be stable lower-kebab-case.
- Place scenarios in `tests/scenarios/<scenario-id>/`.
- Place `scenario.md` in each scenario directory with exactly 1 `- Scenario ID: <scenario-id>` entry.
- Scenario definitions must state purpose, prerequisites, required resources, expected behavior, execution procedure, pass/fail criteria, cleanup, whether AWS mutation is involved, and whether destructive operations are involved.
- Test implementations may use necessary formats such as Shell, Python, AWS CLI, and manual procedures within the scenario directory.
- Before AWS execution, validate the target with `check-deploy-context.py --read-only`. If `awsProfile` exists, use the same profile in all scenario AWS CLI/SDK and child processes. Explicitly specify `--profile` and the target region for CLI, and profile and region for SDK; pass `AWS_PROFILE` per process to tools requiring it. Reject explicit profiles differing from the setting; retain existing authentication methods when unset. Do not fall back to another profile after authentication failure.
- Scenario tests verify expected behavior, not just static settings.

## Current result

- Result scope is the combination of scenario ID, environment, and AWS account ID.
- The target directory is the target alias in `project.json` if present, otherwise the AWS account ID.
- Place current results at `tests/results/<scenario-id>/<environment>/<target-directory>/result.md`. Match the result metadata AWS account ID to the corresponding `project.json` target's actual value, not the directory name.
- Do not add AWS region to directories; record a value matching `project.json` in result metadata.
- Reruns of the same scope update the same `result.md` and stable evidence files directly under the target directory.
- Do not add directories or files per execution date or timestamp.
- Do not create additional directories under the target directory.
- A scenario without results yet is permitted. Orphan results without corresponding scenarios are prohibited.
- Track past results in Git history; do not retain copies or archives in the active tree.

## Result metadata

Record exactly 1 of each of the following in each `result.md`.

```md
- Scenario ID: `<scenario-id>`
- Environment: `<environment>`
- AWS account ID: `<12-digit-account-id>`
- AWS region: `<region>`
- Status: `<PASS|FAIL|BLOCKED|STALE|NOT_EXECUTED>`
- Executed at: `<RFC 3339 timestamp or NOT_EXECUTED>`
```

The body must state expected behavior, actual behavior, executed commands/procedures, evidence file list, cleanup result, and blocker/failure reasons.

- `PASS`: The test ran and met the pass criteria.
- `FAIL`: The test ran and did not meet the pass criteria.
- `BLOCKED`: Execution was attempted but could not complete due to missing prerequisites or permissions.
- `STALE`: Scenario changes make the previous result unusable as the current result.
- `NOT_EXECUTED`: The target is defined but has not yet been executed.

## Scenario changes

- If scenario definitions or implementations change, update every result of the same scenario ID to rerun results in the same task, or to `STALE` or `NOT_EXECUTED`.
- Do not retain old `PASS` as current results of changed scenarios.
- Do not retain results when deleting scenarios.

## AWS mutation and cleanup

- Tests involving AWS mutation may run only when the active prompt explicitly states target operations, target resources, cleanup, and authorization scope.
- Destructive operations require explicit authorization in the active prompt; confirm targets beforehand.
- Record cleanup results in the result body.
- Even on failure, do not infer or execute cleanup, repair, or redeploy outside the active prompt.
