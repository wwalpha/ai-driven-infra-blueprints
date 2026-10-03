# Windows全回帰の人間入力ガード

## Task contract
- Task type: `governance`
- Target: Windows framework regression entrypoint
- Goal: 全回帰の開始前に人間のパスワード入力を要求し、hash照合処理と登録値の変更権限を通常権限のエージェントから分離する。通常の対象限定検証と既存のscopeを維持する。

## Validation scope
- `framework`

## Required changes
- [R1] Windowsで明示／自動追加／affected fallbackの全回帰を開始する前に保護された照合処理を呼ぶ。入力キャンセル、認証失敗、未登録、不正な保護状態では検証を起動せず失敗する。環境変数、引数、承認済みflagによる解除を追加しない。
- [R2] Windows管理者による一回の対話登録で、hashと照合プログラムをWindows既定の共通application data directoryへ設置し、管理者／SYSTEMだけが変更できるACLとownerを設定する。通常権限では登録・変更を拒否する。パスワードは人間のconsole入力のみで受け取り、平文を保存・記録しない。
- [R3] ガードの成否、登録／権限境界、全回帰選択とstaged snapshot、対象限定検証の継続を回帰検証する。運用手順と境界を文書化し、local loopを実行する。

## Acceptance checks
- [R1] `changed:framework/scripts/blueprint-loop.py`
- [R1] `changed:framework/scripts/blueprint-loop.checks.py`
- [R2] `exists:framework/scripts/regression_guard.py`
- [R2] `exists:framework/scripts/regression_guard.checks.py`
- [R3] `changed:framework/rules/loop-engineering.md`
- [R3] `changed:README.md`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/blueprint-loop.py`
- `framework/scripts/blueprint-loop.checks.py`
- `framework/scripts/regression_guard.py`
- `framework/scripts/regression_guard.checks.py`
- `framework/rules/loop-engineering.md`
- `README.md`

## Out of scope
- Windows実機の管理者設定・パスワード登録は人間が行う。本taskのエージェントは登録値を決めず、実機の保護を解除しない。
- macOSの権限・認証方式変更、framework編集自体の禁止、任意Python実行全体のOS sandbox化、実targetの設計/model/IaC/project、AWS操作、consumer同期、catalog変更、scenario、commit、push、index変更。
- 既知passwordやmockを実repositoryの全回帰解除に使わない。mockは一時fixture内のテストだけに使用する。
