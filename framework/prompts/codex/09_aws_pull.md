# AWS pull

## Read first

Read AGENTS.md, [Task transition](../../rules/task-contract.md#task-transition) (including its required common and conditional reads),
[Model sources](../../rules/model-templates.md), [project configuration](../../rules/project-configuration.md),
[Model authority](../../rules/model-information.md#model-authority),
[Properties format](../../rules/model-information.md#properties-format), and
[Validation policy](../../rules/loop-engineering.md#validation-policy).
Use the existing [AWS check](../../../.agents/skills/aws-check/SKILL.md) comparison and
account/profile/region checks for retrieval only; its prohibition on saving Model applies
to aws-check itself. This workflow adds only read-only CREATE comparison before an approved
Model-only update. Import acquisition/registration remains /import-only. Ordinary /update
has no AWS acquisition authority. AWS mutation, IaC changes and deploy/apply are forbidden.

Accept `--environment`, `--target` and comma-separated `--service` names, for example
`/aws-pull --environment stg --target cde --service s3,iam,kms`.
Resolve aliases through project.json. Process one service at a time; do not invent mappings.
Use the Human-selected worktree and existing worktree lifecycle. Do not copy dirty inputs.

## Read-only phase, before the design Task

Do not register a design Task until the final approved AWS values have been rechecked.
Use the managed Python wrapper when in a managed worktree. Execute the existing comparator:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py aws-compare --root . --environment stg --target cde --service s3 --create-only
```

Replace example arguments with the confirmed target. Explicit/implicit CREATE follows the
Model default; IMPORT is excluded. cloudformation-stacks is unsupported by CREATE-only
comparison and must be reported as unsupported. Resource absence never authorizes creation,
deletion or a mode change. Confirm identity through existing Identity/Mapping and actual
identifier evidence; ambiguity is unconfirmed and cannot be saved.

Read differences and incomplete results separately (exit 0 match, 1 differences, 2 incomplete).
The comparator primarily examines Model properties; do not claim complete discovery of
AWS-only settings. Additional list/get/describe calls may investigate only explicitly scoped
existing Resources. Authentication/account/profile failures stop; never fall back.
Acquisition failure is not absence. LLM determines API omission, defaults and unset semantics;
never turn errors, masking, normalization or unresolved values into Model settings.

Prepare a complete external properties candidate with existing `model.sources` and
`model.format.patch`. Only existing desired.row value/document keys may change; identities,
row/property layout, mode, observations and reference declarations remain unchanged.
Preserve JSON/array types and formal `$modelRef` nodes. If safe expression requires new
reference metadata or a new Property, report it for a separate explicit update.
Exclude secrets, redacted values, unverified defaults and guessed ARNs. Retain permitted
Human/acquired ARN inputs; never persist reference-derived generated ARNs as authority.

Create an external evidence JSON object mapping each changed Model key to a non-secret
retrieval citation (API, exact Resource identity, acquisition time and relevant result).
Build the offline Review, using the planned Task selector before registering it:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py pull-review model/stg/cde/s3.properties --candidate /tmp/pull-candidate --task-file tasks/pull-stg-cde-s3.md --evidence /tmp/pull-evidence.json
```

This emits exact serialized Before/After values, identity, source/candidate hashes, scope,
worktree and Task binding. It neither calls AWS nor saves Model. Store Review outside the
repository until Task registration. No differences means no Model update; report and finish.

## Review and Human consent

Display every emitted change, without truncation, as Resource / Property / Model Key /
Identity / Before (Model) / After (exact proposed Model representation) / AWS evidence.
Expand full JSON and arrays in associated blocks when a table is insufficient. Report
excluded/unconfirmed differences separately. Ask for all changes, partial revision or cancel.
Invocation, a digest or a file flag never proves conversational approval. LLM must obtain
explicit final consent in chat. Cancel/no consent means zero Model changes.
For partial revision regenerate the candidate and entire Review, display all changes again
and obtain new explicit consent; never silently retain the old approval.

After approval and before Task creation re-read the exact relevant AWS values and identity
with the same verified connection. Compare the confirmed semantics and proposed saved values
with the approved Review. Failure, ambiguity or changed AWS values stops saving: rebuild
Review and obtain fresh consent. Rebuild the offline Review against current Model/candidate
and compare it exactly with the approved document. Any difference also requires new Review.

## Approved Model-only save

Read [Ordinary Model correction](05_update.md#ordinary-model-correction) and its mandatory
references, including generation and Change Validation. Register the existing design Task:

```text
- Task type: `design`
- Task status: `running`
- Workflow: `update`
- AWS API execution: `forbidden`
- deploy/apply: `forbidden`
- Model source: `aws-pull`
```

Declare the exact source entrance/parts, generated Markdown/JSON and necessary affected
consumers and Acceptance checks. Add `## AWS pull review` containing the complete emitted
JSON as plain JSON, without fences or approval booleans. This is integrity evidence, not
Human authentication. Do not edit Review to overcome a failed check. Task scope and
worktree must match. No AWS APIs may run after this Task starts.

Save once through existing `model/cli.py edit <entrance> --candidate <external-directory>
--task-file <selector>`. The opt-in guard checks exact Review/Before/After/source/candidate,
existing CREATE keys and preserved identity/mode/layout/references; ordinary update is
unaffected. Existing Task authority, Publication Lock, input snapshots, Change Validation
and transaction checks remain mandatory. Final candidate validation repeats Review checks
against the Task baseline, including after base synchronization; changed inputs stop saving
or integration and require renewed review, never automatic rewriting of approved evidence.

Generate necessary Markdown/JSON only with shared guarded generation APIs. Run related
Change Validation for changed Resources/Properties and affected reference contracts; no
unrelated Full quality validation. Follow existing worktree finalization and cleanup.
After one service finishes, start the next service's independent read-only Review cycle.
Report saved keys, validation, excluded/unconfirmed items and limitations. Do not proceed
to IaC or deployment.
