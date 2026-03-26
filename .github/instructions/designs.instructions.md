---
applyTo: 'docs/designs/**/*.md'
---

# Design Markdown Rules

## このファイルの目的

`docs/designs/*.md` を編集または参照する際のルールを定義する。

## 基本方針

- design markdown は現環境の正本として扱う
- サービスごとにファイルを分ける
- 1つのファイルに複数サービスの詳細パラメータを混在させない
- 1リソース = 1見出し + 1 table を基本とする
- 値だけでなく、前提、制約、依存関係、テスト観点も残す
- 新規設計や新規リソース追加時は、必要に応じて `docs/designs/naming-rules.md` を参照する
- 命名規則が関係する場合は、実リソース名に適用するのか `Name` tag に適用するのかを曖昧にしない
- CloudFormation template 構成が関係する場合は、`.github/instructions/cloudformation.instructions.md` の方針に従って構成理由を残す

## 推奨フォーマット

各リソースは、原則として以下の形式で記述する。

```md
## EC2: WEB01

| Property Name | Value     | Comment            |
| ------------- | --------- | ------------------ |
| instanceType  | t3.medium | インスタンスタイプ |
| subnet        | private-a | 配置先             |
| securityGroup | web-sg    | 適用SG             |
```

### フォーマットルール

- 見出しでリソース境界を明確にする
- table の列は原則 `Property Name | Value | Comment`
- `Property Name` は同じサービス内で一貫した命名を使う
- `Comment` は人間向け説明として使う
- セル結合、曖昧な略記、複数値の詰め込みは避ける

## `_llm` 補助ファイルとの関係

- 対応する補助ファイルは `docs/designs/_llm/<service>.properties`
- design markdown の値を変更する場合は、対応する `_llm` 補助ファイルも同一変更で同期更新する
- markdown と `_llm` が不一致の場合は、まず markdown を正本として確認し、`_llm` を同期する
- `docs/designs/_llm/naming-rules.properties` が存在する場合は、`docs/designs/naming-rules.md` の補助表現として扱う
- 命名規則を変更する場合は、markdown と `_llm` を同一変更で同期する

## 命名規則との関係

- AWS リソース命名規則の正本は `docs/designs/naming-rules.md` とする
- 新規リソースまたは新規設計を追加する場合は、必要に応じて `docs/designs/naming-rules.md` を参照する
- `docs/designs/_llm/naming-rules.properties` が存在する場合は、これもあわせて確認する
- 各サービス設計書では、命名規則のプレースホルダを具体値へ置き換えて記載する
- 実リソース名を持つ AWS リソースは、その実名または採用する naming pattern を記載する
- 実リソース名を持たない AWS リソースは、`Name` tag に適用する naming pattern または具体値を記載する
- 命名規則をそのまま適用できない AWS サービス固有制約がある場合は、その理由を明記する
- 既存リソースの命名が naming rules と一致しない場合でも、勝手に一括リネームせず、差分と扱い方針を設計書または結果記録に残す

## CloudFormation template 構成との関係

- CloudFormation template 構成ルールは `.github/instructions/cloudformation.instructions.md` を参照する
- 各システム設計書では、必要に応じて以下を記載する
  - 採用する CloudFormation template 一覧
  - 各 template の deploy責務
  - deploy 順序
  - export / import 一覧
  - この構成にした理由
  - rollback 単位の考え方
- nested stack は採用しない前提で記載する
- template 境界の理由を曖昧にしない

## 期待する構成

各サービスの design markdown には、必要に応じて以下を含めること。

- 目的
- 管理対象リソース
- リソースごとの設定 table
- 前提・制約
- 他サービスとの依存関係
- CloudFormation 実装方針
- シナリオテスト観点
- 変更履歴

命名規則が関係する場合は、必要に応じて以下も含めること。

- 採用する naming rule
- 具体的な Resource Name または `Name` tag
- 実名適用か `Name` tag 適用かの区別
- 命名差分がある既存リソースの扱い方針

CloudFormation template 構成が関係する場合は、必要に応じて以下も含めること。

- template 一覧
- 各 template の deploy責務
- deploy 順序
- export / import 一覧
- template 境界の理由
- 既存構成との差分

## 更新ルール

- 変更が入る場合は、変更後の値だけでなく変更対象と理由が分かるように更新する
- 設計書に未記載の新規パラメータを実装へ先出ししない
- 依存する別サービスに影響がある場合は、関連する design markdown も確認・更新する
- 曖昧な表現を避け、後から見て再現可能な粒度で記載する
- Copilot が変更する場合は、対応する `_llm` 補助ファイルも更新する
- 命名規則を追加または変更した場合は、影響を受けるサービス設計書、CloudFormation、テスト、結果記録も必要に応じて確認する
- CloudFormation template 構成を変更した場合は、template 境界の理由と影響を設計書に残す

## 依存関係の扱い

- 変更対象サービスだけではなく、依存先・依存元のサービスも意識する
- 例:
  - EC2 は VPC、Subnet、Security Group、IAM に依存する可能性がある
  - RDS は VPC、Subnet、Security Group、KMS、監視設定に依存する可能性がある
- 依存がある場合は、本文中に関連ファイル名を明示する

## 書き方

- 値の意味が分かる見出しを使う
- 単なるメモではなく、実装・レビュー・テストに使えるレベルで書く
- 実装ファイル名や関連テンプレート名を書ける場合は書く
- 将来の自動化やレビューで迷わない命名を使う

## 禁止事項

- 実装だけ更新して design markdown を放置すること
- `_llm` だけ更新して design markdown を放置すること
- 他サービス依存を無視して単独サービスだけ更新すること
- 現環境の値を推測で補完すること
- 読み手が理解できない略記だけで済ませること
- `docs/designs/naming-rules.md` を読まずに新規リソース名を決めること
- 実名と `Name` tag の適用先を曖昧なまま記載すること
- 既存命名との差分があるリソースを、影響評価なしに一括リネーム前提で記載すること
- `.github/instructions/cloudformation.instructions.md` を無視して template 境界を決めること
