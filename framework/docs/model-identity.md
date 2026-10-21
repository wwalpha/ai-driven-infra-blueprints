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

## Saved references and anchors

The internal fixed identity is typed logicalId. The independent saved
`desired.resource.<number>.anchor` is the design link destination. Preserve it when
names, physical values or logicalId allocation change. New anchors use the existing
`design_layout.resource_anchor()` and confirmed naming rules, without speculative suffixes.

Save the original Markdown Resource reference, for example
`[lmda-venusinf-dev-inbound-detect](lambda.md#lambda-lmda-venusinf-dev-inbound-detect)`.
Keep its label, relative path and fragment unless that occurrence is explicitly retargeted.
Self links, parentReference, JSON string leaves and `$resource` operands, templateBucket
and artifact buckets follow the same rule. Do not convert them to Resource URIs.

`model.identity.parse_reference(value, consumer_scope)` uses the existing safe
`model.references.link_scope()` to locate the producer scope. `Resolver(root, reads).resolve(
value, consumer_scope)` validates project topology and finds the Resource by its saved
anchor, sharing a snapshot and anchor index. Processing then uses its fixed entry number
and typed logicalId; never infer a Resource from labels, names, or generated Markdown.
Missing or duplicate anchors are semantic reference warnings. Syntax, scope and I/O errors
keep their existing classification; no additional save gate is introduced.

Resource declarations retain producerLogicalId, fixed refids, scope and occurrence.
Stack/context selectors are unchanged; no per-link migration declarations are needed.
Ordinary web URLs, JSON artifact links and descriptive note links are not Resource selectors.
Generate design `<a id>` and Resource links from the saved anchors, independently of
logicalId comments. Preserve observed display and value-resolution responsibilities.

AWS JSON resolves explicit operands to confirmed attributes. A bare Resource link needs
an unambiguous receiving-property contract; a policy operand may use
`{"$resource":"[bucket](s3.md#s3-existing-bucket)","$attribute":"Arn"}`.
Unavailable or ambiguous values remain unresolved; never emit a Markdown reference as an
AWS value or save generated ARNs into authority. Actual `s3://bucket/key` destinations
are unchanged. Already converted consumer data requires a separate restoration task
using pre-conversion properties or confirmed version-controlled originals.

`cfn-logicalId` independently retains `<existing StackName>-<existing Resources key>`.
CloudFormation CREATE with a formal CFn type requires it even when logicalId exists.
This requirement does not extend to Terraform, IMPORT or design-only types without CFn types.
No normal CFn resolver substitutes logicalId for cfn-logicalId.
