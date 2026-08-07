# ai-driven-infra-blueprints

ChatGPT、human、Codex が役割を分け、特定のsystem architectureに依存せずAWS infrastructureを設計・実装・検証するためのrepository blueprintです。配布状態ではprojectやIaC implementationを持ちません。

## Initial setup

1. `blueprint.properties` の `blueprint.mode` を `project` に変更する。
2. `project.name` と `project.environments` を設定する。
3. environmentごとにAWS account ID、region、`cloudformation`または`terraform`を設定する。
4. ChatGPTとhumanが作成resourceと必要parameterを決める。
5. 合意内容を `tasks/<task-id>/prompt.md` に保存する。
6. `docs/designs/`、`llm/designs/`、選択済みIaCの順に更新する。
7. local loopとIaC validate/planを実行し、promptが許可する場合だけdeploy/applyする。

設定例:

```properties
blueprint.mode=project
project.name=example-project
project.environments=dev,prod
environment.dev.awsAccountId=111122223333
environment.dev.awsRegion=ap-northeast-1
environment.dev.iacEngine=cloudformation
environment.prod.awsAccountId=444455556666
environment.prod.awsRegion=ap-northeast-1
environment.prod.iacEngine=terraform
```

`blueprint.properties` がproject設定の単一正本です。`UNSET`が残るprojectはlocal loopを通りません。

## Operating model

1. ChatGPTとhumanが作成対象を決める。
2. ChatGPTは`materials/aws/`の関連catalogを読み、決定が必要なparameterだけを提示する。
3. humanが値を指定または承認し、ChatGPTがtask-specific promptを作る。
4. Codexはactive prompt、`AGENTS.md`、関連する`rules/*.md`を読み、promptの範囲だけを実行する。
5. human-readable design、LLM-readable design、選択済みIaCを順番に同期する。
6. validate/planとtask loopを実行する。
7. deploy/apply後は必要な非ARN actualだけを収集し、scenario testとevidenceを更新する。

1 environmentはCloudFormationまたはTerraformのどちらか一方だけで管理します。deploy/applyにはactive promptの明示許可が必要です。

## Repository structure

```text
AGENTS.md
blueprint.properties
rules/
tasks/<task-id>/prompt.md
materials/
  catalog.properties
  catalog.sha256
  aws/
docs/designs/
llm/
  designs/
  actuals/<environment>/
infra/
  cloudformation/templates/
  cloudformation/parameters/
  terraform/
scripts/
  blueprint-loop.sh
  update-catalog-lock.py
  validate-blueprint.py
tests/
  scenarios/
  results/<task-id>/
```

## Design information

- `docs/designs/`はhuman-readable current designの正本。
- `llm/designs/`は同じintended designのmachine-readable mirror。
- Markdownとpropertiesはresource groupから動的に決まり、同じfile stemを使う。
- `llm/actuals/<environment>/`はcurrent deploymentから取得した必要最小限のactual情報。
- generated current valueはdeploy前に`PENDING_DEPLOY`、teardown後は`NOT_DEPLOYED`とする。
- generated ARNはcurrent actualとして保存しない。

## Materials catalog

`materials/aws/`はAWS CloudFormation Resource Specificationから作成したcurated partial catalogです。AWS resourceの完全一覧ではありません。

- provenanceと件数: `materials/catalog.properties`
- file integrity: `materials/catalog.sha256`
- check: `python3 scripts/update-catalog-lock.py`
- authorized catalog maintenance後のlock更新: `python3 scripts/update-catalog-lock.py --write --task-id <task-id>`

通常のproject taskでは`materials/aws/*.properties`を変更しません。不足resourceがある場合は、source specification versionと対象resourceを明示した専用catalog maintenance taskで更新します。

## Validation

active promptには`## Allowed paths` sectionを置き、許可pathをbacktick付きのbulletで列挙します。

```md
## Allowed paths

- `docs/designs/**`
- `llm/**`
- `infra/cloudformation/**`
- `tests/**`
```

local loop:

```bash
bash scripts/blueprint-loop.sh --task-id <task-id> --mode local
```

local loopはproject設定、task scope、catalog integrity、design/LLM mirror、link/reference、actual ARN、IaC engine selectionを検証します。IaCのsyntax validation、plan、scenario testはtaskのfull loopで別途実行します。
