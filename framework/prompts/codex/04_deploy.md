# Infrastructure Deployment Prompt

## Normal startup

独立DeployはHumanに`/worktree`の追加指定を要求せず、[Managed Deploy snapshot](../../rules/cloudformation.md#managed-deploy-snapshot-and-git-publication)に従い`worktree_task.py deploy-start --task-id <id>`で作成/同一Task再利用する。返されたrootでTask登録・Preparation・実行を行う。再開時は元Snapshot/Journalを保持し、未完了操作のRecoverと新規Deployを区別する。

承認済みIaCをTask範囲でDeployし、AWS・Observed・生成物を確認する。Human指定のenvironment・Target・Region/profile・StackName・service IDsを確定し、`project.json`の同一Targetと`tasks/<task-name>.md`を確認する。認証失敗時に別credentialへ切り替えない。DeployはIaC、意図した設計、scenarioを変更しない。

CloudFormationは現在入力とAWS実状態から独立実行する。現在Taskを明示選択し、type/phase/status、AWS許可、Deployment scopeと出力Allowed pathsの不足は停止する。実行・案内はPython CLI、権限と安全制約はRulesを正本とする。

## Read before changing files

- `AGENTS.md`、現在のTask、`project.json`を読む。新Taskは最初の変更として登録する。
- [task-contract](../../rules/task-contract.md)、[project-configuration](../../rules/project-configuration.md)でTask・Target・認証範囲を確認する。
- Preparationの必須Rulesと読取範囲は`deploy/required_readings.py`が定義する。返されたdocumentsの本文・対象要約・契約候補を読む。本文を省略せず、hashだけを読了証明にしない。入力変更時は必要範囲を確認しPreparationをやり直す。
- 設計の正本はservice Model properties。現在Stack、bootstrap、Observed、診断に必要なModelと参照Producerだけを読む。生成物を設計入力にせず、scopeを推測で拡張しない。
- [CloudFormation](../../rules/cloudformation.md)、[Observed](../../rules/observed-values.md)、[Model authority](../../rules/model-information.md#model-authority)、[Generation](../../rules/model-information.md#properties-first-updates-and-display-generation)、[Policy account selection](../../rules/detailed-design.md#policy-account-selection)の安全制約を適用する。必須読取はPreparationが返す。
- Terraformは[terraform](../../rules/terraform.md)全文と、[Resource management mode](../../rules/model-information.md#resource-management-mode)、[Properties format](../../rules/model-information.md#properties-format)、[Local loop](../../rules/loop-engineering.md#local-loop)、[Validation scope](../../rules/loop-engineering.md#validation-scope)、[Infrastructure task completion](../../rules/loop-engineering.md#infrastructure-task-completion)を読む。生成時は上記Generation節も読む。

追加読取はAGENTSに従う。

## CLI entrypoints

Worktreeでは登録済み共通Pythonをwrapperで使用する。同じPython・PATH/PYTHONPATHを維持し、別Pythonで依存不足を回避しない。

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_preparation.py --help
python3 -B framework/scripts/run-python.py -B framework/scripts/cloudformation-deploy.py --help
python3 -B framework/scripts/run-python.py -B framework/scripts/deploy_handoff.py --help
python3 -B framework/scripts/run-python.py -B framework/scripts/check-deploy-context.py --help
```

Helpの例示Target・パス・IDは今回の確定値へ置換する。JSONの`stage`・`cause`・`nextAction`を確認し、`command: null`では操作を推測しない。案内は権限・承認を与えない。

Preparationはoffline。AIが契約候補と出力範囲を確認してから登録する。登録済みWorktreeでは起動先は短時間の`--action advance`。認証、Stack対応、入力検証、AWS取得、Observed同期・生成は既存Pythonを使い、AIが同種の処理を再実装しない。

## LLM-controlled Stack checkpoints

同じTask・Target・完全な`--stack`範囲を毎回指定し、次の操作をLLMが順番に選ぶ。

1. `--action advance`で実行可能なAWS Stackを先に投入する。各呼出しはRUNNINGを1回確認し、同じDeployOrderと並列上限を守って空き枠へ投入して戻る。CloudFormationはCLI終了後もAWS側で進む。
2. `--action status`でStack別AWS/Observed/生成/checkpointと次の操作を確認する。直ちに投入可能なAWS操作があれば先にadvanceする。
3. AWS実行中に直ちに行うAWS操作がなければ、成功済み未同期Stackを選び`--action sync --sync-stack <StackName>`を実行する。対象成功の再確認、全リソースの識別子確認、Observedのみの保存、参照伝播と必要な生成はPythonが行う。
4. 同期・生成完了後、`--action checkpoint --sync-stack <StackName>`で必要な検証と対象差分のローカルcommitを行う。Git反映は[専用の差分publication](../../rules/cloudformation.md#managed-deploy-snapshot-and-git-publication)として試み、PENDING/CONFLICTでもAWS成功・ローカルcheckpointを保持する。Taskはrunningを維持する。
5. checkpoint後はadvanceへ戻る。全StackのAWS成功、Observed全件確認、必要生成・ローカルcheckpoint・Git反映が完了した場合だけDeploy全体を完了とする。

`--sync-stack`は同期・checkpointだけに指定し、不可分な候補には全対象を繰り返す。Producer依存で生成不能なViewだけを既存待機キューに残す。依存解消後にLLMがsyncを再実行するまでcheckpointしない。更新0件でも全実値確認が必要。desired、IMPORT実体、秘匿ARN規則は維持する。

Sub Agent、PythonによるLLM制御、Model自動更新スケジューラ、背景Model writer、固定間隔自動同期を使わない。保存中は同じWorktreeの入力を編集しない。checkpointの途中に最終finalizeを使わない。

中断時は同じ短時間操作を再実行し、元Stack/ChangeSet/Token、保存publication、commit intentとローカルreceiptを照合する。Journalの未知・破損を理由にResetしない。Task内の第三者差分は停止し、基底側のGit競合はAWSから分離してHuman判断を待つ。強制統合・自動rebase・resetをしない。`--action`省略の従来一括実行と`--recover-operations`は互換入口として残るが、短時間操作の未完了Journalには混用できない。

## Confirm unapproved delete/replacement

[Delete and replacement confirmation](../../rules/cloudformation.md#delete-and-replacement-confirmation)とTerraformの[Validation and execution](../../rules/terraform.md#validation-and-execution)が正本。Remove、Replacement=True/Conditional等の未承認変更がある場合だけHuman承認を待つ。Stack/ChangeSet IDまたは保存Plan、全対象・Action・Replacement・PolicyAction、既知の物理Resourceとデータ/アクセス/可用性への影響を説明する。不明な影響は未確認と明示する。部分承認で実行しない。

同じTask・Target・入力と今回承認された実IDを使う。実行時再検証を省略せず、変更・再作成・期限切れ・中断後に旧承認を流用しない。変更のない通常Deployを一律に承認待ちにしない。

## Unfinished AWS operation recovery

[Independent controller runs](../../rules/cloudformation.md#independent-controller-runs-and-execution-timing)を適用する。送信不明・未完了AWS操作・未確定publicationを通常Deployとして再送しない。`--recover-operations`は現在Taskの権限内で元Stack/ChangeSet/TokenとObserved/publicationを検証・確定し、新規Deployを開始しない。

原因不明・権限/Target不一致・第三者変更・曖昧な識別子では停止する。JournalやLockを手編集・削除して回避しない。PENDING_DEPLOYは依存待ちとして扱い、通常のIaC不具合と断定しない。AWS成功後のObserved/生成失敗では再Executeせず、原因を解決して既存のguard付き復旧を使う。GROUP_COMPLETEは全体完了ではない。updateで許可されたProducer/Consumer変更を確認後、現在入力から独立起動する。

Exportは共通Resolverで対象名だけを解決する。delivery.imports・現在のOutput契約等でProducerが既知なら、そのStackIdへのDescribeStacksでValue/Owner/Statusを再確認し、ListExportsを呼ばない。未知Producerだけ同一検証境界のListExportsでまとめて発見し、DescribeStacksで再確認する。Delivery/Create/Executeの取得結果を境界間で再利用しない。Output反映はDescribeStacks/GetTemplateで検証し、ListExportsを追加しない。

未完了Operationとの依存確認は既存のProducer→Consumer探索を維持し、起点/到達StackのOutputsと保存済み/予定Importを使う。ListImportsは到達StackのExportだけ。Repairの依存確認にも対象Stackを指定したDescribeStacksを許可する。参照APIはAccount/Region/API単位の共有頻度制御・期限・Throttling Retryを使い、変更系の再送設定や設計済み並列度を変更しない。

## External IaC repair handoff

[Controlled deploy repair](../../rules/cloudformation.md#controlled-deploy-repair)と[Worktree repair lifecycle](../../../.agents/skills/worktree/SKILL.md#explicit-cloudformation-repair-handoff)が権限・ライフサイクルの正本。CloudFormationの現在Taskに`External IaC repair: allowed`がある場合だけ、今回の署名付き失敗証拠、正確なIaCと承認済Modelから原因を診断する。`repairFailure`の存在は修復の証明ではない。

承認待ち・認証/権限・設計不足・依存待ち・送信不明は修復依頼の根拠にしない。未完了操作/publicationの確定後、原因と入力/Model証拠が揃った場合だけ`deploy_handoff.py --help`所定の単発依頼を作る。親をsuspendし、別Implement Worktreeにexact IaC pathsだけを許可する。子のAWS API execution/AWS mutation/Deploy/applyは禁止。同一child/requestのstatic検証は最大3回、検証済みexact commit/paths/bytesだけff-only統合する。

親の明示resume後は最新IaC/AWSによる独立Deployとし、必要なHuman承認も新しく取る。無制限の修復・Deploy連続起動は禁止。証拠の保持・明示破棄・cleanupは既存CLI/Worktree規則に従い、秘密値や推測原因を記録しない。

## Terraform

Terraform RulesとHelpに従い、設計済みRoot/workspace/backend/variable inputsと同一Targetを使い、許可されたrepository外の同一保存Planだけapplyする。失敗applyは部分反映を想定し、state/AWSをread-only確認して停止する。成功後は非機密Outputと必要時のstate属性からObservedと生成物を同期する。

## Verify and finish

AWS変更/No Change、Stack別SUCCESS/FAILED/BLOCKED/NOT_STARTED、未反映Output/Export、Observed同期、Markdown/JSON生成、未確定操作を区別する。原因未確定はHuman判断が必要と報告する。

AWS・Observed・生成・Git publicationを別々に報告する。PUBLICATION_PENDINGはAWS失敗ではなくGitのHuman判断/反映待ちであり、成功Stackを再Deployしない。RECOVEREDとGROUP_COMPLETEを新規Deploy全体の完了として報告しない。Task scope/Acceptanceと許可差分を確認し、[Validation policy](../../rules/loop-engineering.md#validation-policy)の最終検証と全保存/反映の成功後にのみTask完了とする。通常Deployはscoped task loopを使う。offline UTから実AWS成功を主張せず、次phase・scenarioを開始しない。
