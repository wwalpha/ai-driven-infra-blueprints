# Infrastructure Deployment Prompt

## Normal startup

Human指定のenvironment、alias/account、execution account、Region/profile、StackNameとservice IDsを確定する。project.jsonの同じtargetだけを使い、認証失敗時に別credentialへ切り替えない。Task契約とAWS実行許可を確認する。Deploy本体はIaC、意図した設計、scenarioを変更しない。

各起動は最新Worktree入力とAWS実状態から独立して実行する。永続Deploy Session、過去IaC Manifest、修復回数、SAME/NEW履歴、過去Human承認、Workflow Ledger/Registryは読み書きしない。旧Sessionファイルを移行・削除せず入力から除外する。以前SUCCESSだったStackも今回のIaCで通常のUPDATE候補とする。ローカルhashだけで適用済みと判定しない。

```console
<fixed-python> framework/scripts/deploy_preparation.py --environment <environment> --alias <alias> --stack <StackName> [--stack <StackName> ...] --service <service-id> [--service <service-id> ...] --task-file tasks/<task-name>.md [--profile <profile>] [--sequential] [--allow-external-repair]
<fixed-python> framework/scripts/deploy_preparation.py --register <external-preparation.json>
<fixed-python> framework/scripts/deploy_preparation.py --run-controller <external-preparation.json>
```

aliasなしは--aws-account-id。preparationはoffline。固定Python/PATH/PYTHONPATHを使い、documentsの必須本文、対象要約と契約候補を読む。hash一致は読了証明ではない。登録は最初の変更とする。既存Taskでは現在契約を選択しcontrollerを直接新規起動できる。preparation/controllerで同じ認証や検査をAI側から重複実行しない。

```console
<fixed-python> framework/scripts/cloudformation-deploy.py --environment <environment> --alias <alias> --stack <StackName> [--stack <StackName> ...] [--profile <profile>] [--sequential] [--timing-log <external.jsonl>]
```

## Lazy inputs and Model reuse

一つのDeployRunContextをメモリ内だけで保持する。load_units()でStack Modelとgenerated Stack view一致、DeployOrder、MaxConcurrentStacksを確認する。空きslot分だけIaCをclaim/decodeし、未着手IaC本文・全service Modelを先読みしない。同じModelのロードと同一世代の検証は実行内共有Cacheで一回とする。Observedで参照依存が変化した場合だけ既存の検証Cacheを失効させる。入力のbytes/識別情報/集合、Task、targetを固定し、途中変更は取り込まず停止する。次の独立起動では更新された入力を採用する。

既存Stack所有権、ValidateTemplate、Import/Export、S3配送barrier、ChangeSet再取得、実行Token、poll/drainを維持する。AWSの実行中Stackは完了を観測してから新しいChangeSetを作る。不明状態はBLOCKED。No Changeでも現在のAWS terminal successと必要Output/Exportを確認し、欠落・owner/value不一致なら未反映として停止する。KMS KeyId Export 4件の追加も例外を作らない。

Stack成功ごとにObservedと必要参照を同期する。AWS SUCCESSとobservedSyncedを分離する。既存publication lock、Task authority、Modelのbefore/after CAS、part集合、Rollback journal、Markdown/JSONのatomic publicationを維持する。checkout-localのModel ownership/reference indexは既存Model publicationが保守し、Deploy中に全Model走査で再構築しない。欠損/曖昧な識別子や削除証拠を推測しない。Retain/DELETE_SKIPPED/不明削除はidentifierをresetしない。

## Read before changing files

