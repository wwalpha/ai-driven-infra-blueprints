# Framework tests

テストは検証責務で分類する。ケース一覧、現在の配置、パラメータ数、直接実行の検証地点は [CASES.md](CASES.md) を参照。

- `units/`: 単一関数・クラスの変換、比較、判定、入力検証。Framework内部定義と合成fixture、既存Fake/Mockで完結する。
- `integrations/`: Model生成・保存・再読込・同期、サービス間参照、CLI、Git/worktree、Adapter連携。
- `support/`: 共通fixture、loader、pytestの診断補助。UTはITテストモジュールをimportしない。
- `unknown/`: 分類対象を残さない。分類済みかどうかはディレクトリ名だけで判断しない。

## Model Designの責務

`model_design` ITは7関数・7 pytest条件。Endpoint/Route53、IMPORT任意Name、KMS Execution Account、Config異型anchor、Stack/索引Model再読込、複数サービス部分失敗、Dynamic Referenceの実生成を検証する。
部分失敗はVPC/Logs/IAMの正常生成後、IAMだけのMarkdown書込失敗で旧Markdown/JSONと全正本を保持し、独立Logsの成功を確認する。
表示・命名・Schema・Mode・異常値の組合せは既存UTの直接関数呼出しへ集約し、重複保証は再追加しない。
単体表示にはSync、実CLI、Git、全Model生成、全Frameworkコピーやroundtripを使わない。
Task変更・publication barrier・sidecar rollbackはsync-model/Task専用テスト、参照警告はmodel-reference-warnings、Dynamic Referenceの値制約はcloudformation_schemaが受け持つ。
実Path.write_text差替えのself/data/encodingと失敗伝播はfunction_wrapper UTが受け持つ。
旧29関数のassertion対応と登録は [CASES.md](CASES.md#issue-17-model-designの検証責務) を参照。
pytest/direct/module completionとrunner receiptの契約は維持する。

## Worktree責務の分離

Worktree機能自体を検証するレビュー済みケースだけが、実worktree操作とLifecycleのMock/fixtureを使う。
許可は `support/worktree_test_policy.py` のケース一覧で固定し、ファイル名の変更だけでは付与しない。
Model / Import / Deploy / Issues / Validation / CloudFormationの業務テストには含めない。

業務側は `repository_fixtures` の独立した通常Git、または `import_repository_fixtures` のファイルsnapshotを使う。
保存能力は `publication_fixtures` で渡し、実Task検証・入力変更検知・保存・生成・rollbackを通す。
productionの管理所有者確認は維持し、そのfactory/registry境界を専用UT/ITで検証する。
通常controllerはsession内ledgerを実保存し、worktree間の所有登録アダプターだけを置換する。
外部修復のcheckpoint・child・検証・親統合・cleanupは専用Worktree ITが実行する。

全UT/IT/supportの依存を静的にたどり、直接/間接Import・動的fixture loader・worktree Mockを検出する。
pytestと公式IT runnerには実操作/管理書込の実行時guardもある。通常Git init/commit/diffとproductionの
read-only discoveryは許可する。公開Reviewの `worktree` フィールドは証跡の入力データとして保持する。
分類・移動先・assertion対応は [CASES.md](CASES.md#worktree-dependency-separation-master-1024v2) を参照。

Worktree関連5 ITは27関数・29入口。実Git/Worktree、CLI連携、状態の永続化、失敗復旧、独立プロセス間Lockだけを検証する。
入力条件は既存Import/Model/Worktree UTへ集約し、Python decodingとglobal wrapperのIT関数は廃止した。
実venv初回生成・再利用とプロセス間排他を保持する。Fake AWSは既存sleep注入で実時間待機せず、1 controller invokeで100回までの上限・poll・終了・Patch復元を検証する。
削除した内部パターン数、既存UT対応、各IT固有の保証は[削減一覧](CASES.md#worktree-it-runtime-reduction-master-1024v4)を参照。
ローカルで長時間ITや性能比較を再実行しない。関連短時間UT・構文・登録静的整合性を確認し、ITと時間測定は既存Framework ITに委ねる。30%以上の時間削減は実測前には達成扱いにしない。

## 実行入口

リポジトリルートから実行する。管理worktreeでは登録済みPython環境のwrapperを使う。

```console
python3 -B framework/scripts/run-python.py -m pytest framework/scripts/tests/units/model_design-unit.checks.py -q
python3 -B framework/scripts/run-python.py -B framework/scripts/tests/units/validation-units.checks.py
python3 -B framework/scripts/run-python.py -B framework/scripts/tests/units/test_issues_iac.py
```

`pytest.ini`は既存のpytest型ファイル、`*-unit.checks.py`、deploy SDK/client/controller/observed-recoveryの明示したpytest型suiteを対象にする。全UTがpytest型ではない。`array_display`、`aws_mapping_catalog`、`check-deploy-context`、`cloudformation_schema`、`comparison_core-unit`、`cloudformation-inputs-unit`、`script_loader`、`update-catalog-lock`、`validation-units`には直接実行の入口がある。`validation_checks/*.py`は同じ分類のaggregatorから呼ぶ。`test_issues_iac.py`は既存unittestメソッドをpytestでも収集する。

`blueprint-loop.py` の `task` / `local` はProjectのValidation scopeに従って検証し、Framework回帰UT／ITを自動実行しない。通常TaskではFrameworkを不変として扱い、FrameworkファイルのGit差分から回帰テストを選択しない。`full` / `--all` は `units/**/*.checks.py` と `units/**/test_*.py` の全UTを既存のPython直接実行入口で起動する。`full` は既存のProject Validation scopeを維持し、`--all` はProject全体を検証する。Scope `all` だけではFramework UTを実行しない。`blueprint-loop.py` からFramework ITは実行しない。


[Framework IT](../../../.github/workflows/framework-it.yml) はすべてのPRおよびmain/masterへのpushと手動 `workflow_dispatch` で、変更ファイルによる選別をせず全UT・全ITを実行する。ファイル種別による起動除外も行わない。Python 3.12と既存requirementsを使用し、唯一の公式入口 `python -B framework/scripts/tests/run_it.py` が既存schedulerで全UTを最大2並列、その後 `integrations/**/*.checks.py` を独立プロセスで全件実行する。UT失敗後もITを実行し、いずれかの失敗でCIを失敗させる。既存のpytest・直接実行・トップレベル実行方式と手動baseline計測を維持する。

runnerは共通fixture bundleを1回初期化し、`input_templates`・`typed_services`・`generated_policy`・`import_sources` の4 seedを各1回生成する。共有seedは読み取り専用で、可変データはケースごとのworkspaceへ展開する。Framework定義は既存の定義rootを参照する。新しいFrameworkコピー・symlink/hardlinkは作らない。実プロジェクトのModelやAWS認証情報は使用しない。

登録件数とparameter数は `CASES.md` と実収集から照合する。pytestは既存 `PytestReceipt`、直接実行は正常return後の `@it_case`、module型は末尾の `module_complete(__file__)` で完了を確認する。未登録suite、未実行・未完了ケース、不正receipt、非0終了を失敗とする。件数を合格ノルマにしない。


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

## Issues v2 / cfn-lint

issuesの正規APIは `issues/`、Model ↔ IaC比較の入口は `comparison.Comparison`。比較の結果・診断・表示差分は `comparison/` が返し、Issuesが1回集約する。旧 `issues_iac.py` / `issues_reports.py` のwrapperは置かず、CLIだけ `issues_scan.py` を維持する。UT追加は `issues-lint-unit.checks.py` の9関数20条件、IT追加は `issues-lint.checks.py` の8関数14条件。正式ITは既存 `Framework IT` / `tests/run_it.py` だけを使う。固定版1.57.2が無い環境で、CLI同等性・状態隔離の検証を実施済みとは扱わない。

一時HOME/cwd/config/custom rule/provider schemaを実環境から分離し、本物のHOMEとインストール済みpackageには書き込まない。Framework定義はコピーも読取専用。モデル・template・parametersは独立した可変fixtureを使う。summary/detail/saveはv2の保存済み集計だけを使う。


## Deploy correctness / 1023v2

`deploy-runtime-unit.checks.py` は旧controller suiteのrequest/判定/scheduler/差替えsessionケースを保持する。`deploy-sdk.checks.py` は境界内共有と境界間再取得、cleanup中の配送条件変更、削除証拠を検証する。`deploy-observed-unit.checks.py` は条件付き親参照とraw候補探索を、`aws-client.checks.py` は実SDKの一時設定/合成credential、生成排他とpaginationを検証する。API総件数や読込量・120秒判定を合格条件にしない。

`integrations/deploy-controller.checks.py` は実controllerからtarget/Task/CFN loader、guard、SDK service wrapper、scheduler、session保存/再読込とobserved公開を通す。AWS応答をSDK client取得境界で置換し、未定義operationは失敗する。static seedは `fixtures/deploy_controller.yaml` と既存 `fixture_cases` を使い、各ケースが独立Project/cwd/実Git/sessionを持つ。別プロセスresumeはfake AWS JSONとsessionファイルだけを共有する。finallyを通らない終了後のlockは、その子を終了確認したテストだけが明示的に回収する。productionには回収分岐を追加しない。

関連UTは各ファイルの既存直接入口または明示pytestで実行できる。既定収集は `python3 -B framework/scripts/run-python.py -m pytest --collect-only -q framework/scripts/tests`。正式ITは既存のGitHub Actions `Framework IT` jobが `framework/scripts/tests/run_it.py` を実行する。新しいFull IT runnerは追加していない。

## Python品質チェック

`requirements.txt`の固定版Ruffと標準ライブラリだけの構造チェッカーを使用する。

```console
python3 -B framework/scripts/run-python.py -m ruff check framework/scripts
python3 -B framework/scripts/python_structure.py
python3 -B framework/scripts/tests/units/python_structure-unit.checks.py
python3 -B framework/scripts/run-python.py -B framework/scripts/tests/units/function_wrapper-unit.checks.py
```

関数・メソッド内のImportとネスト関数は禁止する。Callbackの状態は明示引数や既存の共有実装で渡す。
`Python quality` WorkflowはPython 3.12でRuffだけを導入し、上記の静的チェックを独立実行する。
共有Python環境の更新は自動実行せず、[明示的メンテナンス手順](../../../.agents/skills/worktree/SKILL.md#explicit-shared-python-maintenance)に従う。
Formatterの全件適用はこのチェックに含めない。

AWS SDKのセッション・接続・設定生成は `utils/aws_sdk_runtime.py` に分離する。SDKを必要とする機能だけが `utils.aws_sdk.aws_runtime()` の `importlib.import_module("utils.aws_sdk_runtime")` を通してこの実装を起動し、オフライン比較のImport時にはSDKを読み込まない。Taskの検証付き状態遷移とWorktreeのModel検証・修復実装も、標準ライブラリだけの起動処理から分離する。

Modelの公開編集・描画APIとCLIコマンド実装も機能モジュールに分離し、読取APIとヘルプ表示では編集・描画実装を初期化しない。Resource構成比較は公開処理に依存しない `model/configuration.py` が共通所有する。


## AWS Profile / Identity

純粋な判定条件は `units/aws-identity-unit.checks.py` の49ケースに集約する。
失敗はIdentity専用の `IdentityError` を直接伝播し、呼び出し側で再ラップしない。
既存のValueError捕捉、CLI終了処理とAccountMismatchレポート分類を維持する。
既存のpytest収集規則 `*-unit.checks.py` と直接入口で実行できる。
各機能UTは共通判定の呼び出しとAWS前の停止、Import例外引き渡し、
複数Target事前確認、SDK cacheとSession再開を担当する。
Model Testは既存ITの隔離Python単独実行とMock STS回数で確認する。
Profile条件表をITへ追加せず、実AWS接続を行わない。


## Deploy controller processing reduction / 1024v4

controller ITは6関数6フロー。Order 10の2Stack配送・成功・実Model反映後にOrder 20を開始する正常系、配送AccessDenied、承認済RemoveのExecute直後中断、Observed公開I/O失敗とpeer drain、Model部分書込からの起動時復旧、署名済外部修復のcleanup中断/再開を通す。複数peerの最終生成物は最終Modelからsync(False)で整合を確認し、古いplanのbytesを最終期待にしない。

`deploy-observed-recovery.checks.py` の1フローは、小さいModel/planとMarkdown/JSONの部分書込journalを使い、実reconcile・所有者検証・publication_lock・復元を通す。controller/AWS/Git/seed/renderer/子processは使わない。小型ITからUTをimportしない。

組み合わせは既存SDK/runtime/observed-resume/handoff UTへ集約し、不足する削除イベント照合、応答喪失と保存状態、guard停止、公開stageのI/O失敗、署名/accept/request/未実行失敗だけ直接呼出しで補強する。旧66条件の主要assertion対応と各入口/展開数は[対応台帳](CASES.md#deploy-controller-processing-reduction-1024v4)を参照。

seed・Project全生成・Git initは各66→6、初期Gitは330→30、Python子processは100→7の静的見込み。小型ITと新規UTの追加子processは0。既存sleep無効化・skip・xfail・timeout短縮やrunner選別を短縮根拠にしない。Worktree normal/mergeは実checkpoint/child/validation/merge/cleanup/親Task再開とコピー結果・再適用・未記録変更拒否を保持し、追加assertionを共有helperから明示的に呼ぶ。

ローカル検証は変更に関連するUTだけに限定する。invokeの共通sleep注入を変更した場合は、それを直接利用する既存UTも確認する。controller IT・小型IT・Worktree ITは修正と静的確認だけとし、IT収集・run_it.py・CI起動・IT時間計測は行わない。将来の正式CIでcontroller単独60秒と関連UT/小型ITを含めた合計を比較する。IT未実行、60秒以内の達成は未計測。


追加レビューでは、公開失敗UTのplanに実行証拠を持たせ、stage別I/O失敗後のplan全体保持とdesign既公開候補の不一致拒否を確認する。acceptの再試行は署名付きsessionの実saveを置換前後で中断し、実diskからrestoreして受理済revision・予約・状態を保持する。controllerのdesign I/O失敗には初回のpeer RUNNING状態を記録し、完了後のSUCCESSだけでdrainを代用しない。この記録のためのJSON読込は当該faultの初回だけで、通常invokeには追加しない。6 controllerフロー・小型IT1本・子process7回の構成とする。

CloudFormation共通処理は`utils/cloudformation/inputs.py`（入力評価・Blocked）、`schema.py`（Schema/キャッシュ/Lock）、`format.py`（YAML/JSON解析）へ集約する。純粋な入力判定は`cloudformation-inputs-unit`、Comparison証跡は`comparison_core-unit`、解析とSchemaは既存専用UTが担当する。

Design共通処理は `../design/`、サービス固有処理は `../design/services/` に配置する。固定定義の正本は `../design/services/definitions/<service>.py`、統合先は `../design/services/definitions/registry.py`。`units/design-definitions-unit.checks.py` は31 Policy形式と全固定定義の不変性・重複拒否・サービス登録漏れを検証する。既存のDesign関連UT/ITは新しい内部importを使い、公開CLIの入口は従来の2パスを維持する。
