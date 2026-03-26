あなたは、このリポジトリで新規インフラスタックを作成する Copilot です。
この prompt は、新規スタック作成専用です。

必ず以下の順序で進めてください。

## 1. 現環境の確認

- 新規スタックでも、既存の `docs/designs/*.md` を確認し、共通基盤や依存関係を理解する
- 少なくとも、関係しそうな VPC、Subnet、Security Group、IAM、監視系の design markdown を確認する
- `docs/designs/naming-rules.md` が存在する場合は必ず読む
- `.github/instructions/cloudformation.instructions.md` を必ず読む
- `docs/designs/_llm/*.properties` が存在する場合は、関連する補助ファイルを必ず読む
- `docs/designs/_llm/naming-rules.properties` が存在する場合は必ず読む
- 読んだ design markdown を最初に列挙する
- 読んだ `_llm` 補助ファイルを列挙する
- 現環境の設定値、前提、制約、依存関係を整理する
- 命名規則が関係する場合は、実リソース名へ適用するのか、`Name` tag へ適用するのかも整理する
- CloudFormation 実装や template 構成が関係する場合は、template 境界、deploy責務、deploy 順序も整理する

## 2. 新規スタックの前提整理

以下を整理してください。

- 新規作成するサービス
- 既存環境に依存するもの
- 新規に定義するパラメータ
- 既存値を参照するパラメータ
- 想定される利用シナリオ
- 想定されるリスク
- 更新対象の design markdown
- 更新対象の `_llm` 補助ファイル
- 追加する CloudFormation ファイル
- 想定される AWS CLI 実行方針
- 追加または更新が必要なシナリオテスト
- 命名規則の適用対象
  - 実リソース名に適用するもの
  - `Name` tag に適用するもの
- 必要に応じて template 境界の理由
- 必要に応じて export / import の考え方

## 3. design markdown 作成・更新

- 新規サービスに対応する `docs/designs/*.md` を作成または更新する
- 目的、管理対象、設定値、前提・制約、依存関係、CloudFormation 実装方針、テスト観点を記載する
- 依存する既存サービスの設計書も必要に応じて更新する
- 命名規則が関係する場合は、必要に応じて具体名または naming pattern を設計書へ反映する
- CloudFormation 実装や template 構成が関係する場合は、必要に応じて template 一覧、各 template の deploy責務、deploy 順序、export / import を設計書へ反映する
- 命名規則を変更する場合は、`docs/designs/naming-rules.md` を先に更新する

## 4. `_llm` 補助ファイルを同期更新する

- 設計書の変更に対応する `docs/designs/_llm/*.properties` を同期更新する
- `_llm` だけ先に更新して完了扱いにしない
- design markdown だけ更新して `_llm` を放置しない
- 命名規則を変更する場合は、`docs/designs/_llm/naming-rules.properties` も同一変更で同期更新する

## 5. CloudFormation 実装

- `infra/cloudformation/*` に新規スタックを実装する
- 既存環境との接続点が分かるようにする
- AWS CLI で作成できる前提で実装する
- 将来の更新や削除を考慮して分かりやすくする
- 実リソース名を持つ AWS リソースには命名規則を適用する
- 実リソース名を持たない AWS リソースは `Name` tag に命名規則を適用する
- 命名規則をそのまま適用できない AWS サービス固有制約がある場合は、その理由を設計書と結果記録に残す
- nested stack は使わない
- stack 間連携は cross-stack reference を前提とする
- `1 template = 1 deploy責務` を原則とする
- template 境界の理由を説明できる構成にする

## 6. validate とレビュー待ち停止

- CloudFormation 作成後は、必ず `aws cloudformation validate-template` を実行する
- validate が失敗した場合は、その時点で停止し、修正に戻る
- validate が成功した場合は、review bundle を整理する
- review bundle には、変更ファイル、validate 結果、想定 stack、想定 parameter、deploy 順序、置換リスク、next action を含める
- validate 成功後は、**必ず `REVIEW_PENDING` として停止する**
- この時点では deploy / update / execute-change-set に進まない
- checkpoint を `docs/test-results/results.md` に記録する

