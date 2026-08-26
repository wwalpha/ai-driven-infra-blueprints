# AGENTS.md

このリポジトリは、リポジトリルートを作業ディレクトリとしてCodexで運用する。

## 常時適用ルール

- 変更前に`tasks/active.md`が存在し、`## Task contract`に`Task type`が正確に1件記載されていなければならない。
- 許可するtask typeは`initialization`、`design`、`infrastructure`、`scenario-test`、`governance`、`catalog-maintenance`、`migration`だけとする。
- active promptは今回の変更契約であり、長期的な設計の正本ではない。
- active taskに明記されていない次工程、別taskの作成、別taskの実行へ進まない。
- 人間向けの現行設計は`docs/designs/<environment>/<aws-account-id>/`、同じserviceのdesired/observedを保持する機械可読modelは`model/<environment>/<aws-account-id>/`に置く。
- `docs/system-overview.md`は背景情報のreferenceとし、`UNSET`を一律blockerにしない。
- initialization後のproject、environment、AWS account/region、IaC engineのmachine-readable source of truthは`project.json`とする。
- `framework/materials/aws/`は読み取り専用の不変カタログであり、通常taskでは変更しない。
- 変更前にactive promptとtask typeに関係する`framework/rules/*.md`を読む。
- 人間が決めていないresource選択やparameter値を推測しない。不足値は明示して停止する。
- 1 environment/AWS accountにつきCloudFormationまたはTerraformのどちらか一方だけを変更する。
- validate/plan後にrepository独自のhuman review停止は設けない。
- deploy/applyは`infrastructure` taskのactive promptが明示的に許可した場合だけ実行する。
- 生成ARNをobserved valueとして永続化しない。
- task typeに対応するlocal loopを完了前に実行する。

## Task transition

- repository変更前に、最新のuser依頼のtask type、target、Goalを`tasks/active.md`と比較する。
- task type、target、Goalのいずれかが異なるrepository変更は新しいtaskとし、最初のrepository changeとして`tasks/active.md`を今回の契約へ上書きする。
- read-only調査とchat-only設計相談はrepository taskを開始しない。完了済みの前taskが`tasks/active.md`に残っていてもchat-only作業のblockerにしない。
- chat-only設計をrepositoryへ保存する依頼は新しい`design` taskとし、保存前にactive taskを切り替える。
- `## Required changes`の各項目には一意なRequirement IDを付け、`## Acceptance checks`で同じIDへ一つ以上の機械検証を対応付ける。
- Acceptance checkは`changed:<path-or-glob>`、`exists:<path-or-glob>`、`absent:<path-or-glob>`、またはvalidatorへ登録済みの`check:<check-id>`だけを使用する。任意commandをactive taskから実行しない。
- Requirement IDに対応するAcceptance checkまたはtask type固有checkが未実装、未実行、失敗の場合はtaskを完了扱いにしない。

## Task boundary

- `design`: `docs/designs/**`と対応する`model/**`のdesired namespaceを更新し、local validation後に終了する。IaC、observed value、scenarioへ進まない。
- `infrastructure`: 承認済みdesignを読み、active promptで指定されたIaC、安全確認、許可されたdeploy/apply、成功後のgenerated current valueと`model/**`のobserved namespace更新までを行って終了する。intended designやscenarioを変更しない。
- `scenario-test`: `tests/scenarios/**`と`tests/results/<scenario-id>/<environment>/<aws-account-id>/`だけを作成・更新する。test失敗後に設計変更、IaC修正、redeploy、remediation task作成・実行へ進まない。
- `initialization`、`governance`、`catalog-maintenance`、`migration`: active promptのAllowed pathsと明示scopeだけを実行し、別taskへ進まない。
- infrastructure behaviorが変わってもscenario-test taskを自動作成または自動実行しない。
- scenario-test taskだけが`tests/scenarios/**`と`tests/results/**`を変更できる。
- non-scenario taskのvalidation/deployment結果を`tests/results/**`へ保存しない。verification outputは原則として完了報告だけに記載する。
- `tasks/active.md`は今回のtask contractだけを置き、次のtask開始時に上書きする。task履歴やevidenceを`tasks/`へ保存しない。
- scenario evidenceの過去版はGit履歴で追跡し、実行別・timestamp別directoryを追加しない。

## 詳細ルール

- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/cloudformation.md`
- `framework/rules/terraform.md`
- `framework/rules/observed-values.md`
- `framework/rules/scenario-testing.md`
- `framework/rules/loop-engineering.md`

## Project configuration

- 未初期化の配布状態では`project.json`を置かない。
- `docs/system-overview.md`の作成・記入状態に関係なく、`framework/prompts/codex/initialize-repository.md`を使用できる。Codexが必要な確定値を質問し、`project.json`とtarget pathを作成する。
- initializationでは現時点で必要値が確定しているtargetだけを登録する。未作成または必要値が未確定のtargetは推測やplaceholderで登録せず、確定後に`framework/prompts/codex/add-project-target.md`のmigrationで追加する。
- environment数、environment名、AWS account数を固定しない。
- 1 environment/AWS accountの`IaC engine`は`cloudformation`または`terraform`のどちらか一つとする。
- humanへ`project.json`の直接編集を要求しない。topology変更は明示されたinitializationまたはmigration taskでCodexが行う。
- `project.json`と一致しないpath/IaC implementationはlocal loopを通さない。

## Generated service model

- `docs/designs/**`をintended designのsource of truthとする。
- `model/**`は`framework/scripts/sync-model.py`で生成し、手動編集しない。
- 一つのservice propertiesにintended designを`desired.*`、generated current valueを`observed.*`として保持する。
- design taskと成功したinfrastructure taskはMarkdown更新後に同じservice modelを再生成する。
- local loopはgenerated modelがMarkdownと一致しない場合に失敗する。
