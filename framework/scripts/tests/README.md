# Framework tests

テストは検証責務で分類する。全ケース、元ファイル、移動先、パラメータ数、変更不要ケース、直接実行の検証地点は [CASES.md](CASES.md) を参照。

- `units/`: 単一関数・クラスの変換、比較、判定、入力検証。Framework内部定義と合成fixture、既存Fake/Mockで完結する。
- `integrations/`: Model生成・保存・再読込・同期、サービス間参照、CLI、Git/worktree、Adapter連携。
- `support/`: 共通fixture、loader、pytestの診断補助。UTはITテストモジュールをimportしない。
- `unknown/`: 分類対象を残さない。分類済みかどうかはディレクトリ名だけで判断しない。

## 実行入口

リポジトリルートから実行する。管理worktreeでは登録済みPython環境のwrapperを使う。

```console
python3 -B framework/scripts/run-python.py -m pytest framework/scripts/tests/units/model_design-unit.checks.py -q
python3 -B framework/scripts/run-python.py -B framework/scripts/tests/units/validation-units.checks.py
python3 -B framework/scripts/run-python.py -B framework/scripts/tests/integrations/quicksight-display.checks.py
```

`pytest.ini`は既存のpytest型ファイルと`*-unit.checks.py`を対象にする。全UTがpytest型ではない。`array_display`、`aws_mapping_catalog`、`check-deploy-context`、`cloudformation_schema`、`comparison_core-unit`、`script_loader`、`update-catalog-lock`、`validation-units`には直接実行の入口がある。`validation_checks/*.py`は同じ分類のaggregatorから呼ぶ。`test_issues_iac.py`は既存unittestメソッドをpytestでも収集する。

`blueprint-loop.py`の既存チェック発見は`*.checks.py`を再帰探索する。依存選択は従来のsuiteに対応する分割UTも含める。共有fixtureや不明な依存に対する全回帰へのfallbackは維持する。これは通常運用の収集仕様であり、今回の分離作業ではfull/全回帰を実行しない。

## 分離内容

関数全体の移動に加え、混在関数から内部定義、型比較、命名、表示変換、入力解析、キャッシュ、Fakeによるscheduler、Mockによる割込み処理を抽出した。CLI・Git・Model同期の責務はITに残した。supportに置かれていたvalidatorとサービス検証ケースも分類先へ移した。元のfixtureは共通化し、検証を新しいMockへ置き換えていない。

ケース関数数の増加は混在責務の抽出によるもの。入力パターンや検証条件を追加して件数を増やしていない。関数入口数、pytestの展開数、main/moduleの検証地点数を区別して台帳に記載する。

## 静的照合

- assert文: 4,217 → 4,217。
- 明示的な`raise AssertionError`: 119 → 119、AST多重集合一致。
- unittest/Mockのassert呼出し: 39 → 39、AST多重集合一致。
- assert式の差分は7地点。移動先パスと分割UTの選択期待値だけを更新し、完全一致比較を維持。
- Pythonソースの構文、共有名の参照、移動元・移動先、pytest decoratorをソースだけで調査。全件収集は未実行。

## 今回の最終検証

**FAIL（収集エラー2件）。完了扱いにせずworktreeを保持する。**

2026-10-16、全コード修正後に1バッチだけ実行。バッチ全体 **52.610秒**。40 UT入口中39 PASS / 1 FAIL、IT代表3件はすべてPASS。pytestで実行した本来のUTは92 PASS、ITは2 PASS。追加で直接実行したUT6入口とIT1入口はPASS。

失敗は `units/framework-input-isolation-unit.checks.py`。本来の `check_framework_input_guards` はPASSだが、`from support.framework_input_isolation_fixtures import *` が本体の `check_structure` と `check_validation_scope` も公開し、pytestが意図せず収集した。それぞれ `fixture 'findings' not found` / `fixture 'accounts' not found`。既存ケースではないため全ケース台帳の件数には加算しない。その後のHuman指示「修正して」により、一括importを必要な名前だけの明示importへ変更し、本体関数2つを `_check_structure` / `_check_validation_scope` として参照するよう修正した。静的解析では収集対象名は本来の `check_framework_input_guards` のみで、既存assert 6件は同一。テスト再実行は元の制約に従って未実施。上記FAILは修正前の結果であり、修正後PASSを意味しない。

実行コマンドは表のpytest対象には `python -B -m pytest <対象> -q -rA`、direct対象には `python -B <対象>`。親バッチは管理worktreeの `run-python.py` で起動し、全子プロセスで同じPython環境を使用した。

