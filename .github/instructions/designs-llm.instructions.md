---
applyTo: "docs/designs/_llm/**/*.properties"
---

# Design LLM Properties Rules

## このファイルの目的

`docs/designs/_llm/*.properties` を編集または参照する際のルールを定義する。

## 基本方針

- `_llm/*.properties` は Copilot / LLM 向け補助ファイルである
- 正本は `docs/designs/*.md` である
- `_llm` は機械が安定して読めるよう、単純で一貫した形式を維持する
- 人間向け説明は `docs/designs/*.md` に残し、`_llm` 側に説明文を詰め込みすぎない

## 形式

各行は以下の形式を基本とする。

```properties
service.logicalId.property=value
```

例:

```properties
ec2.WEB01.instanceType=t3.medium
ec2.WEB01.subnet=private-a
ec2.WEB01.securityGroup=web-sg
```

## ルール

- service はサービス名で統一する
- logicalId は markdown 見出しの対象リソースと対応させる
- property は markdown table の `Property Name` と対応させる
- value は markdown table の `Value` と対応させる
- 1行に1プロパティだけ書く
- コメントは書かない
- 曖昧な省略や自由文を入れない

## markdown との同期

- `docs/designs/*.md` の値を変更したら、対応する `_llm` も同一変更で更新する
- `_llm` のみ更新して完了扱いにしない
- markdown と `_llm` が不一致の場合は、まず markdown を正本として確認し、`_llm` を同期する
- まだ `_llm` が存在しないサービスは、必要に応じて新規作成する

## 禁止事項

- 正本として `_llm` だけを信用すること
- 1つの行に複数プロパティを詰めること
- コメントや自由文を混在させること
- markdown と対応しない独自キーを勝手に追加すること
