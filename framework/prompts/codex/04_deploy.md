# Infrastructure Deployment Prompt

## Normal startup

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

Preparationはoffline。AIが契約候補と出力範囲を確認してから登録する。Controllerが所有する認証、Stack対応、入力検証、AWS取得、Observed同期・生成をAI側から重複実行しない。

## Confirm unapproved delete/replacement

[Delete and replacement confirmation](../../rules/cloudformation.md#delete-and-replacement-confirmation)とTerraformの[Validation and execution](../../rules/terraform.md#validation-and-execution)が正本。Remove、Replacement=True/Conditional等の未承認変更がある場合だけHuman承認を待つ。Stack/ChangeSet IDまたは保存Plan、全対象・Action・Replacement・PolicyAction、既知の物理Resourceとデータ/アクセス/可用性への影響を説明する。不明な影響は未確認と明示する。部分承認で実行しない。

同じTask・Target・入力と今回承認された実IDを使う。実行時再検証を省略せず、変更・再作成・期限切れ・中断後に旧承認を流用しない。変更のない通常Deployを一律に承認待ちにしない。

## Unfinished AWS operation recovery

[Independent controller runs](../../rules/cloudformation.md#independent-controller-runs-and-execution-timing)を適用する。送信不明・未完了AWS操作・未確定publicationを通常Deployとして再送しない。`--recover-operations`は現在Taskの権限内で元Stack/ChangeSet/TokenとObserved/publicationを検証・確定し、新規Deployを開始しない。

原因不明・権限/Target不一致・第三者変更・曖昧な識別子では停止する。JournalやLockを手編集・削除して回避しない。PENDING_DEPLOYは依存待ちとして扱い、通常のIaC不具合と断定しない。AWS成功後のObserved/生成失敗では再Executeせず、原因を解決して既存のguard付き復旧を使う。GROUP_COMPLETEは全体完了ではない。updateで許可されたProducer/Consumer変更を確認後、現在入力から独立起動する。

## External IaC repair handoff

[Controlled deploy repair](../../rules/cloudformation.md#controlled-deploy-repair)と[Worktree repair lifecycle](../../../.agents/skills/worktree/SKILL.md#explicit-cloudformation-repair-handoff)が権限・ライフサイクルの正本。CloudFormationの現在Taskに`External IaC repair: allowed`がある場合だけ、今回の署名付き失敗証拠、正確なIaCと承認済Modelから原因を診断する。`repairFailure`の存在は修復の証明ではない。

承認待ち・認証/権限・設計不足・依存待ち・送信不明は修復依頼の根拠にしない。未完了操作/publicationの確定後、原因と入力/Model証拠が揃った場合だけ`deploy_handoff.py --help`所定の単発依頼を作る。親をsuspendし、別Implement Worktreeにexact IaC pathsだけを許可する。子のAWS API execution/AWS mutation/Deploy/applyは禁止。同一child/requestのstatic検証は最大3回、検証済みexact commit/paths/bytesだけff-only統合する。

親の明示resume後は最新IaC/AWSによる独立Deployとし、必要なHuman承認も新しく取る。無制限の修復・Deploy連続起動は禁止。証拠の保持・明示破棄・cleanupは既存CLI/Worktree規則に従い、秘密値や推測原因を記録しない。

## Terraform

Terraform RulesとHelpに従い、設計済みRoot/workspace/backend/variable inputsと同一Targetを使い、許可されたrepository外の同一保存Planだけapplyする。失敗applyは部分反映を想定し、state/AWSをread-only確認して停止する。成功後は非機密Outputと必要時のstate属性からObservedと生成物を同期する。

## Verify and finish

AWS変更/No Change、Stack別SUCCESS/FAILED/BLOCKED/NOT_STARTED、未反映Output/Export、Observed同期、Markdown/JSON生成、未確定操作を区別する。原因未確定はHuman判断が必要と報告する。

COMPLETEはAWS成功だけではなくObserved・生成まで完了した状態。RECOVEREDとGROUP_COMPLETEを新規Deploy全体の完了として報告しない。Task scope/Acceptanceと許可差分を確認し、[Validation policy](../../rules/loop-engineering.md#validation-policy)の最終検証後にのみTask完了とする。通常Deployはscoped task loopを使う。offline UTから実AWS成功を主張せず、次phase・scenarioを開始しない。
