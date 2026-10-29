# Observed Values Rules
Model correction does not require the old Model to be valid or unchanged. IMPORT Resources may be acquired repeatedly and updated or corrected. Safety is determined by Task change authority, necessary Human consent and the final Model integrity. AWS acquisition remains exclusive to `/import`; ordinary `/update` may correct only the Resources and fields explicitly requested by the Human, without AWS acquisition authority. Dedicated merge/delete/retarget and value-preserving operations retain their own raw-value preservation checks.


## Dedicated import boundary

For `/import`, [IMPORT configuration authority](model-information.md#import-configuration-authority)
replaces the design validation/completion rules below: source and display transactions
are separate, and issues runs only when explicitly requested. Other workflows retain these rules.


## Identifier lifecycle

[Service Model templates](model-templates.md) defines the authoritative inputs.
Persist actual observations in environment/service properties; runtime Models
restore property/comment from desired metadata. Markdown and external JSON are generated outputs.

- Observed values are the minimum necessary machine-readable values obtained from the current deployment, not scenario evidence.
- Environment/service observed.row.*.value is the authority for observed values; generate detailed design catalog `IDENTIFIER_OUTPUT` rows and all references from it.
- `scenario-test` tasks may read runtime Models and authoritative source inputs but must not change them.
- Collect only values needed for follow-up configuration, links, connections, operations, and future task inputs.
- Valid examples include actually needed VPC IDs, Subnet IDs, Route Table IDs, Security Group IDs, EC2 Instance IDs, private/public IPs, DNS names, endpoint addresses, and hosted zone IDs.
- Do not save reference-derived generated ARNs in Model authority or `observed.*`. This does not prohibit ARNs resolved from formal Model references in generated Markdown/JSON Views or change existing permitted Human-specified/acquired ARN inputs.
- ARNs may be obtained transiently when AWS APIs require them.
- `QuickSight.Group.Arn` is an ARN output and is excluded through `HIDDEN_PROPERTIES`: retain its catalog marker for transient `QuickSight.DataSource.Permissions[].Principal` references, but never persist its value as a Model row or display it as an identifier row. Use the Group resource link and `GroupName` display label for the reference; generated Principal JSON may contain its resolved ARN.
- Human-provided design ARNs such as AWS managed-policy ARNs are not observed values and may remain in `desired.*` as necessary design inputs.
- Generated fields whose current values do not yet exist must be `PENDING_DEPLOY`; Markdown link display text for all properties referencing that identifier must also be `PENDING_DEPLOY`.
- `PENDING_DEPLOY` is prohibited for CIDR items such as `CidrBlock`, `DestinationCidrBlock`, and `CidrIp` in both detail tables and resource overviews. Display confirmed CIDRs even before deploy; ask the human if unconfirmed. The same applies to reference link display values and arrays, with no exception even for CIDRs marked as identifier outputs in the catalog. Retain PENDING_DEPLOY allowance for generated IDs such as `VpcId`.
- Retain current physical values only while resources currently exist. For replacement, reflect only new values in identifier output rows and all references.
- Do not transcribe past values into scenario evidence.
- Do not assume old IDs are current based only on old result files.

## Local mapping validation

- For child resources integrated into parent model rows without identity, resolve mappings from the parent type/parentProperty in `resource-layout.json` and the template's valid parent Ref. Validate the parent's CREATE classification, formal type, explicit cfn-logicalId, and child setting row existence; require Validation scope for deploy/observation operations; reject duplicate ownership of same-type children under the same parent. Do not require independent resource metadata or identifier rows for children or collect their physical IDs. Stop without guessing if parent references are unresolved or mismatched.
- Exclude `HIDDEN_PROPERTIES` not saved in models, such as `CodeCommit.Repository.RepositoryId`, from mandatory identifier row/Outputs validation and observed collection. Retain validation of other identifiers.
- Since Ref/Id return ARNs for `SecretsManager.Secret.Id` and `SecretsManager.RotationSchedule.Id`, existing `HIDDEN_PROPERTIES` exclude them from non-ARN identifier collection, mandatory Outputs, propagation, and display. The catalog `IDENTIFIER_OUTPUT` marker alone does not establish a persistable non-ARN identifier. RotationSchedule retains existing anchor/logical-id metadata and the formal SecretId parent logical reference; do not require Id rows. SecretId display uses the parent's confirmed Name; do not save reference-derived ARNs or fictitious IDs in Model authority, or add hidden identifier rows. Retain template Ref/GetAtt/ImportValue and transient ARN use at API time.
- `LakeFormation.Resource.Id`, `LakeFormation.PrincipalPermissions.PrincipalIdentifier`, and `LakeFormation.PrincipalPermissions.ResourceIdentifier` are likewise hidden from identifier collection, required rows and Outputs, propagation, and display because their values may contain ARNs. Preserve existing Model rows without collecting or rewriting them; retain CloudFormation Ref/GetAtt/ImportValue and resource ownership independently.

The CloudFormation controller directly matches each model resource's `cfn-logicalId=<StackName>-<Resources key>` using common implement/deploy validation in `model/adapters/observed.py`. Do not use a separate mapping table. Resource correspondence requires explicit cfn-logicalId and Stack identity. Exclude resources with direct IDs from name searches; do not fill invalid/missing IDs by fallback. Evaluate Conditions using stack-specific parameters/defaults and account/region/StackName; exclude false resources from matching, identifier validation, and ownership decisions. Stop for unresolved, cyclic, or non-boolean conditions. Stop with `AMBIGUOUS_OBSERVED_MAPPING` for mapped CREATE classification, formal type, uniqueness, or catalog row/Output/actual mismatches. Do not infer mappings from names, file order, or past physical IDs.

Local implement preflight needs no Task contract and validates only the explicit environment/target-directory/StackNames, including services outside an active Task Validation scope. This read-only exception does not extend to ordinary mapping, observed writes or destroy. Target-local ownership metadata reads do not authorize other Stacks or all-service quality validation.

Local implement preflight excludes formal resource types whose Model resources are all IMPORT without cfn-logicalId, including identity-free settings of an excluded parent. These resources require no creation mapping or identifier Outputs. Mixed CREATE/IMPORT types and unknown types retain strict mapping checks; explicit cfn-logicalId on IMPORT remains invalid. Conditions and integrated parent references are still checked. Deploy, deletion and observed synchronization retain full template ownership checks; local exclusion does not authorize creating or deleting IMPORT resources.

Confirm Output Value is the target logical resource's Ref (when the catalog's unique identifier corresponds to schema primaryIdentifier) or GetAtt of a formal attribute. Use PhysicalResourceId fallback only when the unique catalog identifier corresponds to primaryIdentifier. Other identifiers require formal GetAtt Outputs; reject generated ARNs.

