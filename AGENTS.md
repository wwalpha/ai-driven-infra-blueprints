# AGENTS.md

このリポジトリは、リポジトリルートを作業ディレクトリとしてCodexで運用する。

## 常時適用ルール

- 変更前に`tasks/active.md`が存在し、`## Task contract`に`Task type`が正確に1件記載されていなければならない。
- 許可するtask typeは`initialization`、`design`、`infrastructure`、`scenario-test`、`governance`、`catalog-maintenance`、`migration`だけとする。
- active promptは今回の変更契約であり、長期的な設計の正本ではない。
- active taskに明記されていない次工程、別taskの作成、別taskの実行へ進まない。
- 人間向けの現行設計は`docs/designs/<environment>/<aws-account-id>/`、機械可読な設計情報は`llm/designs/<environment>/<aws-account-id>/`、現行actual情報は`llm/actuals/<environment>/<aws-account-id>/`に置く。
- `docs/system-overview.md`は背景情報のreferenceとし、`UNSET`を一律blockerにしない。
- initialization後のproject、environment、AWS account/region、IaC engineのmachine-readable source of truthは`project-topology.json`とする。
- `materials/aws/`は読み取り専用の不変カタログであり、通常taskでは変更しない。
- 変更前にactive promptとtask typeに関係する`rules/*.md`を読む。
- 人間が決めていないresource選択やparameter値を推測しない。不足値は明示して停止する。
- 1 environment/AWS accountにつきCloudFormationまたはTerraformのどちらか一方だけを変更する。
- validate/plan後にrepository独自のhuman review停止は設けない。
- deploy/applyは`infrastructure` taskのactive promptが明示的に許可した場合だけ実行する。
- 生成ARNをpost-deploy actualとして永続化しない。
- task typeに対応するlocal loopを完了前に実行する。

## Task boundary

- `design`: `docs/designs/**`と対応する`llm/designs/**`を更新し、local validation後に終了する。IaC、actuals、scenarioへ進まない。
- `infrastructure`: 承認済みdesignを読み、active promptで指定されたIaC、安全確認、許可されたdeploy/apply、成功後のactualsとgenerated current value更新までを行って終了する。intended designやscenarioを変更しない。
- `scenario-test`: `tests/scenarios/**`と`tests/results/<scenario-id>/<environment>/<aws-account-id>/`だけを作成・更新する。test失敗後に設計変更、IaC修正、redeploy、remediation task作成・実行へ進まない。
- `initialization`、`governance`、`catalog-maintenance`、`migration`: active promptのAllowed pathsと明示scopeだけを実行し、別taskへ進まない。
- infrastructure behaviorが変わってもscenario-test taskを自動作成または自動実行しない。
- scenario-test taskだけが`tests/scenarios/**`と`tests/results/**`を変更できる。
- non-scenario taskのvalidation/deployment結果を`tests/results/**`へ保存しない。verification outputは原則として完了報告だけに記載する。
- `tasks/active.md`は今回のtask contractだけを置き、次のtask開始時に上書きする。task履歴やevidenceを`tasks/`へ保存しない。
- scenario evidenceの過去版はGit履歴で追跡し、実行別・timestamp別directoryを追加しない。

## 詳細ルール

- `rules/detailed-design.md`
- `rules/llm-design-information.md`
- `rules/cloudformation.md`
- `rules/terraform.md`
- `rules/post-deploy-actuals.md`
- `rules/scenario-testing.md`
- `rules/loop-engineering.md`

## Project configuration

- 未初期化の配布状態では`project-topology.json`を置かない。
- `docs/system-overview.md`の作成・記入状態に関係なく、`prompts/codex/initialize-repository.md`を使用できる。Codexが必要な確定値を質問し、`project-topology.json`とtarget pathを作成する。
- environment数、environment名、AWS account数を固定しない。
- 1 environment/AWS accountの`IaC engine`は`cloudformation`または`terraform`のどちらか一つとする。
- humanへ`project-topology.json`の直接編集を要求しない。topology変更は明示されたinitializationまたはmigration taskでCodexが行う。
- `project-topology.json`と一致しないpath/IaC implementationはlocal loopを通さない。
