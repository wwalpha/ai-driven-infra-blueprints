# AWS pull

The standalone examples use `python3`. Use the Python 3 launcher configured for the repository. In a managed Worktree, pass the script or module and its arguments to `python3 framework/scripts/worktree-cli.py run`. See [Run Python in the Worktree](../../../.agents/skills/worktree/SKILL.md#run-python-in-the-worktree).

## Read first

Read AGENTS.md, [Task transition](../../rules/task-contract.md#task-transition) (including its required common and conditional reads),
[Model sources](../../rules/model-templates.md), [project configuration](../../rules/project-configuration.md),
[Model authority](../../rules/model-information.md#model-authority),
[Properties format](../../rules/model-information.md#properties-format), and
[Validation policy](../../rules/loop-engineering.md#validation-policy). For direct
observation saves, read [Collection and propagation](../../rules/observed-values.md#collection-and-propagation)
and [Observation publication](../../rules/observed-values.md#observation-publication).
Use the existing [AWS check](../../../.agents/skills/aws-check/SKILL.md) comparison and
account/profile/region checks for retrieval only; its prohibition on saving Model applies
to aws-check itself. This workflow uses read-only CREATE acquisition for direct observation
saves and separately approved Model settings updates. Import acquisition/registration remains /import-only. Ordinary /update
has no AWS acquisition authority. AWS mutation, IaC changes and deploy/apply are forbidden.

Accept `--environment`, `--target` and comma-separated `--service` names, for example
`/aws-pull --environment stg --target cde --service s3,iam,kms`.
Resolve aliases through project.json. Process one service at a time; do not invent mappings.
Use the Human-selected worktree. For a managed Task, follow
[Create and execute](../../../.agents/skills/worktree/SKILL.md#create-and-execute). Do not copy dirty inputs.

## Read-only phase, before the design Task

Capture the selected Model inputs before the first AWS read, then execute the existing
comparator. Keep both results in a new external directory for the selected service.
The commands use example paths:

```console
python3 -B framework/scripts/model/cli.py pull-observed model/stg/cde/s3.properties > /tmp/pull-observed-inputs.json
python3 -B framework/scripts/model/cli.py aws-compare --root . --environment stg --target cde --service s3 --create-only --output /tmp/pull-result.json
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

## Direct observation save

Use the acquisition result's `identifier` items with an `observationKey`, including
when the comparison exits 0. A key identifies a potential destination. Confirm from
the existing Mapping, resource identity and API evidence that `awsValue` is the
actual identifier of that exact CREATE resource. A request selector or saved ID alone
does not establish resource ownership. Exclude unconfirmed rows, hidden identifiers,
ARNs, secrets and placeholders. Do not perform another AWS read for this save.

Copy the confirmed items unchanged from the comparison's `results` array to an
external JSON array. Each item binds its AWS value to its original service, resource,
property and observation key.
Run the command below without `--task-file` to obtain the exact Model write paths
without saving. When it returns at least one path, register an observation-only
`design/update` Task with AWS API execution and deploy/apply forbidden, one producer
service, the exact Model source files, and the affected generated files and Validation scope. Use
[dependency analysis](05_update.md#dependency-analysis-and-value-preserving-refactoring)
to plan affected reference displays. In a managed Worktree allocate a separate
Task for each save phase. Keep the acquisition input snapshot for its original
Worktree. Skip the observation Task when there are no confirmed observations or
the write-path plan is empty.

```console
python3 -B framework/scripts/model/cli.py pull-observed model/stg/cde/s3.properties --snapshot /tmp/pull-observed-inputs.json --observations /tmp/pull-observed-results.json --task-file tasks/pull-observed-stg-cde-s3.md
```

The invocation authorizes this observation-only save for the requested service.
Save directly without a value comparison, Review, or additional Human consent.
An absent observation value may be inserted on the existing identifier Row; an
existing value may be replaced. The writer patches only confirmed observation fields,
preserves independent consumer observations and stops on a changed input snapshot.
After a write, generate the necessary Markdown/JSON and run related Change Validation
using [Ordinary Model correction](05_update.md#ordinary-model-correction)'s local
completion procedure. For generation failure, retain the saved Model and retry
local generation. Report the saved observation keys and any unconfirmed observations.

## Settings candidate

Continue with the acquired setting differences. Use the current Model, including
observations saved in the previous step, as the baseline for the settings Review.
There is no settings Task when there are no eligible setting changes.

Prepare a complete external properties candidate with existing `model.sources` and
`model.format.patch`. Only existing desired.row value/document keys may change; identities,
row/property layout, mode, observations and reference declarations remain unchanged.
Preserve JSON/array types and formal `$modelRef` nodes. If safe expression requires new
reference metadata or a new Property, report it for a separate explicit update.
Exclude secrets, redacted values, unverified defaults and guessed ARNs. Retain permitted
Human/acquired ARN inputs; never persist reference-derived generated ARNs as authority.

Use a new external directory. Keep the selected service's entrance and every existing
part at the same path relative to that directory as in the repository. For example,
if the IAM entrance indexes `iam/part-001.properties`, the candidate contains both files:

```text
/tmp/pull-candidate/
└── model/stg/cde/
    ├── iam.properties
    └── iam/
        └── part-001.properties
```

Change the existing key only in its owning candidate file. `patch` takes the exact
serialized Model value, including the backticks in this example. Use the confirmed
key and its property's Model representation for the actual change.

```diff
-desired.row.001-001.value=`Previous role description`
+desired.row.001-001.value=`Example role description`
```

Create an external evidence JSON object with exactly the changed Model keys. Give each key
one nonblank JSON string containing the API, exact Resource identity, acquisition time and
relevant non-secret result. For the example above, `/tmp/pull-evidence.json` contains:

```json
{
  "desired.row.001-001.value": "iam.get_role | arn:aws:iam::123456789012:role/example | 2026-11-13T00:00:00Z | Role.Description=Example role description"
}
```

Build the offline Review, using the planned Task selector before registering it:

```console
python3 -B framework/scripts/model/cli.py pull-review model/stg/cde/iam.properties --candidate /tmp/pull-candidate --task-file tasks/pull-stg-cde-iam.md --evidence /tmp/pull-evidence.json
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
explicit final consent in chat. Cancel/no consent means zero settings changes.
For partial revision regenerate the candidate and entire Review, display all changes again
and obtain new explicit consent; never silently retain the old approval.

After settings approval and before its Task creation re-read the exact relevant AWS settings and identity
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
unrelated Full quality validation. For managed integration, follow
[Complete and integrate](../../../.agents/skills/worktree/SKILL.md#complete-and-integrate).
After one service finishes, start the next service's independent read-only Review cycle.
Report saved keys, validation, excluded/unconfirmed items and limitations. Do not proceed
to IaC or deployment.
