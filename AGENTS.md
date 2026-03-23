# AGENTS.md

このリポジトリでは、Copilot は**ローカル実行**を前提とする。

## 前提

- 仕様は ChatGPT と合意済みである
- AWS 認証は人間が Copilot 実行前に手動で完了する
- 必要な `AWS_PROFILE`、`AWS_REGION`、認証情報、環境変数は事前に設定済みである
- Copilot は既存の認証済みローカル環境を利用して作業する
- 認証方式の取得・変更自体は Copilot の主作業に含めない

## 最重要ルール

- 実装前に、必ず関連する `docs/designs/*.md` を読む
- 関連する `docs/designs/_llm/*.properties` が存在する場合は、必ずあわせて読む
- サービスの設定値の正本は `docs/designs/*.md` とする
- `docs/designs/_llm/*.properties` は Copilot / LLM 向け補助ファイルとして扱う
- 実装は `infra/cloudformation/*` に対して行う
- 構築・更新は AWS CLI で CloudFormation を実行する
- テストは `tests/scenarios/*` に shell script / PowerShell script として追加・更新する
- 単なる設定値確認だけで完了扱いにしない
- 実施内容と結果は markdown に記録する

## design markdown の形式

各サービスの `docs/designs/*.md` は、人間向けに以下の形式を基本とする。

- 1リソース = 1見出し
- 1リソース = 1 table
- table の列は原則として `Property Name | Value | Comment`

例:

```md
## EC2: WEB01

| Property Name | Value     | Comment            |
| ------------- | --------- | ------------------ |
| instanceType  | t3.medium | インスタンスタイプ |
| subnet        | private-a | 配置先             |
| securityGroup | web-sg    | 適用SG             |
```

## \_llm 補助ファイルの形式

各サービスの `docs/designs/_llm/*.properties` は、Copilot / LLM が安定して読むための補助ファイルとする。

形式:

```properties
service.logicalId.property=value
```

例:

```properties
ec2.WEB01.instanceType=t3.medium
ec2.WEB01.subnet=private-a
ec2.WEB01.securityGroup=web-sg
```

## 更新ルール

- Copilot が設定値を変更する場合は、`docs/designs/*.md` と `docs/designs/_llm/*.properties` を同一変更で同期更新する
- markdown と `_llm` の内容が不一致の場合は、まず markdown を正本として確認し、`_llm` を同期させる
- `_llm` だけ先に更新して完了扱いにしない
- design markdown が古いまま CloudFormation を先に変更しない

## 作業順序

1. 読むべき `docs/designs/*.md` を特定する
2. 対応する `docs/designs/_llm/*.properties` が存在するか確認し、あれば読む
3. 現環境の設定値、制約、依存関係を整理する
4. 変更対象の design markdown を更新する
5. 対応する `_llm/*.properties` を同期更新する
6. `infra/cloudformation/*` を実装または更新する
7. AWS CLI による構築・更新方針または実行コマンドを整理する
8. `tests/scenarios/*` にシナリオテストを追加・更新する
9. 結果を markdown に記録する

## 禁止事項

- `docs/designs/*.md` を読まずに実装を始めること
- `_llm` があるのに読まずに設定変更すること
- design markdown が古いまま CloudFormation を先に変更すること
- 設計書にない設定値を推測で採用すること
- `_llm` だけ更新して markdown を放置すること
- 手動構築を主経路にすること
- 設定値確認だけでテスト完了とすること
- 結果記録なしで完了扱いにすること

## 出力時の整理順序

Copilot は、少なくとも次の順序で整理して出力すること。

1. 読んだ design markdown
2. 読んだ `_llm` 補助ファイル
3. 現環境の理解
4. 更新対象の design markdown
5. 更新対象の `_llm` 補助ファイル
6. 変更対象の CloudFormation
7. AWS CLI 実行方針
8. 追加または更新するシナリオテスト
9. リスク
10. 結果または次の1手
