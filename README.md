# ai-driven-infra-blueprints

ChatGPT、human、Codex が役割を分けて AWS infrastructure blueprint を設計・実装・検証するための repository template です。現在の web-nginx は CloudFormation sample であり、2026-03-27 に teardown 済みです。既存の `tests/results/` は過去の実行証跡で、現在 deploy 中の resource を示しません。

## Operating model

1. ChatGPT と human が VPC、Subnet、EC2、S3 などの作成対象を決める。
2. ChatGPT は `materials/aws/` の関連 catalog を読み、決定が必要な parameter だけを提示する。
3. human が値を指定または承認し、ChatGPT が `tasks/<task-id>/prompt.md` を作る。
4. Codex は active prompt と `AGENTS.md`、関連する `rules/*.md` を読み、prompt の範囲だけを実行する。
5. Codex は `docs/designs/`、`llm/designs/`、選択済み IaC の順に同期更新する。
6. validate / plan と task loop を実行し、prompt が許可する場合だけ deploy / apply へ進む。
7. deploy / apply 後は必要な非 ARN actual だけを収集し、設計・actual 情報・scenario test・result evidence を更新する。

CloudFormation と Terraform は環境ごとにどちらか一方を選び、同じ環境を両方で管理しません。validate / plan 後に repository-level の human review stop はありませんが、deploy / apply は active prompt の明示的な許可が必要です。

## Repository structure

```text
AGENTS.md
rules/
  detailed-design.md
  llm-design-information.md
  cloudformation.md
  terraform.md
  post-deploy-actuals.md
  loop-engineering.md
tasks/
  <task-id>/
    prompt.md
materials/
  aws/
docs/
  designs/
llm/
  designs/
  actuals/
    <environment>/
infra/
  cloudformation/
    templates/
    parameters/
  terraform/
scripts/
  blueprint-loop.sh
  validate-blueprint.py
tests/
  scenarios/
  results/
    <task-id>/
```

## Design information

- `docs/designs/` は human-readable な current design の正本。
- `llm/designs/` は同じ intended design の machine-readable mirror。
- `llm/actuals/<environment>/` は current deployment から取得した必要最小限の actual 情報。
- 詳細設計は AWS service namespace や CloudFormation resource type ではなく、`rules/detailed-design.md` の human design resource group 単位で分ける。
- load balancer / target group / listener、route table / route / association のような関連 component は同じ file 内で section と table を分けてよい。
- generated current value は deploy 前に `PENDING_DEPLOY`、teardown 中の current state は `NOT_DEPLOYED` とする。
- generated ARN は current actual として保存しない。AWS managed-policy ARN のような human-provided design input や、API 呼び出しに必要な transient ARN は別物として扱う。

## Materials catalog

`materials/aws/` は configurable field の immutable reference catalog です。project value store ではなく、通常 task で変更しません。詳細設計へ全 field をコピーせず、current project/resource に必要な field だけを選びます。

## IaC

- CloudFormation の active rules は `rules/cloudformation.md`、実装は `infra/cloudformation/`。
- Terraform の active rules は `rules/terraform.md`、実装場所は `infra/terraform/`。
- design を先に更新し、選択していない engine や同じ環境の別 engine は変更しない。
- validate / plan は必須。deploy / apply の可否は active task prompt が決める。

## Loop and evidence

各 coherent logical change 後に local loop、task 完了前に full task loop を実行します。local foundation は次の command です。

```bash
bash scripts/blueprint-loop.sh --task-id <task-id> --mode local
```

scenario test は infrastructure の期待動作を検証し、実行 command、期待値、実績、判定を含む evidence を `tests/results/<task-id>/` に保存します。

## Current sample

web-nginx sample は Multi-AZ VPC、public ALB、private EC2、NAT Gateway、Session Manager 前提の CloudFormation example です。CloudFormation template、parameter、scenario script は sample implementation として残していますが、stacks は 2026-03-27 に削除済みです。current design と `llm/actuals/dev/` はこの状態を `NOT_DEPLOYED` として表現します。
