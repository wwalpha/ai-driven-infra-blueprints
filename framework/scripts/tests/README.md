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

`blueprint-loop.py` は `units/**/*.checks.py`（59スイート）と `units/**/test_*.py`（既存unittest 1スイート）を、既存のPython直接実行入口で起動する。合計60 UTスイート。`full` / `--all` も回帰部分は全UTのみで、validatorのScopeや安全制御は維持する。`task` / `local` の自動回帰もUT限定。元々回帰不要のScopeではUTを追加しない。

`--affected` は従来の依存マッピングと分割UT対応を適用してからUTだけを抽出する。共有・不明・欠落依存は全UTへfallbackする。`--staged` は同じ選択を固定snapshot内で行う。全UT選択時のWindows認証、UTF-8、診断ログ、失敗伝播を維持する。

IT全68スイートは [Framework IT](../../../.github/workflows/framework-it.yml) がPR、main/masterへのpush、手動実行で検証する。Python 3.12と既存requirementsを使用し、唯一の公式入口 `python -B framework/scripts/tests/run_it.py` が各 `integrations/**/*.checks.py` を独立プロセスで起動する。既存のpytest・直接実行・トップレベル実行方式を維持する。

runnerは共通fixture bundleを1回初期化し、`framework`・`input_templates`・`typed_services`・`generated_policy`・`import_sources` の5 seedを各1回生成する。共有seedは読み取り専用で、変更領域は各ケースに独立したコピーを渡し、実行後に内容と権限の整合性を確認する。実プロジェクトのModelやAWS認証情報は使用しない。

`CASES.md` のIT登録は370実行入口・588条件（pytest 234関数、direct 117関数、direct_group 13入口、module 6末尾）。UT登録は397実行入口・959条件。削除分は260登録・590条件から255登録・585条件への減少で、既存の未登録142件とparameter件数1件の訂正を別途反映した。sync-modelのpublication boundaryはmappingを除いた6条件。model_templatesは9条件。pytestは既存 `PytestReceipt` で収集・PASS・パラメータ数を照合する。直接実行117関数と13のmain入口は最外側の `@it_case` が正常return後だけaudit完了イベントを発行し、module型は末尾の `module_complete(__file__)` で完了を通知する。同一ケースの複数回呼出しは独立ケース数に加算しない。未登録スイート、記録対象でない入口、未完了ケース、欠落・不正receipt、非0終了コードは失敗とする。

Model v2 移行専用の10関数・23条件と固定旧Framework checkout・専用Python環境は撤去済み。現行機能の15関数・82条件は既存3 ITへ統合し、ケースID・assertion・parameter matrix・pytest receiptを保持する。

全関数・全行の監視は使用しない。ファイルコピー・子プロセス・fixture生成のauditイベントと、スイート別の時間・終了コード・receiptを維持する。FAIL後も残りのスイートを実行し、結果をActionsログとSummaryに記録する。追加のFull IT実行入口は設けず、`blueprint-loop.py` の回帰はUTのみとする。

手動実行の `baseline_ref` は同じrunnerで旧コードの終了コードと時間を測定する。旧baselineには完了マーカーや台帳を要求せず、ケース到達性は「未検証」、旧profiler由来のfixture要求数・生成数は「比較不能」と明示する。依存パッケージが異なる場合は比較を拒否する。検証内容・スイートの同一性が確立していない時間差を、同条件での性能改善とは扱わない。

ローカル修正では関連UTを実行し、ITの検証はGitHub Actionsへ委ねる。PRの現revisionでIT PASSを確認してからマージする。CI未完了・未実行・キャンセル・FAILをIT検証完了と扱わない。ブランチ保護のRequired status checkに `Framework IT` を指定する設定は別途必要。

契約の選択・通常の状態遷移・公開時の変更検出を既存UTで確認する。実Git、Atomic rollback、finalize/cleanupの安全停止は既存ITで検証する。予約と独自worktree identityだけを検証するケースは廃止した。

生成・保存の回数、実stage/IMPORT一時領域、Git正味差分、rollback/recoveryは既存ITで検査する。sync-model UTは22条件、model_templates UTは1条件で、対象UTから実生成・Git初期化・publication/recoveryとFramework全体コピーを除去した。共有generated_policy seedは外部definitions_rootを使い、通常ケースはFrameworkを配置しない。ケースの分類と統合先はCASES.mdを参照。

Framework定義（Mapping/Schema/Rules/Catalog/Materials等）はテスト中に変更・追加・削除せず、コピーも同じ内容を維持する。定義変更に依存する条件を削除し、現行定義の読取・メモリ上の入力検証・独立した読取例外、Model/Task/生成物の変更と保存保護は維持する。削除・部分削除・Fixture整理と台帳件数の差分は [CASES.md](CASES.md#framework定義不変による削除) を参照。

## 静的Fixture

静的データはchecksファイルごとに最大1つの `fixtures/<name>.yaml` にまとめる。
静的データがないchecksにはYAMLを作らない。共通APIは
`support.fixture_cases.load_suite(name)`、`load_case(name, case_id)`、
`materialize_files(root, files)`。`yaml_values.yaml_read()` で厳格に読み込み、
解析済みデータをプロセス内でキャッシュし、呼出元には独立したコピーを返す。

schemaは `version: 1`、必須の非空 `cases` mappingと省略可能な `base`。
各sectionは任意の `data` mapping、相対パス→テキストの `files` mapping、
必要な場合だけ `expected` を持つ。値はmapping/list、文字列、有限数、bool、null。
suite名とcase IDは小文字英字で始まる英数字（区切りは `-` または `_`）。
`data` / `files` は直下キーだけ上書きし、nested dictionaryはdeep mergeしない。
`expected` はケース指定があれば全体を置換する。

展開先はworkspace内の通常ファイルだけとし、絶対パス、親参照、曖昧なパス、
symlinkと同一ファイルの衝突を拒否する。既存ファイルへの上書きは許可し、
全パス検証後にUTF-8の元の空白・改行をそのまま保存する。
Model正規化・part生成・Markdown改行調整は行わないため、これらが必要な
動的Fixtureでは引き続き `model_sources.write_model()` / `write_fixture_files()` を使う。

初回移行はissues_scanのnaming-target-scopeとmalformed-reportだけ。
resource種別と行は順序付き2要素sequence（種別、property/value行）を保持する。
Model/stack/template/Markdown生成、mock、assertion、状態変更の流れはPythonに残す。
既存IT seedの生成・読取専用管理・独立workspace・receipt契約は変更しない。
loaderのUTは `units/fixture_cases-unit.checks.py`。正式ITと性能の全体比較は
既存Framework ITの `baseline_ref` を使い、未実行のITをPASSとしない。