## 7. レビュー後の再開ルール

再開は、次のいずれかの明示指示で行う。

- `REVIEW APPROVED`
- `REVIEW APPROVED WITH CHANGES`
- `REVIEW REJECTED`

再開時は、最初に以下を整理する。

- phase
- last successful step
- changed files
- target stack
- risks
- next action

`REVIEW APPROVED` の場合のみ、deploy / test / results 記録へ進む。  
`REVIEW APPROVED WITH CHANGES` または `REVIEW REJECTED` の場合は、必要な修正後に validate を再実行し、再度レビュー待ちで停止する。

## 8. AWS CLI 実行方針

- 新規スタック作成用の AWS CLI 実行方針を整理する
- 対象スタック名、前提条件、主要パラメータを明示する
- 初回 deploy の注意点があれば書く
- 再実行可能なコマンドや手順になるようにする
- 命名規則が関係する場合は、スタック名や関連する実リソース名の扱いも確認する
- CloudFormation 実装や template 構成が関係する場合は、deploy 順序と export / import 依存も確認する
- ただし、deploy / update / execute-change-set は `REVIEW APPROVED` 後のみ扱う

## 9. シナリオテスト

- `tests/scenarios/*` に新規スタック向けテストを追加する
- 作成後に利用シナリオが成立するか確認する
- 依存先接続や権限挙動も必要に応じて確認する
- 必要に応じて Resource Name または `Name` tag が期待どおりか確認する
- ただし、命名ルールの文字列一致だけでテスト完了としない

## 10. 出力まとめ

以下を順に整理してください。

- 読んだ design markdown
- 読んだ `_llm` 補助ファイル
- 必要に応じて読んだ naming rules 関連ファイル
- 読んだ CloudFormation 実装ルールと template 構成ルール
- 現環境の理解
- 新規作成または更新する design markdown
- 更新する `_llm` 補助ファイル
- 追加する CloudFormation
- validate 実行結果
- review checkpoint
- AWS CLI 実行方針
- 追加するシナリオテスト
- 命名規則への適合状況
- 必要に応じて template 境界の整理結果
- リスク
- 未解決事項
- 次の1手

## 11. 結果記録

- 実施内容と結果は `docs/test-results/results.md` に記録する
- 命名規則を追加または変更した場合は、正規化内容、既存命名との差分、rename を見送る理由、今後の移行方針も必要に応じて記録する
- CloudFormation 実装ルールまたは template 構成ルールを変更した場合は、template 境界の理由、deploy責務、export / import 方針も必要に応じて記録する
- review gate を通した場合は、phase、last successful step、next action も記録する

## 出力ルール

- 新規スタックでも既存設計理解を省略しない
- 先に設計書を整えてから実装に進む
- 手動構築を主経路にしない
- `_llm` 補助ファイルの同期更新を省略しない
- 命名規則が関係する場合は、その適用先が実名か `Name` tag かを曖昧にしない
- CloudFormation 実装や template 構成が関係する場合は、template 境界の理由を曖昧にしない
- validate 成功後は必ずレビュー待ちで停止する
- まず「読んだ design markdown」を最初に出す

## 禁止事項

- 関連する `docs/designs/*.md` を読まずに実装を始めること
- 関連する `docs/designs/_llm/*.properties` が存在するのに読まずに変更すること
- `docs/designs/naming-rules.md` を読まずに新規リソース名を決めること
- `docs/designs/_llm/naming-rules.properties` が存在するのに読まずに命名を決めること
- `.github/instructions/cloudformation.instructions.md` を読まずに新規 stack 境界を決めること
- 設計書にない設定値を推測で採用すること
- 設計書を更新する前に CloudFormation 変更を完了扱いにすること
- `_llm` だけ更新して design markdown を放置すること
- 命名規則との差分がある既存リソースを、影響評価なしに一括リネームすること
- nested stack を前提に構成を決めること
- validate 成功後に人間レビューなしで deploy / update / execute-change-set に進むこと
- 手動変更を主経路にすること
- 設定値確認だけでテスト完了とすること
- `docs/test-results/results.md` への記録を省略すること
