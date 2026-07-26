# AGENTS.md

このリポジトリは、リポジトリルートを作業ディレクトリとして Codex で運用する。

## 常時適用ルール

- `docs/designs/**`、`llm/**`、`infra/cloudformation/**`、`infra/terraform/**` を変更する前に、ChatGPT が作成した active な `tasks/<task-id>/prompt.md` が存在しなければならない。
- active prompt は今回の変更契約であり、長期的な設計の正本ではない。
- 人間向けの現行設計は `docs/designs/`、機械可読な設計情報は `llm/designs/`、環境別の現行 actual 情報は `llm/actuals/<environment>/` に置く。
- `materials/aws/` は読み取り専用の不変カタログであり、通常タスクでは変更しない。
- 変更前に、active prompt とタスクに関係する `rules/*.md` を読む。
- 人間が決めていないリソース選択やパラメータ値を推測しない。不足値は明示して停止する。
- 人間向け詳細設計、LLM 設計情報、選択済み IaC の順に更新する。
- 1環境につき CloudFormation または Terraform のどちらか一方だけを変更する。
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

## Project-specific section（blueprint 利用時に必ず更新）

- project name: `ai-driven-infra-blueprints` の web-nginx sample
- environments: `dev` sample（現在は `NOT_DEPLOYED`）
- AWS account constraints: 固定アカウントは未指定。実行タスクで対象アカウントを指定し、実行前に一致を確認する。
- AWS region constraints: sample は `ap-northeast-1`
- selected IaC engine: sample は CloudFormation。派生プロジェクトは環境ごとに CloudFormation または Terraform を一つ選ぶ。

派生プロジェクトは、この section をプロジェクト名、全環境、許可 AWS アカウント／リージョン、選択 IaC engine の実値へ置き換える。
