# Framework tests

テストは検証責務で分類する。ケース一覧、現在の配置、パラメータ数、直接実行の検証地点は [CASES.md](CASES.md) を参照。

- `units/`: 単一関数・クラスの変換、比較、判定、入力検証。Framework内部定義と合成fixture、既存Fake/Mockで完結する。
- `integrations/`: Model生成・保存・再読込・同期、サービス間参照、CLI、Git/worktree、Adapter連携。
- `support/`: 共通fixture、loader、pytestの診断補助。UTはITテストモジュールをimportしない。
- `unknown/`: 分類対象を残さない。分類済みかどうかはディレクトリ名だけで判断しない。

## 実行入口

リポジトリルートから実行する。管理worktreeでは登録済みPython環境のwrapperを使う。

```console
python3 -B framework/scripts/run-python.py -m pytest framework/scripts/tests/units/model_design-unit.checks.py -q
python3 -B framework/scripts/run-python.py -B framework/scripts/tests/units/validation-units.checks.py
python3 -B framework/scripts/run-python.py -B framework/scripts/tests/units/test_issues_iac.py
```

`pytest.ini`は既存のpytest型ファイルと`*-unit.checks.py`を対象にする。全UTがpytest型ではない。`array_display`、`aws_mapping_catalog`、`check-deploy-context`、`cloudformation_schema`、`comparison_core-unit`、`script_loader`、`update-catalog-lock`、`validation-units`には直接実行の入口がある。`validation_checks/*.py`は同じ分類のaggregatorから呼ぶ。`test_issues_iac.py`は既存unittestメソッドをpytestでも収集する。

`blueprint-loop.py` は `units/**/*.checks.py`（43スイート）と `units/**/test_*.py`（既存unittest 1スイート）を、既存のPython直接実行入口で起動する。合計44 UTスイート。`full` / `--all` も回帰部分は全UTのみで、validatorのScopeや安全制御は維持する。`task` / `local` の自動回帰もUT限定。元々回帰不要のScopeではUTを追加しない。

`--affected` は従来の依存マッピングと分割UT対応を適用してからUTだけを抽出する。共有・不明・欠落依存は全UTへfallbackする。`--staged` は同じ選択を固定snapshot内で行う。全UT選択時のWindows認証、UTF-8、診断ログ、失敗伝播を維持する。

IT全66スイートは [Framework IT](../../../.github/workflows/framework-it.yml) がPR、main/masterへのpush、手動実行で検証する。Python 3.12と既存requirementsを使用し、唯一の公式入口 `python -B framework/scripts/tests/run_it.py` が各 `integrations/**/*.checks.py` を独立プロセスで起動する。既存のpytest・直接実行・トップレベル実行方式を維持する。

runnerは共通fixture bundleを1回初期化し、`framework`・`input_templates`・`typed_services`・`generated_policy` の4 seedを各1回生成する。共有seedは読み取り専用で、変更領域は各ケースに独立したコピーを渡し、実行後に内容と権限の整合性を確認する。実プロジェクトのModelやAWS認証情報は使用しない。

`CASES.md` の279関数・357パターンに加え、12のmain入口と7のmodule末尾を19実行グループとして別に登録する。pytestは既存 `PytestReceipt` で収集・PASS・パラメータ数を照合する。直接実行112関数と12のmain入口は最外側の `@it_case` が正常return後だけaudit完了イベントを発行し、module型は末尾の `module_complete(__file__)` で完了を通知する。同一ケースの複数回呼出しは独立ケース数に加算しない。未登録スイート、記録対象でない入口、未完了ケース、欠落・不正receipt、非0終了コードは失敗とする。

全関数・全行の監視は使用しない。ファイルコピー・子プロセス・fixture生成のauditイベントと、スイート別の時間・終了コード・receiptを維持する。FAIL後も残りのスイートを実行し、結果をActionsログとSummaryに記録する。追加のFull IT実行入口は設けず、`blueprint-loop.py` の回帰はUTのみとする。

手動実行の `baseline_ref` は同じrunnerで旧コードの終了コードと時間を測定する。旧baselineには完了マーカーや台帳を要求せず、ケース到達性は「未検証」、旧profiler由来のfixture要求数・生成数は「比較不能」と明示する。依存パッケージが異なる場合は比較を拒否する。検証内容・スイートの同一性が確立していない時間差を、同条件での性能改善とは扱わない。

ローカル修正では関連UTを実行し、ITの検証はGitHub Actionsへ委ねる。PRの現revisionでIT PASSを確認してからマージする。CI未完了・未実行・キャンセル・FAILをIT検証完了と扱わない。ブランチ保護のRequired status checkに `Framework IT` を指定する設定は別途必要。

契約の選択・通常の状態遷移・公開時の変更検出を既存UTで確認する。実Git、Atomic rollback、finalize/cleanupの安全停止は既存ITで検証する。予約と独自worktree identityだけを検証するケースは廃止した。
