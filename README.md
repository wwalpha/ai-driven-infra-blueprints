# ai-driven-infra-blueprints

human、chatbot、Codex が役割を分け、特定のsystem architectureに依存せずAWS infrastructureを設計・実装・検証するためのrepository blueprintです。配布状態ではprojectやIaC implementationを持ちません。

## Initial setup

1. `docs/system-overview.md`にsystem全体の目的、capability、制約、必要な全environment/AWS accountを記入する。
2. `prompts/codex/initialize-repository.md`を使い、System Overviewに定義したtarget pathだけを初期化する。
3. `prompts/chatbot/initial-service-design.md`を使い、serviceごとの初期設計をAsk形式で決める。
4. 合意内容からCodex用の`tasks/<task-id>/prompt.md`を作る。
5. Codexが対象AWS accountの`docs/designs/`、`llm/designs/`、選択済みIaCの順に更新する。
6. local loopとIaC validate/planを実行し、promptが許可する場合だけdeploy/applyする。

`docs/system-overview.md`がproject、environment、AWS account、region、IaC engineの単一正本です。environment名、environment数、AWS account数はblueprintで固定しません。System Overviewに`UNSET`が残る状態では初期化しません。

## Repository instructions

- `README.md`: repository全体の役割、情報優先順位、workflow
- `prompts/chatbot/*.md`: 初期設計などで都度使用する具体的なAsk指示
- `prompts/codex/initialize-repository.md`: 完成済みSystem Overviewからrepositoryを初期化する指示
- `tasks/<task-id>/prompt.md`: Codexが一つの変更を実行するためのtask contract

## Context priority

1. `README.md`
2. `docs/system-overview.md`
3. `docs/designs/**/*.md`
4. taskに関係する`rules/*.md`
5. taskに関係する`materials/aws/*.properties`
6. `llm/designs/`と`llm/actuals/`
7. userが明示的に許可した外部情報

`docs/system-overview.md`はsystem全体とproject topologyの前提、`docs/designs/**/*.md`はenvironment/AWS account別resource groupの詳細設計の正本とする。矛盾する場合は推測せず、humanへ確認する。

## Roles

### Human

- system overviewを記入する
- Ask形式の質問へ回答し、設計判断を承認する
- 完成した設計を保存するか、Codexへ反映を依頼する
- deploy/apply許可を明示する

### Codex

- active task promptとrepository ruleに従ってfileを変更する
- detailed design、LLM design、選択済みIaCの順に同期する
- validate/planとscenario testを実行する
- 許可がある場合だけdeploy/applyする

## Initial detailed design

初期設計はAsk workflowとする。

1. system overview、既存設計、関連materialsを確認する。
2. 必須serviceの前提となる未設計serviceを優先する。
3. 通常5〜8個の設計判断を一つのbatchとして質問する。
4. 必須判断が揃ったら、完成形の詳細設計Markdownをfile単位で出力する。
5. humanまたはCodexが出力をrepositoryへ反映する。

## Post-design SDD

初期詳細設計の完成後は、初期Ask workflowと分けて扱う。

- humanは`docs/designs/<environment>/<aws-account-id>/<resource-group>.md`を変更する。
- humanがCodexへ変更反映を依頼する。
- Codexは変更された詳細設計を前提に、関連するLLM design、CloudFormation/Terraform、validation、plan、actuals、scenario evidenceを同期する。
- deploy/applyはactive task promptが明示的に許可した場合だけ行う。

SDDの検知・反映手順は初期設計promptへ混在させず、専用ruleまたはpromptとして追加する。

## Operating model

1. humanが作成対象を決める。
2. 初期設計promptは`materials/aws/`の関連catalogを参照し、決定が必要なparameterだけを平易な質問として提示する。
3. humanが値を指定または承認し、Codex用のtask-specific promptを用意する。
4. Codexはactive prompt、`AGENTS.md`、関連する`rules/*.md`を読み、promptの範囲だけを実行する。
5. human-readable design、LLM-readable design、選択済みIaCを順番に同期する。
6. validate/planとtask loopを実行する。
7. deploy/apply後は必要な非ARN actualだけを収集し、scenario testとevidenceを更新する。

1 environment/AWS accountはCloudFormationまたはTerraformのどちらか一方だけで管理します。deploy/applyにはactive promptの明示許可が必要です。

## Repository structure

```text
AGENTS.md
prompts/
  chatbot/
    initial-service-design.md
  codex/
    initialize-repository.md
rules/
tasks/<task-id>/prompt.md
materials/
  catalog.properties
  catalog.sha256
  aws/
docs/
  system-overview.md
  designs/<environment>/<aws-account-id>/
llm/
  designs/<environment>/<aws-account-id>/
  actuals/<environment>/<aws-account-id>/
infra/
  cloudformation/templates/
  cloudformation/parameters/<environment>/<aws-account-id>/
  terraform/environments/<environment>/<aws-account-id>/
scripts/
  blueprint-loop.sh
  update-catalog-lock.py
  validate-blueprint.py
tests/
  scenarios/
  results/<task-id>/
```

## Design information

- `docs/designs/<environment>/<aws-account-id>/`はhuman-readable current designの正本。
- `llm/designs/<environment>/<aws-account-id>/`は同じintended designのmachine-readable mirror。
- Markdownとpropertiesはresource groupから動的に決まり、同じfile stemを使う。
- `llm/actuals/<environment>/<aws-account-id>/`は対象AWS accountから取得した必要最小限のactual情報。
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

local loopはSystem Overviewのproject topology、task scope、catalog integrity、design/LLM mirror、link/reference、actual ARN、IaC engine selectionを検証します。IaCのsyntax validation、plan、scenario testはtaskのfull loopで別途実行します。
