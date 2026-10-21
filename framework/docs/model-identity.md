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
