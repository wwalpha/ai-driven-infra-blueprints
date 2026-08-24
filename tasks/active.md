# Codex Task: Enforce AWS service-based design file boundaries

## Task contract

- Task type: `governance`
- Goal: ensure future detailed designs are separated by AWS service boundary
- AWS mutation: forbidden
- AWS API execution: forbidden
- IaC execution: forbidden
- Deploy/apply: forbidden

## Background

現在の設計ルールは`human design resource group`をfile grouping単位としており、密接に依存する別AWS serviceのresourceが同じ設計fileへ混在できる。

実例として、VPC設計に次が同居した。

- Amazon VPC: VPC、Subnet、VPC Flow Log
- Amazon CloudWatch Logs: Log Group
- AWS IAM: Flow Logs配送用RoleとPolicy

IAMは独立したsecurity boundary、CloudWatch Logsは独立したlogging service boundaryである。依存関係が密接でも、同じ設計fileへ統合してはいけない。

## Required design contract

詳細設計はAWS service単位で分割する。

例:

- `vpc.md` / `vpc.properties`
  - `EC2.VPC`
  - `EC2.Subnet`
  - `EC2.FlowLog`
- `cloudwatch-logs.md` / `cloudwatch-logs.properties`
  - `Logs.LogGroup`
- `iam.md` / `iam.properties`
  - `IAM.Role`
  - Role trust policy
  - permissions policy

次を明文化する。

1. 一つのdesign fileは一つのAWS service boundaryだけを所有する。
2. 密接な依存serviceを同じ質問batchで確認しても、出力fileはservice別に分ける。
3. 依存関係はfile統合ではなく、relative Markdown linkとLLM stable logical referenceで表現する。
4. IAM resourceは利用先service専用でも`iam.md`へ置く。
5. CloudWatch Logs resourceは利用元serviceのfileではなく`cloudwatch-logs.md`へ置く。
6. VPC Flow LogはAmazon VPCの機能なので`vpc.md`へ置き、IAM RoleとLog Groupを別file参照する。
7. MarkdownとLLM mirrorは同じservice ID、relative path、file stemを使う。
8. design file boundaryとCloudFormation stack/template boundaryは別概念とする。今回CloudFormation ruleは変更しない。

## Machine-readable service ownership

project固有のservice一覧をvalidatorへhard-codeしない。

各design Markdownに、次のmachine-readable metadataを正確に1件ずつ持たせる仕組みを追加する。

```md
- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`, `EC2.Subnet`, `EC2.FlowLog`
```

対応するLLM mirrorにも同じ情報を保持する。

```properties
designService.vpc.serviceId=vpc
designService.vpc.ownedCatalogResourceTypes=EC2.VPC,EC2.Subnet,EC2.FlowLog
```

要件:

- Service IDはlower-kebab-caseとする。
- Service IDとMarkdown／propertiesのfile stemを一致させる。
- Owned catalog resource typesは`materials/aws/*.properties`に存在するresource typeだけを許可する。
- 同じenvironment/AWS account内で、同じcatalog resource typeを複数service fileが所有してはいけない。
- resource-detail tableのcatalog-backed Propertyは、そのfileが宣言したresource typeに属さなければならない。
- catalogに存在しない明確なgenerated／derived documentation fieldは従来どおり許可する。
- 別serviceのresourceはrelative linkまたはstable logical referenceだけで参照する。

## Required changes

### `README.md`

- `resource group`をfile groupingの正本とする記述を、AWS service boundary基準へ変更する。
- service別MarkdownとLLM mirrorの対応を説明する。
- service間dependencyはcross-file referenceで表すことを追加する。

### `rules/detailed-design.md`

- 現在の「AWS service namespace単位ではない」という記述を削除する。
- 一つのfileは一つのAWS service boundaryとする。
- dedicated IAM RoleもIAM service fileへ分けることを明記する。
- `Design service ID`と`Owned catalog resource types`の形式を定義する。
- child componentと別service resourceを区別する。
- anchorはservice IDとlogical IDから作る。

### `rules/llm-design-information.md`

- service単位でMarkdownとpropertiesを一対一対応させる。
- service metadataのmirror形式を定義する。
- cross-service referenceの形式を定義する。
- 別serviceのdesign valueを同じproperties fileへ複製しない。

### `prompts/chatbot/initial-service-design.md`

- 関連serviceは同じ質問batchで確認できるが、完成設計はservice別fileへ分割するよう変更する。
- completion前に、各resourceの所有serviceと出力先fileを内部整理させる。
- IAM、KMS、CloudWatch Logsなどsecurity／shared service boundaryを利用元serviceへ混在させない。
- 複数file出力時にrelative linkを作成する。

### `rules/loop-engineering.md`

- local loopがservice ownership、Markdown／LLM metadata一致、cross-service referenceを検証することを追記する。

### `scripts/validate-blueprint.py`

最小限のgeneric validationを追加する。

- Design service IDが正確に1件ある
- Service IDがlower-kebab-case
- Service IDとfile stemが一致する
- Owned catalog resource typesが正確に1件ある
- 宣言resource typeがmaterials catalogに存在する
- MarkdownとLLM mirrorのservice metadataが一致する
- catalog-backed table propertyが宣言resource typeに所属する
- 同一target内でresource type ownershipが重複しない
- cross-file Markdown linkとLLM referenceが解決できる

project固有の`vpc`、`iam`、`cloudwatch-logs`一覧をvalidatorへhard-codeしない。

## Existing design migration

このgovernance taskでは次を変更しない。

- `docs/designs/**`
- `llm/designs/**`
- `llm/actuals/**`
- `infra/**`
- `tests/**`
- `materials/aws/**`

既存designが新contractに違反する場合は、修正せず対象fileを完了報告へ列挙する。既存designの分割は別の明示された`design`または`migration` taskで行う。

新規または変更されたdesign fileには新contractを必須とする。既存未変更fileを移行するためのcompatibility alias、legacy metadata、二重形式は追加しない。

## Allowed paths

- `README.md`
- `prompts/chatbot/initial-service-design.md`
- `rules/detailed-design.md`
- `rules/llm-design-information.md`
- `rules/loop-engineering.md`
- `scripts/validate-blueprint.py`
- `tasks/active.md`

## Preflight

変更前に`git status`を確認する。

Allowed paths外に未commit変更がある場合は、その変更を取り込まず停止して報告する。特に現在進行中の`docs/designs/**`や`llm/designs/**`をgovernance taskへ混在させない。

最初のrepository changeとして`tasks/active.md`をこのtask contractへ上書きする。

## Verification

1. `bash scripts/blueprint-loop.sh --mode local`
2. repository外のtemporary fixtureで次を確認する
   - VPC／IAM／CloudWatch Logsをservice別fileへ置いた構成がPASS
   - `vpc.md`へ`IAM.Role`を置いた構成がFAIL
   - `vpc.md`へ`Logs.LogGroup`を置いた構成がFAIL
   - `vpc.md`から`iam.md`と`cloudwatch-logs.md`を参照する構成がPASS
   - MarkdownとLLMのService ID不一致がFAIL
   - resource type ownership重複がFAIL
3. `python3 -m py_compile scripts/validate-blueprint.py`
4. `git diff --check`

temporary fixtureとverification evidenceをrepositoryへ保存しない。

## Completion report

次だけを報告する。

- 変更したframework behavior
- service ownership metadata形式
- validator fixture結果
- local loop結果
- 移行が必要な既存design file
- blocker

既存designの分割、IaC作成、AWS接続、deploy、scenario testへ進まない。
