# AGENTS.md

このリポジトリは、リポジトリルートを作業ディレクトリとして Codex で運用する。

## 常時適用ルール

- `docs/designs/**`、`llm/**`、`infra/cloudformation/**`、`infra/terraform/**` を変更する前に、ChatGPT が作成した active な `tasks/<task-id>/prompt.md` が存在しなければならない。
- active prompt は今回の変更契約であり、長期的な設計の正本ではない。
- 人間向けの現行設計は`docs/designs/<environment>/<aws-account-id>/`、機械可読な設計情報は`llm/designs/<environment>/<aws-account-id>/`、現行actual情報は`llm/actuals/<environment>/<aws-account-id>/`に置く。
- `materials/aws/` は読み取り専用の不変カタログであり、通常タスクでは変更しない。
- project、environment、AWS account/region、IaC engineの正本は`docs/system-overview.md`とし、他のactive fileに同じ設定値を重複管理しない。
- 変更前に、active prompt とタスクに関係する `rules/*.md` を読む。
- 人間が決めていないリソース選択やパラメータ値を推測しない。不足値は明示して停止する。
- 人間向け詳細設計、LLM 設計情報、選択済み IaC の順に更新する。
- 1 environment/AWS accountにつきCloudFormationまたはTerraformのどちらか一方だけを変更する。
- validate / plan 後にリポジトリ独自の人間レビュー停止は設けない。
- deploy / apply は active prompt が明示的に許可した場合だけ実行する。
- 生成 ARN を post-deploy actual として永続化しない。
- タスク指定の loop を完了前に実行する。
- シナリオテストは静的設定だけでなく、期待する挙動を検証する。
- 証跡は `tests/results/<task-id>/` に保存する。

## 詳細ルール

- `rules/detailed-design.md`
- `rules/llm-design-information.md`
- `rules/cloudformation.md`
- `rules/terraform.md`
- `rules/post-deploy-actuals.md`
- `rules/loop-engineering.md`

## Project configuration

- 未設定の配布状態は`docs/system-overview.md`のproject topologyを`UNSET`のままにする。
- humanがSystem Overviewを完成させた後、`prompts/codex/initialize-repository.md`を使ってprojectを初期化する。
- environment数、environment名、AWS account数を固定しない。
- 1 environment/AWS accountの`IaC engine`は`cloudformation`または`terraform`のどちらか一つとする。
- project初期化後に`UNSET`が残るtopologyや、設定と一致しないpath/IaC implementationはlocal loopを通さない。
