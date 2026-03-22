# Copilot Instructions

## 目的

このリポジトリでは、ChatGPT と仕様を決め、Copilot がインフラ構築とテストを実施する。
Copilot は、設計書理解、CloudFormation 実装、AWS CLI 実行、シナリオテスト、結果記録の順序を守ること。

## 固定ルール

- 実装前に、必ず関連する `docs/designs/*.md` を読んで現環境の設定値と制約を理解する
- サービスの設計書とパラメータは、サービスごとに `docs/designs/*.md` で管理する
- 実装は `infra/cloudformation/*` に集約する
- インフラ構築・更新は CloudFormation を AWS CLI で実行して行う
- テストは `tests/scenarios/*` に shell script / PowerShell script として実装する
- 単なる設定値確認だけでテスト完了とみなさない
- 実施内容と結果は markdown に記録する

## 設計書の扱い

- `docs/designs/*.md` は現環境の正本である
- 設計書に書かれていない値を推測で採用しない
- 実装と設計書がずれる場合は、先に設計書を更新する
- 変更対象サービスだけでなく、依存する関連サービスの設計書も読む

## 実装前の必須確認

Copilot は作業開始時に、少なくとも以下を明示的に整理すること。

1. 読んだ design markdown
2. 現環境の理解
3. 更新対象の design markdown
4. 変更対象の CloudFormation
5. AWS CLI による実行方針
6. 追加または更新するシナリオテスト

## 実装ルール

- 手動構築を主経路にしない
- CloudFormation を先に作成または更新し、その後 AWS CLI で実行する
- 既存環境変更時は、影響範囲、置換有無、依存関係を意識する
- 実装は design markdown と整合していること

## テストルール

- テストはシナリオベースで行う
- 正常系だけでなく、必要に応じて拒否系、失敗系、到達性確認も含める
- 疎通、利用シナリオ、権限挙動を優先して確認する
- 単なるパラメータ設定確認のみでは不十分とする

## 記録ルール

最低限、以下を markdown に残すこと。

- 対象サービス
- 読んだ design markdown
- 更新した design markdown
- 変更した CloudFormation ファイル
- AWS CLI 実行コマンド
- 追加または更新したテスト
- 実施結果
- 未解決事項
- 次の対応候補

## 禁止事項

- 関連する `docs/designs/*.md` を読まずに実装を始めること
- design markdown が古いまま CloudFormation を先に更新すること
- 設計書にない設定値を推測で採用すること
- 手動変更を主経路にすること
- 設定値確認だけでテスト完了とすること
- 記録を残さずに完了とすること

## 完了条件

以下をすべて満たした場合のみ完了とする。

- 関連する `docs/designs/*.md` を実装前に読んでいる
- 必要な design markdown が更新されている
- 実装が `infra/cloudformation/*` に反映されている
- AWS CLI による実行方針または実行コマンドが整理されている
- `tests/scenarios/*` にシナリオテストがある
- 実施結果が markdown に記録されている
