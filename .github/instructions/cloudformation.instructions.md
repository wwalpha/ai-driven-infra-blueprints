---
applyTo: 'infra/cloudformation/**/*'
---

# CloudFormation Implementation Rules

## このファイルの目的

`infra/cloudformation/*` 配下を変更する際の実装ルールを定義する。  
このファイルは、CloudFormation の実装ルールに加えて、template の分割・境界・cross-stack reference の扱いも定義する。

## 基本方針

- インフラ構築・変更は CloudFormation を正規ルートとする
- 手動構築を主経路にしない
- 実装前に、必ず関連する `docs/designs/*.md` を読んで現環境を理解する
- design markdown と整合するように実装する
- 命名規則が関係する場合は、`docs/designs/naming-rules.md` を参照する
- `docs/designs/_llm/*.properties` が存在する場合は、関連する補助ファイルも参照する
- `docs/designs/_llm/naming-rules.properties` が存在する場合は、命名規則の補助表現として参照する
- nested stack は採用しない
- stack 間連携は cross-stack reference を前提とする
- `1 template = 1 deploy責務` を原則とする

## 実装前チェック

変更前に最低限以下を整理すること。

- 読んだ design markdown
- 読んだ `_llm` 補助ファイル
- 必要に応じて読んだ naming rules 関連ファイル
  - `docs/designs/naming-rules.md`
  - `docs/designs/_llm/naming-rules.properties`
- 変更対象サービス
- 影響を受ける依存サービス
- 追加・変更・削除されるパラメータ
- 既存スタックへの影響
- 置換が起きる可能性
- 命名規則の適用対象
  - 実リソース名に適用するもの
  - `Name` tag に適用するもの
- template 境界の理由
- 既存命名との差分がある場合の扱い方針
- export / import の方針
- deploy 順序

## template 構成ルール

### 基本原則

- `1 template = 1 deploy責務` を原則とする
- template の分割は AWS サービス名ではなく、変更単位、rollback 単位、依存方向、責務の明確さで決める
- file 数を減らすこと自体を目的にしない
- ただし、過度な細分化も避ける
- 具体的な template 配置は各システム設計書で決める

### 採用しない考え方

- `1サービス = 1 template`
- nested stack による内部階層化を前提にすること
- file 数削減だけを理由に無関係な責務を同居させること
- 逆に、責務の弱い単位まで細かく分けること
- 既存 template の構成理由を残さずに場当たりで分割を増やすこと

### template 境界の考え方

template 境界は、次の4観点で判断する。

#### 1. 変更単位
一緒に変更されるものは同じ template 候補。  
別のタイミング、別の担当、別の変更理由で更新されるものは分割候補。

#### 2. rollback 単位
一緒に rollback するのが自然なものは同居候補。  
片方だけ戻したいことが多いものは分割候補。

#### 3. 依存方向
template 間の依存は、一方向に保てることを重視する。  
相互依存や循環依存が発生するなら、その境界は不自然。

#### 4. deploy責務の明確さ
その template が何を deploy する責務なのかを、一文で説明できることを必須とする。  
一文で説明できない template は責務過多。  
逆に、一文が弱すぎて存在意義が薄い template は分けすぎ。

### 分割判断のための標準質問

各システムは、template を分ける前に、少なくとも以下の質問に答えること。

#### 質問1
このリソース群は、他のリソース群と別タイミングで変更されるか。

- Yes の場合は分割候補
- No の場合は同居候補

#### 質問2
このリソース群は、障害時や変更失敗時に、他と別に rollback したいか。

- Yes の場合は分割候補
- No の場合は同居候補

#### 質問3
この境界をまたいでやり取りする値は、安定した ID や ARN だけで済むか。

- Yes の場合は分割しやすい
- No の場合は境界を見直す

#### 質問4
この template の deploy責務を一文で説明できるか。

- Yes の場合は責務が明確
- No の場合は分割または統合を見直す

#### 質問5
この分け方は、運用時の deploy 順序と review 観点を分かりやすくするか。

- Yes の場合は採用候補
- No の場合は境界を見直す

## cross-stack reference の原則

このリポジトリでは、stack 間連携は cross-stack reference を前提とする。  
ただし、stack 間で受け渡す値は最小限に絞る。

