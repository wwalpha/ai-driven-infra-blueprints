あなたは、このリポジトリで既存インフラスタックを変更する Copilot です。
この prompt は、既存スタック変更専用です。

必ず以下の順序で進めてください。

## 1. 変更前の現環境理解

- 変更対象サービスの `docs/designs/*.md` を読む
- 依存する関連サービスの設計書も読む
- `docs/designs/naming-rules.md` が存在する場合は必ず読む
- `.github/instructions/cloudformation.instructions.md` を必ず読む
- `docs/designs/_llm/*.properties` が存在する場合は、関連する補助ファイルを必ず読む
- `docs/designs/_llm/naming-rules.properties` が存在する場合は必ず読む
- 読んだ design markdown を最初に列挙する
- 読んだ `_llm` 補助ファイルを列挙する
- 現在の設定値、前提、制約、依存関係を整理する
- 命名規則が関係する場合は、実リソース名へ適用するのか、`Name` tag へ適用するのかも整理する
- 既存リソースの命名が naming rules と一致しているか、不一致があるかも整理する
- CloudFormation 実装や template 構成が関係する場合は、template 境界、deploy責務、deploy 順序も整理する

## 2. 影響範囲整理

以下を必ず整理してください。

- 変更対象サービス
- 影響を受ける依存サービス
- 追加・変更・削除されるパラメータ
- 既存リソースへの影響
- 置換有無
- ダウンタイム可能性
- ロールバック観点
- 更新対象の design markdown
- 更新対象の `_llm` 補助ファイル
- 変更対象の CloudFormation ファイル
- 想定される AWS CLI 実行方針
- 追加または更新が必要なシナリオテスト
- 命名規則の適用対象
  - 実リソース名に適用するもの
  - `Name` tag に適用するもの
- 既存命名との差分
- 今回 rename を行うか、据え置くか、その方針
- 必要に応じて template 境界の理由
- 必要に応じて export / import の考え方

## 3. design markdown 更新

- 先に `docs/designs/*.md` を更新する
- 変更後の値だけでなく、制約、依存関係、テスト観点も更新する
- 必要なら依存サービス側の設計書も更新する
- 命名規則が関係する場合は、必要に応じて具体名または naming pattern を設計書へ反映する
- CloudFormation 実装や template 構成が関係する場合は、必要に応じて template 一覧、各 template の deploy責務、deploy 順序、export / import を設計書へ反映する
- 命名規則を変更する場合は、`docs/designs/naming-rules.md` を先に更新する
- 既存命名との差分がある場合は、今回の扱い方針を設計書または結果記録に残す

## 4. `_llm` 補助ファイルを同期更新する

- 設計書の変更に対応する `docs/designs/_llm/*.properties` を同期更新する
- `_llm` だけ先に更新して完了扱いにしない
- design markdown だけ更新して `_llm` を放置しない
- 命名規則を変更する場合は、`docs/designs/_llm/naming-rules.properties` も同一変更で同期更新する

## 5. CloudFormation 変更

- `infra/cloudformation/*` を更新する
- design markdown と整合する形で実装する
- 破壊的変更の可能性がある場合は明示する
- AWS CLI で update する前提で整理する
- 実リソース名を持つ AWS リソースには命名規則を適用する
- 実リソース名を持たない AWS リソースは `Name` tag に命名規則を適用する
- 既存リソースの命名が規則と異なる場合でも、影響評価なしに一括リネームしない
- rename が置換や参照切れにつながる場合は、そのリスクを明示する
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

- 既存スタック update 用の AWS CLI 方針を整理する
- 実行前確認事項があれば明示する
- パラメータ、対象スタック、適用順序があれば示す
- 再実行可能なコマンドや手順になるようにする
- 命名規則が関係する場合は、スタック名や関連する実リソース名の扱いも確認する
- CloudFormation 実装や template 構成が関係する場合は、deploy 順序と export / import 依存も確認する
- ただし、deploy / update / execute-change-set は `REVIEW APPROVED` 後のみ扱う

## 9. シナリオテスト追加・更新

- `tests/scenarios/*` に、変更内容に対応するテストを追加または更新する
- 既存機能が壊れていないかも意識する
- 正常系だけでなく、必要に応じて拒否系・失敗系も確認する
- 必要に応じて Resource Name または `Name` tag が期待どおりか確認する
- ただし、命名ルールの文字列一致だけでテスト完了としない

## 10. 最終整理

以下を順にまとめてください。

- 読んだ design markdown
- 読んだ `_llm` 補助ファイル
- 必要に応じて読んだ naming rules 関連ファイル
- 読んだ CloudFormation 実装ルールと template 構成ルール
- 現環境の理解
- 影響範囲
- 更新した design markdown
- 更新した `_llm` 補助ファイル
- 変更した CloudFormation
- validate 実行結果
- review checkpoint
- AWS CLI 実行方針
- 追加または更新したシナリオテスト
- 命名規則への適合状況
- 既存命名との差分
- rename リスク
- 今回の採用方針
- 必要に応じて template 境界の整理結果
- 未解決事項
- 次の1手

## 11. 結果記録

- 実施内容と結果は `docs/test-results/results.md` に記録する
- 命名規則を追加または変更した場合は、正規化内容、既存命名との差分、rename を見送る理由、今後の移行方針も必要に応じて記録する
- CloudFormation 実装ルールまたは template 構成ルールを変更した場合は、template 境界の理由、deploy責務、export / import 方針も必要に応じて記録する
- review gate を通した場合は、phase、last successful step、next action も記録する

## 出力ルール

- 既存変更では、影響範囲、置換、ダウンタイム、ロールバック観点を必ず出す
- 設計書を更新する前に CloudFormation 変更を完了扱いにしない
- 手動変更を主経路にしない
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
