# Resource logical identity

Resource identity is independent of names, physical identifiers and CloudFormation identity.
The canonical ID is `<ResourceType with dots replaced by underscores>_<sequence>`:
`EC2_VPC_001`, `EC2_Subnet_001`, `S3_Bucket_1000`. The sequence has at least three digits.
Its scope is environment / project-resolved target directory / service / ResourceType.
Equal IDs in different scopes do not imply equal roles or AWS resources.

`desired.service.identity.lastAllocated` is a JSON object of ResourceType to last allocated
integer. Keep deleted types and their high watermarks. A normal reader never fills missing
IDs, allocates IDs, repairs properties, or uses an entry number/name/anchor as a fallback.
ResourceType prefix collisions, duplicate IDs, missing counters and decreasing counters fail.

## Ordinary CREATE and IMPORT additions

Use `model.identity.allocate(candidate_values, selected_new_entry_numbers)` once after the
Human-selected Resource correspondence is known. The selected order is explicit; do not derive
it from AWS enumeration, names or physical identifiers. This returns the candidate fields,
including IDs and counters, without writing. Publish both through the existing source API
or IMPORT Review/publication. IMPORT refresh/replace/bind keep the existing ID. The shared
`preserve_allocation` guard rejects renumbering, reuse and inconsistent counters. Concurrent
source changes fail the existing snapshot comparison; never resolve them by automatically
renumbering a saved Resource.

Canonical references always include their full scope:

```text
resource://<environment>/<target-directory>/<service>/<logicalId>
```

Use this for self references, parentReference, row values/documents, structured `$resource`
operands, templateBucket and artifact bucket references. `model.identity.parse_reference`
parses internal addresses; `Resolver(root, reads).resolve(uri)` validates project topology
and reuses a service snapshot/index. These addresses are never network URLs.
Resource `desired.reference.*` declarations retain their IDs, producerScope, consumerKey,
pointer and position, but select `producerLogicalId`. Stack declarations still use producerId;
context declarations retain their own contract. Name/physical-ID literals remain unchanged.
Ordinary URLs, JSON artifact links and descriptive strings are not Resource selectors.

Resource anchors are absent from authority. Markdown projects `resource-<logicalId>` anchors
and ordinary display names. JSON artifacts resolve explicit operands to confirmed attributes;
a bare URI requires an unambiguous receiving-property contract. For policy Resource operands,
select an explicit attribute such as `{"$resource":"resource://qa/team/s3/S3_Bucket_001","$attribute":"Arn"}`.
An unavailable/ambiguous value is unresolved, never a raw URI in an AWS-facing artifact.
Do not save generated ARNs back to authority.

`cfn-logicalId` independently retains `<existing StackName>-<existing Resources key>`.
CloudFormation CREATE with a formal CFn type requires it even when logicalId exists.
This requirement does not extend to Terraform, IMPORT or design-only types without CFn types.
No normal CFn resolver substitutes logicalId for cfn-logicalId.

## One-time consumer rewrite

This Framework change does not convert any consumer Model. Run a separate, explicit Task in
that consumer, using its installed Framework and ordinary managed-worktree lifecycle. No AWS
API, deploy/apply, environment mapping, or permanent migration command is needed.

1. Register the following exact declaration in the existing Task contract. Replace example
   service paths with the complete selected set, including incoming consumers. List every
   existing Model entrance/part and generated Markdown/JSON file under both Modified files
   and Allowed paths. Preserve other Tasks and files. Keep ordinary Required changes and
   Acceptance checks according to task-contract.md.

```markdown
## Task contract
- Task type: `migration`
- Task status: `running`
- Model identity rewrite: `logical-id-v1`
- AWS API execution: `forbidden`
- deploy/apply: `forbidden`
## Validation scope
- `qa/team/vpc`
- `qa/team/consumer-service`
## Modified files
- `tasks/resource-identity.md`
- `model/qa/team/vpc.properties`
- `model/qa/team/consumer-service.properties`
- `docs/designs/qa/team/vpc.md`
- `docs/designs/qa/team/consumer-service.md`
## Allowed paths
- `tasks/resource-identity.md`
- `model/qa/team/vpc.properties`
- `model/qa/team/consumer-service.properties`
- `docs/designs/qa/team/vpc.md`
- `docs/designs/qa/team/consumer-service.md`
```

