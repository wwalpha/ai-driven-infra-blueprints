# Machine-readable Service Model Rules

## Model authority

If updating the model fails, do not update Markdown/JSON. The model is authoritative for design values, names, and descriptions.

- Follow [Topology](project-configuration.md#topology) for target directories.
- Place human-readable current designs in `docs/designs/<environment>/<target-directory>/`.
- Place machine-readable service models in `model/<environment>/<target-directory>/`.
- CloudFormation stack detailed designs retain each stack's name, template filename, parameter filename, and positive integer `deployOrder` in `desired.stack.*` of `cloudformation-stacks.properties`, and target policy in `desired.deployment.maxConcurrentStacks` (integer 1 or greater). Generate Markdown with the same stem. `DeployOrder` is a formal design value for each stack instance, not template identity or a dependency field. Do not add policy to `project.json`. Generate listing `No.` and retain `Comment` in `display.stack.*.comment`. Do not save stack execution state, StackId/ARN, or values temporarily retrieved from AWS in the model.
- Catalog properties are authoritative for selectable items; model properties are authoritative for desired and observed values. Markdown and JSON artifacts are generated outputs for display and use.
- Codex saves confirmed designs in `model/` first. Treat human manual edits to model properties as design inputs as well. `framework/scripts/sync-model.py --write` generates Markdown/JSON artifacts without overwriting the model.
- Fail the local loop if Markdown and the authoritative model do not match. Do not silently adopt either one.
- Save a successfully validated service even if its anchor changes break saved old links in other services. Warn about new breaks with the referencing source and link; the source's authoritative repair and regeneration may be performed in a separate task. Do not automatically add related services to generation scope or manually edit saved displays of failed services. The generation target's own reference, schema, and model matching remain mandatory; a local loop whose validation scope includes a service with broken links fails.
- After saving model properties, design tasks generate Markdown and JSON artifacts in the same coherent logical change. When selected existing resources were retrieved read-only, also generate required non-ARN current identifiers in `observed.*`.
- Follow [observed-values](observed-values.md) for current identifier update conditions and propagation.
- The infrastructure `update` phase treats human-changed model properties as immutable inputs and generates Markdown before deployment. Update observed identifiers and regenerate Markdown only after successful AWS mutations.
- `framework/rules/detailed-design.md` is authoritative for Markdown structure, service grouping, and generated identifier rows.

## Service display inputs

- Derive the `IAM.Role` display name only from confirmed desired rows of formal `IAM.Role.RoleName`, and use it in listings, detail headings, and reference links. Require exactly 1 RoleName row and reject missing, duplicate, empty, or unconfirmed values. Do not substitute Name tags or `display.resource.*.label`; retain internal logical IDs and policy artifact naming.
- Use `## リソース一覧` and `## リソース詳細` as display section boundaries, and generate No. Listing Comments are authoritative in `display.resource.<番号>.comment`; Stack listing Comments are authoritative in `display.stack.<番号>.comment`. Do not treat them as AWS properties. H3 resource headings under the detail section retain display names; identify internal logical IDs from hidden `resource-logical-id` metadata immediately before anchors. For existing formats without markers, the heading identifier can be read as internal identity. Do not output hidden markers to notes or properties; exclude H4 policy tables as derived displays. Do not change resource numbers, anchors, logical IDs, or desired/observed values through heading hierarchy changes alone.

- Retain Name tags for `EC2.VPCEndpoint`/`EC2.Instance` in desired rows using each resource type's formal `Tags[].Key=Name` and corresponding `Tags[].Value`. Do not add design-only `.Name`. Name tags are mandatory for CREATE; reject case differences, missing Values, empty or unconfirmed values, and do not substitute display labels. Listings, headings, ordinary reference links, and anchors use that Value; retain internal logical IDs in hidden metadata and the separation of existing desired logical references/observed IDs for identifier references. Retain VPC/Subnet/RouteTable/Flow Log .Name displays.

- Retain Security Groups and their Ingress/Egress in `security-group.properties`, and generate `security-group.md`. Use `security-group` for service metadata and anchor prefixes. Do not mix other EC2 resources into this model.
- Retain ConfigurationRecorder RoleName displays and KDF BucketARN/RoleARN in desired as resource links displaying confirmed names of referenced resources. If a referenced IAM role name starts with `AWSService` (example: `AWSServiceRoleForConfig`), do not require an IAM Role design or link; retain the role name literal in the formal ARN property's desired value. Do not change formal ARN properties to name properties or generate/save ARNs. Separate KDF KeyARN into a logical reference to the actual KMS Key in desired and the displayed KeyId/PENDING_DEPLOY in observed according to existing identifier reference rules.

## Resource management mode

- Allow only `desired.resource.<nnn>.resourceMode=CREATE` or `IMPORT` for resource-level framework metadata. Reject empty values, alternative spellings, and unknown values. Treat existing resources without a specification as CREATE; do not infer conversion to IMPORT. Explicitly specify the category in new designs.
- CREATE covers new creation and IaC generation based on the framework, retaining existing naming conventions and mandatory Name policy. Do not change to IMPORT merely by retrieving current values after creation.
- IMPORT is the category for incorporating existing resources into design management; retain retrieved, selected actual/current configurations in `desired.row.*` and required non-ARN current identifiers in `observed.row.*`. Do not change AWS resources; exclude them from IaC generation. This is not CloudFormation Resource Import/Terraform import.
- Categories are not provenance such as creator, administrator, or externally created status. Retain the contract prohibiting saving provenance.
- Exempt IMPORT from framework-specific naming conventions, coverage, and mandatory Name tags, and retain existing names, configurations, and presence/absence of Name tags. Do not rename, add/change tags, or fill values. Retain provider schema, catalog, row structure, reference, and confirmed-value validation.
- Retain existing VPC/Subnet/RouteTable/Flow Log Name tags in the existing `.Name` and Endpoint/Instance tags in formal Tags rows. For IMPORT without a Name tag, omit that row. Use human-confirmed `display.resource.<nnn>.label` for display only when needed; do not copy it into AWS properties or tags. A single resource of the above 6 types named only by Name tags may use the existing type-name display if no label exists either.
- Retain resourceMode only in authoritative properties; do not generate `resource-mode` comments in Markdown. Ordinary display validation references the same service model by anchor to obtain the CREATE/IMPORT validation category. Do not mix it into AWS property tables or desired.note. Specify identified grouped children independently using their own anchors too. Inline configurations without identity follow their containing resource's category; if a separate category is needed, stop without inferring it.

## Policy derived views

- Retain policy/configuration JSON bodies as compact JSON in each service model's `desired.row.*.document`. Generate service-owned JSON from JSON artifact links in `desired.row.*.value`, and generate policy tables from that JSON. Do not feed JSON artifacts or tables back as design inputs.
- Do not duplicate in the model the generated ResourceName/Comment table in the resource listing or displays within `<!-- policy-tables:start -->`–`<!-- policy-tables:end -->` and IAM's `<!-- iam-policy-tables:start -->`–`<!-- iam-policy-tables:end -->`. Do not save policy anchors, headings, trust policy Version tables, Statement tables, or configuration tables as `desired.note.*` or additional resources.
- Omit separate Property/JSON/Version/Id metadata rows from derived displays for all services. Continue retaining the original configuration row's property and JSON link, and the canonical hash of the entire JSON including Version/Id, in the model.
- When changing policies, update model `document` first, then generate JSON artifacts and policy tables together with `sync-model.py --write`. The local loop rejects mismatches among properties, JSON, and displays.

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
- Reject old models without `DeployOrder` and old 5-column Markdown in generation/validation/controller. Do not infer from listing order or automatically migrate in ordinary deployment. Humans confirm the order; an explicit design/migration task adds values while retaining existing entry IDs, names, templates, parameters, and comments, then regenerates with sync-model. Do not overwrite existing models through Markdown import.
- The same DeployOrder and the same Template are allowed. Do not add `DependsOn`, `AfterStack`, `DependsOnStack`, or `Dependencies`.
- Display in ascending numeric DeployOrder, then ascending string StackName; No. is a sequential display number. Do not change model entry IDs or comment membership through sorting.

### Resource-level CloudFormation identity

Resources created with CloudFormation retain confirmed `<StackName>-<template Resources key>` in the service model's own `desired.resource.<番号>.cfn-logicalId`. Split at the last hyphen, retaining hyphens within StackName. Template resource IDs cannot contain hyphens. Example:

```properties
desired.resource.005.resourceType=S3.Bucket
desired.resource.005.cfn-logicalId=cfn-stack-venusinf-dev-s3-cde-AuditLogBucket
desired.resource.005.anchor=s3-venusinf-dev-audit-log-639200939566-cde
```

The stack listing remains authoritative in `cloudformation-stacks.properties`. Resource mappings `desired.mapping.*` and generated `## Resource対応` tables are discontinued and rejected when used. When migrating existing models, set StackName and template IDs to human-confirmed values; do not infer them from names.

Handle new-format internal resource identity using service + 3-digit entry number and anchor; do not require engine-common `logicalId`. Do not save `cfn-logicalId` for Terraform. Limit CFn fields to CREATE and formal CFn types, referencing registered StackNames. New-format identifier self-references and same-service parent references use `[<entry番号>](#<anchor>)`. Identify referenced resources by anchor. Do not change display labels, formal names, or existing JSON artifact paths.

Manage resource numbers, resourceMode, and CFn identity in authoritative properties; do not output `resource-entry`/`resource-mode`/`cfn-logical-id` comments to generated Markdown. Ordinary Markdown reparsing uses authoritative model anchor-to-number mappings; do not infer numbers from display order or add generic logicalId. Apply the same convention to grouped children. Models with old logicalIds also use authoritative numbers. Reject anchors absent from the model, missing/modified resources or rows, and mismatches between saved Markdown and deterministic generation results. Retain validation of CREATE/IMPORT and CFn ID formats, CREATE/formal CFn types, stack registration, and template Resources key mappings using the model as input.

Only explicit migration's `--import-markdown` may validate and import old `resource-entry`/`resource-mode`/`cfn-logical-id` comments. Do not overwrite existing models. Reject import of new-format Markdown without comments because numbers, categories, and CFn identity cannot be restored from it alone; retain the authoritative model. Do not infer/fill metadata from resource names, display labels, or display order. Follow existing conventions for read compatibility of the old logicalId format.

Retain old `desired.resource.*.logicalId` and hidden logical ID markers only for read compatibility with existing models. Old models without CFn IDs may use legacy matching only when formal types and old IDs/mechanical PascalCase conversions are unique within the target. Exclude resources with CFn IDs from this legacy search; do not supplement invalid/missing direct mappings through names. If a stack has direct IDs, require direct IDs for all its valid resources.

## Properties-first updates and display generation

1. Before saving, check whether naming rules exist for resources to create, catalog selections, types/constraints, and unconfirmed values.
2. Update all confirmed service model properties first. Normally use `desired.service.*`, `desired.resource.*`, formal property `desired.row.*`, and required `observed.row.*`.
3. Directly validate schema/catalog mandatory root properties from authoritative properties per service. If any are missing, do not proceed even to temporary Markdown/JSON artifact generation; report resources/properties and retain properties and existing generated outputs. Continue processing other services. Temporarily generate Markdown and JSON artifacts only for services with all mandatory items, and check them with existing service display parsers, schema, and reference validation. Retain saved Markdown/JSON and edited models of failed services. If a referenced service failed, revert to saved displays and revalidate references. Do not restore models from Markdown.
4. Before saving, also validate retained referencing sources in the same target; if candidate generated outputs newly break links that resolved in saved displays, restore the referenced service's generated outputs. Report the target service, referencing source, and link, and revalidate candidates after restoration. Distinguish existing reference errors from new breaks. Save successful services' Markdown and JSON artifacts together. Also revert to original displays on write failure and revalidate retained referencing sources and saved candidates by the same criteria. Unrelated successful services may be saved, but if failures remain, report per-service errors and return a nonzero command-wide exit code. Keep the model authoritative and ready to rerun.
5. The local loop compares read-only generation results with saved displays. Do not overwrite properties.

Retain the H1 title (including `# ...`) in `display.service.title`. Write resource functions, purposes, and roles in Japanese in `display.resource.<番号>.comment`. For types without name properties, derive the resource type as the display name if exactly 1 independent resource of that type exists within the same service and neither a selected Name tag nor an existing confirmed display label exists. In this case, do not require `display.resource.<番号>.label` or duplicate the type name into label. Use `### <catalog-resource-type>` for detail headings, the resource type for listings/ordinary reference links, and an anchor derived from the type name. Retain human-confirmed display names distinguishing multiple resources of the same type, or existing confirmed display names, in `display.resource.<番号>.label`. Even with type-name display, retain model entry numbers and anchors or old-format hidden logical IDs; do not infer IaC IDs from type names. This does not apply to omitted name properties or missing mandatory Name tags. Generate display names for types with name properties from formal row values; do not duplicate them. `display.*` is display input; do not add it to catalog AWS properties or IaC settings. Use existing 3-digit formats for resource and row numbers.

Rows with JSON links require `desired.row.<番号>.document`; reject duplicate JSON keys, invalid constants, and non-objects. Artifact hashes are derived values that can be checked during generation; do not make them authoritative design values.

Human-confirmed `display.resource.<番号>.label` for types without name properties is valid as a display name even if it is the same string as the internal logical ID. The validator matches `desired.resource.<番号>.resourceType`, `logicalId`, and explicit label of the same number against corresponding detail headings. Reject reuse of internal IDs without labels or substitution with labels from other resource types or logical IDs. Retain new-format model entry numbers or old-format hidden logical ID markers, display-label-derived anchors, and desired/observed namespaces and values. Do not create Name tags, catalog properties, or IaC settings from display labels.

During generation, arrange ordinary properties in catalog row order without changing model row numbers or saved order. Move contiguous groups of the same array while retaining internal element and field order. Ordinary matching parsers expand displays into formal properties and map back to original model row numbers by resource numbers and occurrence order of each property. Do not use values, comments, or observed values as mapping conditions; verify equality after mapping and reject omissions, additions, or modifications. In explicit Markdown import without an authoritative model, number rows in display order as before.

Generate service-specific abbreviated properties, CodePipeline index/Configuration expansion, CodeBuild variables, GuardDuty Features, CloudTrail recording targets, Security Group horizontal rules, KMS Alias displays within parents, and policy tables from models according to existing display rules. Use validation parsers only to expand displays into formal properties and verify lossless equality.

Adopt existing Markdown only in explicit migration tasks by running `sync-model.py --import-markdown --write`. Do not overwrite existing models. Do not create labels for type-name displays of independent single resources of a type without name properties, or infer other missing display labels/comments. Do not automatically migrate in ordinary design/infrastructure tasks.

## Formal properties and display verification

The following display expansions are reverse-conversion rules for validating displays generated from properties and adopting them in explicit migration. Do not use Markdown as design input or overwrite formal properties rows in ordinary tasks.

- `Glue.Job.DefaultArguments` and `NonOverridableArguments` retain authoritative JSON objects; expand only displays into per-key rows such as `DefaultArguments["--job-language"]`. Generate `<!-- glue-arguments-source: [<元property>,<元value>,<表示行数>] -->` in the first row, and restore original JSON format, whitespace, key order, string values, and comments losslessly. Check markers against regenerated displays and reject modified keys, values, comments, membership, row counts, and missing markers. Unicode-escape JSON `|`, `<`, and `>` within markers. Display original rows for empty objects; reject non-objects, non-string values, and duplicate keys. Do not save display keys or markers to desired/observed.
- Generate numbered displays of object arrays, nesting, and scalar arrays across all services through common processing. Reappearance of a direct field starts the next object element; reappearance of a child array denotes the next child element of the same parent. Include JSON array expansion and items typed as arrays in schemas whose formal paths lack `[]`. Display empty arrays as containers.
- Generate `<!-- array-source: [<元の表示property>,<元value>,<表示行数>] -->` at the start of changed display-row comments. Unicode-escape JSON `|`, `<`, and `>`. Parsers first restore original rows from common markers and check them against all elements' properties, numbers, values, and comments regenerated by the same processing. Reject gaps, duplicates, 0-based or leading-zero numbers, missing or modified elements, invalid markers, and comments differing from original rows. Then expand existing service-specific abbreviated displays into formal properties. Do not save markers or numbers to desired/observed.

- Validate consecutive 1-based element numbers in `EC2.Instance` `BlockDeviceMappings[N].<field>` and restore formal `BlockDeviceMappings[].<field>`. Each element starts with `DeviceName`; reject duplicate fields within an element, 0, gaps, reverse order, and leading-zero numbers. Retain model row numbers, order, values, and comments.
- Restore generated `Name` display rows for `EC2.VPCEndpoint`/`EC2.Instance` into 2 formal `Tags[].Key`/`Tags[].Value` rows of the same resource type using `<!-- ec2-name-tag: [<Keyの元の値>,<Keyの元のcomment>] -->` at the comment start and displayed Value/comment. Metadata is a JSON string array; Unicode-escape `|`, `<`, and `>`. Retain case-sensitive Name for Key and reject missing markers, invalid membership, formats, or Keys. Do not save design-only `.Name` or metadata in the model. Retain tags other than Name and absence of Name tags in IMPORT.

## Properties format

### File size and service index

- Each model properties file has a maximum of 600 lines. At 600 lines or fewer, retain the existing single file; do not inflate it with blank lines. Split bodies exceeding 600 lines into approximately 550-line parts. The last part may have fewer than 500 lines.
- The service entry remains `model/<environment>/<target-directory>/<service-id>.properties`; when split, make it an index containing only `# model-index: 1` and ordered entries starting with `# part: <service-id>/part-001.properties`. Place bodies under `<service-id>/` in the same target; both the index itself and each part must have 600 lines or fewer.
- Parts are not new services. Generate the same existing service Markdown/JSON from one authoritative model concatenated in index order. Do not change service IDs, resource/row numbers, logical IDs, anchors, key/value content or order, or desired/observed separation. Index comments are storage-format metadata, not AWS properties.
- Reject missing parts, duplicate/invalid order, references to other services, path traversal, symlinks, nested indexes, parts unregistered in the index, duplicate keys after concatenation, and more than 600 lines. Do not infer independent services from part filenames. Ordinary `sync-model.py --write` does not change models/indexes/parts.
- When saving new models, determine destinations with `model_file_contents(path, text)` in `framework/scripts/model_files.py`. Physically split existing models only in explicit design or migration tasks, including entries/parts in Validation scope and Allowed paths, by executing the following. Splits without design changes are migration; retain the unresolved issue gate. Do not automatically split immutable infrastructure update inputs.

```console
python framework/scripts/model_files.py model/<environment>/<target-directory>/<service-id>.properties --split
python framework/scripts/model_files.py model/<environment>/<target-directory>/<service-id>.properties --find '<logical-id-or-property-key>'
python framework/scripts/model_files.py model/<environment>/<target-directory>/<service-id>.properties --resource '<resource-number-or-logical-id-or-anchor>'
```

- To save tokens, read the entry index first, then only required parts using files/lines from search results. `--find` outputs matching line locations containing keys or identifiers as `絶対file path:行番号:key`; it does not batch-output values such as long JSON. Edit designs in the target parts after splitting, and validate equality of all parts and generated displays within the same service scope.
- When updating existing resources, partially read authoritative inputs with `--resource` without loading full Markdown or all model parts into chat context. Select exactly one by exact match of number (such as `001`), logical ID, or anchor; unmatched or ambiguous selection fails. Support both single files and entry indexes, displaying original values and order as `絶対file path:行番号: key=value`. This is read-only; do not overwrite the entire model with its output.
- Extraction includes target resource metadata, display settings, desired/observed rows, and selected JSON documents. Follow same-service parent/child relationships through `parentReference`, also including parents, children, and siblings in the same display group. Children without identity are retained as parent rows. Include all service metadata and common `desired.note.*` notes because resource membership cannot be inferred. Do not output unrelated resource details.
- Retain ordinary reference links as extracted rows; do not automatically expand referenced services or other resource details. Additionally read references required for changes using their owning service's `--resource`; when changing names, anchors, or identifiers, check referencing sources with `--find` or searches outputting only locations. Changes to referencing sources retain active task scope.
- Edit relevant sections of authoritative files shown in extraction, and generate Markdown/JSON per service. Read change diffs after generation. Retain one human-readable Markdown per service, and do not omit existing local validation of the entire target service. Do not treat extraction alone as completed schema, reference, or generation-equality validation.

Restore `Config.ConfigurationRecorder.RoleName`, `EC2.RouteTableId`, `S3.Bucket.BucketEncryption.BucketKeyEnabled`, `S3.Bucket.BucketEncryption[].KMSMasterKeyID`, `S3.Bucket.BucketEncryption[].SSEAlgorithm`, and `S3.Bucket.LifecycleConfiguration.Rules[].NoncurrentVersionExpirationDays` used in Markdown configuration tables to formal properties through `framework/rules/display-property-aliases.json` and save them in models. Do not save display names as model properties. Omit heading resource-type prefixes in Property columns.

Do not generate hidden `CodeCommit.Repository.RepositoryId` properties in models; also exclude them from identifier output reference detection. Retain RepositoryName and resource-anchor references in desired. Do not change the catalog.

Restore CodePipeline `Stages[N]` and `Actions[M]`, including single actions, to formal `Stages[]`/`Actions[]` in models, retaining original row order and membership per stage/action. Combine consecutive `Configuration.<Key>` rows of the same action into one formal `CodePipeline.Pipeline.Stages[].Actions[].Configuration` property, generating Value as a JSON object of original string values. Retain resource links losslessly as string values of the corresponding JSON object keys; do not restore them to CFn import expressions or Export names. Combine each key's Japanese comments with key names in occurrence order. Do not save display-only indexes or per-key Configuration properties as model properties. Do not rewrite original Markdown during generation.

During display validation, expand the single-row display `CodeBuild.Project.Environment.Variables[N].<Name>` into 3 formal `EnvironmentVariables[].Name`, `Type`, and `Value` rows of the same array element. For literals, use Type=PLAINTEXT and retain Value as-is. For resource links, restore Type from the hidden `codebuild-variable-type` marker at the start of `Source / Comment`. Retain Value resource links, confirmed display-text names/selectors, and literal `:` losslessly; do not convert to identifier output references or separate into observed. Do not save display-only `Variables.<Name>` or Type markers in models.

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
desired.resource.001.logicalId=vpc-app-dev
desired.resource.001.anchor=vpc-vpc-app-dev
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
desired.row.001-004.artifactSha256=<linked-json-sha256>
desired.note.001.text=実装注記: 必要最小限の注記
```

Specify resource and row numbers in model properties and validate the same order upon display reparsing. Exclude `## リソース一覧` tables from model generation for all services as human-readable guides. Markdown property rows follow materials properties row order, omitting unselected/hidden items. Markdown retains model row order; do not move names or identifiers back to the beginning. Retain existing special display positions for design-only `.Name` and `S3.Bucket.Region`. Match `S3.Bucket` heading identifiers to BucketName; retain internal logicalId from hidden metadata. If markers are omitted, use BucketName as logicalId. For identity-free grouped `S3.BucketPolicy.PolicyDocument` and formal `EC2.SubnetRouteTableAssociation.RouteTableId` displayed as `EC2.RouteTableId` in Markdown, do not create independent `desired.resource.*`; reflect them into the containing parent's `desired.row.*` with formal Property names. Resolve omitted `S3.BucketPolicy.Bucket` and `EC2.SubnetRouteTableAssociation.SubnetId` from containing parents; do not generate `EC2.SubnetRouteTableAssociation.Id` in models. For catalog `IDENTIFIER_OUTPUT` rows, generate the resource's own anchor-based logical reference into `desired.*` and Markdown current values into `observed.*` of the same row key. For Markdown link rows referencing identifier outputs too, generate anchor links displaying logical IDs into `desired.*` and Markdown link display text into `observed.*` of the same row key. Retain Markdown links displaying AliasName losslessly in `desired.*` for rows referencing KMS aliases. Policy JSON bodies are authoritative in document; retain in `desired.row.*` the SHA-256 of parsed JSON deterministically serialized with object-key order, no whitespace, and UTF-8. Do not change hashes for changes only to whitespace, indentation, line breaks, LF/CRLF, trailing file newlines, or object-key order.

Follow [observed-values](observed-values.md) for identifier states and saving conditions.

Markdown/JSON artifact generation commands:

```console
python framework/scripts/sync-model.py --write --environment <environment> --alias <alias>
# aliasなしの場合:
python framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id>
```

## API-backed resources

- Include `framework/materials/api/*.properties` in the same catalog loading. Generate `Macie.ClassificationJob` resource types, logical IDs, anchors, and all design rows into existing `desired.*`.
- Determine `jobId` from that catalog's `IDENTIFIER_OUTPUT`; retain logical references to self-anchors in desired and current IDs or `PENDING_DEPLOY` in observed. Ordinary Markdown links referencing Job IDs also use existing identifier reference processing.
- Retain inline JSON object/array values as-is, and retain existing paths and canonical hashes for JSON artifacts. Do not add `clientToken`, `jobArn`, CFn mapping information, or creator information to models.
- For `bucketDefinitions`-type Macie Jobs, `bucketDefinitions` within model `desired.row.*.document` is authoritative for Job/account/bucket mappings. Generate same-service `S3JobDefinition` JSON artifacts and bucket mapping tables from model `desired.row.*.document`; do not save tables themselves as `desired.note.*` or additional resources. Models retain existing JSON links and canonical hashes. Retain `scoping` as selected configuration within JSON; do not generate mapping tables for `bucketCriteria`-type Jobs.
- Do not use Jobs' presence in service models to determine whether they can be created with CFn or are implemented. Resolve implementation availability from resource types to corresponding catalogs/schemas.

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
- Do not display TemplateBucket/TemplateKeyPrefix tables in generated Markdown; output to hidden `<!-- templateBucket: <value> -->`/`<!-- templateKeyPrefix: <value> -->` only when configured. Generate mapping tables under `## S3配置` and `### 配置ファイル` only if artifact mappings exist. Perform reparsing and model-equality validation; old-format configuration tables can also be parsed. Do not feed Markdown back. Retain existing unconfigured model/Markdown formats.
