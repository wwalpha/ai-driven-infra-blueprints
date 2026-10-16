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
python3 -B framework/scripts/run-python.py -B framework/scripts/tests/integrations/quicksight-display.checks.py
```

`pytest.ini`は既存のpytest型ファイルと`*-unit.checks.py`を対象にする。全UTがpytest型ではない。`array_display`、`aws_mapping_catalog`、`check-deploy-context`、`cloudformation_schema`、`comparison_core-unit`、`script_loader`、`update-catalog-lock`、`validation-units`には直接実行の入口がある。`validation_checks/*.py`は同じ分類のaggregatorから呼ぶ。`test_issues_iac.py`は既存unittestメソッドをpytestでも収集する。

`blueprint-loop.py`の既存チェック発見は`*.checks.py`を再帰探索する。依存選択は従来のsuiteに対応する分割UTも含める。共有fixtureや不明な依存に対する全回帰へのfallbackは維持する。