The task-aware issue gate permits only this validated identity rewrite despite existing
issues. Preserve those inventories and all other guards; the exception is not issue
remediation or validation-failure approval. Ordinary task issue gates remain unchanged.

2. Extract a bounded inventory with a temporary script using
   `model.identity_rewrite.baseline_snapshot(Scope(root, environment, target, service), reads)`.
   This historical reader is only for rewrite comparison; do not send every Model file to an
   LLM. Summarize fixed entries, types, current IDs, references, parts and unresolved choices.
   Pair before/after by scope plus fixed entry number. Keep all Row/Stack IDs, ownership,
   placementName, resourceMode, settings, JSON types/order and observed presence/values.
3. Prepare ordinary properties candidates outside the repository. Explicitly assign typed IDs,
   initialize exact per-type high watermarks, replace only proven Resource references, remove
   authoritative resource anchors, and update resource declaration producerLogicalId/text.
   Preserve existing cfn-logicalId. A missing CFn mapping may be completed only when the old
   ID or its mechanical PascalCase uniquely matches a formal type in unchanged existing
   templates/registered stacks and has no other direct owner. `BaselineIndex.cfn_mapping`
   provides this baseline-only proof; ambiguity or missing evidence stops that conversion.
4. Publish all selected services together through the existing authorized context. An external
   temporary script can use the following API pattern; `candidates` maps each scope tuple to
   its complete `{absolute_model_file: utf8_text}` candidate map. Preserve index/parts files and
   block placement. No force/skip-validation or raw-file publication is authorized.

```python
from pathlib import Path
from model import prepare_edit, publish_edits
from model.adapters.task import edit_write_context
from model.identity_rewrite import baseline_snapshot
from model.sources import Scope

root = Path.cwd().resolve()
scopes = set(candidates)
with edit_write_context(root, scopes, 'tasks/resource-identity.md') as context:
    plans = []
    for identity in sorted(scopes):
        before = baseline_snapshot(Scope(root, *identity), context.snapshot)
        plans.append(prepare_edit(before, candidates[identity], context))
    publish_edits(plans, context)
```

The save boundary compares against the versioned Task baseline with
`model.identity_rewrite.verify(before_root, after_root, declared_service_scopes)`, validates
new authority, checks retained placement/order, and proves the same Resource targets and
configuration. It detects unselected incoming consumers. The shared lock, final input
comparison and transaction prevent partial publication and allocation races. Ordinary Tasks
and value-preserving refactors do not authorize identity changes. Rerunning an already
converted candidate keeps IDs/counters unchanged.

5. Generate registered views with the ordinary scoped write loop:
   `python3 -B framework/scripts/run-python.py -B framework/scripts/blueprint-loop.py --mode task --write --task-file tasks/resource-identity.md`.
   Use the validation mode required by the consumer's applicable policy; do not run local IT
   or AWS tests for this offline rewrite. Unresolved conversions are not success. Reference-only
   warnings retain the existing nonblocking policy for ordinary updates, but cannot prove a
   rewrite's target equivalence.
6. Use the existing final-candidate lifecycle:
   `python3 -B framework/scripts/worktree_task.py finalize --task-id resource-identity`.
   The declared identity rewrite participates in the existing final Model guard/composition.
   Integrate only its successfully validated latest-base candidate. Do not use a failed-validation
   exception. Report Framework implementation, consumer conversion and live AWS verification
   separately; completing one never proves the others.

Historical template-to-properties format conversion remains an exact format comparison.
Its staged output retains the historical identities and is not valid ordinary current Model
input until the separate identity rewrite above succeeds. The historical comparison reader
is limited to this explicit conversion evidence and the identity-rewrite baseline; it does
not enable legacy identities in ordinary loading, generation or Resource resolution.
