# Local loopの時間計測と長時間実行の診断

## Task contract

- Task type: `governance`
- Target: framework共通（viewcard-codeはread-only性能調査だけ）
- Goal: local loopの全体・check別実行時間をローカルファイルへ記録し、profileで確認したprefix判定を軽量化する。VS Code GitHub Copilot Autopilotの待機終了と実プロセス停止を切り分け、重複実行を防ぐ運用を定義する。

## Required changes

- [R1] 既存local loopへcheck別時間、終了code、PID、途中稼働表示、全体時間とローカルログ出力を追加し、全check実行・assert有効化・失敗時FAILを維持する。
- [R2] 既存focused checkへログ内容、failure後の継続、稼働表示、起動失敗・中断の回帰検証を追加する。
- [R3] loopルールとREADMEへ実測結果、計測方法、Copilot長時間実行の切り分け・回復手順を記載する。
- [R4] profileで確認したformal_propertyのprefix判定を標準文字列関数へ置き換え、完全修飾・省略・alias・未知prefixの検証結果を維持する。

## Acceptance checks

- [R1] `changed:framework/scripts/blueprint-loop.py`
- [R1] `check:framework.focused-check-runner`
- [R2] `changed:framework/scripts/blueprint-loop.checks.py`
- [R3] `changed:framework/rules/loop-engineering.md`
- [R3] `changed:README.md`
- [R4] `changed:framework/scripts/design_layout.py`
- [R4] `changed:framework/scripts/design_layout.checks.py`
- [R4] `check:framework.resource-layout`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/blueprint-loop.py`
- `framework/scripts/blueprint-loop.checks.py`
- `framework/rules/loop-engineering.md`
- `README.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/design_layout.checks.py`

## Out of scope

- design/model/IaC、project.json、catalog/lock、AWS API・mutation、deploy/apply、scenario/result、別taskは変更・実行しない。
- viewcard-codeは既存input・task contractを保持し、read-onlyのlocal loop計測と必要なprofileだけを実行する。consumer repositoryへの書き込み・framework同期・設計修正は行わない。
- 計測ログ・profileはrepository外のローカルfileへ保存し、tasks/やtests/results/へ保存しない。
- 検証省略、未確認のcache・並列化、VS Codeのuser設定変更、Copilot timeout/session存続の保証は行わない。
- focused check、governance local loop、git diff --checkを実行し、実測と未再現の現象を区別して報告する。