1. `AGENTS.md`
2. [task-contract](../../rules/task-contract.md)
3. `tasks/<task-name>.md` if present. Otherwise treat as idle and create it first under Create active task contract.
4. `project.json`
5. Identify explicit service selectors and authorized source/view paths without expanding every Model. Read a service Model and its necessary producers only when the current Stack, runtime bootstrap, observation or diagnosis actually needs it.
6. For CloudFormation, same-target `cloudformation-stacks.properties`. Delegate StackName mappings/generated stack Markdown matching to existing controller `load_units()`; AI must not manually compare the same values twice
7. [Policy account selection](../../rules/detailed-design.md#policy-account-selection). For CloudFormation, add [CloudFormation stack detailed design](../../rules/detailed-design.md#cloudformation-stack-detailed-design); add related display sections only when changing/investigating design display.
8. [Model authority](../../rules/model-information.md#model-authority), [Resource management mode](../../rules/model-information.md#resource-management-mode), [Properties format](../../rules/model-information.md#properties-format). For generation, add [Properties-first updates and display generation](../../rules/model-information.md#properties-first-updates-and-display-generation); for CloudFormation, add [CloudFormation deployment policy](../../rules/model-information.md#cloudformation-deployment-policy).
9. [cloudformation](../../rules/cloudformation.md) or [terraform](../../rules/terraform.md) for the selected engine
10. [observed-values](../../rules/observed-values.md)
11. [Local loop](../../rules/loop-engineering.md#local-loop), [Validation scope](../../rules/loop-engineering.md#validation-scope). [Infrastructure task completion](../../rules/loop-engineering.md#infrastructure-task-completion)
12. Identify declared IaC/parameter/artifact paths initially; read/decode bodies only for the current scheduled Stack. Agent repair diagnosis reads only its explicitly identified inputs.

- [project-configuration](../../rules/project-configuration.md).

Read mandatory documents per file/specified section. If tool output limits are exceeded, split the same file by line ranges or 6,000-character chunks described below, reviewing the specified range without omissions. Do not concatenate multiple large files into one output. Only necessary ranges actually reviewed during the same preparation need not be reread if content hashes match. Do not treat unread sections as reviewed merely from matching hashes. On changes/additions/deletions, review changes and necessary input ranges and prepare again. Do not require full rereads due to generated artifact changes.

At preparation start, fix the Python launcher to one existing available environment; use the same absolute path and PATH/PYTHONPATH for subsequent preparation, contract registration, controllers, and local loops. List missing dependencies together and resolve in the same environment; do not try different Pythons sequentially or duplicate authentication checks. Do not save credential values in logs.

Ordinary deploy AI design inputs are authoritative model properties. Obtain design values from `desired.row.*`, JSON bodies from `desired.row.*.document`, resource identity/references from existing metadata such as `desired.resource.*`, current non-ARN identifiers from `observed.*`, and stack settings from `cloudformation-stacks.properties`. Exclude generated service Markdown, `cloudformation-stacks.md`, service-owned generated JSON, and built ZIPs from ordinary body inputs.

Markdown Resource links are internal Model addresses. Resolve them through the common scope-checked resolver and read only necessary producer groups; use the producer Model saved anchor as selector; never use generated Markdown as authority. No generated Markdown fallback is permitted.

Retain generated artifact existence/identity checks and scoped machine validation. Pin body hashes for consumed inputs and generated publication candidates when needed; keep save conflicts and stop conditions. Only for explicit display defect/mismatch investigation, necessary artifact portions may be read. Classify model/generated artifact/IaC mismatches and deployment failures under [Controlled deploy repair](../../rules/cloudformation.md#controlled-deploy-repair). The supervising LLM handles proven IaC defects through the separate implement handoff below. The same controller handles authorized RUNTIME_BOOTSTRAP without repository changes. Secrets Manager initial-value bootstrap classification, CREATE ownership/account/region/schema/value checks, unfinished intent/token persistence, AWS mutation and failed-stack retry belong exclusively to the controller; do not manually run put-secret-value.

`<target-directory>` is the selected target's alias if present, otherwise AWS account ID.

Follow AGENTS.md “How to read required rules” for specified section read ranges and conditional rules.

### Conditional rule readings

Add [Framework regression](../../rules/loop-engineering.md#framework-regression) for framework changes, [Validation cache](../../rules/loop-engineering.md#validation-cache) for validation reuse, and applicable loop diagnostic sections for stops/long execution. Do not additionally read full README or inapplicable sections; retain schema/reference/account/issue/task-specific checks.


## Confirm unapproved delete/replacement

Remove、Replacement=True/Conditionalは今回のChangeSet全体についてHumanの明示承認を必要とする。Stack、ChangeSet ID、LogicalId、Action、Replacement、PolicyAction、既知の物理resource/dataへの影響を示す。不明な影響は未確認と記す。変更がない通常Deployを一律承認待ちにしない。

```console
<fixed-python> framework/scripts/cloudformation-deploy.py <same-target-and-stack-arguments> --approve-change-set <current-ChangeSet-ID>
```

未完了ChangeSetをAWSで再取得し、同じStack ID、ID、全Changes、今回の入力digestが一致し、CREATE_COMPLETE/AVAILABLEの場合だけExecuteする。承認Digestはメモリ内だけに保持する。中断後は再承認が必要。別ID、変更された内容/入力、期限切れ、部分承認では実行しない。旧--state/--resume/--repair-result/--observe-onlyオプションは存在しない。

## Unfinished AWS operation recovery

`deploy/operation_journal.py`だけがaccount/Region別の外部Journalを管理する。OS advisory lockの下で未完了ChangeSet、Execute Token/送信段階、未完了Secrets初期化、未同期成功証拠とpublicationの必要最小限のbefore/after情報を保存する。署名済みの各所有元と操作を保持し、別scopeの未完了記録を新規Deployで上書きしない。署名は未完了操作の整合性だけを保護し、履歴台帳を作らない。すべての操作・Observed・publicationの確定後にJournalデータを破棄する。

起動時にJournalがある場合だけ、今回scopeと重なるAWS操作を照合する。署名、Account/Region、元StackId/ChangeSetId/Tokenと入力証拠を検証し、元Tokenのeventとterminal statusから完了・失敗・未確定を区別する。この状態確認は過去Task Digestの一致を要求せず、不明な送信を新Tokenで再実行しない。AWS状態を先に保存し、Observed/publicationの復旧には現在Taskの明示権限を使う。別Worktreeへの反映は同じGit common directory、environment、target directory、targetを確認した場合に限る。過去Taskの権限・承認は継承しない。

AWS成功・Observed未同期は元Tokenの成功、AWS template/parameters・Resource対応、現在Modelのbefore/afterと現在Taskの出力権限を検証して同期し、再Executeしない。未公開候補では、観測更新対象Resource/Rowのdesired同一性と対象observedのbefore/afterを保つコメント・独立Resourceのdesired修正を現在bytesへ再基準化できる。最新ModelからAWS観測候補を再計算し、保存候補との一致を確認する。対象Resource/Rowの第三者変更や確定不能なpublicationは上書きせず、対象証跡を保持してBLOCKEDにする。scope外の操作を含むatomic planは分割せず、その全scopeの明示権限を待つ。

```console
<fixed-python> framework/scripts/cloudformation-deploy.py <target-and-stack-arguments> --recover-operations
```

この入口は未完了操作の確定/同期だけを行い、新規Deployを開始しない。残った待機生成は完了と報告しない。通常起動は安全に確定後、新しいRunContextで最新IaCからChangeSetを作る。完了済み操作の旧IaC Digestで新規UPDATEを拘束せず、無変更ChangeSetはExecuteしない。別Stackの未完了操作は保持し、Import/Export双方向の依存とpublication出力の非競合を確認できる場合だけ新規Deployを許可する。依存証拠がなければ対象Stackを示してBLOCKEDにする。旧SessionがあってJournalがなくてもAWS実行中状態を直接観測する。

排他はmacOS/Linuxのflock（Windowsは標準のbyte-range lock）を使う。競合ControllerはBLOCKEDとなり、正常終了・強制終了時ともOSが解放する。lockファイルは安定したinodeとして残し、存在だけで停止せず、PID推測やunlinkで解除しない。所有者・権限・symlink/hardlinkを検証し、例外・途中returnでもdescriptorをcloseする。

Deploy入力一時directoryはaccount/Regionのprivate領域に作り、署名済みのrepository/Task/target/生成予定ファイルで所有を識別する。終了時は正常・BLOCKEDを問わずJournalが参照しない所有ファイルを回収する。後続実行では同じTaskの孤児入力と、署名済みJournalから復旧済みと証明できる入力を回収する。他Task/target・所有不明・追加ファイル・symlinkは保持し、判断不能な対象と理由を報告する。所有記録のない旧一時directoryを一括走査・削除しない。

復旧中の生成依存は現在Taskの明示Stack scopeで確認する。過去の完了Stack状態は復元せず、未公開の生成待ちだけを新しいRunContextへ再結合する。書込み候補が残っている場合は元のpublicationを確定するまで新規実行へ進めない。

Secrets初期化はAWSのVersion/Stage、未完了ClientRequestToken、現在段階から冪等性を判定する。既存のCREATE owner/account/Region/schema検証とprivate stageを維持し、他VersionのAWSCURRENTを移動しない。完了したTokenや修復履歴を次回へ引き継がない。同じ実行内のbootstrap/empty-shell retryは有限とする。

未完了bootstrapだけは元ownerのStack入力識別情報を保持し、再起動時に元Execute Tokenの失敗eventとownerのAWS実状態を再取得する。consumer/ownerの元IaCとModelを各変更操作の直前にも照合する。複数の未実行ChangeSetは引き継ぎ途中の停止でも未処理分のJournalを保持する。AWS terminal success後のOutput/Export未反映は失敗として報告し、確定済みExecuteの意図を残して次の独立Deployを拘束しない。

## External IaC repair handoff

CloudFormationのみ。元Taskの`External IaC repair: allowed`が必要。Runtime recoveryは独立した`Runtime recovery: allowed`で制御する。失敗後は新規開始を止めpeerをdrainし、未完了AWS操作とpublicationを先に確定する。LLMが今回の失敗Stack/AWS error、正確なIaCと承認済Modelを調査する。承認待ち、認証/権限、未知の送信、設計不足はIaC修復権限を与えない。

controllerが表示する`repairFailure`は今回の失敗だけの一時署名証拠で、新規Deployの入力にはしない。現在Task自身の参照されない旧失敗証拠だけ、修復依頼の作成と同じrepository排他の下で回収する。使用中の依頼は失敗証拠を保持し、統合後は既存discard_requestで削除する。読めない依頼・所有不明の証拠は保持して理由を報告する。修復用OS lockもrequest directoryの外で安定したファイルを共有する。外部diagnosis JSONは失敗Stack名をkeyとし、各値に具体的な`reason`、`inputRefs: [{path, sha256}]`、`modelRefs: [{path, sha256, key}]`を記す。Model keyは実在するdesired entry。秘密値、過去比較、ダミー原因は記録しない。原因が確認できなければHumanへ報告し修復を依頼しない。

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_handoff.py --failure <current-failure.json> --diagnosis <external-diagnosis.json> --path <exact-IaC-path> [--path <exact-IaC-path>]
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<original>.md --suspend-reason "one-shot implement repair <requestId>"
python3 -B framework/scripts/worktree_task.py create --task-id <child> --repair-request <request.json>
```

最初のcommandは親の許可差分を検証してcheckpointし、Task/target/入力・承認済Model・exact IaC paths・親branch/tipを固定した単発requestを作る。別Implement Worktreeの契約はinfrastructure/implement、同Validation scope、`Deploy repair request: <absolute request.json>`を持つ。Allowed pathsは依頼IaCと自契約のみ。AWS API execution/AWS mutation/Deploy/applyは全てforbidden。Model変更や親への権限追加は禁止。

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<child>.md --source <external-child-contract.md>
python3 -B framework/scripts/worktree_task.py repair-validate --task-id <child> --repair-request <request.json>
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<child>.md --complete
python3 -B framework/scripts/worktree_task.py finalize --task-id <child>
python3 -B framework/scripts/worktree_task.py cleanup --task-id <child>
python3 -B framework/scripts/run-python.py -B framework/scripts/task_contract.py --task-file tasks/<original>.md --resume
python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py <current-target-and-stack-arguments>
```

既存scoped implement検証を実行し、実際のPASS、依存hash、exact commit/paths/before-afterを検証して親へff-only統合する。static失敗は同じchild/requestで最大3回。失敗承認の例外で修復結果を発行しない。統合中断は同じhelperのintentにより回復する。親の最終検証は現在Taskの単発commit証拠だけを帰属させ、同fileへの余分な変更を拒否する。統合後は単発request/失敗/validation/resultを破棄し、現在Task完了時に一時帰属情報も除去する。累積履歴を作らない。

修復後のDeployは独立した新規起動で、最新IaCとAWSからChangeSetを評価し、削除/置換なら新たなHuman承認を取る。PythonがLLM/別Taskを自動起動しない。修復後の独立Deployを際限なく自動連続起動することは禁止。

## Terraform

Use project.json target, existing roots/workspaces/backend/variable inputs and the same Task/account/Region/profile checks. Run check-deploy-context.py with environment and alias (or aws-account-id) and optional profile. Retain Terraform fmt/init/validate/plan with a saved binary under terraform.md; explain and seek approval only for unapproved destruction/replacement. Apply only that identical authorized plan. A failed apply may be partial: inspect state/AWS read-only and stop. After success collect non-sensitive outputs, use read-only state attributes only if outputs are absent, and require agreement if both exist. Update permitted observations/references with the existing publication guard and generation.

## Verify and finish

AWS変更、No Change、未反映Output/Export、Observed、生成、未確定操作を分けて報告する。Issue Gateは既存の非ブロッキング方針を維持する。Task scope/Acceptanceと許可された差分を確認し、loop-engineeringのValidation policyで必要な最終検証だけを実行して完了する。通常のProject Deployはscoped task loopを使う。offlineテストから実AWS成功を主張せず、次phaseやscenarioを開始しない。
