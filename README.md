# ai-driven-infra-blueprints

このリポジトリは、**ChatGPT と仕様を決め、Copilot がローカル実行でインフラ構築とテストを進める**ための土台です。

## 基本方針

- 仕様は ChatGPT と合意する
- Copilot は実装・テストを担当する
- インフラ構築は CloudFormation を作成してから AWS CLI で実行する
- テストは shell script / PowerShell script によるシナリオテストで行う
- 構築済みインフラの設定値は `docs/designs/*.md` にサービスごとに記載する
- Copilot / LLM が安定して読むための補助ファイルを `docs/designs/_llm/*.properties` に配置する

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

Copilot に理解させるためのルール群。

- `copilot-instructions.md`
  - 常に適用される普遍ルール
- `instructions/*.instructions.md`
  - パス別ルール
- `prompts/*.prompt.md`
  - 実行ワークフロー

### `docs/designs/`

人間向けの設計書と設定値の正本。

例:

- `vpc.md`
- `subnet.md`
- `security-group.md`
- `ec2.md`
- `rds.md`

各サービス設計書は、**1リソース = 1見出し + 1 table** を基本とする。

例:

```md
## EC2: WEB01

| Property Name | Value     | Comment            |
| ------------- | --------- | ------------------ |
| instanceType  | t3.medium | インスタンスタイプ |
| subnet        | private-a | 配置先             |
| securityGroup | web-sg    | 適用SG             |
```

### `docs/designs/_llm/`

Copilot / LLM 向けの補助ファイル。

例:

- `docs/designs/_llm/ec2.properties`
- `docs/designs/_llm/vpc.properties`

形式は `service.logicalId.property=value` を基本とする。

例:

```properties
ec2.WEB01.instanceType=t3.medium
ec2.WEB01.subnet=private-a
ec2.WEB01.securityGroup=web-sg
```

### `infra/cloudformation/`

CloudFormation による実装。

### `tests/scenarios/`

shell script / PowerShell script によるシナリオテスト。

### `docs/test-results/`

テスト結果や実施記録を残す場所。

## 正本と補助ファイルの関係

- 正本は `docs/designs/*.md`
- `docs/designs/_llm/*.properties` は補助ファイル
- Copilot が変更する場合は、**markdown と `_llm` を同一変更で同期更新**する
- 不一致がある場合は、まず markdown を正本として確認し、`_llm` を同期させる

## 標準フロー

1. 関連する `docs/designs/*.md` を読んで現環境を理解する
2. 関連する `docs/designs/_llm/*.properties` があればあわせて読む
3. 変更対象の design markdown を更新する
4. 対応する `_llm/*.properties` を同期更新する
5. `infra/cloudformation/*` を更新する
6. AWS CLI で CloudFormation を実行する
7. `tests/scenarios/*` にシナリオテストを追加・更新する
8. 結果を markdown に記録する

## ローカル実行前提

このリポジトリでは、Copilot はローカル実行を前提とする。

- AWS 認証は人間が事前に手動で完了する
- 必要な `AWS_PROFILE` や認証情報は、Copilot 実行前に設定しておく
- Copilot は既存の認証済み環境を利用して実装・CLI 実行を行う
- 認証自体はこのリポジトリの自動化対象に含めない

## 最初に作るべき設計ファイル

最低限、以下のどれかから開始すること。

- `docs/designs/vpc.md`
- `docs/designs/subnet.md`
- `docs/designs/security-group.md`
- `docs/designs/ec2.md`
- `docs/designs/rds.md`

必要に応じて、対応する `_llm` 補助ファイルも作成する。

- `docs/designs/_llm/vpc.properties`
- `docs/designs/_llm/subnet.properties`
- `docs/designs/_llm/security-group.properties`
- `docs/designs/_llm/ec2.properties`
- `docs/designs/_llm/rds.properties`
