# CloudFormation Rules

- Follow [Credentials and account](project-configuration.md#credentials-and-account) for account/profile/target selection.

## Common rules

- Create, change, and execute CloudFormation only in `infrastructure` tasks.
- Infrastructure task design inputs are approved authoritative model properties entries and required parts/referenced models. Obtain design values from `desired.row.*`, JSON bodies from `desired.row.*.document`, identity/references from metadata such as `desired.resource.*`, and current non-ARN identifiers from `observed.*`. In ordinary deploy, do not additionally read generated service Markdown/service-owned JSON bodies. Resolve saved Markdown Resource links using the common Model resolver and consumer scope; stop for unknown, unmatched, or ambiguous mappings, without generated Markdown body fallback.
- Retain generated artifact existence verification, existing hash monitoring, generated artifact validation by sync-model/local loop, and stop conditions. For explicit display defect/mismatch investigation, only necessary corresponding portions may be read. Classify mismatches under Controlled deploy repair below. Do not change intended design.
- If intended design changes are needed, stop without filling values and report that a separate `design` task is required.
- Use only when the active project and target environment/target directory select CloudFormation.
- Do not interpret disappeared/renamed StackNames in design as existing stack deletion/rename. Decide ending management/deletion under a separate authorized scope with explicit targets/impacts; do not implicitly include it in current deploy/update.
- Manage 1 environment/AWS account with only 1 IaC engine, consistent across aliases sharing an AWS account ID. Also keep engines consistent across targets sharing environment/execution account.
- `AWS::AccountId` used to evaluate local/deploy Conditions, ImportValue, artifact references, and Outputs uses the execution account. Use independent explicit parameters when passing `awsAccountId` into resource names, etc.; do not substitute native pseudo parameters. Actual stack/resource owning accounts are determined by AWS execution destinations.

## Template implementation

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
- CloudFormation target stack creation/update requires stack detailed design from `framework/rules/detailed-design.md`. Resolve each stack instance's StackName, template filename, individual parameter filename, DeployOrder, and target MaxConcurrentStacks from authoritative `cloudformation-stacks.properties`. During deploy, existing `load_units()` confirms equality with generated stack Markdown; AI manual duplicate comparison of the same values is not required. Retain existing sync-model/local loop timing for ordinary service generated artifact validation. Template/parameter locations follow this rule's path conventions. Do not infer StackNames from template/parameter filenames alone.
- Do not create standalone templates/stacks owning only CloudWatch Logs resources (`AWS::Logs::*`) and Security Group bodies (`AWS::EC2::SecurityGroup`); include them in templates of using resources. Include IAM Roles in templates of directly using resources in the same target when present. For Roles without directly using resources (such as cross-account switch roles), confirm no same-target design resource directly references the Role and confirm its trust policy Principal; record purpose and AssumeRole sources in design before placing only the Role and associated IAM Policy/ManagedPolicy in a dedicated template/stack. Declare `RolePlacement: standalone` directly under `Metadata` in this template. This declaration expresses design decisions, not proof of nonuse in AWS. A template with InstanceProfile added is not Role-only.
- If part of a confirmed Security Group rule set creates mutual references that would cause resource or cross-stack dependency cycles, do not embed that rule set in the original owning templates. Keep Security Group bodies with their using resources, and permit a dedicated template/stack containing only `AWS::EC2::SecurityGroupIngress` and/or `AWS::EC2::SecurityGroupEgress`. Document the dependency reason in stack design, deploy it after all referenced Security Groups, and use confirmed GroupId exports through `!ImportValue` for cross-stack references. Security Group producer stacks must not depend on the rule stack.
- Template `Resources` keys (resource logical IDs) and final `Outputs.*.Export.Name` values must be PascalCase. Start with ASCII uppercase and use only ASCII alphanumeric characters afterward; no hyphens, underscores, or spaces. This rule does not apply to non-exported Output keys or AWS-generated physical IDs.
- For detailed design identifier references to CREATE, resolve Model Resource links and their explicit cfn-logicalId and generate `!Ref`. Do not hardcode link display text `PENDING_DEPLOY` or physical IDs into templates.
- Uniquely map models to stack resources with resource `cfn-logicalId=<StackName>-<Resources key>`; use only the trailing CFn resource ID in template `!Ref`, `!GetAtt`, and Outputs. Do not use composite IDs as template keys. Do not change anchors, confirmed resource names, or existing CFn IDs. Stop without guessing for invalid/duplicate mappings or unconfirmed final Export Name values including target-specific parameters. Existing stack logical ID/Export Name changes may delete/recreate resources or disconnect cross-stack references; do not automatically change them merely for naming format.
- Static Parameter Export templates have one narrow mapping exception, shared by implement/deploy and observed synchronization: the sole Resource is an `AWS::CloudFormation::WaitConditionHandle` declaration containing only `Type`, every Output directly `Ref`s a declared Parameter and defines `Export.Name`, and no explicit Model `cfn-logicalId` or removal applies to the Handle. Outputs must be nonempty. Prove all template expressions independent of the Handle with the existing local intrinsic evaluator, including unused branches/variable-map values; require nonempty locally resolvable Export names. Reject Transform, dependencies, resource/unknown references and unresolvable expressions conservatively. Only a proven scaffold is omitted from mappings and observed synchronization; ordinary mapping uniqueness, CREATE/type checks, integrated children, IMPORT handling and removal protection remain unchanged. Logical IDs, StackNames, environments and aliases do not select this exception.
- Even when detailed design tables are integrated, implement CREATE KMS Keys and Aliases as their respective formal CloudFormation resources. Do not generate IMPORT. Retain grouped Alias logicalIds and derived display anchors and set `!Ref` of the Key indicated by `parentReference` in model `parentProperty`. References from S3 to Aliases use the corresponding Alias `!Ref`, not Key references. Do not change existing IaC logical IDs solely because display changes.
- Expose CREATE catalog `IDENTIFIER_OUTPUT` needed by subsequent resources or other stacks in CloudFormation `Outputs` through logical resource references. Generated ARNs are excluded from output collection and observed value persistence.
- Place common templates without aliases in `infra/cloudformation/templates/` and alias-specific templates in `infra/cloudformation/templates/<alias>/`. Share templates for the same alias across environments; do not share across different aliases.
- Place target-specific parameters in `infra/cloudformation/parameters/<environment>/<target-directory>/`. The target directory is the alias if present, otherwise AWS account ID.
- When a template references `Environment`, declare it in template `Parameters` and set it to the target Environment ID from `project.json` in target-specific parameter files. Compose names in resource properties/tag values using `!Sub`, `!Join`, `!Ref`, etc., treating it like independent components such as AWS account IDs. Do not change confirmed complete names in detailed designs.
- `Environment` may be used in CloudFormation-supported conditions and environment-specific selection, including `Conditions`, Resource and Output `Condition`, `Fn::If`, `Fn::FindInMap`, `Fn::Select`, and `Fn::ForEach`, subject to CloudFormation syntax and placement constraints. Independent feature flags may be used when the design calls for them, but are not required solely to express environment differences.
- Do not include target Environment ID as a name component in parameter values other than `Environment` (resource names, prefixes, suffixes, etc.) in target-specific parameter files. For example, compose `app-dev-role` inside templates from `Environment=dev` and `NamePrefix=app`. `NamePrefix=app-dev` is a violation regardless of `Environment` parameter presence. Do not hardcode complete names in templates or embed Environment in other parameters to append it twice.

## Cross-stack references

- Cross-stack references expose only stable values needed downstream, avoiding unnecessary coupling.
- When using resources outside templates through `!Ref`, `!GetAtt`, `!Sub`, policy/setting strings, etc., identify actual resources and owning stacks. String equality alone does not establish resource references. If another CloudFormation stack in the same AWS account/region owns them, match producer template Outputs against deployed stack exports and confirm necessary values are exported. Stop without guessing unless owning stacks, referenced values, and export names are uniquely confirmed.
- If necessary exports are absent and producers are managed CREATE targets in this framework, add Output/Export for only necessary values to producer templates and deploy producer stacks first in authorized infrastructure tasks. Do not change/deploy consumer templates until terminal success and actual export names/values are confirmed read-only. Do not change export names/values used by existing imports merely for naming format. If producer/consumer cannot be handled in the same task, execute in order within task boundaries.
- After producer export confirmation, consumer templates reference that export name with `!ImportValue`. For references used within strings, pass `!ImportValue` into `!Sub` variable maps or `!Join`; do not leave physical IDs/generated ARNs as literals. Import destinations must be the same AWS account/region; create consumer change sets after producer success. Even when cross-stack ARN exports are needed, do not save generated ARNs as observed values.

## AWS execution context

- Preflight and controllers automatically use target `awsProfile` if present. Pass the same `--profile` and target region to direct AWS CLI too (including validate-template, list/get/describe, and observed value retrieval). Reject explicit profiles differing from settings before execution; do not fall back to another profile after authentication failure.
- Before deploy, match target account/region stacks read-only and confirm designed stack existence, states, parameters, and resource ownership. Distinguish undesigned stacks, same-named stacks differing from design, and designed stacks absent from AWS; do not automatically adopt/change/delete undesigned stacks. Retrieve current stack status from AWS when needed and retain execution state in the existing execution management, not the Stack Model.
- Framework SDK controllers perform authorized operations through `utils/aws/`; use AWS CLI only for explicitly directed CLI operations.

## Design coverage and CloudFormation support

- Detailed designs/models also contain CFn-unsupported resources. Resolve formal CFn types for every implementation target resource type with `python framework/scripts/design_catalog.py --cloudformation-type <catalog-resource-type>`. Unknown types or `cloudFormationType: null` are failures; do not invent `AWS::` types merely by resource type string replacement.
- `Macie.Session` uses existing CFn schemas. Treat `Macie.ClassificationJob` and `QuickSight.Group` as CFn-unsupported; do not include them in CFn templates, Outputs, or `!Ref`.
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

1. Before implementing existing templates and before finishing generated templates, perform local read-only mapping validation with `python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py observed --environment <environment> --target-directory <target-directory> --stack <StackName>` (repeat `--stack` for each stack). Deployment resolves only resources needed for repair/bootstrap/current Snapshot synchronization. Directly match StackNames/template resource IDs with each resource's `cfn-logicalId`; do not use separate mapping tables. Resource correspondence uses explicit cfn-logicalId and Stack identity. Evaluate Conditions with stack-specific parameters/defaults and account/region/StackName; validate CREATE, formal types, unique mappings, identifier rows, necessary GetAtt Outputs, and duplicate ownership only for active resources. Stop on unresolved, cyclic, or non-boolean Conditions; do not include inactive resources in identifier validation/ownership decisions. Do not automatically add identifier rows; aggregate deficiencies per stack. Absent new templates are not pre-implementation deficiencies; confirm model/placement inputs and always run this common validation after generation.
2. Retain local Model/provider-schema and selected template consistency checks. No template lint engine is required.
3. Do not execute AWS APIs, `aws cloudformation validate-template`, change sets, or deploy/update.

### Deployment validation and execution

`deploy` phase:

1. Decode explicit templates/parameters with `utils/cloudformation/format.py` and monitor their full bytes/file sets; do not build whole-scope resource mappings.
2. Validate template syntax with `aws cloudformation validate-template`. This command alone does not replace property validation.
3. Create change sets and confirm scope, delete, and replacement.
4. Do not introduce human review uniformly stopping all change sets. Wait for human confirmation with an explanation according to `framework/prompts/codex/04_deploy.md` only for unapproved delete/replacement.
5. Proceed to execution only if the active prompt authorizes deploy/update, change scope matches it, and delete/replacement is preapproved or approved by the human after change set creation.
6. Preserve/classify failures under Controlled deploy repair. The supervising LLM uses a separate authorized implement Task for IaC, then integrates its verified result before an independent new Deploy; internal runtime recovery alone may continue without IaC changes.

`framework/scripts/cloudformation-deploy.py` delegates multi-stack queues, order, parallel limits, and failure stops to `deploy/scheduler.py`. The scheduler only calls the injected backend; read workers own snapshots and the controller owns decisions and persistence. `deploy/guards.py` owns immediate mutation checks and timing. `utils/aws/` owns structured SDK operations; `utils/aws/client.py` alone owns Session/client reuse, with no global AWS response cache. Process only Deployment scope StackNames in numeric DeployOrder ascending order and StackName order within groups. Only stacks in the same DeployOrder group may run concurrently; RUNNING count must be at most MaxConcurrentStacks. Reuse free slots for the same group's queue, not fixed batches. Proceed to the next group only after the required earlier AWS attempts succeed. Observed/Git saving is chosen explicitly and is not an additional Order barrier; actual Consumer input dependencies still apply. Values need not be consecutive. Do not convert DeployOrder to CloudFormation resource `DependsOn` or add dependency fields to stack models.

Immediately before consumer change set creation, interpret `!ImportValue` with the shared CloudFormation decoder, resolve referenced Export names using stack-specific parameters/defaults and account/region, and resolve them through the shared Export resolver. A known Producer is revalidated with scoped `DescribeStacks(StackName=StackId)` Outputs, StackId/status and saved Export value/owner; this path never calls ListExports. Only required names whose Producer remains unknown may share one complete ListExports discovery within that verification boundary; DescribeStacks must then reconfirm each discovered Producer. Missing, ambiguous or changed evidence blocks. Evaluate Conditions; scan only selected `!If` branches and active resources/Outputs. Stop for unresolved, cyclic, or non-boolean conditions; do not require ImportValue in unused branches. Unresolved expressions, absent Exports, and unsuccessful in-scope producers are BLOCKED. Explain incorrect DeployOrder and Import/Export contradictions; do not add out-of-scope producers, change order, or automatically repair IaC/intended design. Consumer-only deploy is permitted if out-of-scope producer Exports already exist. Stop for Transform-dynamically-generated imports that cannot be resolved in advance.

A failure/rollback stops dependent later Orders; independent peers at the same Order may continue. Unapproved delete/replacement blocks that Stack. Distinguish SUCCESS, FAILED, BLOCKED, and NOT_STARTED per StackName. Status API errors are not absence or terminal failure; retain that Stack request and continue independent scoped work. Do not automatically rollback, delete, or redeploy successful stacks. Rollback/delete is permitted only under the failed CREATE cleanup exceptions below.

### Infrastructure update execution

`update` phase:

1. Generate Markdown without changing model properties manually edited by the human before task start.
2. Create/change target templates under the same approved-Model and local validation rules as implement phase.
3. Continue with the same preflight, `aws cloudformation validate-template`, change set checks, execution, and completion confirmation as deploy phase.
4. Permit only target template uncommitted diffs generated in this phase for deploy.

## Controlled deploy repair

Deploy never edits IaC. Diagnose the current failed Stack and structured AWS error against approved Model and exact inputs. Proven IaC defects use the separately authorized one-shot [Implement handoff](../prompts/codex/04_deploy.md#external-iac-repair-handoff): settle unfinished operations, pin/checkpoint current Task/input authority, suspend parent, isolate child, run static validation, verify exact commit/paths/bytes, ff-only integrate, discard temporary evidence and start an independent Deploy from latest IaC/AWS. No Session, Workflow Ledger/Registry, cumulative attempt budget, SAME/NEW history or historical approval participates. Unknown cause, authentication/scope/design defects and unconfirmed submissions require investigation/Human action.

Runtime bootstrap remains separate and changes no IaC. Preserve original StackId/Token, failed-template Retain/Custom/nested safety, deletion inventory/protection and empty-shell ownership checks. At most one same-Stack bootstrap/empty-shell retry is permitted within a run; Secrets versions and unfinished stable Token prevent duplicate initialization after interruption. Never use corrected template policy as authority to delete old resources. A subsequent run accepts latest IaC and creates/evaluates its own ChangeSet; no local hash alone proves AWS application.

## Delete and replacement confirmation

`deploy/change_sets.py` owns preparation, content approval and immediate execution checks. Approval identifies the saved ChangeSet and full content digest. Before execution, save StackId, ChangeSetId, changeDigest, clientToken, inputDigest and each change LogicalResourceId/ResourceType/PhysicalResourceId/Action/Replacement/PolicyAction. No Model mapping is required to save this evidence. Fill missing physical identities only from exact AWS resource information; unknown deletion never resets identifiers.

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

Follow [observed-values](observed-values.md) for current identifier collection/synchronization regardless of attempt outcome, and [task-contract](task-contract.md) and [loop-engineering](loop-engineering.md) for task finish.

## S3 deployment artifacts

### Artifact declarations

`deploy/delivery.py`が実行用copy・object配置を、`deploy/s3_delivery.py`が取得とkey別条件判定を担当する。正本は同targetのcloudformation-stacks.properties。templateBucketは同target S3 ModelのBucketName link、templateKeyPrefixは確定prefixで両方指定または両方省略する。project設定への重複保存は禁止。

artifactはstack/resource/property/source/bucket/keyPrefixを明示する。StackName・template LogicalId・同target S3 linkを使い、file名から推測しない。sourceはinfra/cloudformation/artifacts内の既存fileのみ。directory、外部path、外へ逃げるsymlinkは禁止。複数Resourceの同source共有は可。対応はLambda Function.Code/LayerVersion.Contentの構築済ZIP、Glue Job.Command.ScriptLocation、StepFunctions StateMachine.DefinitionS3Location、ApiGateway RestApi.BodyS3Location。container/nested/Transform/未知propertyへ拡張しない。未宣言S3参照は配置済み参照として維持する。

### Artifact execution

元templateのType/property/bucket/keyPrefixを照合し、parameters/default/Ref/Sub/Join/確定ImportValueで解けない値は停止する。実行copyは宣言propertyのkey/version/URIだけcontent hashへ置換できる。bucket式・他設定・元IaC/parameters/Modelは変更しない。実行byte数でinline<=51,200、S3<=1 MiBを決定し、超過は停止。同じ内容/URLをValidateTemplateとCreateへ渡す。copyは今回runの外部一時directoryへ置く。

producer SUCCESS/observed反映/必要Exportsを確認し、同DeployOrderの全artifact、次に実byte数でS3が必要なtemplateを配置する。全配送確認後に新規Create/Executeへ進むbarrierを維持する。bucket作成は先行groupでinline実行し、同group bootstrap・bucket自動作成・代替bucket・scope拡張は禁止。

同じprofile/Region/期待execution ownerでHeadBucket/GetBucketLocation/GetBucketEncryption/GetBucketPolicyを取得する。S3 Modelの一意なBucket/Region/暗号化を正本とし、AES256またはaws:kmsと設計keyを送る。明示deploymentEncryption=default時だけSSE headerを省略するが、formal暗号化行は必須。既存resolverでKey/current ID/Alias-parentを解決し、DescribeKeyのaccount/Region/Enabled/対称ENCRYPT_DECRYPTを確認する。key ARNは今回runの一時証拠のみ。AWS/policyから設計を補わず、欠損・曖昧・未知条件で停止する。

policyはkeyごとにAction/Resource pattern、wildcard principalと暗号化条件StringEquals/NotEquals/Like/NotLike（IfExists含む）/Nullの論理積を評価する。未知の適用条件/principal/variable/否定scopeはINDETERMINATE。一般IAM engineに拡張せず、READ_DENIED/READ_UNCONFIRMED/MISMATCHを区別する。NoSuchBucketPolicyだけpolicyなしと扱う。403/timeout/壊れたpolicyを成功にしない。IAM/SCP/endpoint/実効PutObject・KMS権限は読取だけでPASSにしない。必要objectの実配置が書込確認であり、probe・IAM/KMS/policy緩和・public化は禁止。

取得共有はA同group配置準備、B各Stack Create直前、C各Stack Execute直前の関数呼出し内の明示dictだけ。context/bucket/ownerが同じ情報を共有してもkey別policy判定は残す。KMS selectorを共有しKeyId/Arnを正規化するが異なるaliasは個別解決し、request keyと検証Arnを区別する。API群を原子的snapshotと扱わない。return/承認待ち/resume/repair/入力変更/group移行を越えるcache・失敗時の古い成功へのfallbackは禁止。

object keyはprefix+SHA256+拡張子。不存在HEAD→IfNoneMatch="*"/checksum/SSE/ExpectedBucketOwner付きPutObject→古いHEAD無効化→新しいHEADでchecksum/size/暗号化/必要versionを確認する。既存objectは一致時のみ再利用し、不一致/権限欠損で上書きしない。412は新HEAD一致時だけ再利用、409/timeout等の不明結果は上限付き確認/retryとし無条件PUTへ切り替えない。同じ準備内の確認済みobjectは共有し、Create/Execute境界はfresh HEADとする。

Lambda/Layer/definition/template URLで固定versionを消費する場合と、versionless s3 URI/current key消費を区別する。古いVersionIdのHEADをcurrent確認に使わず、hash keyだけで他主体の上書き防止を保証しない。配置前に解決済暗号化条件/policy digestを今回run内へ記録し、境界/resumeで変更を検出したら停止する。旧objectに暗号化証拠がなければ停止。実行入力hash、copy hash、bucket/key/version/checksum、ChangeSetを維持し、変更object/ZIPを旧承認で実行しない。失敗時もpeer drainを維持する。

executorにHeadBucket/Location/Encryption/Policy、ListBucket、GetObject（固定versionはGetObjectVersion）、PutObjectと必要KMS DescribeKey/暗号化/checksum取得権限、consumerの読取権限を設計する。自動付与しない。rollback用の過去artifactを自動削除せず、retention/lifecycleは明示設計による。status/URL/version/checksumをModel/Gitへ保存しない。

## Independent controller runs and execution timing

### LLM-controlled short operations

Use `cloudformation-deploy.py --action status|advance|sync|checkpoint` in the existing
managed Worktree, with the same current Task, Target and complete Stack scope.
Only the LLM chooses sync timing and explicit `--sync-stack` names. Do not use Sub Agents,
a background Model writer, fixed-period sync or Python-driven agent control.

- `status` reads current AWS and displays current Stack state, this attempt's result,
  Model save, Snapshot validation and Git publication separately.
- `advance` reads current AWS first and advances one bounded poll/prepare/execute turn.
  It keeps DeployOrder and the configured concurrency. A failed Stack does not stop
  independent peers in the same Order. A later Order requires prior Order success;
  saving a failure Snapshot never grants that success.
- `sync` reads the selected current observations, atomically saves permitted Model
  changes, generates available services, validates the complete candidate and uses
  existing checkpoint/Git publication. No separate checkpoint command is required.
- `checkpoint` resumes a saved candidate's validation/commit/publication without a
  new AWS execution or fresh observation. A saved completed contract may retry Git only.

Sync accepts successful, failed, rolled-back, partially applied, unexecuted, running
and unreadable Stacks. Unexecuted does not mean absent. Consistent observations may
be saved while another Stack is changing; no target-wide quiescence is required.
Generation failures retain saved Model authority and successful service outputs;
stale Views are not claimed current. True structural/reference/scope/View mismatch
blocks integration, retaining the candidate for local recovery without new AWS work.

### Explicit operations

Specify `--action` for each invocation. Use `advance` for a bounded turn and `status` to inspect current requests without saving or publication. Select `sync` and `checkpoint` explicitly for Model saving and Git publication. Select sync before the producer/consumer input handoff. Claimed inputs remain fixed; a later update invocation may claim its newly implemented, previously unused Consumer inputs. This grants no IaC changes to Deploy.

Normal decisions use current scoped DescribeStacks and ChangeSets plus this Task's
fixed inputs. CREATE_COMPLETE / UPDATE_COMPLETE / IMPORT_COMPLETE are successful
current states, but do not prove the current Desired is applied. Build/review the
current ChangeSet. UPDATE_ROLLBACK_COMPLETE permits a subsequent update while
retaining the failed attempt result. UPDATE_ROLLBACK_FAILED and ROLLBACK_COMPLETE
retain AWS's actual operation restrictions. REVIEW_IN_PROGRESS is classified with
current ChangeSet execution, never by suffix alone. Structured absence is ABSENT;
read/permission/network failures are UNKNOWN, never absence.

Shared records contain only current unresolved submissions, keyed by execution account,
Region and StackName: operation, StackId, ChangeSetId, ClientRequestToken (ClientToken
for CreateChangeSet), submission state and pre-send AWS identity. Persist intent under
the same Stack lock immediately before submission. Lost replies retain the original
request/token across Worktrees. A single old UPDATE_COMPLETE does not settle an
uncertain Execute; inspect its ChangeSet and token events. Retire a confirmed AWS
request before Model/Git work. No TTL/PID inference or old Task/Outputs/checkpoint proof.
Corruption affects only that Stack's new mutation; other Stacks and Snapshot saves continue.

The account/Region compatibility lock also excludes old running controllers during
one-time format conversion. Preserve the raw old journal, migrate only possibly pending
AWS requests, and write the protocol marker that old controllers reject before mutation.
Do not use older controller code after cutover. Normal calls inspect the marker and
selected current requests, never scan or validate all old history. Historical failures,
completed or sync/Git-waiting records and old Fences are not new request conditions.

### Managed Deploy snapshot and Git publication

Independent Deploy uses `worktree_task.py deploy-start --task-id <id>`, reusing a
suitable valid managed Worktree. Keep lifecycle ownership, current Task authority,
Target/Account/Region, destructive-change consent and fixed IaC/parameters/artifacts.
Self-authored Observed/View/contract commits advance HEAD without changing execution
inputs. Base advancement or rewritten publication history does not replace fixed inputs.
No historical digest/executionDigest ledger is added. Other Workflow safeguards remain.

Local sealed progress resumes this Task's save/generation/checkpoint. Git receipts prove
only saved candidates; restoring one never creates AWS SUCCESS. Current observations,
attempt result, Snapshot validation, commit/merge and Task state remain separate.
A failure Snapshot can have Deploy FAIL, UPDATE_ROLLBACK_COMPLETE, Snapshot PASS,
commit/merge complete and Task completed. Desired remains the Human's intended design.

Reuse the existing private candidate against the latest clean local base, scoped
Model/Task validation, lifecycle lock and ff-only delivery. Validate the actual final
candidate, including authorized scope, structure/types, references, unknown/pending
identifiers and corresponding generated Views. No all-Stack success, all physical IDs,
Desired/Observed equality, individual checkpoints or old Journal/Fence completion is
required. Do not scan unrelated AWS resources or regenerate unrelated services.

The final snapshot includes Task completed when observations, required generation and
validation are complete and no AWS request is active/uncertain. Intermediate saves keep
Task running and the same Worktree can continue AWS work. Failed finalized attempts do
not remain suspended as old recovery work. AWS failure stays FAIL; validation remains
PASS/FAIL and unexecuted required checks are never PASS. Other Workflow completion is unchanged.

Git publication has independent SUCCESS/PENDING/CONFLICT. Commit success with merge
failure retains the exact candidate (possibly completed locally). Use only
`worktree_task.py deploy-publish --task-id <id>` to retry saved commits; no AWS call,
Observed recollection or working-candidate commit is required. Existing Human conflict
review remains: inspect files/base/source/impact, provide the approved exact resolution
through `--publication-resolution <absolute-json-path>`, and validate the resulting
candidate before delivery. Never automatically overwrite conflicts or force integration.
After verified publication, ordinary finalize verifies and performs guarded cleanup.

A settled current request may leave its attempt outcome UNKNOWN while the current Snapshot is saved and validated independently. Never persist UNKNOWN as an identifier. Exact root Stack events use the original StackId/token; later Stack replacement, repair or failure cannot rewrite the original attempt result or replace current observation fields.

### Human-authorized operation journal reset

Lost signature keys need no separate exception ledger or release proof. Use the same
Reset plan/apply with preserved raw originals; the retired lost-key commands are not required.

Only the Human decides Reset scope and approves it explicitly. Never Reset automatically
because recovery fails or records are corrupt. The LLM must not enter console consent;
console simulation is confined to synthetic offline tests. Reset calls no AWS APIs.

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-operation-reset.py plan --environment dev --alias cde --mode all
python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-operation-reset.py plan --environment dev --alias cde --mode record --record <record-sha256>
python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-operation-reset.py apply --environment dev --alias cde --plan <plan-sha256>
```

Plan lists exact recovery records, related old Fences and lost information together.
ALL supports corrupt JSON/old proof. RECORD selects whole records or exact Fence IDs;
related files join the same Plan, unrelated records remain. Keep target configuration,
private ownership, safe paths, exact bytes and current-request locks. No force/bypass.

One explicit approval covers that Plan's complete action. Persist approval and every
original before processing records/Fences. The Reset transaction is never a new Fence.
No RESOLVE step, release proof or additional approval follows.

Retry the same Plan after interruption. Reuse its durable approval, finish remaining
exact targets, and infer completion from processed files if only the result notification
is missing. Preserve raw corrupt originals. A newly created request or changed file is
outside the old approval and is never deleted on retry. Backup failure leaves original
records intact. Keep private originals and approval outside Git for the Reset transaction.

Reset does not stop AWS, certify success/rollback, resolve Model values or publish a
Task. If AWS is still running, Reset itself completes and normal current-state
classification continues to report RUNNING. No Reset history gates ordinary Deploy.

### Deployment execution

Use current Task/target/account/Region/profile/scope/input guards before each mutation, original ChangeSet ID/Stack ID and full content re-fetch immediately before Execute, and one stable persisted Token for uncertain submissions. Human approval applies only to the current complete destructive ChangeSet. Hold new starts for actual authority/scope/concurrency violations and drain active requests. A failed Stack leaves independent same-Order peers eligible; later Orders still require their earlier AWS success conditions. The LLM explicitly saves current observations for any outcome and verifies current Output/Export facts. Retain/DELETE_SKIPPED/unknown destruction and integrated children without identifiers never reset identifiers. Do not change IaC, widen scope or infer missing evidence.

## Explicit Stack destroy

Use only `framework/prompts/codex/07_destroy.md` and independent `cloudformation-destroy.py` in infrastructure phase `destroy`. Explicit human StackNames are authorized after safety checks; no duplicate confirmation. Do not route through deploy options, deploy preparation, repair, change sets or deploy mutation guards. No Terraform/resource/retained-resource/force deletion.

Resolve local units, DeployOrder, MaxConcurrentStacks, resource ownership, identifier outputs/incoming references and exact observed/model/view paths before AWS calls. Use existing deterministic model readers and explicit cfn-logicalId; legacy name inference and template/parameter body reading are prohibited. Reject out-of-target references under existing scope policy before deletion. No desired/IaC changes.

Authenticate once per invocation through the existing `deploy/context.py` read-only target/account and STS logic (no IaC command requirement). Destroy uses the existing SDK, not an AWS CLI subprocess: DescribeStacks, ListImports and DeleteStack use `utils/aws/cloudformation.py`; DescribeStackEvents uses the common `utils/aws/client.py` request per page. Pin execution account, region, profile and each described StackId; all deletes address StackId. Confirm StackName/StackStatus/EnableTerminationProtection/ParentId/RootId. Block termination protection or direct nested targets without changing protection or scope. Share the target controller lock with deploy.

Build the Export snapshot once per external session from confirmed scoped Stack Outputs, then query imports only for scoped owner exports; do not call ListExports. On resume, reuse export snapshot only when current scoped Outputs' ExportNames match it; recheck relevant imports. Outside importers block all new deletes. Require importer DeployOrder strictly greater than producer; conflicts, including the same order, block without redesign. AWS standard deletion remains the final authoritative dependency enforcement.

Delete reverse DeployOrder; cap same-order running deletions by MaxConcurrentStacks (`--sequential` uses 1). Poll every running peer before starting new work. Complete the entire group before lower orders. Failure stops starts and drains all running stacks; transient read loss stops starts, and repeated read loss preserves running state for resume. Save identity and intent before standard DeleteStack; never use FORCE_DELETE_STACK or resource-specific cleanup. DELETE_FAILED saves reason/events and blocks Human action. Fresh absence is ALREADY_ABSENT and does not prove destruction. Saved StackId plus accepted deletion/DELETE_IN_PROGRESS evidence proves DELETE_COMPLETE on subsequent absence; intent alone does not.

Use only lightweight pre-mutation task/target/account/region/profile/scope/StackId/session invariants and pinned identity reads. Never hash infra/framework/template/parameter/artifact trees or run deploy validation. Save external session state without credentials. Batch proven deleted stacks' observed synchronization once, including partial failures; report retained/DELETE_SKIPPED resources, then follow destroy completion rules.

## Scoped CloudFormation reference reads

Deploy delivery, Create and Execute use independent verification boundaries; acquired AWS responses never cross them. Same-boundary Producer reads are shared. Unfinished-operation independence retains the existing Producer→Consumer graph, seeded by scoped Stack Outputs, saved delivery imports and current planned imports. ListImports reads only Exports owned by reached Stacks; shared Producers alone do not create a conflict. Cycles/diamonds are deduplicated; absent, incomplete or changed proof blocks. Repair permits scoped DescribeStacks in this same proof.

DescribeStacks/DescribeStackEvents/GetTemplate/ListExports are limited to 5 req/s and ListImports to 1 req/s per execution Account/Region/API across all Threads and profiles in the process. The common SDK read controller accounts for every page and retry, retries only Throttling with exponential backoff and jitter, and shares the operation deadline. Controlled read SDK clients use one transport attempt; mutation SDK clients use standard retries with up to two total attempts. The slot remains held through transport completion to prevent delayed requests bunching together. Other processes are outside this budget.

Destroy preflight validates scoped StackIds/Outputs and records exportNames; dependency snapshots use those names/owners, never ListExports. Resume compares saved Export ownership/names with fresh scoped Outputs before targeted ListImports. Unknown or changed evidence stops deletion; order, approval and out-of-scope importer guards remain required. Destroy SDK reads use the same in-process Account/Region/API budgets and common retry control. DescribeStackEvents requests each page with a shared deadline until the root DELETE_IN_PROGRESS event or the end, rejecting invalid continuation tokens.