## Collection and propagation

- Patch permitted observed.row.*.value fields first and regenerate Markdown with `framework/scripts/sync-model.py` only after AWS mutation in a successful `infrastructure` task or read-only retrieval of existing resources selected by the human in a `design` task.
- The explicit Model-only `/update` merge/delete branch may transfer already recorded observations or remove only the selected IMPORT observations, under its exact-diff guard; it performs no retrieval.
- Also treat `Macie.ClassificationJob.jobId` and `QuickSight.Group.PrincipalId` as persistable API catalog `IDENTIFIER_OUTPUT` values. In authorized design retrieval, use `DescribeClassificationJob` or `DescribeGroup` after the required human selection. Do not expand discovery to CFn Outputs or stack resources; do not persist Macie response `jobArn`, statistics, or execution status.
- Existing-resource retrieval directly reflects differences only for chatbot-selected properties into detailed design desired values and necessary non-ARN generated identifiers into observed values. Do not change unselected properties or resources.

Retrieve IMPORT settings and update their observed values only via the authorized import design workflow. Collection and output addition from CloudFormation/Terraform below apply only to CREATE; do not migrate to Stack/state management or change AWS settings for IMPORT.
- CloudFormation identifies target resources by detailed stack design StackName and the executed template's LogicalId, matching service detailed designs. Stop without guessing if mappings are ambiguous. Obtain necessary non-ARN identifiers from that stack's `Outputs`. Use stack resource `PhysicalResourceId` only when the target output is absent; confirm equality if both are available for the same logical resource. Even if multiple stacks use the same template/LogicalId, reflect them in separate design resource rows.
- Terraform obtains necessary non-sensitive identifiers from root module `output`. Read state resource attributes read-only only when target outputs are absent; confirm equality if both are available for the same resource.
- If necessary IaC outputs are missing, stop without IaC changes in the `deploy` phase. The `implement` or `update` phase adds only necessary outputs, retaining logical resource references in CloudFormation and resource attribute references in Terraform.
- Map retrieved identifiers to formal catalog `IDENTIFIER_OUTPUT` properties. Stop without guessing unless the mapping is unique.
- After updating observed rows corresponding to model identifier outputs, update observed values of all model rows referencing the same identifier to the same value. Generation updates Markdown link display text. Do not change reference source `Source / Comment`, link target paths, or anchors.
- After updates, regenerate Markdown and use the validator to confirm equality of identifier outputs and all references. Do not save reference-derived generated ARNs in Model authority or `observed.*`, secrets in any output, or old physical IDs as current observations.