| 分類 | 方式 | 実際の対象 | 結果 | 秒 |
|---|---|---|---|---:|
| UT | direct | `units/array_display.checks.py` | PASS | 1.718 |
| UT | pytest | `units/aws_mapping-unit.checks.py` | PASS | 2.566 |
| UT | direct | `units/aws_mapping_catalog.checks.py` | PASS | 3.350 |
| UT | pytest | `units/aws_mapping_compare-unit.checks.py` | PASS | 0.270 |
| UT | pytest | `units/aws_mapping_display-unit.checks.py` | PASS | 4.767 |
| UT | pytest | `units/blueprint-loop-unit.checks.py` | PASS | 0.331 |
| UT | direct | `units/check-deploy-context.checks.py` | PASS | 0.090 |
| UT | pytest | `units/check-model-aws-unit.checks.py` | PASS | 0.261 |
| UT | pytest | `units/cloudformation-deploy-unit.checks.py` | PASS | 0.210 |
| UT | direct | `units/cloudformation_schema.checks.py` | PASS | 0.140 |
| UT | pytest | `units/compare-environments-unit.checks.py` | PASS | 0.150 |
| UT | direct | `units/comparison_core-unit.checks.py` | PASS | 0.843 |
| UT | pytest | `units/deploy_preparation-unit.checks.py` | PASS | 0.316 |
| UT | pytest | `units/design_catalog-unit.checks.py` | PASS | 0.206 |
| UT | pytest | `units/design_document-unit.checks.py` | PASS | 0.895 |
| UT | pytest | `units/design_layout-unit.checks.py` | PASS | 1.004 |
| UT | pytest | `units/framework-input-isolation-unit.checks.py` | FAIL (exit 1) | 0.326 |
| UT | pytest | `units/glue_datazone_catalog-unit.checks.py` | PASS | 0.262 |
| UT | pytest | `units/import-model-unit.checks.py` | PASS | 0.271 |
| UT | pytest | `units/issue_gate-unit.checks.py` | PASS | 0.206 |
| UT | pytest | `units/issues_api_only-unit.checks.py` | PASS | 0.210 |
| UT | pytest | `units/issues_scan-unit.checks.py` | PASS | 0.740 |
| UT | pytest | `units/json-yaml-document-hash-unit.checks.py` | PASS | 0.193 |
| UT | pytest | `units/lambda_permission-unit.checks.py` | PASS | 1.203 |
| UT | pytest | `units/model_design-unit.checks.py` | PASS | 17.311 |
| UT | pytest | `units/model_files-unit.checks.py` | PASS | 0.382 |
| UT | pytest | `units/model_parameter_inputs-unit.checks.py` | PASS | 0.271 |
| UT | pytest | `units/model_templates-unit.checks.py` | PASS | 0.267 |
| UT | pytest | `units/policy_tables-unit.checks.py` | PASS | 0.261 |
| UT | pytest | `units/producer-identifier-reference-unit.checks.py` | PASS | 0.207 |
| UT | pytest | `units/quicksight-display-unit.checks.py` | PASS | 1.042 |
| UT | pytest | `units/raw-bucket-name-reference-unit.checks.py` | PASS | 0.204 |
| UT | pytest | `units/regression_guard-unit.checks.py` | PASS | 0.149 |
| UT | pytest | `units/resource_mode-unit.checks.py` | PASS | 0.271 |
| UT | pytest | `units/security_group_tables-unit.checks.py` | PASS | 0.270 |
| UT | pytest | `units/sync-model-unit.checks.py` | PASS | 0.270 |
| UT | direct | `units/validation-units.checks.py` | PASS | 6.605 |
| UT | pytest | `units/validation_cache-unit.checks.py` | PASS | 1.139 |
| UT | pytest | `units/validation_scope-unit.checks.py` | PASS | 0.271 |
| UT | pytest | `units/worktree_python-unit.checks.py` | PASS | 0.205 |
| IT | pytest | `integrations/model_design.checks.py::check_route53_endpoint_dns_roundtrip` | PASS | 1.517 |
| IT | pytest | `integrations/issues_scan.checks.py::check_summary_detail_cli` | PASS | 0.446 |
| IT | direct | `integrations/quicksight-display.checks.py` | PASS | 0.980 |

未実行: 変更不要のUT、上記以外のIT、full、全回帰、全件収集、反復実行・再計測。全ITの実行結果は未確認であり、assert保存の静的結果だけで同等動作の証明とはしない。AWS実環境にはアクセスしていない。今回の失敗を無視したcommit/mergeは行わない。
