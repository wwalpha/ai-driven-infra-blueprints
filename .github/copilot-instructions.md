# Copilot Instructions

## 目的

このリポジトリでは、ChatGPT と仕様を決め、Copilot がインフラ構築とテストを実施する。  
Copilot は、設計書理解、CloudFormation 実装、AWS CLI 実行、シナリオテスト、結果記録の順序を守ること。

## 固定ルール

- 実装前に、必ず関連する `docs/designs/*.md` を読んで現環境の設定値と制約を理解する
- 関連する `docs/designs/_llm/*.properties` が存在する場合は、必ずあわせて読む
- サービスの設計書と人間向けパラメータ表現は、サービスごとに `docs/designs/*.md` で管理する
- Copilot / LLM が安定して読む補助ファイルは `docs/designs/_llm/*.properties` で管理する
- 実装は `infra/cloudformation/*` に集約する
- インフラ構築・更新は CloudFormation を AWS CLI で実行して行う
- テストは `tests/scenarios/*` に shell script / PowerShell script として実装する
- 単なる設定値確認だけでテスト完了とみなさない
- 実施内容と結果は markdown に記録する

## 設計書の扱い

- `docs/designs/*.md` は現環境の正本である
- `docs/designs/_llm/*.properties` は補助ファイルである
- markdown と `_llm` が不一致の場合は、まず markdown を確認し、`_llm` を同期する
- 設計書に書かれていない値を推測で採用しない
- 実装と設計書がずれる場合は、先に設計書を更新する
- 変更対象サービスだけでなく、依存する関連サービスの設計書も読む

## 命名規則の扱い

- AWS リソース命名規則の正本は `docs/designs/naming-rules.md` とする
- `docs/designs/_llm/naming-rules.properties` が存在する場合は、必ずあわせて読む
- 新規リソースを追加する場合は、関連する design markdown に加えて命名規則も確認する
- CloudFormation 実装時は、実リソース名を持つ AWS リソースには命名規則をそのまま適用する
- AWS サービス仕様上、明示的な Resource Name を持たない場合は `Name` tag に命名規則を適用する
- 各サービス設計書では、命名規則のプレースホルダを具体値へ置き換えて記載する
- 命名規則をそのまま適用できないサービス固有制約がある場合は、設計書に理由を残す
- 命名規則を変更した場合は、関連する design markdown、`_llm` 補助ファイル、CloudFormation、テスト、結果記録への影響を確認する
- 既存リソースの命名が規則と一致しない場合でも、勝手に一括リネームしない
- 既存命名との差分を見つけた場合は、設計書または結果記録に差分、影響、据え置きまたは移行方針を残す

## design markdown の形式

各サービスの `docs/designs/*.md` は、原則として **1リソース = 1見出し + 1 table** を基本とする。

推奨例:

```md
## EC2: WEB01

| Property Name | Value     | Comment            |
| ------------- | --------- | ------------------ |
| instanceType  | t3.medium | インスタンスタイプ |
| subnet        | private-a | 配置先             |
| securityGroup | web-sg    | 適用SG             |
```

- 見出しはリソース境界を明確にするために必須とする
- table の列は原則 `Property Name | Value | Comment`
- `Comment` は人間向け説明として使う

## \_llm 補助ファイルの形式

各サービスの `docs/designs/_llm/*.properties` は、以下の形式を基本とする。

```properties
service.logicalId.property=value
```

例:

```properties
ec2.WEB01.instanceType=t3.medium
ec2.WEB01.subnet=private-a
ec2.WEB01.securityGroup=web-sg
```

## 実装前の必須確認

Copilot は作業開始時に、少なくとも以下を明示的に整理すること。

1. 読んだ design markdown
2. 読んだ `_llm` 補助ファイル
3. 必要に応じて読んだ naming rules 関連ファイル
   - `docs/designs/naming-rules.md`
   - `docs/designs/_llm/naming-rules.properties`