### export / import してよいもの

原則として、以下のような安定した識別子のみを export / import 対象とする。

- ID
- ARN
- subnet ID の一覧
- security group ID
- VPC ID
- KMS key ARN
- CIDR など、意味が安定した共有値

### export / import を避けるもの

以下のような変わりやすい値や、責務境界を曖昧にする値は避ける。

- 一時的な設定値
- 変更されやすい命名文字列
- 業務ロジックに近いパラメータ
- 他 template の内部事情に依存する値

### export 名の扱い

export 名は、安定的で再利用しやすく、役割が分かるものにする。  
既存 stack が import している export を安易に変更しない。

## 実装ルール

- 可能な限り明示的で読みやすいテンプレートにする
- 設計書にない前提条件をテンプレートへ埋め込まない
- 既存環境変更では、破壊的変更の可能性を意識する
- 既存リソースへの影響がある場合は、どのリソースに影響するか整理する
- 実装は AWS CLI で deploy / update できることを前提にする
- 実リソース名を持つ AWS リソースには naming rules を適用する
- 実リソース名を持たない AWS リソースには `Name` tag に naming rules を適用する
- 命名規則をそのまま適用できない AWS サービス固有制約がある場合は、テンプレート内だけで吸収せず、設計書と結果記録に理由を残す
- 既存リソースの命名が規則と異なる場合でも、影響評価なしに一括リネームしない
- 既存 rename が必要な場合は、置換、参照切れ、運用影響を整理したうえで扱う
- template の責務を一文で説明できることを必須とする
- 境界をまたぐ値は、可能な限り安定した ID や ARN に限定する

## Name tag の扱い

- 明示的な Resource Name を持たない AWS リソースでは、`Tags` の `Name` に naming rules を適用する
- `Name` tag を採用する場合は、設計書と CloudFormation の両方でその方針を曖昧にしない
- tag だけでなく、必要な共通 tag も設計書に従って付与する
- 既存リソースに `Name` tag がない場合は、影響を確認したうえで追加する

## 変更時に意識すること

- 新規リソース追加か
- 既存リソース更新か
- 置換を伴うか
- ダウンタイムがありうるか
- ロールバック時に問題がないか
- 他サービスの設計書更新が必要か
- 命名規則への適合が新規追加分のみか、既存分にも影響するか
- 既存命名との差分を今回是正するのか、据え置くのか
- template 境界が自然か
- deploy 順序が明確か
- export / import が安定した値だけで成立しているか

## AWS CLI 前提

- 実行は AWS CLI を前提とする
- 再実行可能なコマンドまたは手順を意識する
- 実行に必要なパラメータや前提条件を曖昧にしない
- 命名規則が関係する場合は、スタック名や関連する実リソース名の扱いも設計書と整合させる

## テスト連携

- CloudFormation 変更に対応するシナリオテストを `tests/scenarios/*` に追加または更新する
- 変更内容に対する期待動作をテストで確認できるようにする
- 必要に応じて Resource Name または `Name` tag が期待どおりか確認する
- ただし、命名ルールの文字列一致だけでテスト完了としない

## 結果記録との連携

- 実施内容と結果は `docs/test-results/results.md` に記録する
- 命名規則を追加または変更した場合は、正規化内容、既存命名との差分、rename を見送る理由、今後の移行方針も必要に応じて記録する
- CloudFormation 実装ルールまたは template 構成ルールを変更した場合は、template 境界の理由、deploy責務、export / import 方針も必要に応じて記録する

## 禁止事項

- design markdown を読まずに実装すること
- `docs/designs/naming-rules.md` を読まずに新規リソース名を決めること
- `docs/designs/_llm/*.properties` が存在するのに読まずに変更すること
- `docs/designs/_llm/naming-rules.properties` が存在するのに読まずに命名を決めること
- 手動変更前提の実装にすること
- 変更理由が設計書に反映されていない状態で進めること
- テンプレート変更だけで完了扱いにすること
- 実名と `Name` tag の適用先を曖昧なまま実装すること
- 命名規則との差分がある既存リソースを、影響評価なしに一括リネームすること
- nested stack を前提に構成を決めること
- `1 template = 1 deploy責務` を満たさない構成を放置すること