Plan all updates and reference propagation and check task scope before writing observed only, then generate/validate per service with existing sync-model. Do not write models if ambiguity exists. On generation failure, retain models as the authority and retry synchronization in the same session.

Observed synchronization uses the same mappings validated before deploy and reconfirms them on resume with the immutable input guard and common validation. For Remove, validate the change set's formal type and mapping before execution even if the new template Condition is false or the resource is absent. Do not infer new owners during post-deletion synchronization; return identifiers and references to PENDING_DEPLOY only when physical destruction by Delete/Snapshot is confirmed. Retain them and stop for Retain/unknown policies.

## Destroy synchronization

- After destroy, return identifier output rows and all references to `PENDING_DEPLOY` and regenerate Markdown.
- Track obsolete physical IDs and past values in Git history, CloudFormation/Terraform, and AWS deployment history.

Explicit Stack destroy retains the existing rule: after destroy, return identifier output rows and all references to `PENDING_DEPLOY` and regenerate Markdown. Retained/DELETE_SKIPPED resources are reported; this does not introduce different identifier semantics for Stack destroy. The Remove/update retention rules above remain unchanged.

Before deletion, `model.adapters.observed.destroy_plan()` resolves explicit model-owned cfn-logicalId, catalog non-ARN identifier rows, incoming references and exact observation-bearing properties/generated Markdown/JSON paths using shared parsers/reference scanning. CREATE designs lacking cfn-logicalId may remain unimplemented: when their non-ARN observed output identifiers are absent or PENDING_DEPLOY, report them in unmappedResources and exclude them from ownership and synchronization. Legacy logicalId is not ownership evidence; do not infer a mapping or live absence. A resolved observed output identifier without cfn-logicalId remains a stop. Reject ambiguous ownership, out-of-target references, out-of-scope paths before mutation. No templates/parameters or deploy mapping path are used. Declare all possible paths first.

`sync_destroyed()` uses this saved plan and batches only stacks proven DELETE_COMPLETE by pinned session identity/deletion evidence. Fresh ALREADY_ABSENT, failed and unexecuted stacks never reset identifiers. Write observed only after success; preserve desired/display values, comments, links and anchors. Generate affected services once per batch. If generation fails, retain authoritative models and resume the same session; do not repeat completed deletion. Never persist generated ARNs or AWS execution state in models.

## Compact observation persistence

Store actual `observed.row.*.value` only. Runtime Models restore property/comment from
desired metadata and preserve every observed value without desired-value substitution.
An absent observed.row.<id>.value means unobserved. Distinguish empty string and PENDING_DEPLOY; do not create observation sidecars.
JSON/read errors, orphan rows and unknown states remain errors. Required observation
checks never treat unobserved as success. Keep the existing no-generated-ARN rule and
atomic publication/rollback; do not regenerate metadata or empty files during sync.

## Observation publication

Observation publication uses the shared Model API with an explicit Row allowlist.
Preserve non-observed fields, reference metadata, fixed placement and unrelated bytes.
General synchronization cannot change IMPORT physical identity. Model/display saves are
separate transactions. Deploy advances only permitted observations after checking the
complete snapshot; it never rebaselines concurrent design changes.