4. 現環境の理解
5. 更新対象の design markdown
6. 更新対象の `_llm` 補助ファイル
7. 変更対象の CloudFormation
8. AWS CLI による実行方針
9. 追加または更新するシナリオテスト

## 更新ルール

- Copilot が設定値を変更する場合は、`docs/designs/*.md` と `docs/designs/_llm/*.properties` を同一変更で同期更新する
- `_llm` だけ先に更新して完了扱いにしない
- design markdown だけ更新して `_llm` を放置しない
- `_llm` がまだ存在しない場合は、必要に応じて新規作成する
- 命名規則を追加または変更した場合は、`docs/designs/naming-rules.md` と `docs/designs/_llm/naming-rules.properties` を同一変更で同期更新する
- 命名規則変更の影響があるサービス設計書、CloudFormation、テスト、結果記録も必要に応じて更新する

## 実装ルール

- 手動構築を主経路にしない
- CloudFormation を先に作成または更新し、その後 AWS CLI で実行する
- 既存環境変更時は、影響範囲、置換有無、依存関係を意識する
- 実装は design markdown と整合していること
- 実リソース名を持つ AWS リソースは naming rules に従う
- 実リソース名を持たない AWS リソースは `Name` tag に naming rules を適用する
- 命名規則との差分がある既存リソースを扱う場合は、rename の要否と影響を明示する

## テストルール

- テストはシナリオベースで行う
- 正常系だけでなく、必要に応じて拒否系、失敗系、到達性確認も含める
- 疎通、利用シナリオ、権限挙動を優先して確認する
- 単なるパラメータ設定確認のみでは不十分とする
- 必要に応じて Resource Name または `Name` tag が期待どおりか確認する
- ただし、命名ルールの文字列一致だけでテスト完了としない

## 記録ルール

最低限、以下を markdown に残すこと。

- 対象サービス
- 読んだ design markdown
- 読んだ `_llm` 補助ファイル
- 必要に応じて読んだ naming rules 関連ファイル
- 更新した design markdown
- 更新した `_llm` 補助ファイル
- 変更した CloudFormation ファイル
- AWS CLI 実行コマンド
- 追加または更新したテスト
- 実施結果
- 未解決事項
- 次の対応候補

命名規則を追加または変更した場合は、必要に応じて以下も残すこと。

- 更新した命名規則ファイル
- 命名規則の正規化内容
- 既存命名との差分
- rename を見送る場合の理由
- 今後の移行方針

## 禁止事項

- 関連する `docs/designs/*.md` を読まずに実装を始めること
- `_llm` が存在するのに読まずに設定変更すること
- design markdown が古いまま CloudFormation を先に更新すること
- 設計書にない設定値を推測で採用すること
- `_llm` だけ更新して markdown を放置すること
- 手動変更を主経路にすること
- 設定値確認だけでテスト完了とすること
- 記録を残さずに完了とすること
- `docs/designs/naming-rules.md` を読まずに新規リソース名を決めること
- `docs/designs/_llm/naming-rules.properties` が存在するのに読まずに命名を決めること
- 実名と `Name` tag の適用先を曖昧なまま実装すること
- 命名規則との差分がある既存リソースを、影響評価なしに一括リネームすること

## 完了条件

以下をすべて満たした場合のみ完了とする。

- 関連する `docs/designs/*.md` を実装前に読んでいる
- 関連する `docs/designs/_llm/*.properties` が存在する場合は実装前に読んでいる
- 命名規則が関係する場合は `docs/designs/naming-rules.md` を読んでいる
- `docs/designs/_llm/naming-rules.properties` が存在する場合は読んでいる
- 必要な design markdown が更新されている
- 必要な `_llm` 補助ファイルが更新されている
- 命名規則変更がある場合は markdown と `_llm` の両方が同期更新されている
- 実装が `infra/cloudformation/*` に反映されている
- AWS CLI による実行方針または実行コマンドが整理されている
- `tests/scenarios/*` にシナリオテストがある
- 実施結果が markdown に記録されている
