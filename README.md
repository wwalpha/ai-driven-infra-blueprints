# ai-driven-infra-blueprints

このリポジトリは、**ChatGPT と仕様を決め、Copilot がローカル実行でインフラ構築とテストを進める**ための土台です。

## 基本方針

- 仕様は ChatGPT と合意する
- Copilot は実装・テストを担当する
- インフラ構築は CloudFormation を作成してから AWS CLI で実行する
- テストは shell script / PowerShell script によるシナリオテストで行う
- 構築済みインフラの設定値は `docs/designs/*.md` にサービスごとに記載する
- Copilot / LLM が安定して読むための補助ファイルを `docs/designs/_llm/*.properties` に配置する
- AWS リソース命名規則の正本は `docs/designs/naming-rules.md` で管理する
- 命名規則の機械可読な補助表現は `docs/designs/_llm/naming-rules.properties` で管理する
- CloudFormation 実装ルールと template 構成ルールは `.github/instructions/cloudformation.instructions.md` で管理する

## リポジトリ構成

```text
.github/
  copilot-instructions.md
  instructions/
  prompts/

docs/
  designs/
    _llm/
  test-results/

infra/
  cloudformation/

tests/
  scenarios/
```

## ディレクトリの役割

### `.github/`

Copilot に理解させるためのルール群です。

- `copilot-instructions.md`
  - 常に適用される普遍ルール
- `instructions/*.instructions.md`
  - パス別ルール
- `prompts/*.prompt.md`
  - 実行ワークフロー

`.github/instructions/cloudformation.instructions.md` は、CloudFormation 実装ルールに加えて、template の分割・境界・cross-stack reference の扱いも定義します。

### `docs/designs/`

人間向けの設計書と設定値の正本です。

例:

- `naming-rules.md`
- `vpc.md`
- `subnet.md`
- `security-group.md`
- `ec2.md`
- `rds.md`

各サービス設計書は、**1リソース = 1見出し + 1 table** を基本とします。

例:

```md
## EC2: WEB01

| Property Name | Value     | Comment            |
| ------------- | --------- | ------------------ |
| instanceType  | t3.medium | インスタンスタイプ |
| subnet        | private-a | 配置先             |
| securityGroup | web-sg    | 適用SG             |
```

`docs/designs/naming-rules.md` は、AWS リソース命名規則の正本です。  
新規リソースを追加する場合や、設計書に具体的な Resource Name または `Name` tag を記載する場合は、このファイルを参照します。

CloudFormation template の具体的な構成結果は、各システムの design markdown に記載します。  
分割方針そのものは `.github/instructions/cloudformation.instructions.md` を参照します。

### `docs/designs/_llm/`

Copilot / LLM 向けの補助ファイルです。

例:

- `docs/designs/_llm/naming-rules.properties`
- `docs/designs/_llm/ec2.properties`
- `docs/designs/_llm/vpc.properties`

形式は `service.logicalId.property=value` を基本とします。

例:

```properties
ec2.WEB01.instanceType=t3.medium
ec2.WEB01.subnet=private-a
ec2.WEB01.securityGroup=web-sg
```

`docs/designs/_llm/naming-rules.properties` は、`docs/designs/naming-rules.md` の機械可読な補助表現です。

### `infra/cloudformation/`

CloudFormation による実装を置く場所です。  
インフラ構築・変更は、原則としてここを正規ルートとします。

### `tests/scenarios/`

shell script / PowerShell script によるシナリオテストを置く場所です。  
単なる設定値確認だけではなく、変更したインフラが期待どおり動くかを確認します。

### `docs/test-results/`

テスト結果や実施記録を残す場所です。  
命名規則追加や変更を行った場合は、必要に応じて正規化内容、既存命名との差分、rename を見送る理由、今後の移行方針も記録します。

## 正本と補助ファイルの関係

- 正本は `docs/designs/*.md`
- `docs/designs/_llm/*.properties` は補助ファイル
- Copilot が変更する場合は、**markdown と `_llm` を同一変更で同期更新**する
- 不一致がある場合は、まず markdown を正本として確認し、`_llm` を同期させる

命名規則についても同じです。

- 命名規則の正本は `docs/designs/naming-rules.md`
- 命名規則の補助ファイルは `docs/designs/_llm/naming-rules.properties`
- 命名規則を更新する場合は、markdown と `_llm` を同一変更で同期更新する

## 命名規則の扱い

新規リソースを追加する場合は、必要に応じて `docs/designs/naming-rules.md` を参照してください。

命名規則を適用する際は、次を区別します。

- 実リソース名を持つ AWS リソース  
  例: S3 bucket, RDS instance, Security Group, CloudWatch Log Group  
  → 実リソース名に適用する

- 実リソース名を持たず、タグで識別する AWS リソース  
  例: VPC, subnet, route table, internet gateway など  
  → `Name` tag に適用する

CloudFormation logical ID はこの命名規則の対象外です。  
また、既存リソースの命名が新ルールと一致しない場合でも、影響評価なしに一括リネームしません。

## CloudFormation template 構成の扱い

新規 stack を作る場合や、既存 stack 境界を見直す場合は、`.github/instructions/cloudformation.instructions.md` を参照してください。

このリポジトリでは、CloudFormation template の分割は、AWS サービス名ではなく次で決めます。

- 変更単位
- rollback 単位
- 依存方向
- deploy責務の明確さ

nested stack は採用せず、stack 間連携は cross-stack reference を前提とします。  
また、`1 template = 1 deploy責務` を原則とします。

## 標準フロー

1. 関連する `docs/designs/*.md` を読んで現環境を理解する
2. 命名規則が関係する場合は `docs/designs/naming-rules.md` を読む
3. CloudFormation 実装や template 構成が関係する場合は `.github/instructions/cloudformation.instructions.md` を読む
4. 関連する `docs/designs/_llm/*.properties` があればあわせて読む
5. 命名規則が関係する場合は `docs/designs/_llm/naming-rules.properties` も読む
6. 変更対象の design markdown を更新する
7. 対応する `_llm/*.properties` を同期更新する
8. `infra/cloudformation/*` を更新する
9. AWS CLI で CloudFormation を実行する
10. `tests/scenarios/*` にシナリオテストを追加・更新する
11. 結果を markdown に記録する

## ローカル実行前提

このリポジトリでは、Copilot はローカル実行を前提とします。

- AWS 認証は人間が事前に手動で完了する
- 必要な `AWS_PROFILE` や認証情報は、Copilot 実行前に設定しておく
- Copilot は既存の認証済み環境を利用して実装・CLI 実行を行う
- 認証自体はこのリポジトリの自動化対象に含めない

## 最初に作るべき設計ファイル

最低限、以下のどれかから開始します。

- `docs/designs/naming-rules.md`
- `docs/designs/vpc.md`
- `docs/designs/subnet.md`
- `docs/designs/security-group.md`
- `docs/designs/ec2.md`
- `docs/designs/rds.md`

必要に応じて、対応する `_llm` 補助ファイルも作成します。

- `docs/designs/_llm/naming-rules.properties`
- `docs/designs/_llm/vpc.properties`
- `docs/designs/_llm/subnet.properties`
- `docs/designs/_llm/security-group.properties`
- `docs/designs/_llm/ec2.properties`
- `docs/designs/_llm/rds.properties`
