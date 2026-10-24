# CloudFormation Rules

- Follow [Credentials and account](project-configuration.md#credentials-and-account) for account/profile/target selection.

Follow [issue-gate](issue-gate.md) for target service stops and exceptions.

- Create, change, and execute CloudFormation only in `infrastructure` tasks.
- Infrastructure task design inputs are approved authoritative model properties entries and required parts/referenced models. Obtain design values from `desired.row.*`, JSON bodies from `desired.row.*.document`, identity/references from metadata such as `desired.resource.*`, and current non-ARN identifiers from `observed.*`. In ordinary deploy, do not additionally read generated service Markdown/service-owned JSON bodies. Resolve saved Markdown Resource links using the common Model resolver and consumer scope; stop for unknown, unmatched, or ambiguous mappings, without generated Markdown body fallback.
- Retain generated artifact existence verification, existing hash monitoring, generated artifact validation by sync-model/local loop, and stop conditions. For explicit display defect/mismatch investigation, only necessary corresponding portions may be read. Classify mismatches under Controlled deploy repair below. Do not change intended design.
- If intended design changes are needed, stop without filling values and report that a separate `design` task is required.
- Use only when the active project and target environment/target directory select CloudFormation.
- Preflight and controllers automatically use target `awsProfile` if present. Pass the same `--profile` and target region to direct AWS CLI too (including validate-template, list/get/describe, and observed value retrieval). Reject explicit profiles differing from settings before execution; do not fall back to another profile after authentication failure.
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
- Before deploy, match target account/region stacks read-only and confirm designed stack existence, states, parameters, and resource ownership. Distinguish undesigned stacks, same-named stacks differing from design, and designed stacks absent from AWS; do not automatically adopt/change/delete undesigned stacks. Retrieve current stack status from AWS each time; do not save status snapshots in Git.
- Do not interpret disappeared/renamed StackNames in design as existing stack deletion/rename. Decide ending management/deletion under a separate authorized scope with explicit targets/impacts; do not implicitly include it in current deploy/update.
- Do not create standalone templates/stacks owning only CloudWatch Logs resources (`AWS::Logs::*`) and Security Group bodies (`AWS::EC2::SecurityGroup`); include them in templates of using resources. Include IAM Roles in templates of directly using resources in the same target when present. For Roles without directly using resources (such as cross-account switch roles), confirm no same-target design resource directly references the Role and confirm its trust policy Principal; record purpose and AssumeRole sources in design before placing only the Role and associated IAM Policy/ManagedPolicy in a dedicated template/stack. Declare `RolePlacement: standalone` directly under `Metadata` in this template. This declaration expresses design decisions, not proof of nonuse in AWS. A template with InstanceProfile added is not Role-only.
- If part of a confirmed Security Group rule set creates mutual references that would cause resource or cross-stack dependency cycles, do not embed that rule set in the original owning templates. Keep Security Group bodies with their using resources, and permit a dedicated template/stack containing only `AWS::EC2::SecurityGroupIngress` and/or `AWS::EC2::SecurityGroupEgress`. Document the dependency reason in stack design, deploy it after all referenced Security Groups, and use confirmed GroupId exports through `!ImportValue` for cross-stack references. Security Group producer stacks must not depend on the rule stack.
- Cross-stack references expose only stable values needed downstream, avoiding unnecessary coupling.
- When using resources outside templates through `!Ref`, `!GetAtt`, `!Sub`, policy/setting strings, etc., identify actual resources and owning stacks. String equality alone does not establish resource references. If another CloudFormation stack in the same AWS account/region owns them, match producer template Outputs against deployed stack exports and confirm necessary values are exported. Stop without guessing unless owning stacks, referenced values, and export names are uniquely confirmed.
- If necessary exports are absent and producers are managed CREATE targets in this framework, add Output/Export for only necessary values to producer templates and deploy producer stacks first in authorized infrastructure tasks. Do not change/deploy consumer templates until terminal success and actual export names/values are confirmed read-only. Do not change export names/values used by existing imports merely for naming format. If producer/consumer cannot be handled in the same task, execute in order within task boundaries.
- After producer export confirmation, consumer templates reference that export name with `!ImportValue`. For references used within strings, pass `!ImportValue` into `!Sub` variable maps or `!Join`; do not leave physical IDs/generated ARNs as literals. Import destinations must be the same AWS account/region; create consumer change sets after producer success. Even when cross-stack ARN exports are needed, do not save generated ARNs as observed values.
- Template `Resources` keys (resource logical IDs) and final `Outputs.*.Export.Name` values must be PascalCase. Start with ASCII uppercase and use only ASCII alphanumeric characters afterward; no hyphens, underscores, or spaces. This rule does not apply to non-exported Output keys or AWS-generated physical IDs.
- For detailed design identifier references to CREATE, resolve Model Resource links and their explicit cfn-logicalId and generate `!Ref`. Do not hardcode link display text `PENDING_DEPLOY` or physical IDs into templates.
- Uniquely map models to stack resources with resource `cfn-logicalId=<StackName>-<Resources key>`; use only the trailing CFn resource ID in template `!Ref`, `!GetAtt`, and Outputs. Do not use composite IDs as template keys. Do not change anchors, confirmed resource names, or existing CFn IDs. Stop without guessing for invalid/duplicate mappings or unconfirmed final Export Name values including target-specific parameters. Existing stack logical ID/Export Name changes may delete/recreate resources or disconnect cross-stack references; do not automatically change them merely for naming format.
- Static Parameter Export templates have one narrow mapping exception, shared by implement/deploy and observed synchronization: the sole Resource is an `AWS::CloudFormation::WaitConditionHandle` declaration containing only `Type`, every Output directly `Ref`s a declared Parameter and defines `Export.Name`, and no explicit Model `cfn-logicalId` or removal applies to the Handle. Outputs must be nonempty. Prove all template expressions independent of the Handle with the existing local intrinsic evaluator, including unused branches/variable-map values; require nonempty locally resolvable Export names. Reject Transform, dependencies, resource/unknown references and unresolvable expressions conservatively. Only a proven scaffold is omitted from mappings and observed synchronization; ordinary mapping uniqueness, CREATE/type checks, integrated children, IMPORT handling and removal protection remain unchanged. Logical IDs, StackNames, environments and aliases do not select this exception.
- Even when detailed design tables are integrated, implement CREATE KMS Keys and Aliases as their respective formal CloudFormation resources. Do not generate IMPORT. Retain grouped Alias logicalIds and derived display anchors and set `!Ref` of the Key indicated by `parentReference` in model `parentProperty`. References from S3 to Aliases use the corresponding Alias `!Ref`, not Key references. Do not change existing IaC logical IDs solely because display changes.
- Expose CREATE catalog `IDENTIFIER_OUTPUT` needed by subsequent resources or other stacks in CloudFormation `Outputs` through logical resource references. Generated ARNs are excluded from output collection and observed value persistence.
- Place common templates without aliases in `infra/cloudformation/templates/` and alias-specific templates in `infra/cloudformation/templates/<alias>/`. Share templates for the same alias across environments; do not share across different aliases.
- Place target-specific parameters in `infra/cloudformation/parameters/<environment>/<target-directory>/`. The target directory is the alias if present, otherwise AWS account ID.
- If formal resource name properties or `Name` tags include Environment ID, declare independent `Environment` in template `Parameters` and set `Environment` to the target Environment ID from `project.json` in target-specific parameter files. Compose names in resource properties/tag values using `!Sub`, `!Join`, `!Ref`, etc., treating it like independent components such as AWS account IDs. Do not change confirmed complete names in detailed designs.
- Use `Environment` only for identity, naming, and value composition, including resource names, tags, and Export names. Do not use it for control-flow or selection: Conditions (including nested expressions), resource/property/Output existence, or environment-specific value selection. This includes Environment-dependent `Fn::FindInMap` map/key selectors, `Fn::Select` indexes, and `Fn::ForEach` collections, even through composed expressions. Pass differences between dev/stg/prod through explicit deployment parameters/inputs instead. Conditions and `Fn::If` controlled by independent feature/configuration parameters such as `Suffix` or `EnableVpcEndpoint` remain permitted; Condition names do not determine compliance.
- Do not include target Environment ID as a name component in parameter values other than `Environment` (resource names, prefixes, suffixes, etc.) in target-specific parameter files. For example, compose `app-dev-role` inside templates from `Environment=dev` and `NamePrefix=app`. `NamePrefix=app-dev` is a violation regardless of `Environment` parameter presence. Do not hardcode complete names in templates or embed Environment in other parameters to append it twice.
- Manage 1 environment/AWS account with only 1 IaC engine, consistent across aliases sharing an AWS account ID. Also keep engines consistent across targets sharing environment/execution account.
- `AWS::AccountId` used to evaluate local/deploy Conditions, ImportValue, artifact references, and Outputs uses the execution account. Use independent explicit parameters when passing `awsAccountId` into resource names, etc.; do not substitute native pseudo parameters. Actual stack/resource owning accounts are determined by AWS execution destinations.
- Perform authorized operations with AWS CLI.

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

`implement` phase:

1. Before implementing existing templates and before finishing generated templates, perform local read-only mapping validation with `python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py observed --environment <environment> --target-directory <target-directory> --stack <StackName>` (repeat `--stack` for each stack). Deployment resolves only resources needed for repair/bootstrap/post-success synchronization. Directly match StackNames/template resource IDs with each resource's `cfn-logicalId`; do not use separate mapping tables. Resource correspondence uses explicit cfn-logicalId and Stack identity. Evaluate Conditions with stack-specific parameters/defaults and account/region/StackName; validate CREATE, formal types, unique mappings, identifier rows, necessary GetAtt Outputs, and duplicate ownership only for active resources. Stop on unresolved, cyclic, or non-boolean Conditions; do not include inactive resources in identifier validation/ownership decisions. Do not automatically add identifier rows; aggregate deficiencies per stack. Absent new templates are not pre-implementation deficiencies; confirm model/placement inputs and always run this common validation after generation.
2. Retain local Model/provider-schema and selected template consistency checks. No template lint engine is required.
3. Do not execute AWS APIs, `aws cloudformation validate-template`, change sets, or deploy/update.

`deploy` phase:

1. Decode explicit templates/parameters with `utils/cloudformation/format.py` and monitor their full bytes/file sets; do not build whole-scope resource mappings.
2. Validate template syntax with `aws cloudformation validate-template`. This command alone does not replace property validation.
3. Create change sets and confirm scope, delete, and replacement.
4. Do not introduce human review uniformly stopping all change sets. Wait for human confirmation with an explanation according to `framework/prompts/codex/04_deploy.md` only for unapproved delete/replacement.
5. Proceed to execution only if the active prompt authorizes deploy/update, change scope matches it, and delete/replacement is preapproved or approved by the human after change set creation.
6. Preserve/classify failures under Controlled deploy repair. The supervising LLM uses a separate authorized implement Task for IaC, then returns its verified result to the same deploy session; internal runtime recovery alone may continue without IaC changes.

`framework/scripts/cloudformation-deploy.py` delegates multi-stack queues, order, parallel limits, and failure stops to `deploy/scheduler.py`. The scheduler only calls the injected backend; read workers own snapshots and the controller owns decisions and persistence. `deploy/guards.py` owns immediate mutation checks and timing. `utils/aws/` owns structured SDK operations; `utils/aws/client.py` alone owns Session/client reuse, with no global AWS response cache. Process only Deployment scope StackNames in numeric DeployOrder ascending order and StackName order within groups. Only stacks in the same DeployOrder group may run concurrently; RUNNING count must be at most MaxConcurrentStacks. Reuse free slots for the same group's queue, not fixed batches. Proceed to the next group only after terminal success and observed value reflection of the entire group. Values need not be consecutive. Do not convert DeployOrder to CloudFormation resource `DependsOn` or add dependency fields to stack models.

Immediately before consumer change set creation, interpret `!ImportValue` with the shared CloudFormation decoder, resolve referenced Export names using stack-specific parameters/defaults and account/region, and confirm existence with target `list-exports`. Evaluate Conditions; scan only selected `!If` branches and active resources/Outputs. Stop for unresolved, cyclic, or non-boolean conditions; do not require ImportValue in unused branches. Unresolved expressions, absent Exports, and unsuccessful in-scope producers are BLOCKED. Explain incorrect DeployOrder and Import/Export contradictions; do not add out-of-scope producers, change order, or automatically repair IaC/intended design. Consumer-only deploy is permitted if out-of-scope producer Exports already exist. Stop for Transform-dynamically-generated imports that cannot be resolved in advance.

On failure/rollback, blockers, or unapproved delete/replacement, do not start new units; confirm only running stacks through terminal states. Distinguish SUCCESS, FAILED, BLOCKED, and NOT_STARTED per StackName. Status API errors are not terminal failures: stop queues and retry only running stack retrieval. Do not automatically rollback, delete, or redeploy successful stacks. Rollback/delete is permitted only under the failed CREATE cleanup exceptions below.

`update` phase:

1. Generate Markdown without changing model properties manually edited by the human before task start.
2. Create/change target templates under the same approved-Model and local validation rules as implement phase.
3. Continue with the same preflight, `aws cloudformation validate-template`, change set checks, execution, and completion confirmation as deploy phase.
4. Permit only target template uncommitted diffs generated in this phase for deploy.

## Controlled deploy repair

Deploy never edits template/parameters/artifact source authority and never invokes an LLM or implement. The supervising LLM owns cause investigation and the explicitly authorized [external implement handoff](../prompts/codex/04_deploy.md#external-iac-repair-handoff). External execution copies and declared S3 delivery key/version substitution remain legitimate delivery, not source edits. Ordinary startup/Create/Execute retains no whole-scope mapping or lint. Use the existing `comparison.Comparison`/provider-schema/typed reference semantics in the separate implement Task when required; do not redesign Issues lint or general gates here.

Stop new Stack starts, drain accepted peers and synchronize successful observations before handoff. Preserve the failure set, input manifest/revision, stage, service/operation/error code, original Stack/ChangeSet/token/resource identity and execution evidence outside Git. Cause classification is independent of AWS execution status: an unexecuted ValidateTemplate/ChangeSet/input failure stays unexecuted. Approval waits keep the same ChangeSet and consume no repair cycle. Auth/read/guard/unknown-submission/observed failures are not automatically IaC candidates. Deficient design, expanded scope or uncertain cause waits for investigation/Human. Never fabricate FAILED or ROLLBACK_COMPLETE to enable repair.

- `RUNTIME_BOOTSTRAP`: Repository/model/IaC remain unchanged. For Secrets Manager missing initial Secret value/AWSCURRENT failures only, the controller may initialize a dummy runtime value in a uniquely proven in-scope CREATE-managed Secret. Error text selects the failure category only; derive identity from active consumer template expressions, explicit parameters, Ref/Sub/Join, confirmed ImportValue/Export owners, resource-owned cfn-logicalId, and actual StackId/resource mappings. Require the execution account/region and exact local/deployed owner template identity to match. IMPORT, external, cross-account, unknown ownership, generated/configured initial values, rotation/service-owned/replicated Secrets, ambiguous schemas/selectors, and unknown credential constraints are HUMAN_REQUIRED. Supported scalar slots are QuickSight DataSource CredentialPair Username/Password, RDS DBInstance/DBCluster MasterUserPassword, and Glue Connection USERNAME/PASSWORD; opaque JSON/rotation/application credential schemas require Human input. Versionless SecretString references or explicit AWSCURRENT only; extract precisely the explicitly referenced JSON keys, reject mixed whole-string/JSON consumers, and infer no additional keys.

RUNTIME_BOOTSTRAP requires separate Runtime recovery authorization and existing deploy AWS mutation authorization. Persist classification, type, consumer/failure class, canonical Secret identifier, CREATE owner/model/resource/StackId, account/region, value type, required JSON key names, stable ClientRequestToken and stage outside Git before any mutation. Resume the same intent/token through BOOTSTRAP_INTENT, VALUE_CHECKED_MISSING, PUT_SUBMITTED, BOOTSTRAP_CONFIRMED and RETRY_READY. Retrieve complete version metadata and get-secret-value inside the metadata-only SDK service function immediately before PUT; only an explicitly confirmed missing AWSCURRENT/value on an existing Secret with no other versions permits the initial PUT. Existing current values, unknown/inconsistent versions, missing resources, AccessDenied/KMS/API/network failures prohibit PUT. Never log/persist values, including the fixed dummy, in sessions, diagnostics, timing, stdout, repository or task files.

Use the guarded controller SDK functions only: put-secret-value with the stable token, DUMMY_DEPLOY_ONLY (or the minimal explicitly required JSON object), and a private per-intent stage. When necessary attach AWSCURRENT using update-secret-version-stage without RemoveFromVersionId; never move another version's current label. This prevents overwriting a value registered concurrently after the read check. An interrupted PUT is confirmed by its token/version metadata; never submit a new token/version on resume. Bootstrap at most once per Secret/workflow; recurrence of the same missing-initial-value problem forbids another PUT and empty-shell fallback. A later distinct IaC error remains diagnosable from safe structured events/code/property evidence; do not replace every post-bootstrap reason with one generic Human message. Retain the three-iteration/material-progress limits. After confirmed bootstrap, verify unchanged immutable inputs and retain unchanged failed CREATE cleanup safeguards, change-set recreation and failed-unit retry; preserve successful peer observed sync and the original DeployOrder, MaxConcurrentStacks and dependency barriers. Do not bypass failure stops with manual CLI commands or separate deploy loops.


For a scoped `ROLLBACK_COMPLETE` stack, pin its exact StackId and retrieve all `list-stack-resources` pages. When every resource is `DELETE_COMPLETE` (including an explicitly empty list), delete the empty failed stack without additional Human confirmation and create a new CREATE change set only after stack DELETE_COMPLETE. This exception also covers stacks existing before this session and resumed failures; no IaC change or same-session creation provenance is required. Missing/failed resource retrieval, remaining resources, termination protection, or a direct nested-stack target stop cleanup. Persist deletion intent and the deleted StackId outside Git, resume interrupted deletion using that ID, and reject name reuse. Allow only one recreation without material IaC repair per stack/session; repeated failures return to controlled repair classification.

An external accepted input revision may also clean a session-owned failed CREATE change-set shell while its live status is `REVIEW_IN_PROGRESS`: require original absence-before-CREATE, matching StackId/ChangeSetId, FAILED/UNAVAILABLE without execution, empty complete inventory, and no protection/parent/root. Retain the unexecuted state and original evidence, persist cleanup intent, and reacquire the normal fresh preparation boundary after deletion. Require the separate runtime-recovery authorization; never relabel this shell as rollback or reuse its delivery/approval for changed inputs.

For other `ROLLBACK_COMPLETE` cleanup candidates, require this session's confirmed absence before CREATE and a returned StackId matching the execution token StackId. Do not automatically delete if DeletionPolicy/UpdateReplacePolicy Retain/Snapshot, custom/nested resources, DELETE_SKIPPED, or existing resources remain. Match exact StackId current/resource terminal states; delete only proven failed CREATE shells and rerun CREATE after DELETE_COMPLETE confirmation. Do not infer provenance from same names. Diagnose `ROLLBACK_FAILED` and `UPDATE_ROLLBACK_FAILED` and hand off to Human because template repair alone cannot prove safe normal rollback continuation. Existing stacks outside the empty failed-stack exception and automatic `ResourcesToSkip` use are prohibited.

External repair requests freeze exact IaC paths and parent branch/checkpoint while keeping parent Allowed paths unchanged. Child is implement-only with AWS API/mutation/deploy forbidden and immutable approved Model. A signed real static-loop receipt plus exact commit/current bytes/dependency snapshot is mandatory; handwritten PASS grants no authority. Static PASS is a retry candidate, not problem resolution. A signed request/result ledger keeps workflow/problem/attempt/input histories across Task switches, process restarts and lost-session recovery. Same-result replay is idempotent; old, unrelated, reordered or unrecorded changes fail closed.

The supervising LLM explicitly diagnoses SAME/NEW/UNKNOWN against retained causes,
with concrete reasons and pinned current/prior observation, IaC and Model references.
Python validates references/scope/revisions and records that judgment; it never infers a
root cause from fingerprints, schema strings or an AWS-message pattern table. Stable
opaque problem IDs retain request targets; causeId links SAME across Resources and
shares attempts/stops. NEW must compare all retained prior problems and cannot reuse a
known structured failure by changing labels/constraintRefs. A schema pointer's existence
is not causal evidence. UNKNOWN is saved without dummy cause/constraint and issues no
request; insufficient structural distinction requires investigation/Human.
Stop A→repair→A without target progress and A→B→A. Untargeted B in A+B consumes no B
attempt. Only actual target/nested AWS successes count as progress, within 3 repairs per
cause; static FAILs stay in the same child/attempt. The total interval budget defaults
to 20. No externally verifiable Human budget approval is available: budget extension
fails closed with WAITING_HUMAN. Close/new Task cannot bypass unresolved history.



Before redeploy reject unchanged effective inputs and known failed inputs using the existing CFn decoder, parameter content and artifact hashes. No generic intrinsic evaluator or semantic-equivalence engine is added. Before cleanup archive original failures/execution evidence, verify original failed-input Retain/Custom/nested safety and live identity/token; a corrected template cannot authorize deleting old resources. begin_prepare's unchanged-input empty-shell cleanup retains delivery and reacquires Import/Export and delivery conditions at its new boundary. External changed-input acceptance invalidates old delivery/preparation/approval, including declared consumers. Preserve unaffected SUCCESS/observed; impact on SUCCESS waits for scope confirmation. Runtime recovery remains separate and may legitimately keep IaC unchanged.

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

Follow [observed-values](observed-values.md) for identifier collection/synchronization after success, and [task-contract](task-contract.md) and [loop-engineering](loop-engineering.md) for task finish.

## S3 deployment artifacts

`deploy/delivery.py`が実行用copy・object配置を、`deploy/s3_delivery.py`が取得とkey別条件判定を担当する。正本は同targetのcloudformation-stacks.properties。templateBucketは同target S3 ModelのBucketName link、templateKeyPrefixは確定prefixで両方指定または両方省略する。project設定への重複保存は禁止。

artifactはstack/resource/property/source/bucket/keyPrefixを明示する。StackName・template LogicalId・同target S3 linkを使い、file名から推測しない。sourceはinfra/cloudformation/artifacts内の既存fileのみ。directory、外部path、外へ逃げるsymlinkは禁止。複数Resourceの同source共有は可。対応はLambda Function.Code/LayerVersion.Contentの構築済ZIP、Glue Job.Command.ScriptLocation、StepFunctions StateMachine.DefinitionS3Location、ApiGateway RestApi.BodyS3Location。container/nested/Transform/未知propertyへ拡張しない。未宣言S3参照は配置済み参照として維持する。

元templateのType/property/bucket/keyPrefixを照合し、parameters/default/Ref/Sub/Join/確定ImportValueで解けない値は停止する。実行copyは宣言propertyのkey/version/URIだけcontent hashへ置換できる。bucket式・他設定・元IaC/parameters/Modelは変更しない。実行byte数でinline<=51,200、S3<=1 MiBを決定し、超過は停止。同じ内容/URLをValidateTemplateとCreateへ渡す。copyは外部sessionの.filesへ置く。

producer SUCCESS/observed反映/必要Exportsを確認し、同DeployOrderの全artifact、次に実byte数でS3が必要なtemplateを配置する。全配送確認後に新規Create/Executeへ進むbarrierを維持する。bucket作成は先行groupでinline実行し、同group bootstrap・bucket自動作成・代替bucket・scope拡張は禁止。

同じprofile/Region/期待execution ownerでHeadBucket/GetBucketLocation/GetBucketEncryption/GetBucketPolicyを取得する。S3 Modelの一意なBucket/Region/暗号化を正本とし、AES256またはaws:kmsと設計keyを送る。明示deploymentEncryption=default時だけSSE headerを省略するが、formal暗号化行は必須。既存resolverでKey/current ID/Alias-parentを解決し、DescribeKeyのaccount/Region/Enabled/対称ENCRYPT_DECRYPTを確認する。key ARNは外部sessionの一時証拠のみ。AWS/policyから設計を補わず、欠損・曖昧・未知条件で停止する。

policyはkeyごとにAction/Resource pattern、wildcard principalと暗号化条件StringEquals/NotEquals/Like/NotLike（IfExists含む）/Nullの論理積を評価する。未知の適用条件/principal/variable/否定scopeはINDETERMINATE。一般IAM engineに拡張せず、READ_DENIED/READ_UNCONFIRMED/MISMATCHを区別する。NoSuchBucketPolicyだけpolicyなしと扱う。403/timeout/壊れたpolicyを成功にしない。IAM/SCP/endpoint/実効PutObject・KMS権限は読取だけでPASSにしない。必要objectの実配置が書込確認であり、probe・IAM/KMS/policy緩和・public化は禁止。

取得共有はA同group配置準備、B各Stack Create直前、C各Stack Execute直前の関数呼出し内の明示dictだけ。context/bucket/ownerが同じ情報を共有してもkey別policy判定は残す。KMS selectorを共有しKeyId/Arnを正規化するが異なるaliasは個別解決し、request keyと検証Arnを区別する。API群を原子的snapshotと扱わない。return/承認待ち/resume/repair/入力変更/group移行を越えるcache・失敗時の古い成功へのfallbackは禁止。

object keyはprefix+SHA256+拡張子。不存在HEAD→IfNoneMatch="*"/checksum/SSE/ExpectedBucketOwner付きPutObject→古いHEAD無効化→新しいHEADでchecksum/size/暗号化/必要versionを確認する。既存objectは一致時のみ再利用し、不一致/権限欠損で上書きしない。412は新HEAD一致時だけ再利用、409/timeout等の不明結果は上限付き確認/retryとし無条件PUTへ切り替えない。同じ準備内の確認済みobjectは共有し、Create/Execute境界はfresh HEADとする。

Lambda/Layer/definition/template URLで固定versionを消費する場合と、versionless s3 URI/current key消費を区別する。古いVersionIdのHEADをcurrent確認に使わず、hash keyだけで他主体の上書き防止を保証しない。配置前に解決済暗号化条件/policy digestを外部sessionへ記録し、境界/resumeで変更を検出したら停止する。旧objectに暗号化証拠がなければ停止。実行入力hash、copy hash、bucket/key/version/checksum、ChangeSetを維持し、変更object/ZIPを旧承認で実行しない。失敗時もpeer drainを維持する。

executorにHeadBucket/Location/Encryption/Policy、ListBucket、GetObject（固定versionはGetObjectVersion）、PutObjectと必要KMS DescribeKey/暗号化/checksum取得権限、consumerの読取権限を設計する。自動付与しない。rollback用の過去artifactを自動削除せず、retention/lifecycleは明示設計による。status/URL/version/checksumをModel/Gitへ保存しない。

## Controller sessions and execution timing

`deploy/session.py` owns external state, immutable guards, target locks and recovery. `deploy/observed.py` owns post-success synchronization. CLI files are thin entrypoints, never internally loaded.

Keep one session for the exact target/scope, numeric DeployOrder and designed concurrency (or explicit sequential limit 1). Successful Stacks never execute again. On stop, drain RUNNING peers. AWS SUCCESS is independent of observedSynced: unresolved owner/reference/deletion evidence leaves SUCCESS unsynchronized, stops new starts, and replans only unsynchronized work on resume.

Session v4 retains ChangeSet/token, SUCCESS/unsynchronized observations, cleanup intent, repair evidence and counters. infraManifest/unitDigests describe IaC; inputDigest fixes root/target/scope/execution conditions; designDigest/modelInputManifest retain approved design and only proven observed transitions. Historical static PASS grants no execution permission. Signed workflow/save intents reject stale session copies and reserve cycles exactly once.



Ordinary Project Tasks treat Framework as immutable; Deploy does not scan or hash Framework definitions. Observed plan comparison validates the complete saved identity, Task/target/taskBytes, execution inputs/evidence, manifests and journal ownership. Authentication, imports, object conditions/HEAD and the latest ChangeSet remain fresh boundary reads. `--resume --observe-only` observes the current Session's original operations without AWS mutation or Model publication.

New metrics include controllerInvocationCount, deployOrderCount, awsPollCount, observedSyncSeconds, inputLoadSeconds, totalControllerSeconds and contextCheckSeconds. Preserve Stack changeSetCreateSeconds/changeSetWaitSeconds/executionSeconds/pollCount/pollApiCount. Historical metrics remain historical.

Existing external timing.jsonl records environment, contractPreparation, documentRead, documentReview, contractRegistration, authenticationContext and awsApi operation/service, success/failure, UTC and duration. Never log API arguments/responses or secrets. Individual parallel durations do not sum to wall time. Existing audit timing and receipts remain in force.

### Deployment execution

承認済Modelから正確なStackName/入力path/DeployOrder/並行数を選ぶ。Read契約に従って必須本文を読み、Model/IaC/parameters/artifactの全byteと依存file集合を監視する。preparationはoffline、runtimeは各起動で指定profile/Region/期待execution accountを一度認証する。値・target・対応付けを推測しない。

running infrastructure Taskのscope/AWS許可内だけ変更し、全mutation直前にTask/Issue/target/入力不変guardを通す。既存Stackの実owner確認は維持する。startup/resume/Create/Executeは全体mapping/lint/Issue PASS証明/過去検証cacheを実行許可にしない。implementの独立mapping検証は維持する。

同DeployOrderの全配送成功後に新規Createへ進む。実byte数inline<=51,200、S3<=1 MiBで同じ内容/URLをValidateTemplate/Createに渡す。有効Condition/Fn::IfのImportValueだけ名前を解決し、必要な時だけExports全pageを取得。必要name/value/producerだけ再確認し、scope内producerはSUCCESS必須。

Execute直前に最新の同一ChangeSetの全Changesを取得し、承認full change digest/入力digestを一致させ実行証拠を保存する。Remove/Replaceは全ChangeSetへのHuman承認が必要。intent/tokenを送信前に保存し、不明応答では同tokenをpollし再送しない。今回tokenのStack eventとterminal Stack status一致だけを成功とする。

error/曖昧/同期失敗時は新規開始を止めpeerをdrainしSUCCESSを保つ。失敗Resource、bootstrapのconsumer/Secret owner、未同期SUCCESSの更新Resourceと必要参照だけowner/type/identity解決する。Retain/DELETE_SKIPPED/削除不明はobservedをresetしない。独立identifierのない統合子で親をresetしない。全更新計画成立後に既存publication guardで保存・生成する。

## Explicit Stack destroy

Use only `framework/prompts/codex/07_destroy.md` and independent `cloudformation-destroy.py` in infrastructure phase `destroy`. Explicit human StackNames are authorized after safety checks; no duplicate confirmation. Do not route through deploy options, deploy preparation, repair, change sets or deploy mutation guards. No Terraform/resource/retained-resource/force deletion.

Resolve local units, DeployOrder, MaxConcurrentStacks, resource ownership, identifier outputs/incoming references and exact observed/model/view paths before AWS calls. Use existing deterministic model readers and explicit cfn-logicalId; legacy name inference and template/parameter body reading are prohibited. Reject out-of-target references under existing scope policy before deletion. No desired/IaC changes.

Authenticate once per invocation using existing read-only context/account logic (no IaC command requirement). Pin execution account, region, profile and each described StackId; all deletes address StackId. Confirm StackName/StackStatus/EnableTerminationProtection/ParentId/RootId. Block termination protection or direct nested targets without changing protection or scope. Share the target controller lock with deploy.

List exports once per external session, then query imports only for scoped owner exports. On resume, reuse export snapshot only when current scoped Outputs' ExportNames match it; recheck relevant imports. Outside importers block all new deletes. Require importer DeployOrder strictly greater than producer; conflicts, including the same order, block without redesign. AWS standard deletion remains the final authoritative dependency enforcement.

Delete reverse DeployOrder; cap same-order running deletions by MaxConcurrentStacks (`--sequential` uses 1). Poll every running peer before starting new work. Complete the entire group before lower orders. Failure stops starts and drains all running stacks; transient read loss stops starts, and repeated read loss preserves running state for resume. Save identity and intent before standard DeleteStack; never use FORCE_DELETE_STACK or resource-specific cleanup. DELETE_FAILED saves reason/events and blocks Human action. Fresh absence is ALREADY_ABSENT and does not prove destruction. Saved StackId plus accepted deletion/DELETE_IN_PROGRESS evidence proves DELETE_COMPLETE on subsequent absence; intent alone does not.

Use only lightweight pre-mutation task/target/account/region/profile/scope/StackId/issue-snapshot/session invariants and pinned identity reads. Never hash infra/framework/template/parameter/artifact trees or run deploy validation. Save external session state without credentials. Batch proven deleted stacks' observed synchronization once, including partial failures; report retained/DELETE_SKIPPED resources, then follow destroy completion rules.
