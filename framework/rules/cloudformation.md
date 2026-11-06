# CloudFormation Rules

- Follow [Credentials and account](project-configuration.md#credentials-and-account) for account/profile/target selection.

## Common rules

- Create, change, and execute CloudFormation only in `infrastructure` tasks.
- Infrastructure task design inputs are approved authoritative model properties entries and required parts/referenced models. Obtain design values from `desired.row.*`, JSON bodies from `desired.row.*.document`, identity/references from metadata such as `desired.resource.*`, and current non-ARN identifiers from `observed.*`. In ordinary deploy, do not additionally read generated service Markdown/service-owned JSON bodies. Resolve saved Markdown Resource links using the common Model resolver and consumer scope; stop for unknown, unmatched, or ambiguous mappings, without generated Markdown body fallback.
- Retain generated artifact existence verification, existing hash monitoring, generated artifact validation by sync-model/local loop, and stop conditions. For explicit display defect/mismatch investigation, only necessary corresponding portions may be read. Classify mismatches using [Deploy failure and runtime recovery](#deploy-failure-and-runtime-recovery). Do not change intended design.
- If intended design changes are needed, stop without filling values and report that a separate `design` task is required.
- Use only when the active project and target environment/target directory select CloudFormation.
- Do not interpret disappeared/renamed StackNames in design as existing stack deletion/rename. Decide ending management/deletion under a separate authorized scope with explicit targets/impacts; do not implicitly include it in current deploy/update.
- Manage 1 environment/AWS account with only 1 IaC engine, consistent across aliases sharing an AWS account ID. Also keep engines consistent across targets sharing environment/execution account.
- `AWS::AccountId` used to evaluate local/deploy Conditions, ImportValue, artifact references, and Outputs uses the execution account. Use independent explicit parameters when passing `awsAccountId` into resource names, etc.; do not substitute native pseudo parameters. Actual stack/resource owning accounts are determined by AWS execution destinations.

## Template implementation

Before selecting additional rules, inspect relevant Model Resources, Stack placement and dependencies, and the existing template’s Resources, Parameters and Outputs; for a new template inspect its authorized planned structure. Read each applicable section; if classification or cycle risk is uncertain, read all potentially applicable sections:

- Roles with no directly using resource: [Standalone IAM Role stacks](#standalone-iam-role-stacks).
- Security Group mutual references or uncertain cycle risk: [Security Group cycle rules](#security-group-cycle-rules).
- Possible Static Parameter Export scaffold in Resources, Parameters and Outputs: [Static Parameter Export](#static-parameter-export).
- KMS Key or Alias resources, or consumers referencing an Alias (including S3): [KMS Key and Alias](#kms-key-and-alias).
- Environment-based naming or selection: [Environment composition and selection](#environment-composition-and-selection).

- In YAML CloudFormation templates, use `!` form for every intrinsic function with AWS shorthand; corresponding long-form `Ref:` and `Fn::...:` are prohibited except for the following combinations. Permit `Fn::ImportValue: !Sub 'VpcId${Suffix}'`, with `!Sub` on the same line or an indented following line, and `!ImportValue {Fn::Sub: 'VpcId${Suffix}'}` (including flow-form variable maps); Export bases and parameter names are not fixed. Import names must not depend on resource values, and final Export names must satisfy the existing naming rules. Also permit `!ImportValue {Fn::Join: ['', ['ExportBase', !Ref ParameterName]]}` joining a fixed PascalCase Export name base with a parameter value using an empty delimiter. Select the parameter whose value preserves the confirmed Export name. YAML cannot directly nest shorthand tags, so only the outer `Fn::ImportValue` with `!Sub`, the inner `Fn::Sub` with `!ImportValue`, and this expression's inner `Fn::Join` may use long form. Array arguments also use shorthand flow form such as `JobId: !Select [0, !Split ['|', !Ref GlueJobDefinition075]]`.
- For `!If` array arguments, place true and false values after the condition name on separate lines at the same indentation for comparison. Retain flow form; for example:

  ```yaml
  Value: !If [ConditionName,
    TrueValue,
    FalseValue]
  ```
- Do not use YAML anchors/aliases or hash merge (`<<:`) in CloudFormation YAML. Explicitly state original values for identical trust policies, IAM/KMS permission Policies, and other setting blocks in each resource. Do not require sharing merely because content is identical; retain per-Role design JSON artifacts and references.
- Under `Resources` in CloudFormation YAML, insert at least 1 blank line between consecutive resources.
- Do not use nested stacks.
- Determine stack/template boundaries by change units, rollback units, dependency direction, and deploy responsibility, not AWS services.
- Default to `1 template = 1 deploy responsibility`, but the same template may serve multiple stack instances. Deploy/update execution units are StackNames in authoritative `cloudformation-stacks.properties`, not template paths.
- CloudFormation template implementation requires stack detailed design from `framework/rules/detailed-design.md`; ordinary Deploy uses approved Model, Template and Parameters without requiring generated design prose. Resolve each stack instance's StackName, template filename, individual parameter filename, DeployOrder, and target MaxConcurrentStacks from authoritative `cloudformation-stacks.properties`. During deploy, `load_units()` validates the authoritative Model directly; saved generated Markdown is not an execution input or readiness condition. Retain existing sync-model/local loop timing for ordinary service generated artifact validation. Template/parameter locations follow this rule's path conventions. Do not infer StackNames from template/parameter filenames alone.
- Do not create standalone templates/stacks owning only CloudWatch Logs resources (`AWS::Logs::*`) and Security Group bodies (`AWS::EC2::SecurityGroup`); include them in templates of using resources. Include IAM Roles in templates of directly using resources in the same target when present.
- Template `Resources` keys (resource logical IDs) and final `Outputs.*.Export.Name` values must be PascalCase. Start with ASCII uppercase and use only ASCII alphanumeric characters afterward; no hyphens, underscores, or spaces. This rule does not apply to non-exported Output keys or AWS-generated physical IDs.
- For detailed design identifier references to CREATE, resolve Model Resource links and their explicit cfn-logicalId and generate `!Ref`. Do not hardcode link display text `PENDING_DEPLOY` or physical IDs into templates.
- Uniquely map models to stack resources with resource `cfn-logicalId=<StackName>-<Resources key>`; use only the trailing CFn resource ID in template `!Ref`, `!GetAtt`, and Outputs. Do not use composite IDs as template keys. Do not change anchors, confirmed resource names, or existing CFn IDs. Stop without guessing for invalid/duplicate mappings or unconfirmed final Export Name values including target-specific parameters. Existing stack logical ID/Export Name changes may delete/recreate resources or disconnect cross-stack references; do not automatically change them merely for naming format.
- Expose values in CloudFormation `Outputs` through logical resource references when required by other stacks or external contracts; do not add Outputs solely for observation synchronization. Generated ARNs are excluded from output collection and observed value persistence.
- Place common templates without aliases in `infra/cloudformation/templates/` and alias-specific templates in `infra/cloudformation/templates/<alias>/`. Share templates for the same alias across environments; do not share across different aliases.
- Place target-specific parameters in `infra/cloudformation/parameters/<environment>/<target-directory>/`. The target directory is the alias if present, otherwise AWS account ID.
- When a template references `Environment`, declare it in template `Parameters` and set it to the target Environment ID from `project.json` in target-specific parameter files. Compose names in resource properties/tag values using `!Sub`, `!Join`, `!Ref`, etc., treating it like independent components such as AWS account IDs. Do not change confirmed complete names in detailed designs.

## Standalone IAM Role stacks

- For Roles without directly using resources (such as cross-account switch roles), confirm no same-target design resource directly references the Role and confirm its trust policy Principal; record purpose and AssumeRole sources in design before placing only the Role and associated IAM Policy/ManagedPolicy in a dedicated template/stack. Declare `RolePlacement: standalone` directly under `Metadata` in this template. This declaration expresses design decisions, not proof of nonuse in AWS. A template with InstanceProfile added is not Role-only.

## Security Group cycle rules

- If part of a confirmed Security Group rule set creates mutual references that would cause resource or cross-stack dependency cycles, do not embed that rule set in the original owning templates. Keep Security Group bodies with their using resources, and permit a dedicated template/stack containing only `AWS::EC2::SecurityGroupIngress` and/or `AWS::EC2::SecurityGroupEgress`. Document the dependency reason in stack design, deploy it after all referenced Security Groups, and use confirmed GroupId exports through `!ImportValue` for cross-stack references. Security Group producer stacks must not depend on the rule stack.

## Static Parameter Export

- Static Parameter Export templates have one narrow mapping exception, shared by implement/deploy and observed synchronization: the sole Resource is an `AWS::CloudFormation::WaitConditionHandle` declaration containing only `Type`, every Output directly `Ref`s a declared Parameter and defines `Export.Name`, and no explicit Model `cfn-logicalId` or removal applies to the Handle. Outputs must be nonempty. Prove all template expressions independent of the Handle with the existing local intrinsic evaluator, including unused branches/variable-map values; require nonempty locally resolvable Export names. Reject Transform, dependencies, resource/unknown references and unresolvable expressions conservatively. Only a proven scaffold is omitted from mappings and observed synchronization; ordinary mapping uniqueness, CREATE/type checks, integrated children, IMPORT handling and removal protection remain unchanged. Logical IDs, StackNames, environments and aliases do not select this exception.

## KMS Key and Alias

- Even when detailed design tables are integrated, implement CREATE KMS Keys and Aliases as their respective formal CloudFormation resources. Do not generate IMPORT. Retain grouped Alias logicalIds and derived display anchors and set `!Ref` of the Key indicated by `parentReference` in model `parentProperty`. Follow the Model reference target and attribute: use the corresponding Alias reference for an Alias, a KeyId reference for a Key `KeyId`, and a confirmed ARN reference for a Key ARN. This also applies to S3 encryption. Do not automatically convert among Alias, KeyId and ARN. Do not change existing IaC logical IDs solely because display changes.

## Environment composition and selection

- `Environment` may be used in CloudFormation-supported conditions and environment-specific selection, including `Conditions`, Resource and Output `Condition`, `Fn::If`, `Fn::FindInMap`, `Fn::Select`, and `Fn::ForEach`, subject to CloudFormation syntax and placement constraints. Independent feature flags may be used when the design calls for them, but are not required solely to express environment differences.
- Do not include target Environment ID as a name component in parameter values other than `Environment` (resource names, prefixes, suffixes, etc.) in target-specific parameter files. For example, compose `app-dev-role` inside templates from `Environment=dev` and `NamePrefix=app`. `NamePrefix=app-dev` is a violation regardless of `Environment` parameter presence. Do not hardcode complete names in templates or embed Environment in other parameters to append it twice.

## Cross-stack references

- Cross-stack references expose only stable values needed downstream, avoiding unnecessary coupling.
- For Implement, identify the formal Model resource and attribute, its unique owning Producer Stack, and the Producer template Output/Export. Resolve the Consumer Export name locally using each target environment's stack parameters, defaults and Conditions, and confirm consistent stack dependencies and DeployOrder in the same account/region. String equality alone does not establish a resource reference. Stop without guessing if ownership, target, name, active Output or dependency is ambiguous or unresolved.
- AWS Export lookup is not an Implement prerequisite: a not-yet-deployed Producer or an observed KeyId of `PENDING_DEPLOY` does not block a confirmed logical reference. Never embed `PENDING_DEPLOY` as a KeyId or infer a physical value. If a necessary Producer Output/Export is missing, add only the necessary definition when authorized by the existing task scope; otherwise stop and report the missing prerequisite. Do not change existing logical IDs or Export names/values merely for naming format.
- Once locally confirmed, reference the Export with `!ImportValue`; for references within strings, pass it into `!Sub` variable maps or `!Join`. Do not leave physical IDs/generated ARNs as literals or save reference-derived generated ARNs as observed values. Report unmet Deploy prerequisites.
- Deploy uses the existing Export Resolver and Controller to verify AWS Export evidence before ChangeSet creation and again immediately before execution. Confirm Producer StackId, successful status and Outputs, and Export name, value and owner; missing, changed, ambiguous or unavailable evidence is BLOCKED. Deploy in dependency order and do not create a Consumer ChangeSet before an in-scope Producer succeeds. Consumer-only Deploy still verifies the existing Export; unverified AWS state cannot establish Deploy success. Do not expand scope or automatically deploy an external Producer.

## AWS execution context

- Preflight and controllers automatically use target `awsProfile` if present. Pass the same `--profile` and target region to direct AWS CLI too (including validate-template, list/get/describe, and observed value retrieval). Reject explicit profiles differing from settings before execution; do not fall back to another profile after authentication failure.
- Before deploy, match target account/region stacks read-only and confirm designed stack existence, states, parameters, and resource ownership. Distinguish undesigned stacks, same-named stacks differing from design, and designed stacks absent from AWS; do not automatically adopt/change/delete undesigned stacks. Retrieve current stack status from AWS when needed and retain execution state in the existing execution management, not the Stack Model.
- Framework SDK controllers perform authorized operations through `utils/aws/`. In the explicitly selected CLI method, the LLM performs authorized AWS operations directly through AWS CLI under [Direct AWS CLI deployment](#direct-aws-cli-deployment); do not route that method through a Python Controller or SDK.

## Design coverage and CloudFormation support

- Detailed designs/models also contain CFn-unsupported resources. Resolve formal CFn types for every implementation target resource type with `python framework/scripts/design_catalog.py --cloudformation-type <catalog-resource-type>`. Unknown types or `cloudFormationType: null` are failures; do not invent `AWS::` types merely by resource type string replacement.
- `Macie.Session` uses existing CFn schemas. Treat `Macie.ClassificationJob` as CFn-unsupported; do not include it in CFn templates, Outputs, or `!Ref`.
- `QuickSight.Group` resolves to `AWS::QuickSight::Group`. Retain API Model identity `AwsAccountId`, but implement only `GroupName`, `Namespace` and optional `Description`; CFn uses the execution account. Expose `Arn` and `PrincipalId` through `!GetAtt` when needed; retain hidden-ARN Model rules. The pinned Group provider schema comes from the official `us-east-1` archive because it was absent from the `ap-northeast-1` archive on 2026-11-03. This type mapping does not prove regional availability; confirm the deployment region supports it before deployment.
- If the active task specifies only CFn-supported scope, implement that scope and finish. If API-only resources are requested for implementation, explicitly state them as unimplemented; do not silently narrow scope or call the request complete. Do not automatically add Custom Resources or other engines.
- Even if CFn resources need API resource identifiers, do not generate fictitious `!Ref`. Without approved external input handoff design, report missing dependencies and stop. Do not infer implementation methods from link display current IDs.

## Resource mode boundary

- Only authoritative model resourceMode=CREATE (including unspecified mode) is generated for CloudFormation. Retain IMPORT in detailed designs/properties, outside IaC generation, without AWS resource changes. Do not generate IMPORT in `Resources`. Do not create/execute CloudFormation Resource Import or Import change sets, or migrate existing resources to Stack management.
- IMPORT is a framework design management classification, not CloudFormation import functionality. Do not correct values to framework naming or add/change Name tags.
- Resource implementation, logical ID mappings, identifier references, and Outputs/output generation in this rule apply only to CREATE. Grouped children with independent identities are classified by their own resourceMode. Inline settings follow the containing resource's classification.
- For CREATE references to IMPORT, do not generate fictitious resource references. Without an existing approved handoff design, report what is missing and stop; do not design new external input mechanisms. Do not change external stacks/states owning IMPORT.
- Do not interpret switching already IaC-managed resources to IMPORT as authorization to automatically delete them from templates/configurations or release management. Report impacts and stop when detected.

## Validation and execution

### Local implementation validation

`implement` phase:

1. Before implementing existing templates and before finishing generated templates, perform local read-only mapping validation with `python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py observed --environment <environment> --target-directory <target-directory> --stack <StackName>` (repeat `--stack` for each stack). Deployment resolves only resources needed for repair/bootstrap/current Snapshot synchronization. Directly match StackNames/template resource IDs with each resource's `cfn-logicalId`; do not use separate mapping tables. Resource correspondence uses explicit cfn-logicalId and Stack identity. Evaluate Conditions with stack-specific parameters/defaults and account/region/StackName; validate CREATE, formal types, unique mappings, identifier rows, available observation acquisition contracts, declared Outputs, and duplicate ownership only for active resources. Stop on unresolved, cyclic, or non-boolean Conditions; do not include inactive resources in identifier validation/ownership decisions. Do not automatically add identifier rows; aggregate deficiencies per stack. Absent new templates are not pre-implementation deficiencies; confirm model/placement inputs and always run this common validation after generation.
2. Retain local Model/provider-schema and selected template consistency checks. No template lint engine is required.
3. Do not execute AWS APIs, `aws cloudformation validate-template`, change sets, or deploy/update.

### Deployment validation and execution

`deploy` phase:

1. Decode explicit templates/parameters with `utils/cloudformation/format.py` and monitor their full bytes/file sets; do not build whole-scope resource mappings.
2. Validate template syntax with `aws cloudformation validate-template`. This command alone does not replace property validation.
3. Create change sets and confirm scope, delete, and replacement.
4. Do not introduce human review uniformly stopping all change sets. Wait for human confirmation with an explanation according to [approval procedure](../prompts/codex/deploy/runbook.md#confirm-unapproved-deletereplacement) only for unapproved delete/replacement.
5. Proceed to execution only if the active prompt authorizes deploy/update, change scope matches it, and delete/replacement is preapproved or approved by the human after change set creation.
6. Preserve and classify failures using [Deploy failure and runtime recovery](#deploy-failure-and-runtime-recovery).

Process only Deployment scope StackNames in numeric DeployOrder ascending order and StackName order within groups. Only stacks in the same DeployOrder group may run concurrently; RUNNING count must be at most MaxConcurrentStacks. Reuse free slots for the same group's queue, not fixed batches. Proceed to the next group only after the required earlier AWS attempts succeed. Observed/Git saving is chosen explicitly and is not an additional Order barrier; actual Consumer input dependencies still apply. Values need not be consecutive. Do not convert DeployOrder to CloudFormation resource `DependsOn` or add dependency fields to stack models.

Immediately before consumer change set creation, interpret `!ImportValue` with the shared CloudFormation decoder, resolve referenced Export names using stack-specific parameters/defaults and account/region, and resolve them through the shared Export resolver. A known Producer is revalidated with scoped `DescribeStacks(StackName=StackId)` Outputs, StackId/status and saved Export value/owner; this path never calls ListExports. Only required names whose Producer remains unknown may share one complete ListExports discovery within that verification boundary; DescribeStacks must then reconfirm each discovered Producer. Missing, ambiguous or changed evidence blocks. Evaluate Conditions; scan only selected `!If` branches and active resources/Outputs. Stop for unresolved, cyclic, or non-boolean conditions; do not require ImportValue in unused branches. Unresolved expressions, absent Exports, and unsuccessful in-scope producers are BLOCKED. Explain incorrect DeployOrder and Import/Export contradictions; do not add out-of-scope producers, change order, or automatically repair IaC/intended design. Consumer-only deploy is permitted if out-of-scope producer Exports already exist. Stop for Transform-dynamically-generated imports that cannot be resolved in advance.

A failure/rollback stops dependent later Orders; independent peers at the same Order may continue. Unapproved delete/replacement blocks that Stack. Distinguish SUCCESS, FAILED, BLOCKED, and NOT_STARTED per StackName. Status API errors are not absence or terminal failure; retain that Stack request and continue independent scoped work. Do not automatically rollback, delete, or redeploy successful stacks. Rollback/delete is permitted only under the failed CREATE cleanup exceptions below.

### Infrastructure update execution

`update` phase:

1. Generate Markdown without changing model properties manually edited by the human before task start.
2. Create/change target templates under the same approved-Model and local validation rules as implement phase.
3. Continue with the same preflight, `aws cloudformation validate-template`, change set checks, execution, and completion confirmation as deploy phase.
4. Permit only target template uncommitted diffs generated in this phase for deploy.

## Deploy failure and runtime recovery

Deploy never edits IaC. Review the current failed Stack and structured AWS errors against the approved Model and exact inputs. Settle unfinished operations and preserve their evidence. Use a separate authorized Implement Task in a normal Worktree for proven IaC defects. After validation and integration, start a new Deploy Task if needed. Unknown causes, authentication or scope errors, design defects and unconfirmed submissions require investigation or Human action.

Runtime bootstrap remains separate and changes no IaC. Preserve original StackId/Token, failed-template Retain/Custom/nested safety, deletion inventory/protection and empty-shell ownership checks. A failed Stack remains FAILED in this Task; never retry it within the same run. Secrets versions and the current Task’s stable Token prevent duplicate initialization after interruption. Never use corrected template policy as authority to delete old resources. A subsequent run accepts latest IaC and creates/evaluates its own ChangeSet; no local hash alone proves AWS application.

## Delete and replacement confirmation

For SDK, `deploy/change_sets.py` owns preparation, content approval and immediate execution checks. For CLI, the LLM performs the same content review and immediate rechecks directly using AWS JSON. Approval identifies the saved ChangeSet and full content digest. Before execution, save StackId, ChangeSetId, changeDigest, clientToken, inputDigest and each change LogicalResourceId/ResourceType/PhysicalResourceId/Action/Replacement/PolicyAction. No Model mapping is required to save this evidence. Fill missing physical identities only from exact AWS resource information; unknown deletion never resets identifiers.

- `Remove`, `Replacement: True`, and `Replacement: Conditional` require confirmation regardless of resource type. If `Action` or `Replacement` values cannot be determined, stop without treating changes as approvable.
- Do not treat unapproved delete/replacement as deployment failure/task completion; wait for human confirmation without executing created change sets.
- After human approval, retrieve the same change set ID again in the same task; execute it only if status is `CREATE_COMPLETE`, execution status is `AVAILABLE`, and approved logical IDs, actions, replacements, and `PolicyAction` match.
- If change sets expired, were recreated, or changed, do not use previous approval; explain new contents and reconfirm.
- Do not execute change sets with approval for only a subset of changes. If template repair, resource retention, or removal from CloudFormation management is needed, stop without IaC changes in the current deploy/update phase.

Stop in the following cases.

- Validation failures without unique repair evidence
- required input missing
- AWS account or region mismatch
- Delete/replacement actions cannot be determined
- Intended design is deficient or needs changes

When the active prompt limits targets, implement phase may process only some templates and deploy phase only some stacks/resources, then finish. Do not automatically proceed to remaining resources, other stacks, or scenario tests.

Follow [observed-values](observed-values.md) for current identifier collection/synchronization regardless of attempt outcome, and [task-contract](task-contract.md), [Validation policy](loop-engineering.md#validation-policy), [Validation scope](loop-engineering.md#validation-scope), and [Infrastructure task completion](loop-engineering.md#infrastructure-task-completion) for task finish. When a loop is required, follow [Local loop](loop-engineering.md#local-loop) and its conditional reads; retain the applicable phase-specific CloudFormation checks above.

## S3 deployment artifacts

### Artifact declarations

SDK方式では`deploy/delivery.py`が実行用copy・object配置を、`deploy/s3_delivery.py`が取得とkey別条件判定を担当する。CLI方式では以下の同じ配送条件をLLMが直接AWS CLIで確認する。Pythonの配送処理をAWS backendとして呼ばない。正本は同targetのcloudformation-stacks.properties。templateBucketは既存バケット名を直接指定するか同target S3 ModelのBucketName参照を指定し、templateKeyPrefixと両方指定または両方省略する。直接指定にS3 Modelは不要。project設定への重複保存は禁止。

artifactはstack/resource/property/source/bucket/keyPrefixを明示する。StackName・template LogicalId・同target S3 linkを使い、file名から推測しない。sourceはinfra/cloudformation/artifacts内の既存fileのみ。directory、外部path、外へ逃げるsymlinkは禁止。複数Resourceの同source共有は可。対応はLambda Function.Code/LayerVersion.Contentの構築済ZIP、Glue Job.Command.ScriptLocation、StepFunctions StateMachine.DefinitionS3Location、ApiGateway RestApi.BodyS3Location。container/nested/Transform/未知propertyへ拡張しない。未宣言S3参照は配置済み参照として維持する。

### Artifact execution

元templateのType/property/bucket/keyPrefixを照合し、parameters/default/Ref/Sub/Join/確定ImportValueで解けない値は停止する。実行copyは宣言propertyのkey/version/URIだけcontent hashへ置換できる。bucket式・他設定・元IaC/parameters/Modelは変更しない。実行byte数でinline<=51,200、S3<=1 MiBを決定し、超過は停止。同じ内容/URLをValidateTemplateとCreateへ渡す。copyは今回runの外部一時directoryへ置く。

producer SUCCESS/observed反映/必要Exportsを確認し、同DeployOrderの全artifact、次に実byte数でS3が必要なtemplateを配置する。全配送確認後に新規Create/Executeへ進むbarrierを維持する。bucket作成は先行groupでinline実行し、同group bootstrap・bucket自動作成・代替bucket・scope拡張は禁止。

Artifactでは同じprofile/Region/期待execution ownerでHeadBucket/GetBucketLocation/GetBucketEncryption/GetBucketPolicyを取得する。S3 Modelの一意なBucket/Region/暗号化を正本とし、AES256またはaws:kmsと設計keyを送る。明示deploymentEncryption=default時だけSSE headerを省略するが、formal暗号化行は必須。既存resolverでKey/current ID/Alias-parentを解決し、DescribeKeyのaccount/Region/Enabled/対称ENCRYPT_DECRYPTを確認する。key ARNは今回runの一時証拠のみ。AWS/policyから設計を補わず、欠損・曖昧・未知条件で停止する。

ArtifactのpolicyはkeyごとにAction/Resource pattern、wildcard principalと暗号化条件StringEquals/NotEquals/Like/NotLike（IfExists含む）/Nullの論理積を評価する。未知の適用条件/principal/variable/否定scopeはINDETERMINATE。一般IAM engineに拡張せず、READ_DENIED/READ_UNCONFIRMED/MISMATCHを区別する。NoSuchBucketPolicyだけpolicyなしと扱う。403/timeout/壊れたpolicyを成功にしない。IAM/SCP/endpoint/実効PutObject・KMS権限は読取だけでPASSにしない。必要objectの実配置が書込確認であり、probe・IAM/KMS/policy緩和・public化は禁止。

Use fresh evidence at group preparation and each Stack Create/Execute boundary; evaluate policy per key. Resolve aliases separately and distinguish the requested key from the verified ARN. Do not treat APIs as an atomic snapshot or reuse evidence across return, approval, resume, repair, input changes or group transitions. Stop on failure; never reuse stale success.

object keyはprefix+SHA256+拡張子。不存在HEAD→IfNoneMatch="*"/checksum/ExpectedBucketOwner付きPutObject（Artifactは設計に従いSSEを指定）→古いHEAD無効化→新しいHEADでchecksum/size/必要versionとArtifactの暗号化を確認する。既存objectは一致時のみ再利用し、不一致/権限欠損で上書きしない。412は新HEAD一致時だけ再利用、409/timeout等の不明結果は上限付き確認/retryとし無条件PUTへ切り替えない。同じ準備内の確認済みobjectは共有し、Create/Execute境界はfresh HEADとする。

Lambda/Layer/definition/template URLで固定versionを消費する場合と、versionless s3 URI/current key消費を区別する。古いVersionIdのHEADをcurrent確認に使わず、hash keyだけで他主体の上書き防止を保証しない。Artifactの配置前に解決済暗号化条件/policy digestを今回run内へ記録し、境界/resumeで変更を検出したら停止する。旧Artifact objectに暗号化証拠がなければ停止。実行入力hash、copy hash、bucket/key/version/checksum、ChangeSetを維持し、変更object/ZIPを旧承認で実行しない。失敗時もpeer drainを維持する。

Template配置ではバケットのModel/Region/暗号化/Policy/KMSを事前照合せず、SSE headerを指定せずバケット既定の暗号化を使用する。HeadObject、checksum、size、ExpectedBucketOwner、条件付きPUTとversion確認は維持する。用途不明の旧記録はArtifactと同じ検証を行う。

ArtifactのexecutorにHeadBucket/Location/Encryption/Policy、ListBucket、GetObject（固定versionはGetObjectVersion）、PutObjectと必要KMS DescribeKey/暗号化/checksum取得権限、consumerの読取権限を設計する。自動付与しない。rollback用の過去artifactを自動削除せず、retention/lifecycleは明示設計による。status/URL/version/checksumをModel/Gitへ保存しない。

## Direct AWS CLI deployment

### Method and local lifecycle

Select CLI explicitly before preparation; keep that choice on interruption/resume.
The LLM invokes AWS CLI directly through its execution tool, reads each JSON result
and chooses the next bounded operation. No Python subprocess wrapper, boto3/botocore
API, Controller, SDK Scheduler/Journal or shared AWS lock participates. Do not add
a shared backend/interface/state/lock or silently fall back to SDK. AWS CLI's own
bundled implementation does not authorize importing its Python internals.

Keep the Worktree Skill unchanged; repository development/setup is separate from
the Deploy execution method. CLI AWS execution needs AWS CLI, not a Python SDK.
Existing non-AWS Model/generation/validation/Git utilities remain usable. CLI Task
completion uses the ordinary `task_contract.py --complete` local validator rather
than SDK local progress/final-save receipts. Task completion and any later Git integration are separate.
These local branches perform no AWS retrieval, submission, scheduling or recovery;
the LLM remains responsible for all AWS decisions and unsettled-request tracking.
Do not call SDK `sync`/`checkpoint`, manufacture SDK receipts, edit
lifecycle metadata or change the Task phase to complete CLI. SDK-bound lifecycle
state cannot be converted to CLI; preserve the original Task and request evidence.

### Preflight and fixed Snapshot

1. Confirm AWS CLI v2 availability and required command options using local help.
   Use the configured profile (omit only when genuinely unset), explicit target
   Region and expected execution account under project configuration. Verify STS;
   never change credentials after failure. A missing CLI/option or mismatched
   profile/account/Region stops before mutation.
2. Register/select the same infrastructure/deploy Task in the calling repository.
   Confirm allowed AWS actions, exact StackNames, Model/View output paths and
   destructive-change consent. Before fixing the Snapshot, record the following
   Task context from the configured target and verified STS response; Partition
   is the partition component of the caller ARN, not a guessed Region prefix.
   Local Model reference projection checks account/Region and uses this confirmed
   Partition without loading SDK endpoint metadata. Missing/mismatched fields stop.

   ```md
   - Deploy execution method: `cli`
   - CLI AWS account: `<verified-execution-account>`
   - CLI AWS region: `<configured-target-region>`
   - CLI AWS partition: `<verified-caller-arn-partition>`
   ```

   Resolve StackName/template/parameters/DeployOrder/
   MaxConcurrentStacks from authoritative stack properties, and verify generated
   stack-design equality. Do not infer these from filenames or generated labels.
3. Fix the start Snapshot: Task, project/target, desired Model/parts/references,
   stack inventory, IaC, parameters and declared artifact bytes/file sets. Retain
   a hash manifest and immutable execution copies outside the repository. Recheck
   against those inputs before every mutation and after any interruption; only
   authorized observation/View/status saves may differ. Preserve original hashes
   across those saves; changes or missing evidence stop, never silently rebaseline.
4. Decode templates/parameters with existing local, non-AWS utilities; check
   required/default/unknown parameters, Conditions, Model ownership and CREATE-only
   boundaries. ValidateTemplate does not validate supplied parameter values against
   all constraints or replace local Model/provider-schema/mapping checks. Review
   current scoped Stacks, resources, ChangeSets, Outputs and required Exports.
   UNKNOWN is not ABSENT. `REVIEW_IN_PROGRESS` requires ChangeSet inspection.
   Detect conflicting active/uncertain AWS operations before any new submission.

Examples below use shell arrays (bash/zsh). Replace every placeholder with confirmed
values; define the referenced IDs/paths/tokens only after the relevant checks. These
are individual LLM operations, not a script to run through unattended. Keep JSON
stdout, structured errors and exit status separate in private Task-local evidence
outside Git. Do not display secret parameters, credentials or sensitive Outputs.

```sh
aws --version
deploy_context=(--profile '<configured-profile>' --region '<target-region>' --output json --no-cli-pager)
export AWS_CLI_ERROR_FORMAT=json
aws "${deploy_context[@]}" sts get-caller-identity
aws "${deploy_context[@]}" cloudformation describe-stacks --stack-name "$deploy_stack_name"
aws "${deploy_context[@]}" cloudformation list-change-sets --stack-name "$deploy_stack_name"
aws "${deploy_context[@]}" cloudformation list-stack-resources --stack-name "$deploy_stack_id"
```

Use automatic pagination for complete JSON inventories; never approve a truncated
Changes list, exports, resources or events. A missing/failed page stops dependent
decisions. Structured not-found for the exact identity may prove Stack absence;
AccessDenied, generic ValidationError, non-JSON errors and timeout cannot. Pace reads
within the existing API budgets (5 requests/s for scoped Stack/event/template/export
reads, 1 request/s for ListImports), including CLI pagination/retries. Do not infer
the SDK's in-process limiter protects direct CLI processes.

### Order, dependencies and S3 delivery

The LLM starts only the selected numeric DeployOrder group, ordered by StackName.
Only independent same-Order Stacks may overlap, with RUNNING no greater than
MaxConcurrentStacks; count existing accepted/uncertain requests against that limit.
Reuse a free slot within that group. A failed Stack permits independent same-Order
peers to continue but blocks dependent work and later Orders until required earlier
attempts succeed. On authority/scope/concurrency violation, stop new starts and
observe/drain active requests; do not abandon an accepted request. Serial execution
is safe when independence or capacity cannot be proved.

Resolve active `ImportValue` expressions with the local decoder and current
parameters/Conditions. Perform the AWS side of Export resolution directly: known
Producers use scoped DescribeStacks; unknown owners use only necessary complete
ListExports discovery followed by scoped owner confirmation. Check actual values,
owner StackId and success immediately before consumer Create and again at Execute.
No out-of-scope producer deploy, guessed export or unresolved Transform/Condition.
The SDK AWS-facing resolver is not a CLI backend.

Apply [S3 deployment artifacts](#s3-deployment-artifacts) in full: same-Order artifact
delivery then necessary template delivery must finish before Create/Execute. Fixed
copies may replace only declared artifact keys/versions/URIs. Templates at most
51,200 bytes may be inline; larger ones through 1 MiB require the designed S3
destination. Validate and submit the exact same bytes or pinned URL. Never create
buckets/permissions or build artifacts implicitly.

For Artifact objects, directly inspect HeadBucket, GetBucketLocation, encryption,
key-specific policy and, when applicable, KMS DescribeKey against approved Model.
Stop for denied, unconfirmed, indeterminate or changed evidence. Template objects
retain the existing exception: no bucket Model/Region/encryption/policy/KMS preflight
and no SSE header. Both retain expected owner, checksum, size and version checks.
This is a template-only upload example after proving the key is absent; for an
Artifact add its exact designed SSE/KMS arguments. SHA256 is local hex for the key,
Base64 for the checksum. Do not use ETag as a SHA256 substitute.

```sh
aws "${deploy_context[@]}" s3api head-object --bucket "$deploy_bucket" --key "$deploy_key" --expected-bucket-owner "$deploy_account" --checksum-mode ENABLED
```

Only after confirming absence and recording the fixed delivery intent:

```sh
AWS_MAX_ATTEMPTS=1 aws "${deploy_context[@]}" s3api put-object --bucket "$deploy_bucket" --key "$deploy_key" --body "$deploy_copy" --if-none-match '*' --checksum-sha256 "$deploy_checksum_base64" --expected-bucket-owner "$deploy_account"
aws "${deploy_context[@]}" s3api head-object --bucket "$deploy_bucket" --key "$deploy_key" --expected-bucket-owner "$deploy_account" --checksum-mode ENABLED
```

Fresh HEAD must match checksum/size/required version and Artifact encryption before
Create and Execute, including after approval/resume. Match 412 with a fresh HEAD;
409/timeout require bounded reconciliation, never an unconditional overwrite. Do
not use an old version's HEAD to prove a versionless current-key consumer. Retain
the confirmed bucket/key/version/URL and input/copy hashes in private run evidence,
never Model authority. Stop if policy/encryption/object evidence changes.

### ChangeSet review and execution

For a proven absent Stack use CREATE; for an eligible existing Stack use UPDATE.
Pin StackId as soon as known. Preserve existing stack settings (including service
role, capabilities, tags and rollback settings); include only confirmed required
options. Never use IMPORT or `aws cloudformation deploy`, `create-stack` or
`update-stack` to bypass explicit ChangeSet review. Do not execute a block of
Create/Execute commands without examining the intervening responses.

For an inline template, after local validation and required delivery:

```sh
aws "${deploy_context[@]}" cloudformation validate-template --template-body "file://$deploy_template_copy"
```

Inspect the returned Parameters/Capabilities. For S3 use `--template-url` with the
verified pinned URL for both ValidateTemplate and Create instead of template-body.
Record the unique ChangeSet name, Create client token and exact request/input digest
before submitting. `$deploy_stack_selector` is the confirmed StackName only for a
new CREATE and the pinned StackId for an existing Stack. Append required confirmed
capabilities/role/tags only; do not add a blanket IAM capability.

```sh
AWS_MAX_ATTEMPTS=1 aws "${deploy_context[@]}" cloudformation create-change-set --stack-name "$deploy_stack_selector" --change-set-name "$deploy_change_set_name" --change-set-type "$deploy_change_set_type" --template-body "file://$deploy_template_copy" --parameters "file://$deploy_parameters_copy" --client-token "$deploy_create_token"
```

Inspect the returned StackId/ChangeSet Id; keep the original identities on a lost
response. Poll the same ID until ChangeSet creation settles, with bounded waits:

```sh
aws "${deploy_context[@]}" cloudformation describe-change-set --stack-name "$deploy_stack_id" --change-set-name "$deploy_change_set_id"
```

Review the full Changes and input identity; execution requires `CREATE_COMPLETE`
and `ExecutionStatus=AVAILABLE`. Under [Delete and replacement confirmation](#delete-and-replacement-confirmation),
show every LogicalResourceId/ResourceType/PhysicalResourceId/Action/Replacement/
PolicyAction, full content digest and known data/access/availability impact. Obtain
Human approval for all unapproved Remove/Replacement=True/Conditional entries;
unknown actions stop, partial approval cannot execute. Ordinary non-destructive
changes do not require an additional uniform approval. No-change is accepted only
when exact AWS reason and fixed-input comparison prove it, not for arbitrary
`Status=FAILED` or an empty/incomplete Changes response.

Immediately before Execute, re-fetch that same complete ChangeSet and Stack,
compare all approved content, inputs/parameters and delivery/dependency evidence,
check current Task/target/account/Region/authority and absence of competing operations.
Expired/recreated/changed ChangeSets invalidate consent. Record the original Execute
ClientRequestToken and submission intent before sending; do not generate a new token
because a response was lost.

```sh
AWS_MAX_ATTEMPTS=1 aws "${deploy_context[@]}" cloudformation execute-change-set --stack-name "$deploy_stack_id" --change-set-name "$deploy_change_set_id" --client-request-token "$deploy_execute_token"
```

An exit 0/empty Execute response proves submission only. Inspect current StackStatus
and root events scoped by original StackId/token, not a name or status suffix alone:

```sh
aws "${deploy_context[@]}" cloudformation describe-stacks --stack-name "$deploy_stack_id"
aws "${deploy_context[@]}" cloudformation describe-stack-events --stack-name "$deploy_stack_id"
```

Report per-Stack SUCCESS/FAILED/BLOCKED/NOT_STARTED and current state separately.
Confirm this operation's terminal evidence and current Outputs/Exports before
success. CREATE_COMPLETE/UPDATE_COMPLETE predating Execute proves nothing about
this attempt. Rollback is a failed attempt; UPDATE_ROLLBACK_COMPLETE may permit a
later separately reviewed update, not automatic resubmission. ROLLBACK_COMPLETE,
UPDATE_ROLLBACK_FAILED and other failed states retain AWS restrictions. Stop on
failure requiring repair/Human action; do not delete, continue rollback, bootstrap,
initialize secrets or redeploy successful Stacks automatically. SDK runtime cleanup
is not available as a CLI recovery shortcut.

### Interruption and independent recovery

Retain Task-local input manifest, original request arguments/digests, StackId,
ChangeSet name/ID, Create/Execute tokens, reviewed contents/consent and raw AWS
responses privately outside Git. These are CLI evidence, not SDK Journal/progress
or new cross-method coordination. Never persist credentials or secret values.

On resume recheck fixed inputs and caller context, then directly read StackStatus,
ChangeSet Status/ExecutionStatus, complete root Stack Events and matching
ClientRequestToken, plus any unfinished operation. For a lost Create response,
inspect the original unique ChangeSet name and Stack, rather than create another.
For a lost Execute response, reconcile the original ChangeSet and original token
events before considering anything else. IN_PROGRESS means observe, not resend.
An old COMPLETE, AVAILABLE, ChangeSetNotFound, timeout or absence of an event alone
does not settle an uncertain submission. Missing identity/evidence, incomplete
reads, a replaced Stack or uncertain outcome stops new mutation and retains tracking.
Never unconditionally reissue the change or recover via SDK Journal/Controller.

Concurrent SDK/CLI mutations of the same Stack are outside the guarantee; there is
no shared lock. Detect a competing active ChangeSet execution/Stack operation,
unexpected identity/content or token events and stop new CLI mutations. Drain only
requests proven to be this Task's. Absence of visible conflict is not atomic exclusion.

### Observations, validation and publication

Keep AWS result, current Stack, Model save, View generation, Snapshot Validation,
Git publication and Task status independent. A successful AWS deploy cannot turn
missing/failed local work into PASS; a failed attempt may have a consistent saved
Snapshot. Active/uncertain requests retain tracking and prevent Task completion.

Direct CLI DescribeStacks/ListStackResources and needed scoped resource reads
collect verified Outputs, PhysicalResourceId or scoped read-only API observations under existing observation rules. Match explicit
cfn-logicalId, formal types, active Conditions and Rows. Use only identity-verified acquisition sources; hidden/generated ARNs, IMPORT identities and secrets are
not persisted. Confirmed uncreated/deleted uses PENDING_DEPLOY; unavailable means
remove the old observed Row value, never UNKNOWN/lastKnownValue. Retain/DELETE_SKIPPED
does not prove destruction. Account for every required resource/Row and incoming
reference before saving; stop for ambiguous or out-of-scope writes.

Existing non-AWS functions `model.observed.observed_outputs` and
`publish_observed_candidates` can prepare/publish the exact observed-only candidate
with fixed input bytes, explicit Row allowlist and the real Task/publication guard.
Do not replace them with direct properties writes. They are local Model utilities,
not an AWS executor. Generate affected Views through `sync-model.py`; run the
existing scoped Snapshot/Task validator and task loop as required by Validation
policy. Preserve Desired/reference/placement metadata, unknown absence and permitted
bytes; never save runtime projections as authority. A generation failure retains
the Model and successful Views and blocks completion for stale required Views.

After the LLM confirms all AWS requests settled and every required observation,
View and scoped task-loop check succeeded, complete through the local Task validator:

```sh
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<task-id>.md --complete
```

The CLI completion branch uses its selected local Task and scoped Model/View
validation. An SDK-bound Task cannot switch methods. While AWS is active or uncertain
or approval is pending, keep tracking the original request. Local Python validation
does not establish AWS success or settle CLI requests. Report AWS, Model, Views,
Validation and Task status separately. Do not use SDK sync or progress for CLI recovery.

AWS command arguments follow the official CLI references for
[CreateChangeSet](https://docs.aws.amazon.com/cli/latest/reference/cloudformation/create-change-set.html),
[DescribeChangeSet](https://docs.aws.amazon.com/cli/latest/reference/cloudformation/describe-change-set.html),
[ExecuteChangeSet](https://docs.aws.amazon.com/cli/latest/reference/cloudformation/execute-change-set.html),
[PutObject](https://docs.aws.amazon.com/cli/latest/reference/s3api/put-object.html) and
[HeadObject](https://docs.aws.amazon.com/cli/latest/reference/s3api/head-object.html).

## Independent controller runs and execution timing

This section's Controller commands, Scheduler, Task-local progress and receipts describe the existing **SDK method**.
They are not CLI execution/recovery dependencies. The fixed-input Snapshot,
Model/Observed/View, Validation and Git integrity requirements still apply to CLI;
its independent procedure and non-AWS completion path are defined above.

### LLM-controlled short operations

Use `cloudformation-deploy.py --action status|advance|sync|checkpoint` from the calling repository root, with the same current Task, Target and complete Stack scope.
Only the LLM chooses sync timing and explicit `--sync-stack` names. Do not use Sub Agents,
a background Model writer, fixed-period sync or Python-driven agent control.

- `status` reads current AWS and displays current Stack state, this attempt's result,
  Model save, Snapshot validation and Task status separately.
- `advance` reads current AWS first and advances one bounded poll/prepare/execute turn.
  It keeps DeployOrder and the configured concurrency. A failed Stack does not stop
  independent peers in the same Order. A later Order requires prior Order success;
  saving a failure Snapshot never grants that success.
- `sync` reads the selected current observations, atomically saves permitted Model
  changes, generates available services and validates the local candidate. No separate
  checkpoint command is required.
- `checkpoint` resumes a saved local sync and its validation without a new AWS
  execution or fresh observation; it is not a Git checkpoint or publication.

Sync accepts successful, failed, rolled-back, partially applied, unexecuted, running
and unreadable Stacks. Unexecuted does not mean absent. Consistent observations may
be saved while another Stack is changing; no target-wide quiescence is required.
Generation failures retain saved Model authority and successful service outputs;
stale Views are not claimed current. True structural/reference/scope/View mismatch
blocks completion, retaining the candidate for local recovery without new AWS work.

### Explicit operations

Specify `--action` for each invocation. Use `advance` for a bounded turn and `status` to inspect current requests without saving or publication. Select `sync` for Model saving and `checkpoint` for saved local sync recovery. Select sync before the producer/consumer input handoff. Claimed inputs remain fixed; a later update invocation may claim its newly implemented, previously unused Consumer inputs. This grants no IaC changes to Deploy.

Normal decisions use current scoped DescribeStacks and ChangeSets plus this Task's
fixed inputs. CREATE_COMPLETE / UPDATE_COMPLETE / IMPORT_COMPLETE are successful
current states, but do not prove the current Desired is applied. Build/review the
current ChangeSet. UPDATE_ROLLBACK_COMPLETE permits a subsequent update while
retaining the failed attempt result. UPDATE_ROLLBACK_FAILED and ROLLBACK_COMPLETE
retain AWS's actual operation restrictions. REVIEW_IN_PROGRESS is classified with
current ChangeSet execution, never by suffix alone. Structured absence is ABSENT;
read/permission/network failures are UNKNOWN, never absence.

Keep this Task's original Stack ID, ChangeSet ID and token when a submission reply is lost. Report an uncertain outcome without blind resubmission. A new Deploy uses a new Task and checks current AWS Account, Region, Stack and ChangeSet state, without consulting another Task's local progress. Do not submit new AWS operations while AWS is busy or its state is unknown.

### Local Deploy completion

Use the calling checkout for Preparation, AWS execution, Observed and View synchronization,
Validation and Task completion. A Worktree is optional; when needed, use ordinary
`create --task-name` and its returned Task ID and root. `sync --final` completes the
local Task only after settled requests, required saves, Views and Validation. Git
integration is separate and is not a completion condition. A settled failed attempt
may complete with Deploy FAIL unchanged; active or uncertain requests prevent completion.

A settled request may have an UNKNOWN attempt outcome while its current Snapshot is
saved and validated independently. Never persist UNKNOWN as an identifier. Exact root
Stack events use the original StackId/token; later operations cannot rewrite the attempt.

### Deploy contract correction

The suspended same-Task operation in [Self recovery](task-contract.md#self-recovery)
permits monotone additions only to Validation scope, Modified files and Allowed paths.
Missing owner services must match fixed Execution scope and unique Model ownership of
the saved execution inputs. A Task without fixed Resource evidence is BLOCKED;
no Execution scope is inferred or added. Exact entrances, necessary parts and generated
Markdown/JSON are derived from Model sources, never directory-wide permissions. Existing
observation writers still permit only observed fields; additions grant no Desired or IaC
authority. Preserve all other contract content. Changes to target/Account/Region/Stack, execution
units/templates/parameters/artifacts, permissions or consent require their original Human
authority and cannot be disguised as preparation omissions. The digest comparison in normal
Deploy remains mandatory.

Correction requires the current Python environment, original contract text and readable
saved progress. Existing applicable lifecycle/HEAD/index integrity checks remain in force. It verifies current project target, execution
units, file identities/consumed hashes/unit digests, saved Model inputs, and closed checkpoint
receipts. Current Task operations must be settled: an uncertain submission, active/unknown recorded Stack or active controller stops correction. No AWS read is used to settle operations on this path. Missing progress/input evidence stops.

Pending Observed and generation Intents may be rebound only after checking original Task
bytes, ownership, execution evidence, exact before/after manifests, current bytes, file
selections and corrected output authority. Existing journal recovery verifies its originals
belong to that Intent before restoring an interrupted batch. Candidates are preserved,
never initialized, discarded or unconditionally regenerated. A generation error requires
its retained generation Intent. An unfinished checkpoint without an adopted after/final
candidate may continue when every changed byte is explained by those Intents or a verified
observation patch from its Git source. A fixed after/final candidate, commit intent,
pending/conflicted/final Git publication or unresolved failure evidence
stops for review of the retained evidence first. Failure
evidence is inspected and retained, never implicitly erased. Completed Tasks are not
reopened. Missing/inconsistent proof is BLOCKED with its concrete recovery need.

Same-target reference consumers require explicit Human consent for each service. Review
retained Producer/Consumer/Reference Key/Stack evidence, add exact outputs and Validation
entries to the external candidate, and pass
`--approve-deferred-consumer <environment/target-directory/service>` alongside
`--correct-deploy-contract`. The option records consent; it does not obtain or infer it.
Only matching typed references to selected owners qualify. Consumer updates may remove
stale Observed values on those reference Rows; they cannot save derived ARNs, change
Desired or observe arbitrary Resources outside selected Stacks. `ownerObservedSynced`,
`referenceObservedSynced` and `referenceSynced` are separate: the last requires the Model
barrier and successful generated publication. Deferred records remain after resolution;
`sync-model` alone cannot resolve them.

Other Environment/Account/alias consumers retain exact scope, producer, key and Stack in
Deferred evidence and receive no authority. Typed references resolve within their Target;
cross-target declared dependencies require independent authorized Model synchronization
in the consumer's existing workflow, or Human facts/IMPORT refresh when acquisition is
needed. Present affected Target, key, producer Stack and unconfirmed facts; do not create
or execute a follow-up Task automatically or claim View generation changed Consumer AWS.

The operation holds existing progress, failure-evidence, Model publication and lifecycle locks. It compares candidate, contract, Git/index, project inputs, progress and
temporary template owners again before saving. One rollback batch changes the current
contract, lifecycle identity/text, progress identity, verified closed receipt identities and
matching temporary template ownership, including pending Intent identities. Tokens/results,
input digests, consumed inputs, Snapshot and checkpoint history remain unchanged.
Snapshot validation becomes NOT_RUN. A transient intent in the existing lifecycle protects
multi-file interruption, not a history or approval ledger. Normal Deploy rejects an unfinished
intent. Retry the same correction command with the exact external candidate: only unchanged
inputs and files individually matching recorded before/after bytes permit restoration of
the prior batch and revalidation of the correction. Unknown/concurrent bytes stop and remain
untouched; never hand-edit metadata or remove locks. Ordinary save failures roll back;
unrecoverable interruption retains the intent and evidence for review. Correction does not
resume execution, reissue AWS, erase progress, waive failed checks or complete the Task.
Continue with `--check-resume-scope`, the authorized `--resume` and needed Controller
`sync`/`checkpoint`, using the complete fixed Stack scope. A retained candidate is finished
without collecting it twice. Do not relaunch old `preparation.json` through `--run-controller`
after correction, or `advance`/redeploy successful Stacks as recovery.

### Deployment execution

Use current Task/target/account/Region/profile/scope/input guards before each mutation, original ChangeSet ID/Stack ID and full content re-fetch immediately before Execute, and one stable persisted Token for uncertain submissions. Human approval applies only to the current complete destructive ChangeSet. Hold new starts for actual authority/scope/concurrency violations and drain active requests. A failed Stack leaves independent same-Order peers eligible; later Orders still require their earlier AWS success conditions. The LLM explicitly saves current observations for any outcome and verifies current Output/Export facts. Retain/DELETE_SKIPPED/unknown destruction and integrated children without identifiers never reset identifiers. Do not change IaC, widen scope or infer missing evidence.

## Explicit Stack destroy

Use only `framework/prompts/codex/07_destroy.md` and independent `cloudformation-destroy.py` in infrastructure phase `destroy`. Explicit human StackNames are authorized after safety checks; no duplicate confirmation. Do not route through deploy options, deploy preparation, change sets or deploy mutation guards. No Terraform/resource/retained-resource/force deletion.

Resolve local units, DeployOrder, MaxConcurrentStacks, resource ownership, identifier outputs/incoming references and exact observed/model/view paths before AWS calls. Use existing deterministic model readers and explicit cfn-logicalId; name-based ownership inference and template/parameter body reading are prohibited. Reject out-of-target references under existing scope policy before deletion. No desired/IaC changes.

Authenticate once per invocation through the existing `deploy/context.py` read-only target/account and STS logic (no IaC command requirement). Destroy uses the existing SDK, not an AWS CLI subprocess: DescribeStacks, ListImports and DeleteStack use `utils/aws/cloudformation.py`; DescribeStackEvents uses the common `utils/aws/client.py` request per page. Pin execution account, region, profile and each described StackId; all deletes address StackId. Confirm StackName/StackStatus/EnableTerminationProtection/ParentId/RootId. Block termination protection or direct nested targets without changing protection or scope. Use the destroy controller's existing lock.

Build the Export snapshot once per external session from confirmed scoped Stack Outputs, then query imports only for scoped owner exports; do not call ListExports. On resume, reuse export snapshot only when current scoped Outputs' ExportNames match it; recheck relevant imports. Outside importers block all new deletes. Require importer DeployOrder strictly greater than producer; conflicts, including the same order, block without redesign. AWS standard deletion remains the final authoritative dependency enforcement.

Delete reverse DeployOrder; cap same-order running deletions by MaxConcurrentStacks (`--sequential` uses 1). Poll every running peer before starting new work. Complete the entire group before lower orders. Failure stops starts and drains all running stacks; transient read loss stops starts, and repeated read loss preserves running state for resume. Save identity and intent before standard DeleteStack; never use FORCE_DELETE_STACK or resource-specific cleanup. DELETE_FAILED saves reason/events and blocks Human action. Fresh absence is ALREADY_ABSENT and does not prove destruction. Saved StackId plus accepted deletion/DELETE_IN_PROGRESS evidence proves DELETE_COMPLETE on subsequent absence; intent alone does not.

Use only lightweight pre-mutation task/target/account/region/profile/scope/StackId/session invariants and pinned identity reads. Never hash infra/framework/template/parameter/artifact trees or run deploy validation. Save external session state without credentials. Batch proven deleted stacks' observed synchronization once, including partial failures; report retained/DELETE_SKIPPED resources, then follow destroy completion rules.

## Scoped CloudFormation reference reads

Deploy delivery, Create and Execute use independent verification boundaries; acquired AWS responses never cross them. Same-boundary Producer reads are shared. Unfinished-operation independence retains the existing Producer→Consumer graph, seeded by scoped Stack Outputs, saved delivery imports and current planned imports. ListImports reads only Exports owned by reached Stacks; shared Producers alone do not create a conflict. Cycles/diamonds are deduplicated; absent, incomplete or changed proof blocks.

DescribeStacks/DescribeStackEvents/GetTemplate/ListExports are limited to 5 req/s and ListImports to 1 req/s per execution Account/Region/API across all Threads and profiles in the process. The common SDK read controller accounts for every page and retry, retries only Throttling with exponential backoff and jitter, and shares the operation deadline. Controlled read SDK clients use one transport attempt; mutation SDK clients use standard retries with up to two total attempts. The slot remains held through transport completion to prevent delayed requests bunching together. Other processes are outside this budget.

Destroy preflight validates scoped StackIds/Outputs and records exportNames; dependency snapshots use those names/owners, never ListExports. Resume compares saved Export ownership/names with fresh scoped Outputs before targeted ListImports. Unknown or changed evidence stops deletion; order, approval and out-of-scope importer guards remain required. Destroy SDK reads use the same in-process Account/Region/API budgets and common retry control. DescribeStackEvents requests each page with a shared deadline until the root DELETE_IN_PROGRESS event or the end, rejecting invalid continuation tokens.

### Explicit final sync candidate

Use CloudFormation `--action sync --final` only when the LLM ends the Task. The full
`--stack` selection matches Task scope; `--sync-stack` selects observations needed now
and may be omitted when all required observations are saved. Ordinary sync retains
running. Final sync validates the local Model, Views and Task Acceptance before setting
Task completed. Validation failure retains the running Task, saved Model and successfully
generated Views. A settled failed AWS attempt remains Deploy FAIL.

`--action checkpoint` resumes an already saved local sync, including its final intent,
without another `--final`, new AWS execution or fresh observation. Keep its saved scope
and intent. It is local save recovery, not a Git checkpoint. Git integration is separate
from local Task completion. Retain current Task request identity and evidence; never
blindly resend an uncertain AWS request.

## DeployOrder selection and synchronization scope

SDK offline Preparation accepts either repeated `--stack` or inclusive numeric
`--order-from` / `--order-to` bounds. For example, `--order-to 20` selects all designed
Stacks through 20; `--order-from 30 --order-to 50` selects 30 through 50;
`--order-from 40 --order-to 40` selects 40; `--order-from 30` selects 30 and above.
Missing Order numbers are allowed. Mixed selectors, reversed/nonpositive bounds and
an empty selection stop before Task registration. Invalid Stack definitions, including
outside the selection, may stop preparation: errors identify StackName, DeployOrder,
the Model entry and invalid field/value. Only selected execution files are opened.

Preparation discovers owner services using explicit `cfn-logicalId` ownership and the
existing dependency index/mapping resolver. `--service` is optional and checks the
exact discovered set; it cannot add services. The exact StackNames and Resource
ownership (including explicit Model owners eligible for removal) are fixed in the Task. Controller `status`, `advance`, `sync` and `checkpoint`
continue with that complete `--stack` scope; a resumed Task never re-resolves an Order
range or gains more Stacks. Existing Tasks keep their recorded Deployment scope.

Only selected owner observations are patched. Owner service Views and necessary
references within those authorized services are regenerated through guarded APIs.
References from other services are discovered read-only and saved as `deferredConsumers`
in Stack progress, including consumer/key, producer, Stack and separate completion flags.
Those external services gain no Model/View write authority or full-quality validation
unless the same-target limited correction above is explicitly approved.
A service file shared across Orders is read for structure/reference integrity; selected
Resources and actual Model changes receive quality validation. Publication uses Change
Validation plus explicit selected Stack/Resource/identifier/mapping checks, and rejects
observation changes outside selected Resource ownership. View generation remains a separate output step.
Destroy and Import retain their existing propagation and permission checks.

Necessary external producers are not deployed automatically. The existing Export Resolver
checks current required Exports before creating a consumer ChangeSet; selected producers
still require success. Missing/unknown/pending values do not prove a dependency satisfied.
Snapshot, current AWS state checks, change/replacement approval, Order barriers,
same-Order concurrency, partial saves and local sync recovery remain required.
CLI deployment remains independent: the LLM fixes the explicit selected StackNames in
its Task and applies the same Order/dependency boundaries without calling SDK Preparation.
