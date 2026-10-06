# Task Contract Rules

## Task transition

- 許可するtask typeは`initialization`、`design`、`infrastructure`、`scenario-test`、`governance`、`catalog-maintenance`、`migration`だけとする。active promptは今回の変更契約であり、長期的な設計の正本ではない。

- repository変更前に今回の`tasks/<task-name>.md`を選び、最新依頼のtask type、target、Goalを照合する。契約のないclean repositoryはidleとする。新規taskは既存契約を上書きせず、最初の変更として個別契約を登録する。
- Task contractへTask status（`running`／`suspend`／`completed`）を記載し、`## Modified files`へ具体的なfile pathを列挙する。glob、directory、別taskの契約は禁止する。自分の契約、未作成file、生成artifact、model part、削除対象も含め、Allowed paths内だけを予約する。
- `task_contract.py --task-file tasks/<task-name>.md --source <repository外の契約候補file>`で登録する。登録は同時実行を直列化し、全running taskのModified filesを比較する。repository rootの`issues/`配下以外のfileが重複すれば新規taskを停止し、競合fileと既存taskを報告する。候補と対象fileをrepositoryへ保存せず、既存taskを継続する。
- `issues/`配下の全fileは、file名や階層にかかわらず登録・契約更新・再開・local loopの競合停止対象から除外する。`issues/issue.md`、`issues/<environment>/<target-directory>/issues.md`、`diff.md`も含む。各taskは変更するfileをModified filesへ列挙し、Allowed paths、未登録変更、task boundary、issue gateとAcceptance checksの検査を維持する。
- 各processは`BLUEPRINT_TASK_FILE`、local loop／validatorは`--task-file`でも契約を選ぶ。複数running taskがある場合は明示選択必須。変更予定fileの追加・変更時も実変更前に契約を更新し、`task_contract.py --task-file tasks/<task-name>.md`で再検査する。競合する更新は元へ戻し、今回のtaskを停止する。
- read-only調査とchat-only設計相談は契約の登録・切替を要求しない。
- loopは全契約の競合と未登録変更を検査し、今回の予約fileの変更だけへtask type、issue gate、Acceptance checksを適用する。別taskの変更を成果や違反として数えない。生成とmodel分割も保存前に今回の予約fileを検査する。
- local loop成功後だけ今回のTask statusをcompletedへ変更する。completed契約はfile予約を解放し、未commit変更の所属を保持する間だけ残す。差分がなくなれば削除し、task履歴やevidenceは残さない。
- check errorによる停止では、原因が自task、他task、未登録変更、baselineのどれでも今回のTask statusだけを`suspend`にする。`## Suspension reason`は必須とし、失敗check、対象file、具体的error、必要なrepository外log pathを記載する。現在の停止理由だけを保持し、実行履歴やevidenceは追加しない。local loopは全check終了または子process停止後に自動suspendにし、事前検査失敗も含める。明示selectorがない複数running taskから停止対象を推測しない。staged検証の状態変更はsnapshot内だけに適用する。
- local loop以外の単独checkや作業中errorで停止する場合も、`task_contract.py --task-file tasks/<task-name>.md --suspend-reason '<具体的な問題>'`で今回の契約をsuspendにする。他taskの契約と未commit変更は維持し、無関係な失敗を今回のtask内で修復しない。
- suspend契約は予約を解放するため、同じfileを扱う他taskも登録できる。未commit変更の所属は保持し、他taskのAcceptance checksへ流用しない。suspend中は生成・deploy・loopなどのtask実行を拒否する。修正・再検証を再開する前に`task_contract.py --task-file tasks/<task-name>.md --resume`を実行し、全running taskとの予約競合を直列化して検査する。成功時だけrunningへ戻して現在の停止理由を除去し、競合時はsuspendと理由を維持する。自動再開はしない。
- 旧`tasks/active.md`は単独の場合だけ従来契約として許可する。並行運用前に個別契約へ移し、Task statusとModified filesを記載する。契約がない状態の非契約変更は拒否する。
- loop成功後に別taskを作成または実行しない。
- retry中にtask typeまたは作業段階を変更しない。
- infrastructure behaviorの変更を理由にscenario testへ進まない。
- test failureをdesign変更、IaC変更、redeployで自動修正しない。

