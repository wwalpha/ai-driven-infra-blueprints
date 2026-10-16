# Service Model templates
IMPORT desired configuration changes are exclusive to `/import`; follow [IMPORT configuration authority](model-information.md#import-configuration-authority). Read/compare remains allowed. Value-preserving source refactors are allowed; CREATE workflow is unchanged. Ordinary design, aws-check and update must delegate substantive IMPORT changes to import and cannot bypass the mechanical evidence guard.


## Dedicated import boundary

For `/import`, [IMPORT configuration authority](model-information.md#import-configuration-authority)
replaces the design validation/completion rules below: source and display transactions
are separate, and issues runs only when explicitly requested. Other workflows retain these rules.


## Authority and layout

Every service uses YAML-only authoritative inputs. The common service template is
`model/templates/<target-directory>/<service>.properties.tpl`; each created environment
service directory `model/parameters/<environment>/<target-directory>/<service>/` contains
`parameters.yaml` and fixed `bindings.json`. Optional `observed.json` holds actual observed values. Service directory identities,
including bindings-only instances, define discovery. Missing or broken inputs fail;
uncreated project environments may have no service directory.

`model/<environment>/<target-directory>/<service>.properties` is a logical API selector,
not a stored file. Models expand directly from authoritative inputs at runtime.
Markdown and external JSON remain generated outputs. One service template aggregates
its resources across CFn stacks. This contract applies to this repository only.

## Fixed version 1 syntax

```properties
# model-template: 1
# definition: role
# parameter: Name string
# parameter: Anchor string
# parameter: Placement string
# resource: role
# row: name role
desired.resource.role.resourceType=IAM.Role
desired.resource.role.anchor=<<Anchor>>
desired.resource.role.cfn-logicalId=<<Placement>>
desired.row.name.property=IAM.Role.RoleName
desired.row.name.value=<<Name>>
desired.row.name.comment=ロール名
# end-definition
```

```yaml
instances:
  lambda:
    parameters:
      Name: app-dev-role
```

The matching bindings.json declares lambda's definition and the existing fixed resource
and row maps; Anchor and Placement are internal parameters, not public YAML inputs.
Use described # parameter declarations for public inputs and # internal for fixed maps.


Use separate definitions for service metadata and named resource groups. Keys remain
existing Model keys, with declared local resource/row IDs replaced by explicit fixed
maps. Each row declares its local owner. `<<Id_role>>` and `<<Anchor_role>>` resolve
local identity/anchor after remapping. Existing cross-service logical links remain
explicit strings. No ID comes from list order/count. Definitions may contain parent
and child resources; parentReference uses the same existing link contract. Notes,
display fields, resourceMode and engine identity fields are ordinary preserved keys.
A service metadata definition may explicitly declare `# retained-display: 037` to
preserve fixed `display.resource.037.comment` or `.label` with no corresponding
resource. The ID is a fixed numeric metadata identity, never a resource mapping.
Undeclared fixed display keys, other fields, duplicate declarations/identities and
collisions with active resource IDs are rejected. Retained display declarations use only existing
orphan display IDs; they preserve values without inventing resource definitions.

Undeclared local IDs, duplicate output keys/anchors/identities, broken references,
unknown input keys/definitions/parameters and missing used parameters are errors.
Unused definitions require no environment values. Parameter types are `string`,
`integer`, `number`, `boolean`, `object`, `array`, `null` (booleans are not integers).

Variable expressions use only `<<Name>>` substitution, using Pystache 0.6.8 with strict
missing tags and identity escaping. Mustache sections, partials, lambdas, unescaped
forms, delimiter changes and executable code are unavailable. `${...}` and
`{{resolve:...}}` remain AWS strings. Parameter strings are never reparsed as templates.
JSON `.document` is parsed first; exact placeholder nodes preserve JSON types, embedded
placeholders accept strings only; keys cannot be templated. JSON is emitted by the
JSON serializer. Properties scalar values must remain one line (CR/LF and other
Unicode line separators are rejected); multiline JSON strings are escaped safely.
There is no overlay or whole-definition override.

Use one definition for the same resource role across environments within an alias.
Values and selectable relationships belong in declared inputs; an environment name
does not select a definition or execute template code. Different aliases may retain
different definitions. When a common resource shape has explicitly designed optional
fields, declare their presence with a boolean input:

```properties
# optional: desired.resource.role.logicalId HasLogicalId
# optional-json: desired.row.policy.document /Statement/1 HasExtraStatement
# choice: desired.row.name.value {"parameter":"UsesReference","value":"<<SelectedRole>>"}
```

Each directive names an existing property and a declared boolean parameter. `optional`
omits the property when false; `optional-json` omits the existing JSON pointer target.
`choice` uses its declared alternate expression when true, otherwise the property's
ordinary expression. A choice may also declare `pointer` to replace a JSON node with
the declared alternate JSON value. Selectors require explicit booleans, including when
the containing property is omitted. Missing or unknown inputs, invalid pointers,
overlapping removals and multiple selected alternatives for one node are errors.
These directives do not compare dev/stg names or interpret parameter strings.
JSON pointers apply to `.document` and backtick-wrapped JSON objects/arrays in `.value`;
annotated JSON values use the same typed substitution and serialization contract.
Only parameters used by the selected shape are accepted. Resource/row maps must match
that shape exactly and preserve explicit IDs; omission never allocates new identities.

Templates may use the existing `# model-index: 1` / `# part:` rules, with the same
600-line bound and sequential part names under `<service>.properties/`. The template
parser validates each definition before using the existing splitter.
Templates retain the bounded entry/part convention; logical Model selectors retain service identities.

## Generation, tracing and scope

All shared Model readers expand authoritative YAML sources and merge observed values.
`sync-model.py --write` publishes Markdown and JSON in one rollback-protected service
batch after existing Model/catalog/schema/reference validation. Read-only validation
rejects stale views. Observed updates publish only observed.json and authorized generated
views.
Generation validates every candidate, including unchanged sidecars. Only outputs whose
publication bytes differ from existing files require reservations and enter publication;
preserve existing Markdown newline conventions when comparing. Under the publication
lock, recheck source snapshots, output differences and write reservations immediately
before saving. A previously unchanged output that now differs requires its own writable
reservation; never overwrite it without authorization. Keep each service's changed
outputs in one rollback-protected batch, without restoring excluded unchanged outputs.
All saves retain exclusion locks, input snapshots, atomic publication and rollback.
`model_files.py <service.properties> --trace <exact-key>` reports definition/key and
instance/parameter keys on demand; no permanent source map is saved.

`model_templates.py --alias <alias> --service <service> --affected` lists registered
consumers. A common template edit requires ALL its direct registered consumers in
Validation scope; a parameter/binding/observed edit requires its environment/service.
Downstream services enter scope only when an active resource reference changes its
resolved value or selected identity/type. Compare selected definitions and optional/choice
branches against the managed task's pinned start (HEAD for unmanaged tasks), including
staged and unstaged inputs. Compare each downstream reference before propagating again;
an unchanged exported reference stops the chain. Ignore unused definitions and unselected
references. Missing baselines, claimed changes without a known diff, and missing,
ambiguous or cyclic reference results cannot justify exclusion: retain conservative
service dependency scope or include the unresolved consumer for validation.
Uncreated services have no inputs; an existing incomplete source is an error.
Scope precision does not weaken source-byte hashes, caches, immutable plans, publication
snapshots or IMPORT authority. Input hashes include authoritative template entry/parts,
YAML parameters, bindings, observed and producer dependencies; old validations/plans
cannot survive source changes. Validation/ generation across environments never changes Deployment
scope, account, AWS permissions, delete/replacement approval or existing IaC placement.

## Human input format (YAML-only)

The required filename is `parameters.yaml`. The YAML/bindings schemas validate input format and reject invalid/missing YAML, unknown fields and missing mandatory inputs.

External parameters are independent values that vary by environment or instance.
Common fixed settings belong directly in the template, without parameter declarations
or defaults. Derived names belong in template expressions using existing `<<Name>>`
substitution; parameter strings are never interpreted as expressions. Fixed resource
relationships belong in template references; only selectable targets are public inputs.
Do not infer fixed settings from accidental equality or hide settings in bindings.

```yaml
parameters:
  AvailabilityZone1: ap-northeast-1a
  AvailabilityZone2: ap-northeast-1c
instances:
  main-vpc:
    parameters:
      CidrBlock: 10.10.0.0/23
```

Shared declarations precede definitions and are defined once per service template.
`# input` defaults to `source:service`, reading the top-level YAML parameters.
`source:consumer.environment` reads the registered consumer directory's environment;
there is no manual Environment input. `source:consumer.executionAccountId` reads the
registered target through the existing local topology validator, selecting
`awsExecutionAccountId` or `awsAccountId` when absent. It is a raw string, cannot be
overridden in YAML/bindings, and project.json enters trace, source hashes and impact. Definition-local `# parameter` reads instance
parameters. The sources are disjoint: a shared/context/reference name cannot be
redeclared or overridden by an instance. Unused shared declarations are errors.

```properties
# input: Environment {"type":"string","description":"登録されたconsumerの環境名","required":true,"source":"consumer.environment"}
# definition: MainVpc
# parameter: CidrBlock {"type":"string","description":"VPCのIPv4ネットワーク範囲","required":true,"format":"literal","constraints":{"cidr":"ipv4"}}
# internal: Anchor string
# resource: vpc
# row: name vpc
# row: cidr vpc
# row: dns vpc
desired.resource.vpc.resourceType=EC2.VPC
desired.resource.vpc.anchor=<<Anchor>>
desired.row.name.property=EC2.VPC.Name
desired.row.name.value=`vpc-venusinf-<<Environment>>`
desired.row.cidr.property=EC2.VPC.CidrBlock
desired.row.cidr.value=<<CidrBlock>>
desired.row.dns.property=EC2.VPC.EnableDnsSupport
desired.row.dns.value=`true`
# end-definition
```

The fragment above illustrates substitutions; include existing required comments/metadata
in actual Models. Declare each shared AZ once and use it only in its placement definitions.
Shared fragments are raw strings. Put Model literal backticks around the completed value,
e.g. `` `/aws/vpc/flow-logs<<FlowLogSuffix>>` ``. Do not format Environment/Suffix before
concatenation. Empty, hyphen-prefixed and slash-prefixed suffixes are retained exactly;
there is no separator normalization, recursive calculation or override hierarchy.
`format:literal` remains available for an entire scalar instance input such as CIDR,
never for a shared fragment. JSON document substitutions retain their original types.

Structured declarations provide description, type, required, optional default and
constraints (enum, full-match pattern, minimum/maximum, length, strict IPv4/IPv6 CIDR).
Required inputs are not hidden by defaults. YAML uses a safe loader and rejects duplicate,
non-string and merge keys. on/off/yes/no, dates and leading-zero integers remain strings.
Unknown fields, missing values, constraint violations and types are rejected without coercion.

Template references use existing Model links/anchor validation:

```properties
# reference: Vpc {"instance":"main-vpc","resourceType":"EC2.VPC"}
# reference: LoggingRole {"service":"iam","resource":"075","resourceType":"IAM.Role"}
```

Fixed producer IDs are explicit logical Model identity, never a physical AWS ID or a
completed name repeated in YAML. Resolve the producer's authoritative name/anchor;
missing, ambiguous or type-mismatched targets fail. Producer source bytes enter hashes,
immutable snapshots and consumer impact. Public `type:reference` parameters remain
available for actual target selection; local instance names resolve only under this
explicit type. External selectable references use declared service/type and a logical Model resource ID,
requiring exactly one target. Completed producer names are never selector inputs. No AWS is used.

For a JSON scalar that requires the producer's raw BucketName, use the same typed
external S3 reference with `format:name`:

```properties
# reference: Bucket {"service":"s3","resource":"001","resourceType":"S3.Bucket","format":"name"}
```

This resolves the authoritative BucketName without a Model link or literal formatting;
interpolate `<<Bucket>>` into the JSON string or format the completed Model value in
the template. It uses the existing named external producer resolver and rejects
unnamed producers and label overrides; local instance references remain links.
Ordinary references retain their links and existing labels. The same
producer type, uniqueness, dependency snapshots, hashes and impact checks apply.
The same format applies to named producers such as `IAM.Role.RoleName`,
`Glue.SecurityConfiguration.Name`, `Lambda.Function.FunctionName` and
`CloudTrail.Trail.TrailName`. Names remain unformatted fragments: assemble paths
such as `/aws-glue/jobs/<<Configuration>>-role/<<ExecutionRole>>/error` and apply
Model literal formatting only to the completed value.

For a raw producer identifier in a JSON scalar, declare its exact non-ARN catalog
identifier-output property on an external typed reference:

```properties
# reference: VpcId {"service":"vpc","resource":"001","resourceType":"EC2.VPC","format":"identifier","property":"EC2.VPC.VpcId"}
```

This requires one desired identifier row and its matching authoritative observed row.
It removes Model literal formatting and retains the string exactly, including
`PENDING_DEPLOY`; it never falls back to a desired name/link or queries AWS. Missing,
duplicate, mismatched, non-string and ARN identifiers and label overrides fail.
Producer observed inputs retain the existing snapshot, hash and impact tracking.

`parameters.yaml` lists only instances with public, instance-local inputs. Instances
whose definition has no public inputs (including service metadata) are omitted entirely;
do not write empty `parameters: {}` blocks for them. Their existence and definition
are explicit in the existing `bindings.json` instance list. For example, the `flow-log`
binding declares `definition: FlowLogStackPlacedFlowLog` alongside its unchanged internal
maps and values. All instances, including `main-vpc`, declare their definition solely in
bindings. YAML instance entries contain only `parameters`; a definition in YAML is an
unknown field, never an override or fallback. Missing bindings/definitions, input-bearing
instances without YAML inputs, unknown definitions and identity collisions are errors.
Omitting a no-input instance from YAML never removes its resource. Saving inputs resolves
parameter order from the binding's definition without writing it back into YAML.

`bindings.json` holds the complete instance composition, fixed resource/row maps, anchors,
IaC placement, original reference labels and differing annotations. It contains no desired
setting overrides. Resource count/presence comes from explicit instance lists and
declared boolean field presence, without environment-name branches or if/for generation.
Observed stays exclusively in observed.json; artifact hashes
for YAML consumers are derived from each expanded row document with the
existing canonical JSON hash contract. Saved hashes are regenerated; they are not
independent inputs or binding values. Input serialization and dependency digest
contracts remain unchanged. Neither names, environment, suffix nor list
order allocate IDs. Logical instance names and physical resource names are distinct.
Rename a public input instance and its binding together; rename a binding-only instance
in bindings. Update template/reference selectors explicitly and preserve maps. Adding or
deleting a binding-only resource requires an explicit binding change and consistent
references/observed; deleting YAML input alone cannot silently delete an input-bearing
resource. Shared template relationships may refer to public or binding-only instances.

Edit parameters.yaml for independent values; edit the shared template for fixed settings,
derived expressions or logical relationships. Normally do not edit bindings.

```console
python3 framework/scripts/model_templates.py --alias cde --service vpc --environment dev --inputs
python3 framework/scripts/model_files.py model/dev/cde/vpc.properties --trace desired.row.001-003.value
python3 framework/scripts/sync-model.py --write --environment dev --alias cde --service vpc
python3 framework/scripts/model_parameter_inputs.checks.py
```

Trace uses existing placeholders to show descriptions/current values/destinations,
explicit input sources and fixed references; no duplicate hand-maintained mapping.
`save_parameters(model_path, inputs)` validates and writes readable YAML under existing
reservation and atomic publication guards. Saving follows the YAML input contract and declared parameter order. Common template changes require all registered
consumers in Validation scope; local inputs/bindings require their own consumer.

## New service creation

Declare a service template, human `parameters.yaml`, explicit `bindings.json`, and
optional `observed.json` only when values exist under the target source directory. Reserve those inputs and the generated Markdown/JSON paths. `model_templates.py --create --environment <environment> --alias <target-directory> --service <service>`
validates the YAML and fixed bindings. It rejects invalid/missing inputs.
Run normal sync and the scoped local loop before completion. This repository's input
contract is YAML-only; no other repository is asserted to have adopted this contract.

## Compact observed and fixed bindings

Persist only `observed.row.<fixed-row-id>.value` in `observed.json` version 1.
Expand observed property/comment from the corresponding desired row; never derive an
observed value from desired. Values keep the existing one-line string contract, so
false, zero, an empty string, null text and an absent observation remain distinct.
Native JSON booleans/numbers/null are invalid values, rather than missing observations.
An absent observed file means unobserved; an invalid JSON document, permission failure,
unknown state/key or orphan row is an error. Required observed identifiers still stop
when unobserved/PENDING_DEPLOY. Writers verify metadata equality, omit it on disk, and
remove empty observed files within the existing atomic, locked rollback transaction.
Input guards include absent optional files and producer dependencies.

Only empty `labels` may be omitted from an instance binding; omitted labels mean an
empty reference-label map. Nonempty labels and all required definition/resource/row/
internal-parameter fields retain their strict validation. Writers/fixtures omit empty
labels; neither omission nor shared definitions infer fixed IDs or instance presence.

Share a definition within one alias/service for the same resource role, preserving
parameter meanings, resource types and row owners. Environment-specific values,
annotations, source forms and field presence use declared inputs and explicit shape
directives; they do not require dev/stg-specific definitions.
Update explicit binding definition references without changing instances or fixed maps.
Keep distinct definitions for different roles even if expanded values happen to match.
Add only inputs needed to preserve real differences; do not split service sources by CFn stacks.


## IMPORT Property promotion

AWS-confirmed values are authoritative only for selected IMPORT Properties. The importer
first reuses provable independent parameter updates. A fixed/shared expression mismatch
then promotes only that Property to an instance parameter in its common Definition,
without changing fixed instance maps or introducing value-only private Definitions.
Use existing schema types (string, integer, number, boolean, object, array, null), typed
JSON document/node expansion and literal serialization; format: literal also supports
object/array/null as a complete scalar, never a fragment or document placeholder.

Only when a Property is promoted, enumerate direct users of its Definition and evaluate
that Property's old expression from local inputs. Preserve CREATE and other instances'
values; never traverse service references or expand entire foreign Models for comparison.
Keep unrelated declarations and YAML inputs. Remove an old input only when the required
rewrite removes its last use. Unrepresentable expressions fail with Property provenance.
Acquired non-secret ARN strings are values; generated ARNs and secrets remain forbidden.

The acquisition scope stays one environment/target/service. Save planned Model sources
in one guarded journal transaction; then generate and publish only that service's views
in a second transaction. Display failure retains saved Model. Recheck source snapshots,
reservations, output collisions and hashes; do not perform candidate validation or
source/view equality validation. Unchanged Model can regenerate stale displays. Explicit
issues remains responsible for design/input/reference and generated consistency checks.
