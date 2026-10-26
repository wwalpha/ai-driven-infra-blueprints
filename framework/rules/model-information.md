# Machine-readable Service Model Rules

## Model authority

[Service Model sources](model-templates.md) and [properties v2](../docs/model-format-2.md)
define the environment-specific properties authority. Each stored entrance and its parts
contain desired, display, observations and explicit reference meaning. project.json retains
topology/target/Region/profile authority. Runtime Property/comment are
derived and never editable source. Model is the single source of truth; Markdown and JSON
are generated views. Validate Model inputs against the authoritative Model contract,
Mapping, Catalog and Schema before rendering once. Validate generated views for
structure, links, artifacts and consistency, then save or compare them with existing
outputs using the existing generation comparison. Whole-model reverse projection
from Markdown is not required and must not be used as a publication gate.
The field/identity/display rules below apply to canonical Models, runtime projections and generated views.


If updating the model fails, do not update Markdown/JSON. The model is authoritative for design values, names, and descriptions.

- Follow [Topology](project-configuration.md#topology) for target directories.
- Place human-readable current designs in `docs/designs/<environment>/<target-directory>/`.
- Store authority in `model/<environment>/<target-directory>/<service-id>.properties` and its indexed parts. Alias takes precedence over awsAccountId; execution account is not a path identifier. Every environment has explicit values.
- CloudFormation stack detailed designs retain each stack's name, template filename, parameter filename, and positive integer `deployOrder` in `desired.stack.*` of `cloudformation-stacks.properties`, and target policy in `desired.deployment.maxConcurrentStacks` (integer 1 or greater). Generate Markdown with the same stem. `DeployOrder` is a formal design value for each stack instance, not template identity or a dependency field. Do not add policy to `project.json`. Generate listing `No.` and retain `Comment` in `display.stack.*.comment`. Do not save stack execution state, StackId/ARN, or values temporarily retrieved from AWS in the model.
- S3 placement may explicitly approve delegation to bucket default encryption using model-only `desired.resource.<id>.deploymentEncryption=default` on `S3.Bucket`. No other value/resource type is permitted. Omission means explicit encryption headers derived from the selected formal BucketEncryption rows; it never means approval to delegate. Retain confirmed default SSEAlgorithm and, for SSE-KMS, KMSMasterKeyID rows in either mode. Validate this approval directly in the authoritative Model, like model-only CFn identity; do not infer it from Markdown, policy, missing rows, or AWS settings.
- Catalog properties are authoritative for selectable items; model properties are authoritative for desired and observed values. Markdown and JSON artifacts are generated outputs for display and use.
- Codex saves confirmed designs in environment-specific properties first through the shared Task-authorized Model APIs. Human properties edits are design inputs. the integrated `blueprint-loop.py --mode task --write --task-file tasks/<task-name>.md` generates and validates Markdown/JSON artifacts without overwriting the model; `sync-model.py --write` remains the generation-only entrypoint.
- Fail the local loop for Markdown/Model mismatches when reference-complete generation is available. A View retained because of a reference problem is NOT_RUN, not an equality failure. Do not silently adopt either one.
- Ordinary saves validate the corrected Model and affected consumers through the common candidate guard. Do not require the old Model to load or preserve its fields. Missing/ambiguous final reference targets and invalid reference types/Properties block final save/completion/integration; pending observations and saved-text differences remain diagnostics. Dedicated operation leaves may save intermediate sources, but their parent must pass final candidate validation.
- After saving authoritative Model inputs, design tasks generate Markdown and JSON artifacts in the same coherent logical change. When selected existing resources were retrieved read-only, also generate required non-ARN current identifiers in `observed.*`.
- Follow [observed-values](observed-values.md) for current identifier update conditions and propagation.
- The infrastructure `update` phase treats human-changed authoritative service Model inputs as immutable inputs and generates Markdown before deployment. Update observed identifiers and regenerate Markdown only after successful AWS mutations.
- `framework/rules/detailed-design.md` is authoritative for Markdown structure, service grouping, and generated identifier rows.

## Service display inputs

- Derive the `IAM.Role` display name only from confirmed desired rows of formal `IAM.Role.RoleName`, and use it in listings, detail headings, and reference links. Require exactly 1 RoleName row and reject missing, duplicate, empty, or unconfirmed values. Do not substitute Name tags or `display.resource.*.label`; retain internal logical IDs and policy artifact naming.
- Use `## リソース一覧` and `## リソース詳細` as display section boundaries, and generate No. Listing Comments are authoritative in `display.resource.<番号>.comment`; Stack listing Comments are authoritative in `display.stack.<番号>.comment`. Do not treat them as AWS properties. H3 resource headings under the detail section retain display names; identify internal logical IDs from hidden `resource-logical-id` metadata immediately before anchors. For existing formats without markers, the heading identifier can be read as internal identity. Do not output hidden markers to notes or properties; exclude H4 policy tables as derived displays. Do not change resource numbers, anchors, logical IDs, or desired/observed values through heading hierarchy changes alone.

- Retain Name tags for `EC2.VPCEndpoint`/`EC2.Instance` in desired rows using each resource type's formal `Tags[].Key=Name` and corresponding `Tags[].Value`. Do not add design-only `.Name`. Name tags are mandatory for CREATE; reject case differences, missing Values, empty or unconfirmed values, and do not substitute display labels. Listings, headings and ordinary reference link labels use that Value; anchors retain their saved values; retain internal logical IDs in hidden metadata and the separation of existing desired logical references/observed IDs for identifier references. Retain VPC/Subnet/RouteTable/Flow Log .Name displays.

- Retain Security Groups and their Ingress/Egress in `security-group.properties`, and generate `security-group.md`. Use `security-group` for service metadata and anchor prefixes. Do not mix other EC2 resources into this model.
- Retain ConfigurationRecorder RoleName displays and KDF BucketARN/RoleARN in desired as resource links displaying confirmed names of referenced resources. If a referenced IAM role name starts with `AWSService` (example: `AWSServiceRoleForConfig`), do not require an IAM Role design or link; retain the role name literal in the formal ARN property's desired value. Do not change formal ARN properties to name properties or generate/save ARNs. Separate KDF KeyARN into a logical reference to the actual KMS Key in desired and the displayed KeyId/PENDING_DEPLOY in observed according to existing identifier reference rules.

For `Config.ConfigurationRecorder.RoleARN`, an IMPORT resource may retain an acquired,
valid IAM Role ARN with its full partition, account ID, path and role name. Display
that value as `RoleARN`. IAM Role links and permitted `AWSService...` names retain
`RoleName`. CREATE still requires an IAM Role link or permitted service-role name;
direct ARN strings remain forbidden. Determine mode from the authoritative resource,
never from the value's ARN shape. IMPORT literal parameter formatting affects only
the generated display, with one pair of backticks; editing expansion and stored
saved desired values stay unchanged.

## Resource management mode

- Allow only `desired.resource.<nnn>.resourceMode=CREATE` or `IMPORT` for resource-level framework metadata. Reject empty values, alternative spellings, and unknown values. Treat existing resources without a specification as CREATE; do not infer conversion to IMPORT. Explicitly specify the category in new designs.
- CREATE covers new creation and IaC generation based on the framework, retaining existing naming conventions and mandatory Name policy. Do not change to IMPORT merely by retrieving current values after creation.
- IMPORT is the category for incorporating existing resources into design management; retain retrieved, selected actual/current configurations in `desired.row.*` and required actual current identifiers (including acquired non-secret ARNs) in `observed.row.*`. Do not change AWS resources; exclude them from IaC generation. This is not CloudFormation Resource Import/Terraform import.
- Categories are not provenance such as creator, administrator, or externally created status. Retain the contract prohibiting saving provenance.
- Exempt IMPORT from framework-specific naming conventions, coverage, and mandatory Name tags, and retain existing names, configurations, and presence/absence of Name tags. Do not rename, add/change tags, or fill values. Retain provider schema, catalog, row structure, reference, and confirmed-value validation.
- When an IMPORT name property is provider-optional and unselected, its same-resource confirmed `display.resource.<nnn>.label` may supply the display name. Match resourceType/logicalId and hidden identity to that authoritative resource. Selected valid names take precedence; selected empty, unconfirmed or invalid names and missing required properties cannot use this fallback. Retain IAM RoleName, CodeBuild Name, CREATE naming and Name-tag requirements. This does not expand type-only display or generate AWS properties, tags, IDs or ARNs from labels; preserve saved anchors.
- Retain existing VPC/Subnet/RouteTable/Flow Log Name tags in the existing `.Name` and Endpoint/Instance tags in formal Tags rows. For IMPORT without a Name tag, omit that row. Use human-confirmed `display.resource.<nnn>.label` for display only when needed; do not copy it into AWS properties or tags. A single resource of the above 6 types named only by Name tags may use the existing type-name display if no label exists either.
- Retain resourceMode only in authoritative properties; do not generate `resource-mode` comments in Markdown. Ordinary display validation references the same service model by logicalId to obtain the CREATE/IMPORT validation category. Do not mix it into AWS property tables or desired.note. Specify identified grouped children independently using their own logicalIds too. Inline configurations without identity follow their containing resource's category; if a separate category is needed, stop without inferring it.

## Reference diagnostics

Reference existence, changed targets, unresolved/cyclic/ambiguous references, type or
label mismatches and surviving links are WARNING diagnostics in read-only analysis.
Final candidates must resolve Resource/Stack/Model targets and match producer types and
Properties. Missing/ambiguous targets, including surviving links to deleted Resources,
fail ordinary saves, Task completion and integration. Saved name/identifier text differences
and pending observations remain warnings. The old Model is never subject to this final gate.
The LLM uses warning locations and authoritative sources to repair what it can determine
within the authorized scope; ask the Human about undetermined repairs. Repair, warning
acknowledgement and Issue migration do not gate read-only analysis or intermediate leaves.
The final candidate guard still rejects invalid reference targets/types before completion. Do not infer targets or values, add a force/allow-warning flag, or expand authority.

Validate final syntax and Resource/Row/Instance IDs; retain operation targets and non-reference literals in dedicated operations,
observed/acquired values, JSON structure/types, I/O, Task scope, input snapshots and
publication locks mandatory. Compare every JSON leaf and literal prefix/suffix even when
another reference is unresolved. Use typed ReferenceResolutionError at semantic resolution
boundaries; never downgrade generic ValueError/OSError or classify by a reference keyword.

Report stable code/message, known producer/consumer IDs, source line, Model key/Property,
JSON pointer, raw expression, resolution state and known current/previous value. Unknown
values remain unknown. JSON CLI carries warnings in stdout JSON; normal CLI emits WARNING.
Warnings alone exit zero and recur until resolved. Reference analysis returns references,
warnings and complete; incomplete analysis is not proof of no references. Use existing
before/after snapshots to diagnose removed IDs and anchors.

Generate and save views that can be produced. For reference-only inability, retain the
existing Markdown/JSON (or report not-generated), keep saved Model sources, and record the
unexecuted checks as NOT_RUN with reason reference and the affected scope/retained views.
Only that identified condition is nonblocking for read-only analysis or intermediate source saving; final completion still requires valid candidate references. Arbitrary NOT_RUN and
real errors remain blocking. Do not put warning/incomplete results in the PASS cache.

## IMPORT configuration authority

Model correction does not require the old Model to be valid or unchanged. IMPORT Resources may be acquired repeatedly and updated or corrected. Safety is determined by Task change authority, necessary Human consent and the final Model integrity. AWS acquisition remains exclusive to `/import`; ordinary `/update` may correct only the Resources and fields explicitly requested by the Human, without AWS acquisition authority. Dedicated merge/delete/retarget and value-preserving operations retain their own raw-value preservation checks.

Explicit standalone reference retarget is a separate narrow `/update` exception under
[Standalone Model reference retarget](task-contract.md#standalone-model-reference-retarget).
Only declared existing references may change; both IMPORT producers and every other
setting/identity/observation remain preserved. It grants no acquisition, configuration
transfer/deletion, Subnet association, IaC or AWS permission. Its source save guard proves
the before/candidate comparison as well as final verification after rebase; ordinary
save routes cannot bypass ownership, one-use context, snapshot or publication checks.
The following transfer/removal requirements apply to merge/delete only.

Captured AWS facts are authoritative for the acquired fields of an `/import` transaction; explicit ordinary corrections are authorized by the Human design Task. The dedicated [import
workflow](../prompts/codex/08_import.md) permits user-selected add/refresh/replace/bind from
captured AWS facts. Present the complete normalized Review with concrete IDs, typed
Before/After, references and risks before Human approval of any addition or overwrite.
Python verifies identity, values, nonselected preservation and atomic publication.
The LLM obtains explicit final consent to reflect the complete current Review in ordinary
chat, then edits candidates and invokes existing Python validation/save APIs. Dedicated
Host approval, issuers, Human authentication tokens/signatures and Human-only publishers
are not required. Python verifies change integrity, not the identity or existence of
conversational consent; no `approved=true` flag grants save permission. A regenerated
Review proves content consistency only. The LLM must obtain renewed consent after changes.
Direct CLI execution can bypass dialogue; that is an accepted operating risk.
The LLM owns chat questions, answers, recommendations, corrections and external-session
checkpoints. Python validates their binding and final selections, never orchestrates them.
All Resource answers are required before the one-service transaction; unresolved entries
cannot be silently excluded or partially published.
Explicit final consent must cover the complete current Review before publication;
corrections require a rebuilt full Review and renewed consent; cancellation performs no source save.
Follow existing Worktree validation/merge and Human review of the merged Model.
Explicit Model-only merge/delete uses [update](../prompts/codex/05_update.md#model-only-import-merge-or-deletion).
That design branch requires exact source/destination IDs and verifies the actual diff:
complete source transfer/removal, stable destination identities, unchanged CREATE and
other non-reference consumer values; remaining source references produce warnings. It uses existing source
editing and per-write publication/rollback without AWS or IaC. In a managed worktree,
independent transfer/retarget/delete may save intermediate sources under the running
parent contract; generation is separate and final validation proves the whole operation
after rebase before integration. Declared references alone may be retargeted, retaining
their structural meaning; D→D reevaluation is explicit.
Other-environment inputs may receive necessary value-preserving additions only in this
branch. CREATE retains its existing workflow. Explicit value-preserving dependency detach
uses an ordinary design /update Task for an independent request under
[Value-preserving Model refactor](task-contract.md#value-preserving-model-refactor):
prove preserved non-reference settings/types/structure and shared consumers, report
reference-derived differences and remaining dependencies, and validate the actual rebased candidate before merge.
For a registered import-delete request, related detach/reference repairs instead share
its parent Task, Worktree and final validation/merge. Resource leaves save raw sources
sequentially; only the parent finalizes after all deletions. Unrelated properties,
non-target consumers/environments, fixed identities and observations stay protected.
These dedicated-operation constraints do not restrict the separately authorized ordinary correction branch.

Import verifies target/profile/account/Region, acquisition success and scope, resource
identity, secrets, source ownership, concurrent edits and atomic publication. It does
not decide design correctness or run naming/schema constraints, whole-service
design reference validation, whole-repository candidate copies, generated equality or
local loops. Selected-resource physical references are acquisition consistency checks under [Selected-resource references](../prompts/codex/08_import.md#selected-resource-references),
using declared receiving contracts and exact same-target producer identities.
The agent edits only changed source candidates outside the repository; publication
checks their syntax and native types without applying unrelated design constraints.
Explicit issues retains those design and consistency checks without requiring AWS.

Bind importer evidence to Task, target, acquisition, planned source changes,
pre-save snapshots and saved source hashes. The source publication guard and Worktree
completion verify this evidence without expanding old Git Models or other services.
Self-declared flags cannot authorize changes. Missing, stale or incomplete evidence
blocks reflection completion. Ordinary workflows retain their IMPORT protection.
Acquisition evidence is a private sealed temporary session outside the repository,
binding normalized non-secret records, STS/connection/time, Task/Worktree/scope,
source hashes and the direct consumer set across acquire/publish processes. The agent
records correspondence and review there; source publication follows explicit final consent in chat.
Only after complete source/display success or explicit Human termination, remove
temporary acquisition/candidate contents; retain only a sealed task receipt at
`evidence_store(execution_root)/<task-name>.json`, outside the repository. Dry-run
persists no Model, displays, contract or completion receipt; retain its session until
explicit Human termination. Pre-save failure, incomplete display or display I/O failure
retains acquisition/review evidence for diagnosis and display-only recovery.
Never save raw responses. Acquisition/receipt timestamps expire after seven days;
future timestamps beyond five minutes are rejected. Review version 4 and receipt version 6
record the conversational responsibility boundary. Version 6 binds Review/selection,
acquisition/baseline, proposed values, Reference/Selector meaning, Task/Worktree/scope
and exact saved source hashes. Receipt parsing requires the current version and sealed external location. Local seals and the Review
binding provide integrity, not Human authentication. Worktree reuse remains rejected.
Temporary snapshot receipts are removed in finally; source evidence remains retryable. Worktree evidence
is removed only after verified integration and successful checkout/branch cleanup.
See 08_import for failure/cancellation cleanup.

Import reflection uses explicit `add`, `refresh`, `replace` and `bind` correspondence in the
existing selection.json. Add requires new fixed IDs and IMPORT mode. Refresh requires
one matching physical ID. Replace requires the Human-selected existing IMPORT ID,
verified previous identity/Model digest and no duplicate destination physical ID.
Bind requires an explicit existing IMPORT ID with unknown physical identity, a matching
before-Model digest, valid acquired identity and no known duplicate owner; its duplicate
risk is reviewed. All overwrite actions preserve Resource entry ID/logicalId/type/mode and existing Row IDs;
only captured Properties and their observations may change or gain rows. Unacquired
Properties, nonselected resources and CREATE remain protected. Unknown or ambiguous
matching never authorizes guessing. No implicit deletion, mode conversion or retargeting.

The LLM reads sources through `load_for_edit`, handles confirmations and executes
ordinary candidate edits one resource at a time. Reuse unchanged Definitions or add
reusable Definitions with necessary inputs/composition; only a selected overwrite
Instance may switch binding Definition. Other consumers, common inputs and other
Environment inputs stay unchanged. Preserve native value types, arrays and formal
references. Use the existing physical Reference Resolver only for captured Properties
of selected resources. Do not infer/generated ARNs or persist secrets.

For replace/bind, existing incoming-reference analysis reads registered same-target services
as preservation evidence and returns non-self incoming usages and unresolved analysis as warnings.
It does not edit them or authorize a Model-only operation; transfer/retarget/delete and
value-preserving detach retain their separate contracts. No other Environment is edited.
Acquisition/normalization, Singleton/cache, STS/Region checks, source/evidence hashes,
publication lock, journal and rollback remain the existing mechanisms. Do not add a
batch Python controller or Model update engine. For multiple services, the LLM repeats
independent single-service Tasks/acquisitions/publications sequentially. Acquire once
and publish once per service; no per-resource retrieval/publication loop in Python.

Distinguish an absent service from a zero-resource existing Model. Missing/broken
inputs are errors; an absent service uses an explicit complete properties candidate
and the same guarded source creation transaction.
Dry-run writes no authoritative Model, contract, display or completion receipt.
Follow [IMPORT Property source edits](model-templates.md#import-property-source-edits)
and [08_import](../prompts/codex/08_import.md#agent-selection-and-source-edits).

Normal `/import` permits explicitly managed additions and confirmed refresh/replace.
Save Model sources
atomically first. Then generate and atomically save only the selected service's
Markdown/JSON. Never directly edit generated design Markdown/JSON or use display edits
as a substitute for Model reflection, including during display-only recovery.
Reference-only display inability retains views and reports NOT_RUN with warnings, exit 0.
Other display failure rolls back only display writes and is exit 3;
it never invalidates completed reflection. Exit 2 includes unreflected items. Report
Model, display and `Design validation: not-run` separately. Stale views can be refreshed
without Model changes. Never auto-run issues or repeat AWS acquisition for display failure.


## Policy derived views

- Retain policy/configuration JSON bodies as compact JSON in each service model's `desired.row.*.document`. Generate service-owned JSON from JSON artifact links in `desired.row.*.value`, and generate policy tables from that JSON. Do not feed JSON artifacts or tables back as design inputs.
- Do not duplicate in the model the generated ResourceName/Comment table in the resource listing or displays within `<!-- policy-tables:start -->`–`<!-- policy-tables:end -->` and IAM's `<!-- iam-policy-tables:start -->`–`<!-- iam-policy-tables:end -->`. Do not save policy anchors, headings, trust policy Version tables, Statement tables, or configuration tables as `desired.note.*` or additional resources.
- Omit separate Property/JSON/Version/Id metadata rows from derived displays for all services. Continue retaining the original configuration row's property and JSON link in the model, and Version/Id in the authoritative `desired.row.*.document`.
- When changing policies, update model `document` first, then generate and validate JSON artifacts and policy tables with the integrated task loop (`--write`). Independent read-only validation still rejects mismatches among properties, JSON, and displays.

## CloudFormation deployment policy

StackName normally omits numbers. The following are optional examples using numbers to distinguish multiple stacks with the same purpose. Model entry IDs `001`/`002` and StackName numbers are independent; do not append entry IDs to names.

```properties
desired.deployment.maxConcurrentStacks=2
desired.stack.001.name=cfn-stack-app-dev-job-01
desired.stack.001.template=job.yaml
desired.stack.001.parameters=job-01.json
desired.stack.001.deployOrder=10
display.stack.001.comment=日次集計jobを配置するstack
desired.stack.002.name=cfn-stack-app-dev-job-02
desired.stack.002.template=job.yaml
desired.stack.002.parameters=job-02.json
desired.stack.002.deployOrder=10
display.stack.002.comment=月次集計jobを配置するstack
```

- Use StackName as identity; do not combine separate stacks with the same template. Parameter files are stack-specific.
- The effective value when `MaxConcurrentStacks` is omitted is 1. Generated Markdown retains the effective value in hidden HTML comment `<!-- max-concurrent-stacks: N -->`, preserving restoration to the formal model value and mismatch detection. Specify it explicitly in new designs.
- Each stack requires a human-confirmed `DeployOrder`, validated by generation/validation/controller. Do not infer it from listing order. An explicit design/migration task changes the authoritative inputs while retaining existing entry IDs, names, templates, parameters, and comments, then generates and validates Markdown with the integrated write loop.
- The same DeployOrder and the same Template are allowed. Do not add `DependsOn`, `AfterStack`, `DependsOnStack`, or `Dependencies`.
- Display in ascending numeric DeployOrder, then ascending string StackName; No. is a sequential display number. Do not change model entry IDs or comment membership through sorting.

Deploy checks the signed Model dependency index and only the current execution slots' known Observed owners/consumers before delivery or ChangeSet creation, then checks ChangeSet removals before execution. The index and first-used Model snapshots are checked once per process through the shared session cache; saved READY state does not replace these checks. Physical identifiers and actual Outputs remain post-success checks. Bootstrap a missing index offline with `python framework/scripts/model/cli.py index --repository-root <project-root>`; Deploy never rebuilds it.

Canonical Model publication updates owner/reference metadata for desired changes and only file revisions for Observed changes, in the same rollback-protected transaction. Unchanged index content is not rewritten. Direct file edits outside the guarded Model publication API cannot guarantee index freshness: first-used snapshots are compared with the signed index, but newly added owners or incoming references in otherwise unselected Models cannot be detected completely without a full scan. After such edits, explicitly rebuild the index offline before Deploy; signature validity alone does not prove freshness.

### Resource-level CloudFormation identity

Resources created with CloudFormation retain confirmed `<StackName>-<template Resources key>` in the service model's own `desired.resource.<番号>.cfn-logicalId`. Split at the last hyphen, retaining hyphens within StackName. Template resource IDs cannot contain hyphens. Example:

```properties
desired.resource.005.resourceType=S3.Bucket
desired.resource.005.cfn-logicalId=cfn-stack-venusinf-dev-s3-cde-AuditLogBucket
desired.resource.005.logicalId=S3_Bucket_001
desired.service.identity.lastAllocated={"S3.Bucket":1}
```

The stack listing is generated from the same-target `cloudformation-stacks.properties`, retaining each fixed Stack ID and placementName.

Resource identity uses immutable typed logicalId; saved Resource references use original Markdown links and independent saved anchors. See [Resource logical identity](../docs/model-identity.md) for allocation, references and anchor preservation. Ordinary corrections validate the final entry/Row/Stack IDs and layout; dedicated operations preserve fields outside their explicit authority. Resource anchors are independent saved authority and are used by the common resolver to select producer Resources. Resource declarations select producerLogicalId; Stack/context selectors are unchanged.

CloudFormation CREATE resources with formal CFn types require explicit cfn-logicalId even when logicalId is present. Do not extend that requirement to IMPORT, Terraform or design-only types. Ordinary resolution has no old-ID/PascalCase fallback. Ambiguity is not permission to infer a mapping.

Markdown is a generated view and cannot be imported as Model authority. Preserve names, settings, observed values and their absence; do not derive identity from names, labels or display order.

## Properties-first updates and display generation

1. Before saving, check whether naming rules exist for resources to create, catalog selections, types/constraints, and unconfirmed values.
2. Update all confirmed environment-specific service properties first. Normally use `desired.service.*`, `desired.resource.*`, formal property `desired.row.*`, and required `observed.row.*`.
3. Directly validate schema/catalog mandatory root properties from authoritative properties per service. If any are missing, do not proceed even to temporary Markdown/JSON artifact generation; report resources/properties and retain properties and existing generated outputs. Continue processing other services. Temporarily generate Markdown and JSON artifacts only for services with all mandatory items, and check them with existing service display parsers, schema, and reference validation. Retain saved Markdown/JSON and edited models of failed services. If a referenced service failed, revert to saved displays and revalidate references. Do not restore models from Markdown.
4. Before saving, compute reference warnings on the final candidate stage, including the selected service's own links and retained incoming links. Preserve generated views when possible. Reference-only generation inability retains saved views and reports the affected NOT_RUN scope; it neither cancels source saves nor requires a repair Task. Actual write failures retain service rollback/journal recovery and dependent revalidation; preserve unrelated successful saves and return nonzero for real failures.
5. Run `python -X utf8 framework/scripts/blueprint-loop.py --mode task --write --task-file tasks/<task-name>.md` for ordinary Model edits. Common preconditions, all-target candidate generation/content validation, one all-target pre-save input comparison, publication, then output-dependent task/Acceptance checks execute in that validator process. No post-save regeneration, full readback/content validation or full input rescan is required. Independent read-only loops/validators retain saved-view equality checks. Do not overwrite properties.


Retain the H1 title (including `# ...`) in `display.service.title`. Write resource functions, purposes, and roles in Japanese in `display.resource.<番号>.comment`. For types without name properties, derive the resource type as the display name if exactly 1 independent resource of that type exists within the same service and neither a selected Name tag nor an existing confirmed display label exists. In this case, do not require `display.resource.<番号>.label` or duplicate the type name into label. Use `### <catalog-resource-type>` for detail headings, the resource type for listings/ordinary reference links, and the saved anchor. Retain human-confirmed display names distinguishing multiple resources of the same type, or existing confirmed display names, in `display.resource.<番号>.label`. Even with type-name display, retain model entry numbers and immutable logicalIds; do not infer IaC IDs from type names. This does not apply to omitted name properties or missing mandatory Name tags. Generate display names for types with name properties from formal row values; do not duplicate them. `display.*` is display input; do not add it to catalog AWS properties or IaC settings. Use existing 3-digit formats for resource and row numbers.

JSON bodies and inline JSON objects/arrays must contain meaningful AWS configuration
values, without Markdown Resource links, including `$resource` operands. Reuse external
`desired.reference.*`, `format=identifier` and JSON Pointer metadata for confirmed non-ARN
identifiers; never invent physical IDs or resolve confirmed literals again. Existing
producer integrity, change-impact analysis and warnings still apply. Source publication
and generation reject embedded Resource links with Model, Resource, Property and JSON
Pointer diagnostics. Do not automatically migrate/overwrite existing Models, introduce
new reference syntax, or save generated ARNs.
Ordinary URLs and legitimate non-Resource JSON strings remain valid. Resource links and
JSON artifact links outside JSON bodies remain supported.

For a CNAME `Route53.RecordSet.ResourceRecords` Resource link to an Interface
`EC2.VPCEndpoint`, optional `desired.reference.<id>.valueSelector=dns-entry[n].dns-name`
declares the zero-based `DnsEntries` entry and its DNS-name component. Use existing
resource/link metadata (including the exact saved text, occurrence, producer scope and
logicalId); do not change the saved row value or infer `n=0`. This selector is restricted
to these links, including an explicitly numbered ResourceRecords row. It does not extend
`$modelRef` or authorize links inside AWS JSON. Comparison requires Model/IaC CNAME and
Interface types, the same proven Producer and `Select(1, Split(":", Select(n, DnsEntries)))`,
with a unique same-scope Export. Missing selection, provenance or extraction proof remains
uncompared. Structural equality retains runtime Select-bounds uncertainty and
`current_aws_verified=false`; it never supplies an observed DNS value.

Rows with JSON links require `desired.row.<番号>.document`; reject duplicate JSON keys, invalid constants, and non-objects. Validate generated JSON directly against the projected document; do not store derived JSON Artifact hashes in the Model or require `artifactSha256`.

Model JSON retains typed `$modelRef` nodes as authority. `execution_document()` is the
design projection and preserves them. Generated artifacts use `generated_document()` to
resolve them through the common Reference Value Resolver; Markdown uses the same resolver.
Confirmed desired attributes can derive ARNs without observed values, including CREATE S3
BucketName. CREATE does not imply undeployed. AWS-generated identifiers require measured
values; never infer them. Observed PENDING_DEPLOY means the physical identifier is
unconfirmed, with identical reference resolution for CREATE and IMPORT: generated IDs
and ARNs requiring them are pending_deploy; ARNs derivable from confirmed attributes
remain resolved. PENDING_DEPLOY is invalid in desired values except the Mapping-defined
environment Values below. This does not change
resourceMode ownership, IaC/deploy eligibility or the approved Import acquisition flow.
Reject desired/observed conflicts rather than selecting one silently. Resolution reports
resolved/pending_deploy/unresolved with its cause and never writes values back to authority.
ARN assembly is shared with comparison, with ARN_SHAPES as the sole format definition.

Environment Value positions are defined only by `environment` metadata on AWS Mapping
properties. The common classifier handles CodeBuild PLAINTEXT Values, Lambda Variables
map Values, ECS container Environment Values, CodePipeline direct Values and encoded
Configuration EnvironmentVariables, and Glue's explicitly registered customer-driver /
customer-executor argument Values. Lambda Variables and ECS ContainerDefinitions are
Model-managed, displayed and acquired through their existing provider mappings.
CREATE and IMPORT have identical pending rules; neither mode proves deployment state.
A literal PENDING_DEPLOY with no identified dependency is allowed only in these Values
and retains an unknown-dependency diagnostic. Confirmed reference attributes retain their
real values; never guess IDs or query AWS at Model saving. Names, Types, ordinary IDs/ARNs,
CIDRs, whole JSON objects, secrets references and unrelated arguments gain no exception.
CodeBuild PLAINTEXT Resource links remain forbidden. Typed JSON references remain atomic;
ordinary JSON strings never become references through matching text.

Markdown and authoritative Model JSON retain these pending Values. Materialized AWS JSON
artifacts require resolved Values and fail only their owning service through existing
reference diagnostics. Desired Model/IaC comparison defers each pending Value and compares
confirmed siblings, including encoded JSON and quoted Glue assignments. Observations are
not a new comparison source. The decoded Stack Template/Parameters snapshot is checked
once before delivery/AWS submission. Existing CFn evaluation selects active conditions and
known parameter/mapping expressions; valid AWS-resolved references remain expressions.
A remaining environment PENDING_DEPLOY blocks that Stack, while independent peers at the
same DeployOrder may finish. The existing DeployOrder barrier, approval and execution
guards remain. No Model-wide load, persistent Deploy Session or repair history is added.
Unstructured scripts, UserData, Event/Scheduler inputs and SSM parameter payloads have no
blanket environment exception; unproven indirect paths retain their ordinary rules.

Independent AWS configuration/policy JSON has no CloudFormation execution context. The
AWS submission boundary rejects internal Model nodes, nested Fn::*/Ref, unresolved
AWS substitutions and dynamic references, including JSON encoded in strings. The existing
CFn evaluator may locally resolve supported expressions; unproven expressions retain their
design structure and warning and do not certify AWS readiness. Unresolved Model nodes fail
artifact generation for that service, reporting Model path, consumer/producer logicalId,
attribute, Property, JSON Pointer, status and cause. Other services continue; failed services
retain saved artifacts. Never guess missing values or persist generated ARNs.
Generation and policy display use the corresponding projected document;
validate candidates before publication. IAM Resource/NotResource must be strings or arrays
of strings. Legitimate IAM variables such as `${aws:username}` remain literal strings.
CloudFormation templates and their IaC comparison evaluator retain their own semantics.

Human-confirmed `display.resource.<番号>.label` for types without name properties is valid as a display name even if it is the same string as the internal logical ID. The validator matches `desired.resource.<番号>.resourceType`, `logicalId`, and explicit label of the same number against corresponding detail headings. Reject reuse of internal IDs without labels or substitution with labels from other resource types or logical IDs. Retain model entry numbers, saved anchors, and desired/observed namespaces and values. Do not create Name tags, catalog properties, or IaC settings from display labels.

During generation, arrange ordinary properties in catalog row order without changing model row numbers or saved order. Move contiguous groups of the same array while retaining internal element and field order. Track consumption of selected input row IDs in the existing display transformations; allow deliberate multi-row aggregation and exclude Mapping-hidden rows. Reject missing or duplicate consumption without constructing an intermediate Model. Check values and comments with transformation regression tests and saved-output comparison.

Generate service-specific abbreviated properties, CodePipeline index/Configuration expansion, CodeBuild variables, GuardDuty Features, CloudTrail recording targets, Security Group horizontal rules, KMS Alias displays within parents, and policy tables from models according to existing display rules. Use local table normalization for existing structural, schema and link checks; never reconstruct a whole Model for equality.

Create/update explicit properties candidates through the shared Model save API. Do not infer IDs, labels, comments or placement from generated views.

## Formal properties and display verification

- CloudFormation string properties use common dynamic-reference validation, including embedded/multiple references. Validate `secretsmanager`, `ssm` and `ssm-secure` syntax before deferring resolved-value constraints (`minLength`, `maxLength`, `pattern`, `enum`, `const`) to deployment. Preserve ordinary literal constraints, property/type/structure checks, and SSM secure-property restrictions in the local utils/cloudformation/schema.py constant. Reject malformed/unknown references and EC2 UserData usage. API-only properties do not acquire CloudFormation reference semantics.
- Offline validation never retrieves secret/parameter values or proves their existence, access permissions or resolved-value constraints. Keep existing Model/property checks and authorized AWS ValidateTemplate; this does not certify all template-level property constraints. This policy does not change source authority, IMPORT guards, publication checks.

The following local display normalizations support table, schema and link validation. They do not reconstruct the whole Model or compare it with authoritative inputs. Do not use Markdown as design input or overwrite formal properties rows in ordinary tasks.

- `Glue.Job.DefaultArguments` and `NonOverridableArguments` retain authoritative JSON objects; expand only displays into per-key rows such as `DefaultArguments["--job-language"]`. Generate `<!-- glue-arguments-source: [<元property>,<元value>,<表示行数>] -->` in the first row, and restore original JSON format, whitespace, key order, string values, and comments losslessly. Check markers against regenerated displays and reject modified keys, values, comments, membership, row counts, and missing markers. Unicode-escape JSON `|`, `<`, and `>` within markers. Display original rows for empty objects; reject non-objects, non-string values, and duplicate keys. Do not save display keys or markers to desired/observed.
- Generate numbered displays of object arrays, nesting, and scalar arrays across all services through common processing. Reappearance of a direct field starts the next object element; reappearance of a child array denotes the next child element of the same parent. Include JSON array expansion and items typed as arrays in schemas whose formal paths lack `[]`. Display empty arrays as containers.
- Generate `<!-- array-source: [<元の表示property>,<元value>,<表示行数>] -->` at the start of changed display-row comments. Unicode-escape JSON `|`, `<`, and `>`. Parsers first restore original rows from common markers and check them against all elements' properties, numbers, values, and comments regenerated by the same processing. Reject gaps, duplicates, 0-based or leading-zero numbers, missing or modified elements, invalid markers, and comments differing from original rows. Then expand existing service-specific abbreviated displays into formal properties. Do not save markers or numbers to desired/observed.

- Validate consecutive 1-based element numbers in `EC2.Instance` `BlockDeviceMappings[N].<field>` and restore formal `BlockDeviceMappings[].<field>`. Each element starts with `DeviceName`; reject duplicate fields within an element, 0, gaps, reverse order, and leading-zero numbers. Retain model row numbers, order, values, and comments.
- Restore generated `Name` display rows for `EC2.VPCEndpoint`/`EC2.Instance` into 2 formal `Tags[].Key`/`Tags[].Value` rows of the same resource type using `<!-- ec2-name-tag: [<Keyの元の値>,<Keyの元のcomment>] -->` at the comment start and displayed Value/comment. Metadata is a JSON string array; Unicode-escape `|`, `<`, and `>`. Retain case-sensitive Name for Key and reject missing markers, invalid membership, formats, or Keys. Do not save design-only `.Name` or metadata in the model. Retain tags other than Name and absence of Name tags in IMPORT.

## Properties format

### File size and service index

Follow [properties v2](../docs/model-format-2.md) for headers, whole-block parts,
strict JSON continuation and discovery. Initial conversion targets about600 lines;
a giant Resource may exceed600 lines in its own part. Ordinary edits preserve part names,
order, retained block placement and Row order. Append Resources without repartitioning.
Observation updates patch only their values and preserve unrelated bytes.
Use model/cli.py edit with an external complete properties candidate and explicit Task;
generate Markdown/JSON separately through the existing validation pipeline.

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py find model/<environment>/<target-directory>/<service-id>.properties '<logical-id-or-property-key>'
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py resource model/<environment>/<target-directory>/<service-id>.properties '<resource-number-or-logical-id>'
```

Use trace for source files/lines and derived origins. find returns matching locations;
resource returns one exact number/logicalId's authoritative group and source
locations, including parent/child/siblings, desired/display/observed/documents/references
and service metadata/notes. Unknown/ambiguous selectors fail. Do not write an extracted
subset or runtime projection back over the Model. Read required producers separately;
do not use generated Markdown as a fallback or expand every service into chat context.
Retain one generated Markdown per service and its full scoped validation. Read the final
diff; extraction alone is not schema/reference/generated-equality validation.

Restore `Config.ConfigurationRecorder.RoleName`, `EC2.RouteTableId`, `S3.Bucket.BucketEncryption.BucketKeyEnabled`, `S3.Bucket.BucketEncryption[].KMSMasterKeyID`, `S3.Bucket.BucketEncryption[].SSEAlgorithm`, and `S3.Bucket.LifecycleConfiguration.Rules[].NoncurrentVersionExpirationDays` used in Markdown configuration tables to formal properties through `framework/mappings/aws/<service>.yaml display.name` and save them in models. Do not save display names as model properties. Omit heading resource-type prefixes in Property columns.

Do not generate hidden `CodeCommit.Repository.RepositoryId` properties in models; also exclude them from identifier output reference detection. Retain RepositoryName and Markdown Resource link references in desired. Do not change the catalog.

Restore CodePipeline `Stages[N]` and `Actions[M]`, including single actions, to formal `Stages[]`/`Actions[]` in models, retaining original row order and membership per stage/action. Combine consecutive `Configuration.<Key>` rows of the same action into one formal `CodePipeline.Pipeline.Stages[].Actions[].Configuration` property, generating Value as a JSON object of original string values. Store confirmed AWS setting values under the corresponding JSON object keys and track Resource relationships with external reference metadata; do not restore them to CFn import expressions or Export names. Combine each key's Japanese comments with key names in occurrence order. Do not save display-only indexes or per-key Configuration properties as model properties. Do not rewrite original Markdown during generation.

During display validation, expand the single-row display `CodeBuild.Project.Environment.Variables[N].<Name>` into 3 formal `EnvironmentVariables[].Name`, `Type`, and `Value` rows of the same array element. For literals, use Type=PLAINTEXT and retain Value as-is. For resource links, restore Type from the hidden `codebuild-variable-type` marker at the start of `Source / Comment`. Retain Value resource links, confirmed display-text names/selectors, and literal `:` losslessly; do not convert to identifier output references or separate into observed. Do not save display-only `Variables.<Name>` or Type markers in models.

CodeBuild `Environment.EnvironmentVariables[].Value` with `Type=PLAINTEXT` must be a literal string. Markdown Resource links and structured `$modelRef` references are blocking ERRORs in both CREATE and IMPORT, regardless of producer type, attribute, existence or Model/IaC equality. Plain ARN/URL strings remain literals. The validator reports the Model/design path, Resource, variable Name, Type and Property; Issues saves these as numbered CodeBuild issues in `issues.md`. A missing display Type marker means PLAINTEXT and does not permit a Resource link. Never change Type or convert links automatically.

IaC GetAtt/Ref/ImportValue/Sub use their actual return semantics. Alias and Key identities and attributes remain distinct. Unproven targets, attributes and exports remain uncompared; an Export name literal is not its exported value.

During display validation, restore one-resource-per-row displays of `CodeBuild.Project.VpcConfig.Subnets[N]`/`SecurityGroupIds[N]` to multiple rows of formal `VpcConfig.Subnets`/`VpcConfig.SecurityGroupIds`, respectively, retaining resource links and order. Do not save display-only `N` as a model property.

Apply Subnet listing `[N]` displays commonly to all targets in `detailed-design.md`. Replace formal property suffix `[]` only for display, and restore per-element resource-link rows to multiple rows of the same formal property. Retain existing per-element separation rules for desired logical references and observed current identifiers; do not change order or row membership.

Split existing JSON arrays, single literals of properties ending in `[]`, and Secrets Manager comma-separated strings into per-element rows only for display. Generate `<!-- subnet-list-source: <元valueをJSON文字列でescapeした値> -->` at the start of the first display row's `Source / Comment`. Escape characters that break HTML comments/tables. Validation parsers verify equality of all displayed elements and comments using original values recorded in markers and restore exactly one original row. Retain model values, whitespace, presence/absence of backticks, desired/observed, and row numbers in their saved format. Markers are display-only; do not save them in models or notes. Do not require markers as human design inputs or overwrite authoritative inputs from Markdown.

During display validation, expand the single-row `GuardDuty.Detector.Features[N].<Name>` display into 2 formal `Features[].Name` and `Features[].Status` rows of the same array element. Do not save display-only `Features.<Name>` in models. Also number each level of `Features[].AdditionalConfiguration[]` in displays while retaining formal properties in models.

During display validation, expand one-recording-target-per-row displays of `CloudTrail.Trail.EventSelectors[M].DataResources[N].S3`/`.Lambda` into formal `EventSelectors[].DataResources[].Type` and `EventSelectors[].DataResources[].Values` while retaining row order. Retain the corresponding AWS resource type in `Type` and target resource links in `Values` for individual resource selections. If `.S3` Value is backtick-enclosed `All current and future S3 buckets`, generate `Type` as `AWS::S3::Object` and `Values` as JSON array `["arn:aws:s3"]` in desired. This ARN prefix is a design recording target; do not save it in observed. Do not save display-only selections, `N`, or abbreviated Type names as model properties/values.

Use UTF-8 `.properties` files. Output desired and observed in separate namespaces within one service model.

```properties
# Authoritative design values; Markdown is generated from these properties.
desired.service.vpc.serviceId=vpc
desired.service.vpc.ownedCatalogResourceTypes=EC2.VPC,EC2.Subnet
desired.resource.001.resourceType=EC2.VPC
desired.resource.001.logicalId=EC2_VPC_001
desired.service.identity.lastAllocated={"EC2.VPC":1}
desired.row.001-001.property=EC2.VPC.VpcId
desired.row.001-001.value=[vpc-app-dev](#vpc-vpc-app-dev)
desired.row.001-001.comment=VPCを一意に識別するID
observed.row.001-001.property=EC2.VPC.VpcId
observed.row.001-001.value=vpc-0123456789abcdef0
observed.row.001-001.comment=VPCを一意に識別するID
desired.row.001-002.property=EC2.VPC.CidrBlock
desired.row.001-002.value=10.1.0.0/16
desired.row.001-002.comment=VPCで使用するIPv4アドレス範囲
desired.row.001-003.property=EC2.VPC.Name
desired.row.001-003.value=vpc-app-dev
desired.row.001-003.comment=VPCを識別するNameタグの値
desired.note.001.text=実装注記: 必要最小限の注記
```

Specify resource and row numbers in authoritative Model inputs. Validate deterministic output order with saved-view comparison. Exclude `## リソース一覧` tables from Model inputs for all services as human-readable generated guides. Markdown property rows follow materials properties row order, omitting unselected/hidden items. Markdown retains model row order; do not move names or identifiers back to the beginning. Retain existing special display positions for design-only `.Name` and `S3.Bucket.Region`. Match `S3.Bucket` heading identifiers to BucketName; retain internal logicalId from hidden metadata. Missing identity markers are not permission to infer logicalId from BucketName. For identity-free grouped `S3.BucketPolicy.PolicyDocument` and formal `EC2.SubnetRouteTableAssociation.RouteTableId` displayed as `EC2.RouteTableId` in Markdown, do not create independent `desired.resource.*`; reflect them into the containing parent's `desired.row.*` with formal Property names. Resolve omitted `S3.BucketPolicy.Bucket` and `EC2.SubnetRouteTableAssociation.SubnetId` from containing parents; do not generate `EC2.SubnetRouteTableAssociation.Id` in models. For catalog `IDENTIFIER_OUTPUT` rows, generate the resource's own fully scoped Markdown Resource link into `desired.*` and Markdown current values into `observed.*` of the same row key. For Markdown link rows referencing identifier outputs too, retain fully scoped Markdown Resource links in `desired.*` and Markdown link display text into `observed.*` of the same row key. Retain Alias Markdown Resource links losslessly in `desired.*` for rows referencing KMS aliases. Policy JSON bodies are authoritative in document. Validate JSON syntax, native types, array order, AWS document constraints and generated content directly; do not generate a derived runtime document hash. Import approval, Deploy current-run input guards/unfinished-operation journals and file delivery integrity retain their separate SHA-256 evidence.

Follow [observed-values](observed-values.md) for identifier states and saving conditions.

Markdown/JSON artifact generation commands:

```console
python framework/scripts/sync-model.py --write --environment <environment> --alias <alias>
# aliasなしの場合:
python framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id>
```

## API-backed resources

- Include `framework/materials/api/*.properties` in the same catalog loading. Generate registered API resource types, including `Macie.ClassificationJob` and `QuickSight.Group`, logical IDs, anchors, and all design rows into existing `desired.*`.
- Determine API outputs from each catalog's `IDENTIFIER_OUTPUT`; retain logical references to self-anchors in desired and current non-ARN identifiers or `PENDING_DEPLOY` in observed. Ordinary Markdown links referencing API identifiers also use existing identifier reference processing. QuickSight Group `Arn` is hidden from persisted model rows; `PrincipalId` is a persisted non-ARN output.
- Retain inline JSON object/array values as-is, and retain existing paths for JSON artifacts. Do not add `clientToken`, `jobArn`, CFn mapping information, or creator information to models.
- For `bucketDefinitions`-type Macie Jobs, `bucketDefinitions` within model `desired.row.*.document` is authoritative for Job/account/bucket mappings. Generate same-service `S3JobDefinition` JSON artifacts and bucket mapping tables from model `desired.row.*.document`; do not save tables themselves as `desired.note.*` or additional resources. Models retain existing JSON links. Retain `scoping` as selected configuration within JSON; do not generate mapping tables for `bucketCriteria`-type Jobs.
- Do not use API resources' presence in service models to determine whether they can be created with CFn or are implemented. Resolve implementation availability from resource types to corresponding catalogs/schemas. QuickSight `Permissions[].Principal` may reference a Group anchor; the link represents its ARN output without persisting the ARN.

## Grouping

- `framework/rules/resource-layout.json` is authoritative for display relationships. Retain single children without identity, such as S3 BucketPolicy and Subnet Route Table Association, as parent resource rows.
- For children with identity such as KMS Alias, generate independent `desired.resource.<番号>.resourceType`, `logicalId`, `anchor`, and their own `desired.row.*` even within the same Markdown table. Place children after parents in occurrence order. Interpret hidden Markdown markers as structure; retain only Japanese descriptions in row comments.
- Derive KMS Key display names from `AliasName` of Aliases whose membership is verified through `parentReference`, removing the leading `alias/`. If there is 1 alias type, do not save derived display names in labels. If multiple types exist, require confirmed `display.resource.*.label` to match a name derived from one of the aliases. When reading multiple-alias displays in explicit migration, retain the selected display name in label. Do not convert AliasName desired values or KeyId desired/observed.
- Generate child `desired.resource.<番号>.parentProperty=KMS.Alias.TargetKeyId` and `parentReference=[S3FILETRANSFERKEY01](#kms-s3filetransferkey01)`. Restore omitted parent properties from this logical reference; do not fill using physical KeyIds or the first Alias. This is desired membership; do not add observed values.
- Lambda Permissions also retain independent desired resources and their own formal rows. Specify owning Functions through `parentProperty=Lambda.Permission.FunctionName` and `parentReference`, matching formal FunctionName row desired values. Restore Markdown `Permission.*` to formal `Lambda.Permission.*` and restore Id/FunctionName, each comment, and confirmed display names from hidden markers. Retain Id desired logical references/observed current IDs; do not save markers or abbreviated names as model properties.
- Retain child anchors and AliasName as-is in Alias references; do not convert to KeyId or separate into observed namespaces. When moving children, only parentReference points to the new owning parent; retain confirmed logical IDs and anchors.

- During display validation, read Security Group detail table Id, GroupDescription, selected GroupName, VpcId, and the owning SG's hidden security-group-tags metadata only once, and match them against authoritative model values. Map each Tags element to `Tags[].Key` and `Tags[].Value` while retaining order. Generate in order of Id, GroupDescription, selected GroupName, VpcId, and Tags; VPC references also use existing desired logical reference/observed current identifier separation. Do not generate tag metadata comments in desired.note.
- Security Groups without rules also have H3 headings and basic configuration tables; generate identification, VPC references, and selected tags into the same SG model. Do not fill rules or empty rule resources or change the next SG's anchors or membership.
- During display validation, read the single Security Group rule table and map Direction `Inbound`/`Outbound` to Ingress/Egress. Expand independent rules into existing grouped-resource formats and generate `parentProperty=EC2.SecurityGroupIngress.GroupId` or `EC2.SecurityGroupEgress.GroupId` and `parentReference` to containing SGs. Map hidden `rule-id` markers in Direction cells to formal property `Id`; map `security-group-id` markers to `SourceSecurityGroupId` for Inbound and `DestinationSecurityGroupId` for Outbound. Retain reference values losslessly; do not add visible columns or model metadata properties. Rule desired is a logical self-reference; observed is current ID/`PENDING_DEPLOY`. Distinguish multiple uncreated rules by logical IDs and anchors.
- Retain inline rules in the SG's own `EC2.SecurityGroup.SecurityGroupIngress[].<property>`/`SecurityGroupEgress[].<property>`; do not generate independent resources or Ids. Place Inbound then Outbound after SG attributes, in table row order within each direction. Place independent rules afterward in table row order. Keep one inline rule's properties contiguous and always place `IpProtocol` first. The next `IpProtocol` in the same array starts the next element; do not infer membership from presence/absence of optional properties.
- Expand `Port` into the same value for both FromPort/ToPort if single-valued, start/end values if a range, or type/code for ICMP `Type=n, Code=n`. Omit both properties for `—`. Retain expanded results in formal catalog properties of the independent rule itself or under inline rules; do not add a Port property to models.
- Do not generate properties for omitted horizontal-rule cells `—`. Retain reference links and selections; use common parser attribute descriptions for each property's Japanese comments. Do not add display column names such as Direction/Port, Types such as HTTP/HTTPS, rule-table headings, or identity markers to models.

- Map Markdown and properties one-to-one per AWS service ownership boundary, using the same Service ID, relative path, and file stem.
- Match both key and value of `desired.service.<service-id>.serviceId` to the file stem.
- In `desired.service.<service-id>.ownedCatalogResourceTypes`, comma-separate the same resource types as Markdown in the same order.
- Retain Markdown relative paths and explicit anchors of other-service resource references in `desired.*`. Separate physical IDs of identifier output references into `observed.*` of the same row key.
- Do not duplicate other services' values into referencing properties files.
- Existing or human-provided design inputs such as AWS managed-policy ARNs may remain in `desired.*` when needed.
- Default references to stable logical references within the same environment/target directory. Explicitly specify owning AWS accounts and connection methods for cross-account references in human designs; do not infer values.

- Even when changing to resource-name displays, retain existing internal IDs in `desired.resource.*.logicalId` and identifier logical-reference display text from hidden metadata. `desired.resource.*.anchor` retains resource-display-name-derived anchors; retain desired/observed separation. Do not use internal IDs for display links in human-readable Markdown.

Minimal properties format example (confirm names/purposes in target designs):

```properties
desired.service.logs.serviceId=logs
desired.service.logs.ownedCatalogResourceTypes=Logs.LogGroup
desired.resource.001.resourceType=Logs.LogGroup
desired.resource.001.logicalId=FlowLogs
desired.resource.001.anchor=logs-cwlogs-app-dev-flow
desired.row.001-001.property=Logs.LogGroup.LogGroupName
desired.row.001-001.value=cwlogs-app-dev-flow
desired.row.001-001.comment=ログを保存する名前
desired.row.001-002.property=Logs.LogGroup.RetentionInDays
desired.row.001-002.value=30
desired.row.001-002.comment=ログを保持する日数
display.service.title=# CloudWatch Logs 詳細設計
display.resource.001.comment=VPCの通信ログを保存するLog Group
```

## RotationSchedule grouped identity

Display `SecretsManager.RotationSchedule` in the same Markdown table as its parent Secret, but retain independent `desired.resource.*`, confirmed `display.resource.*.label`, display-name-derived anchors, and hidden logical IDs. Require `parentProperty=SecretsManager.RotationSchedule.SecretId` and `parentReference` to the Secret in the same model; formal SecretId desired rows also have the same logical reference exactly once. Id desired retains logical self-references; Id and SecretId observed retain current identifiers/`PENDING_DEPLOY`. Extract Id-row display-name prefixes and identity markers as structural information upon reparsing; do not mix them into attribute comments or desired.note. Also match formal SecretId row comments and observed losslessly; do not omit authoritative rows by filling from parent metadata. Limit to a maximum of 1 per parent Secret; do not treat identical `PENDING_DEPLOY` values of different parents as duplicate identity.

## CloudFormation S3配置

Optional settings in `cloudformation-stacks.properties`. Deployment buckets point to `S3.Bucket` anchors in the same target; link display names must match confirmed BucketNames in those models. The following names/paths are format examples; use human-confirmed values for actual targets.

```properties
desired.deployment.templateBucket=[app-dev-assets](s3.md#s3-app-dev-assets)
desired.deployment.templateKeyPrefix=cloudformation/templates/
desired.artifact.001.stack=cfn-stack-app-dev-job
desired.artifact.001.resource=FunctionA
desired.artifact.001.property=Code
desired.artifact.001.source=infra/cloudformation/artifacts/function-a.zip
desired.artifact.001.bucket=[app-dev-assets](s3.md#s3-app-dev-assets)
desired.artifact.001.keyPrefix=lambda/functions/
```

- TemplateBucket/TemplateKeyPrefix may be omitted as a pair. Stop if unset when required for large-template deployment.
- Artifact entries require all 6 fields; reject duplicates for the same stack/resource/property. Multiple entries may use the same source. Explicitly specify different buckets in each entry as well.
- keyPrefix is a relative prefix ending with `/`. Allow only alphanumeric characters, underscores, and hyphens in segments. Sources are repository-relative files; do not specify build commands, directories, credentials, or status.
- Mapping tables represent deployment inputs replacing S3 keys/versions with content hashes. Save per-execution hashes and versions only in sessions outside the repository. S3 models are authoritative for S3 bucket configurations/names; stack models have references only.
- Do not display TemplateBucket/TemplateKeyPrefix tables in generated Markdown; output to hidden `<!-- templateBucket: <value> -->`/`<!-- templateKeyPrefix: <value> -->` only when configured. Generate mapping tables under `## S3配置` and `### 配置ファイル` only if artifact mappings exist. Validate Stack displays structurally and compare saved outputs with generated candidates. Do not feed Markdown back. Retain existing unconfigured model/Markdown formats.

## Narrow DNS and IMPORT preparation references

Route53 CNAME ResourceRecords may retain a desired logical Interface Endpoint link and
its observed DNS value. Validate the DNS against the linked same-target Endpoint
Id and ServiceName; ordinary Endpoint identifier references retain their checks.
Explain the Endpoint with its confirmed Name tag link, separately from the DNS value.

For IMPORT preparation only, Config.ConfigurationRecorder.RoleARN and Firehose
S3DestinationConfiguration BucketARN and RoleARN may use the exact literal `Pending` for unconfirmed references. Do not save dummy ARNs
as observed. CREATE requires normal references; confirmed references, arbitrary ARN
literals and broken links retain normal validation. AWS_OWNED_CMK requires no KeyARN.

## Compact source fields

Observed property/comment are derived from desired metadata; only actual observed
values persist in the same properties. An absent observed.value key means unobserved;
empty string and PENDING_DEPLOY remain distinct. Fixed IDs, composition, placementName
and reference meaning stay explicit. Do not save derived metadata or runtime projections. See [Model source contract](model-templates.md#observations-and-fixed-identities).