- task type、target、Goalのいずれかが異なる変更は新しいtaskとする。
- chat-only設計をrepositoryへ保存する依頼は新しい`design` taskとし、保存前にactive taskを切り替える。
- Requirement IDに対応するAcceptance checkまたはtask type固有checkが未実装、未実行、失敗の場合はtaskを完了扱いにしない。

## Task boundary

- `design`: `docs/designs/**`と対応する`model/**`を更新し、local validation後に終了する。既存resource取得ではchatbotが選択したpropertyと必要な非ARN current identifierだけを反映できる。IaC、AWS mutation、scenarioへ進まない。
- `infrastructure`: 承認済みdesignを読み、active promptで指定されたIaC、安全確認、許可されたdeploy/apply、成功後の`model/**`のobserved namespace更新とMarkdown生成までを行って終了する。`update` phaseではhumanがtask開始前にmodel propertiesへ手動修正した未commitのintended designをimmutable inputとして許可するが、Codexはintended designやscenarioを変更しない。
- `scenario-test`: `tests/scenarios/**`と`tests/results/<scenario-id>/<environment>/<target-directory>/`だけを作成・更新する。test失敗後に設計変更、IaC修正、redeploy、remediation task作成・実行へ進まない。
- `initialization`、`governance`、`catalog-maintenance`、`migration`: active promptのAllowed pathsと明示scopeだけを実行し、別taskへ進まない。
- infrastructure behaviorが変わってもscenario-test taskを自動作成または自動実行しない。
- scenario-test taskだけが`tests/scenarios/**`と`tests/results/**`を変更できる。
- non-scenario taskのvalidation/deployment結果を`tests/results/**`へ保存しない。verification outputは原則として完了報告だけに記載する。
- `tasks/`には独立した契約だけを置き、task履歴やevidenceを保存しない。Task statusは`running`、`suspend`、`completed`。現在の停止理由はsuspend契約に記載してよい。local loop成功後に今回の契約だけをcompletedへ変更する。suspend契約は再開と未commit差分の所属のため保持し、完了済み契約は未commit差分の所属を保持する間だけ残し、差分がなくなれば削除する。
- scenario evidenceの過去版はGit履歴で追跡し、実行別・timestamp別directoryを追加しない。

## Controlled deploy repair contract

CloudFormation deploy phaseは[Controlled deploy repair](cloudformation.md#controlled-deploy-repair)だけIaC修正を許可する。`- Controlled repair: `と`- Deploy repair session: `の値をそれぞれbacktick付き`allowed`、repository外の絶対session pathで明記し、対象template／parameter／宣言済みartifactだけを具体的Modified files／Allowed pathsへ予約する。intended design、scope、task typeはimmutableとし、file追加は既存scope expansion／予約検査に従う。修復許可は任意編集の許可ではなく、validatorが同sessionのAUTO_REPAIRABLE履歴・file digestへ一致を要求する。Humanによる既存change setの承認更新は従来どおり許可する。

## Acceptance contract

active taskの`## Required changes`は一意なRequirement IDを持ち、`## Acceptance checks`で同じIDへ一つ以上のcheckを対応付ける。

```md
- [R1] 実施内容
- [R1] `changed:path/to/file`
```

Acceptance checkは`changed:`、`exists:`、`absent:`、validator登録済み`check:`だけを許可する。任意command、未登録check、対応先Requirement IDがないcheck、checkがないRequirement IDは拒否する。

## Retry and stop

- 同じactive task、同じtask type、同じlogical failure classのautomatic correctionは最大3 iterationとする。
- material progressなしで同じerrorが2回続いた場合は停止する。
- missing human inputを値の発明で直さない。
- out-of-scope file changeで停止する。
- 未承認のdelete/replacementはfailureまたはautomatic retryとして扱わず、説明付きhuman確認待ちにする。承認されない場合はdeploy/applyを実行せず停止する。
- `framework/materials/aws/`がbaselineと異なる場合は停止する。
- passのためにfailing checkを抑制しない。

validate/plan後に全deploymentを一律停止するhuman reviewは要求しない。未承認のdelete/replacementに対するplan固有のhuman確認と、Codex sandbox/OS permission controlは別の仕組みであり、permissionが必要な操作はrepository ruleにかかわらずplatform controlに従う。
