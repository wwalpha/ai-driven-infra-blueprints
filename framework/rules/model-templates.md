# Service Model sources

Model correction does not require the old Model to be valid or unchanged. IMPORT Resources may be acquired repeatedly and updated or corrected. Safety is determined by Task change authority, necessary Human consent and the final Model integrity. AWS acquisition remains exclusive to `/import`; ordinary `/update` may correct only the Resources and fields explicitly requested by the Human, without AWS acquisition authority. Dedicated merge/delete/retarget and value-preserving operations retain their own raw-value preservation checks.

## Dedicated import boundary

For `/import`, [IMPORT configuration authority](model-information.md#import-configuration-authority)
and [08_import](../prompts/codex/08_import.md) own acquisition, full Review, explicit
conversational save consent and separate Model/display transactions. Ordinary Import
never adds naming/global-design/generated-equality/local-loop/UT/IT gates.
Framework development checks are separate.

## Authority and layout

The stored entrance is `model/<environment>/<target-directory>/<service>.properties`.
Alias takes precedence over awsAccountId for the directory. awsExecutionAccountId is
execution context only. Resolve environments, aliases and services from project.json
and existing Model entrances using the scope selected at task start. Environment names
inside saved strings are ordinary literal values, with no environment context reference
metadata, inference or automatic substitution. Only executionAccountId context declarations
are accepted. Never merge aliases sharing an account or create Models
merely because a target is registered.

Each environment explicitly stores all its service values. There are no templates,
parameter YAML, bindings, observation sidecars, inheritance, overlays or expressions.
project.json retains topology/account/Region/profile authority. Markdown/JSON are generated.
The full [v2 format](../docs/model-format-2.md) is the storage/schema authority.

## Properties and parts

Data files begin with `# model-format: 2`. A large service entrance additionally has
`# model-index: 2` followed by ordered `# part: <service>/part-NNN.properties` lines.
Each part has its own format header. Assemble all parts before duplicate-key checks.
Keep each owning Resource/Row/document/reference/observed block together; keep Stack
blocks whole. Initial conversion targets about600 lines. A giant Resource owns a whole
part and may exceed600 lines.

Ordinary corrections may repair part names/order, block placement and Row order. Validate
the complete final file set. Dedicated operations preserve layout outside their declarations. Observation saves never reflow/repartition the Model.
Reject unsafe/symlink/missing/duplicate/unregistered parts, split blocks and unknown versions.

Only document and backtick JSON object/array values allow explicit trailing-backslash
continuation outside JSON strings. No trailing spaces, string newlines, implicit
continuation, intermediate comments, EOF or cross-part continuation. Insert JSON
whitespace between fragments and perform strict duplicate-key/nonfinite-constant checks.
Other scalar bytes, quoting, spaces, backslashes and numeric-looking strings are retained.

## Generation, tracing and scope

Use the single `framework/scripts/model/cli.py` through run-python.py for read, resource,
find, trace, render, incoming, Import, observations, AWS comparison, audit.
Imports use model.*; do not dynamically load the same file under another module name.
The public API and helper contracts are [documented here](../docs/model-helper-integration.md).

The reader returns full authoritative fields separately from runtime projections.
Serializer and save guards always include reference and placementName.
Use shared input recording/cache within an invocation; retain fresh prepublication checks.
Read dependencies never grant write permission. Record raw bytes, absence, file sets,
project and actual producer dependencies. Scope and Allowed paths are checked independently.

Generate ordinary design views through the existing classified validation pipeline.
Model-only intermediate source publication and final validation are separate. A reference
semantic WARNING does not excuse syntax, scope, native type, evidence, identity or I/O errors.
Never reconstruct design authority from generated Markdown/JSON or projected values.

## New service creation

Explicitly prepare a complete properties candidate outside the repository, including
service metadata, confirmed Resource/Row identities, desired values and existing observations.
Use candidate_base only for explicitly requested candidate creation; normal load_model
still fails for an absent service. Validate the target and record its entrance absence,
parts discovery set and dependencies. Publish the complete service once through the
shared capability-based save API. Do not persist empty initial authority first.

## Observations and fixed identities

Final Resource/Row/Stack IDs, logicalId, resourceMode, cfn-logicalId, parent relationships
and placementName must be valid. Ordinary authorized corrections may change them. Dedicated
operations and observation writers retain their narrower preservation rules.
observed.value absence, empty string and PENDING_DEPLOY are distinct. Derive observed
Derive observed Property/comment from desired at read time; never save them. JSON documents have no derived runtime hash.

General observed saves change only explicitly permitted Rows and preserve all other
canonical fields and unrelated raw bytes. They do not bypass IMPORT physical-ID protection.
Design digest excludes observed but includes display/reference/placementName. Complete
snapshots additionally include observations, original bytes, file sets, project and actual
read dependencies. After a Deploy observation save, advance only the permitted delta;
do not absorb concurrent desired/display/reference changes into the session baseline.

## IMPORT Property source edits

The LLM matches acquired records and asks the Human for necessary selections. Python
acquires/normalizes and verifies acquired values, correspondence, full Review, candidate,
scope and snapshot; it does not choose an overwrite target or orchestrate services.

add allocates new fixed Resource/Row IDs and shared typed logicalIds/counters in IMPORT mode. refresh keeps
the same physical identity. bind/replace require the explicit existing IMPORT target and
validated before physical ID. Preserve type/mode/logicalId/placement, existing Row ownership
and metadata, native JSON types and array order, unacquired Properties and nonselected
Resources. No implicit deletion or CREATE conversion.

Reference proposals are optional. An explicit map is the complete after map; an empty
map proposes deletion. Do not merge the before map back into it. Determine owners from
consumerKey; moves check both owners and deletions check the old owner. Protect every
nonselected owner. Re-extract candidate metadata and compare it with the full Review,
including reference-only semantic changes even when the saved value is unchanged.

Read-only incoming analysis for bind/replace never calls a CREATE mutation guard.
Keep semantic warnings; propagate malformed metadata, I/O and scope violations.
Accumulate the whole service candidate and all acquired-record Reviews before one save.
Model and receipt rollback together. Save generated views afterward in a separate
transaction. A display failure keeps the Model and permits recover-display without
acquisition, new Import or renewed consent for unchanged approved content.

## Model-only intermediate sources

Use the running parent's managed worktree and its exact Task/scope/path authority.
The Task adapter issues a one-use SourceWriteContext. prepare_edit validates the final
canonical structure. Dedicated operations check raw-field preservation and layout; ordinary
edits do not require the old Model to load. publish_edit compares fresh inputs,
Task/HEAD/worktree ownership, locks and journals the exact candidate. Neither policy
names nor approved flags confer authority. All commands use this shared save boundary.

Each successful leaf save survives a later failed leaf. Intermediate saves do not
complete/generate/merge or add unconditional final design validation. retarget retains
its required pre-save operation check. One import-delete parent owns its named sources
and declared repairs; perform all leaves before one generation/final-integration phase.
The final latest-base comparison proves every pair/deletion and retained configuration,
observation, identity, composition and reference position across the full candidate.
Integration consumes the same validated HEAD/base/Task; no force/skip alternative exists.

## Reference usage and dependency detach

Metadata describes the actual saved consumer string occurrence; it never regenerates it.
Trace direct links and declared resource/stack/context references, including JSON leaf
pointers and incoming consumers. Raw name reads desired; identifier reads observed;
KMS grouped display is used only by the existing display rule. Conflicting declared and
direct-link producers remain separate meanings with a WARNING.

Incoming analysis is read-only and target-scoped. Keep fixed producer identity even when
names match; use existing immutable read contexts. Invalid metadata ownership/position,
syntax, I/O and scope remain errors. An unfinished journal stops read-only analysis.

Value-preserving detach requires its exact existing Task declaration and surviving IMPORT
consumer. Keep saved native values and every undeclared meaning unchanged, and remove
only the declared dependency metadata. Direct links still represent dependencies; merely
removing metadata does not detach them. Use the named retarget/delete operation for
other explicit reference changes. Preserve retained refids; never renumber them on reorder.

Resource allocation and Markdown reference semantics follow [Resource logical identity](../docs/model-identity.md). The common allocate function owns new CREATE/IMPORT counters; dedicated acquired/operation preservation uses preserve_allocation. Ordinary explicit repairs validate final IDs/counters without old allocation invariance. Publish counters and additions atomically. Preserve independent saved Resource anchors and original Markdown links. Read-time logicalId fallbacks remain forbidden.
