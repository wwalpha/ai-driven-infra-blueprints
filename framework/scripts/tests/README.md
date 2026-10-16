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

`blueprint-loop.py` は `units/**/*.checks.py`（42スイート）と `units/**/test_*.py`（既存unittest 1スイート）を、既存のPython直接実行入口で起動する。合計43 UTスイート。`full` / `--all` も回帰部分は全UTのみで、validatorのScopeや安全制御は維持する。`task` / `local` の自動回帰もUT限定。元々回帰不要のScopeではUTを追加しない。

`--affected` は従来の依存マッピングと分割UT対応を適用してからUTだけを抽出する。共有・不明・欠落依存は全UTへfallbackする。`--staged` は同じ選択を固定snapshot内で行う。全UT選択時のWindows認証、UTF-8、診断ログ、失敗伝播を維持する。

IT全67スイートは [Framework IT](../../../.github/workflows/framework-it.yml) がPR、main/masterへのpush、手動実行で検証する。Python 3.12と既存requirementsを使用し、各 `integrations/**/*.checks.py` を直接実行する。`__main__` の有無で省略せず、トップレベル実行6スイートも含める。`design_document.checks.py` は既存2ケースを明示呼出しする。各スイートのPASS/FAIL・秒数をActionsログとSummaryに残し、FAIL後も残りを実行、最後に1件でもFAILならジョブを失敗させる。事前fixture生成や追加Fullは行わず、実AWSや認証情報を必要としない。

ローカル修正では関連UTを実行し、ITの検証はGitHub Actionsへ委ねる。PRの現revisionでIT PASSを確認してからマージする。CI未完了・未実行・キャンセル・FAILをIT検証完了と扱わない。ブランチ保護のRequired status checkに `Framework IT` を指定する設定は別途必要。
