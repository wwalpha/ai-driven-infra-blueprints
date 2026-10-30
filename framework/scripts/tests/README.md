# Framework tests

テストは検証責務で分類する。ケース一覧、現在の配置、パラメータ数、直接実行の検証地点は [CASES.md](CASES.md) を参照。

- `units/`: 単一関数・クラスの変換、比較、判定、入力検証。Framework内部定義と合成fixture、既存Fake/Mockで完結する。
- `integrations/`: Model生成・保存・再読込・同期、サービス間参照、CLI、Git/worktree、Adapter連携。
- `support/`: 共通fixture、loader、pytestの診断補助。UTはITテストモジュールをimportしない。
- `unknown/`: 分類対象を残さない。分類済みかどうかはディレクトリ名だけで判断しない。

## UTの重複実行

`issues_scan-unit` のstage/material障害隔離9条件は、実lint計画・結果集約を通し、lint workerだけを合成成功結果に置き換える。
lint起動・失敗・復旧は既存 `issues-lint-unit` と専用ITが担当する。障害隔離の各条件と既存の完了確認は維持する。

CodeBuildのScan/Saveは18→14条件、Scanは36→15回、Saveは32→14回に整理する。
通常表示の6条件を維持し、読取り不能ViewはModel違反の有無・複数変数・所有権違反の4条件、
typed IAM.RoleはModel-only・Markdown-only・両方・所有権違反の4条件で確認する。
読取り不能ViewではMarkdown改変を適用しないため同じ入力となる条件と、既に通る変数数の組合せを削減する。
Issue IDの再Scan/Save安定性はtyped・Model/Markdown両方・2変数の代表1条件が担当する。
全UTの時間比較は同じPython・既存schedulerの最大2並列・同じ収集対象で行い、ログはリポジトリ外に保存する。

## Model Designの責務

`model_design` ITは7関数・7 pytest条件。Endpoint/Route53、IMPORT任意Name、KMS Execution Account、Config異型anchor、Stack/索引Model再読込、複数サービス部分失敗、Dynamic Referenceの実生成を検証する。
部分失敗はVPC/Logs/IAMの正常生成後、IAMだけのMarkdown書込失敗で旧Markdown/JSONと全正本を保持し、独立Logsの成功を確認する。
表示・命名・Schema・Mode・異常値の組合せは既存UTの直接関数呼出しへ集約し、重複保証は再追加しない。
単体表示にはSync、実CLI、Git、全Model生成、全Frameworkコピーやroundtripを使わない。
Task変更・publication barrier・sidecar rollbackはsync-model/Task専用テスト、参照警告はmodel-reference-warnings、Dynamic Referenceの値制約はcloudformation_schemaが受け持つ。
実Path.write_text差替えのself/data/encodingと失敗伝播はfunction_wrapper UTが受け持つ。
旧29関数のassertion対応と登録は [CASES.md](CASES.md#issue-17-model-designの検証責務) を参照。
pytest/direct/module completionとrunner receiptの契約は維持する。

## Importの責務

`import-model` ITは29登録関数・37 pytest条件（変更前47関数・104条件）。Acquire→Review→Publishの保存/再読込、
bind/replace、参照、Atomicity、部分失敗Rollback、Receipt整合性、実Recovery、非選択Resource・他サービス/環境の不変を検証する。
Identity/Scope、Review/Approval、候補差分、参照診断の入力組合せは既存Import UTの直接関数呼出に集約する。
削除18関数と縮小条件のAssertion対応は [Issue 14台帳](CASES.md#issue-14-import-it-responsibility-reduction) を参照。
UTからITのPublication helperやFull fixtureを実行しない。

共有seedの `populate()` は既存Fullのまま。Import ITだけ明示的にFocused（project.jsonと対象dev Serviceの入口/parts）を選べる。
コピー先は独立した書込可能ファイルで、seed生成追加・symlink/hardlinkはない。
Full代表ITと明示構築したCloudTrail/S3参照ITで、Focusedにない他サービス/環境の保護を保証する。
Git/WorktreeとCLI実行境界は既存専用ITに任せ、Import ITのPopen Git禁止・worktree fixture非ロードを維持する。

ローカルでは関連UT・構文・pytest収集・登録/Receipt静的整合性を確認する。ITと性能測定は実行しない。
目標10秒未満と削減対象UT+IT合計時間の非悪化は、公式Framework ITのbaseline_refを使う同条件比較で判定する。
CI実測前に高速化達成と報告しない。Fixtureのコピー削減だけから性能効果を断定しない。

### Import 第2段階の検証

`import-sdk-inventory-unit` は親Scope・複合Identity・全ページ・途中失敗・9型のCoverage到達性、
`import-limitations-unit` はMapping/SDKに基づく取得不能分類、Treatment、秘匿、Bindingと未完了判定を検証する。
`import-model` の `check_limited_acquisition_preserves_values_and_completes` は取得不能項目を含む
Acquire→Review→未承認拒否→既存値保持の提案→再開→Publish→Receipt→Task完了を検証する。
承認は会話上の運用境界で、テストのBindingやFixtureは人間の認証を証明しない。

Framework実装を明示検証する際は既存の公式IT runnerで、関連するImport業務ITとCLI ITを実行する。
業務ITは既存の独立Fixtureとリポジトリ読み取りProviderを使用し、worktreeを作成しない。

### Offline Import Coverage

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py import-coverage --repository-root .
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py import-coverage --repository-root . --format json
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py import-coverage --service quicksight --strict
```

Ownersから動的に全型を列挙し、Model対象判定・取得方式・Identity・include対象の各Propertyを独立に診断する。
SDK Inventory登録、detail envelope、必須Filterの親探索はRuntimeと同じDiscovery定義を使う。
親由来AssociationのreadyはSubnetへの付加取得を意味し、独立Import候補を意味しない。
Identity readyは生成経路の静的成立であり、Discovery失敗やProperties不足を打ち消さない。

Propertyの`capturable`は静的取得経路、`unobservable`は明示された非AWS入力/取得不能値、
`broken`は実装不整合、`uncertain`は未証明の分岐/selector/projectionを示す。
Model/Target入力とlocal_metadataはAWS確認値に数えない。SDKの単純な直接呼出しは実fetch_sdkを読んで
selectorとseedPropertiesを確認し、条件分岐や動的処理は推測せずuncertainを返す。
AdapterもseedされたpayloadのSchema/Pathが証明できる範囲だけcapturableとし、fetchの存在だけでは成功扱いしない。
全結果は`runtimeVerified: false`。AWS認証・通信・Model読込/保存は不要。

同じ実行内でMappingからAdapter/SDK Getterを列挙し、対応FixtureがあるPropertyだけ実Adapter、SDK入力、
SelectorとMapping Pathを検査する。`adapterContracts`は`verified` / `unverified` / `broken`を静的Coverageとは別に返す。
`verified`は列挙したFixture分岐だけのオフライン証拠であり、他の分岐や実AWSの成功を意味しない。
Fixture未作成のPropertyや分岐は未検証のまま残り、証拠は保存・再利用しない。
現在のFixtureはQuickSight VPC接続のDnsResolversとGroupのGroupNameで、Getter全体は他のPropertyが未検証の間は未検証となる。

通常終了は0、`--strict`は未解消のbroken（取得経路不足を含む）があれば1、検証処理/設定エラーは2。
既存の取得未対応型と不確実性を隠さず出すため、strictをCI必須Gateにはしない。
`propertyGapTypes`には不整合だけでなく、明示的な非AWS入力と未証明条件も含む。
固定の型数/サービス数を合格条件にしない。

`import-coverage-unit.checks.py`は小さいメモリ上のMapping/SDK/Schemaと1つのYAML fixtureで判定を検証する。
新しい取得シナリオは追加していない。既存Import UTのSDK呼出し回数、Cloud Control、親Filter、部分保持、
singleflight・Context分離を使って互換性を確認し、Acquire→Review→Publishと実CLIの正式ITは既存CIに委ねる。

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

Deploy repair専用ITは2関数3入口（normal batch/stepsとMerge復旧）。通常修復は両方式の独立Deployと実CLI・fresh Validationまで通し、Merge復旧は正式Requestと実Git FF直後中断・永続State再開・証拠/入力保持・Cleanupを検証する。同じ異常YAMLはbatchだけで一度確認する。Assertionの対応は[責務一覧](CASES.md#worktree-deploy-repair-performance-responsibilities)を参照。進捗/Journalの永続化地点は維持し、性能未計測や10秒未達を達成扱いにしない。

## 実行入口

リポジトリルートから実行する。管理worktreeでは登録済みPython環境のwrapperを使う。

```console
python3 -B framework/scripts/run-python.py -m pytest framework/scripts/tests/units/model_design-unit.checks.py -q
python3 -B framework/scripts/run-python.py -B framework/scripts/tests/units/validation-units.checks.py
python3 -B framework/scripts/run-python.py -B framework/scripts/tests/units/test_issues_iac.py
```

`pytest.ini`は既存のpytest型ファイル、`*-unit.checks.py`、deploy SDK/client/controller/observed-recoveryの明示したpytest型suiteを対象にする。全UTがpytest型ではない。`array_display`、`aws_mapping_catalog`、`check-deploy-context`、`cloudformation_schema`、`comparison_core-unit`、`cloudformation-inputs-unit`、`script_loader`、`update-catalog-lock`、`validation-units`には直接実行の入口がある。`validation_checks/*.py`は同じ分類のaggregatorから呼ぶ。`test_issues_iac.py`は既存unittestメソッドをpytestでも収集する。

`blueprint-loop.py` の `task` / `local` はProjectのValidation scopeに従って検証し、Framework回帰UT／ITを自動実行しない。通常TaskではFrameworkを不変として扱い、FrameworkファイルのGit差分から回帰テストを選択しない。`full` / `--all` は `units/**/*.checks.py` と `units/**/test_*.py` の全UTを既存のPython直接実行入口で起動する。`full` は既存のProject Validation scopeを維持し、`--all` はProject全体を検証する。Scope `all` だけではFramework UTを実行しない。`blueprint-loop.py` からFramework ITは実行しない。


[Framework IT](../../../.github/workflows/framework-it.yml) はすべてのPRおよびmain/masterへのpushと手動 `workflow_dispatch` で、変更ファイルによる選別をせず全UT・全ITを実行する。ファイル種別による起動除外も行わない。Python 3.14と既存requirementsを使用し、唯一の公式入口 `python -B framework/scripts/tests/run_it.py` が既存schedulerで全UTを最大2並列、その後 `integrations/**/*.checks.py` を独立プロセスで全件実行する。UT失敗後もITを実行し、いずれかの失敗でCIを失敗させる。既存のpytest・直接実行・トップレベル実行方式と手動baseline計測を維持する。

runnerは共通fixture bundleを1回初期化し、`input_templates`・`typed_services`・`generated_policy`・`import_sources` の4 seedを各1回生成する。共有seedは読み取り専用で、可変データはケースごとのworkspaceへ展開する。Framework定義は既存の定義rootを参照する。新しいFrameworkコピー・symlink/hardlinkは作らない。実プロジェクトのModelやAWS認証情報は使用しない。

`worktree-deploy-repair.checks.py` の batch、steps、Merge復旧は、各ケースを独立Pythonプロセスで同時実行する。各プロセスは全ケースを収集して固定された3 node IDとの一致を確認し、指定ケースだけを実行する。親は正常終了とケース別Receiptを検証して一つに統合し、既存の台帳到達性検査に渡す。一時領域と検証キャッシュはケースごとに分離し、共有Fixtureは読み取り専用とする。失敗・中断時は残存プロセスを停止してケース別ログを保存する。baselineと他のスイートは従来の実行経路を使う。

登録件数とparameter数は `CASES.md` と実収集から照合する。pytestは既存 `PytestReceipt`、直接実行は正常return後の `@it_case`、module型は末尾の `module_complete(__file__)` で完了を確認する。未登録suite、未実行・未完了ケース、不正receipt、非0終了を失敗とする。件数を合格ノルマにしない。


全関数・全行の監視は使用しない。ファイルコピー・子プロセス・fixture生成のauditイベントと、スイート別の時間・終了コード・receiptを維持する。FAIL後も残りのスイートを実行し、結果をActionsログとSummaryに記録する。追加のFull IT実行入口は設けず、`blueprint-loop.py` の回帰はUTのみとする。

手動実行の `baseline_ref` は同じrunnerで旧コードの終了コードと時間を測定する。旧baselineには完了マーカーや台帳を要求せず、ケース到達性は「未検証」、旧profiler由来のfixture要求数・生成数は「比較不能」と明示する。依存パッケージが異なる場合は比較を拒否する。検証内容・スイートの同一性が確立していない時間差を、同条件での性能改善とは扱わない。

ローカル修正では関連UTを実行し、ITの検証はGitHub Actionsへ委ねる。PRの現revisionでIT PASSを確認してからマージする。CI未完了・未実行・キャンセル・FAILをIT検証完了と扱わない。ブランチ保護のRequired status checkに `Framework IT` を指定する設定は別途必要。

契約の選択・通常の状態遷移・公開時の変更検出を既存UTで確認する。実Git、Atomic rollback、finalize/cleanupの安全停止は既存ITで検証する。予約と独自worktree identityだけを検証するケースは廃止した。

Sync Model ITは20関数・28 pytest条件（旧25関数67条件、今回開始時のmasterは20関数27条件）。実Stage/定義共有・cold並列worker・CLI・複数Service・候補Validation・Publication・Rollback・Recoveryを保持する。
入力差分、Cache、Git正味差分、Task境界、出力形式、Property判定、集計条件は直接UTへ集約する。対象UT3ファイルは合計84→137条件（sync-model 34→69、model_design 46→59、validation_cache 4→9）。
UTで実Sync、Git初期化/commit、全Model生成、Framework全体コピーを行わず、既存の小さい合成入力/fixtureを利用する。Framework読取例外はMockで注入し、定義ファイルを変更しない。
Snapshotの12差分条件は既存check_snapshot_conflictへ集約し、Sync UTは28関数69条件。project change/deleteは既存check_snapshot_project_common_inputsがsealed bytesと外部変更保持まで確認する。Stage代表ITはModel不整合とリンク破損を別々にassertし、Table Schemaは直接UTで実Table Validatorまで呼ぶ。
read-onlyのView欠落拒否も既存check_missing_validation_inputsへ補い、Model欠落とは別条件で非生成と入力不変を確認する。
Validator正常ITは新規生成/既存更新の2条件を維持する。欠落からのMarkdown/JSON生成とoriginals=None、Markdownだけの更新と旧bytesの受渡しを区別し、両方で保存後Acceptance・正本保護を確認する。
PassCacheは同一呼出し内だけ再利用する。別Validatorの生成省略を期待せず、freshと入力変更後の失効は直接UT、候補結果からAcceptanceへの再利用は既存CheckResult UTが保証する。
共有generated_policy seedと既存pytest入口・receipt・reachabilityを維持する。旧67条件のAssertion分類、削除/統合理由と各ITの固有保証は [CASES.md](CASES.md#issue-15-sync-model-itの責務再編) を参照。
ローカルでは関連UTと構文/parameter数/登録を静的確認し、IT本体・時間計測・cProfileは実行しない。直近成功CIの13.37秒は1024v9自体の測定値ではない。10秒以下の達成とIT PASSは、変更後の既存Framework ITでの確認待ち。

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

## Issues Artifact v5 / Immutable Snapshot / cfn-lint

issuesの正規APIは `issues/`、Model ↔ IaC比較の入口は `comparison.Comparison`。比較の結果・診断・表示差分は `comparison/` が返し、Issuesが1回集約する。旧 `issues_iac.py` / `issues_reports.py` のwrapperは置かず、CLIだけ `issues_scan.py` を維持する。現行 `issues-lint-unit.checks.py` はlint/Artifact境界を、`issues-lint.checks.py` は4関数5条件の接続を検証する。旧report notice保持UTはSnapshot UTへ置換した。正式ITは既存 `Framework IT` / `tests/run_it.py` だけを使う。CLI同等性・状態隔離の検証結果は実行時に使用したcfn-lintについてのみ適用する。

ITは実行環境のCLI一致（正常/異常の各代表1件）、Worker設定隔離、schema障害と新Worker復旧、実OS Timeout回収の4契約。
設定隔離の4連続要求でHOME/cwd設定、custom ruleの状態、registry/overrideの再読込、NoEcho、output非書込をまとめる。
Scan→Lint→Artifact→Review→Saveと入力変更後の保存許容の実接続は既存 `issues_scan::check_scan_publish_mismatch` に一本化し、重いケースを他suiteへ追加しない。
View障害別分類・独立Service継続・非Cache・入力変更許容は `issues_scan-unit`、設定/入力/schema分類・期限/protocol/fatal・終了エスカレーションは `issues-lint-unit` が受け持つ。
全旧assertionと削除/移管先は [Issue 21対応表](CASES.md#issue-21-issues-lintの検証責務) を参照。

要求は `time.monotonic()` の一つの期限で管理し、固定5秒猶予と無期限readlineを使わない。
既存progress packetを中継し、断片stdoutでも期限を守り、取得済み診断をTimeout/異常終了後も保持する。
正常EOF終了待ちと強制回収を分け、専用sessionのWorker/childだけをTERM→残存時KILLで回収、join/wait後にpipe/handleを閉じる。
IT fixtureは30秒sleepを廃止し、起動確認後0.2秒の要求期限でTERMを無視する実childも回収する。起動確認はfixtureだけでproduction protocolは追加しない。
Windowsは既存 `--once` と実OS subprocessのtimeout/回収、UTのprogress/protocol契約を維持する。

Issue 21のローカル確認は関連UT・構文・collect-only・登録/参照の静的整合性だけ。IT/Full IT・AWS・Actions手動起動は禁止。
51.079秒から10秒以内の目標はGitHub Actionsの実測待ちであり、未測定の時間やIT PASSを報告しない。

一時HOME/cwd/config/custom rule/provider schemaを実環境から分離し、本物のHOMEとインストール済みpackageには書き込まない。Framework定義はコピーも読取専用。モデル・template・parametersは独立した可変fixtureを使う。summary/detail/validate_artifact/save_scanはv5専用で、未対応versionを拒否する。summary/detail/saveはv5の保存済み集計だけを使う。


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
`Python quality` WorkflowはPython 3.14でRuffだけを導入し、上記の静的チェックを独立実行する。
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

## check-model-aws の責務 (Issue #20)

全52 Adapter Resource Type、全supported field、ID/ARN/NameとAPI trace/cache、
27サービス×4比較状態は `units/check-model-aws-adapter-unit.checks.py` が実Adapterと比較関数で検証する。
`SchemaOffline` はBotocore Service Modelを実行内再利用し、API名・入力・応答をSDK Schemaで検証する。
応答はSchemaと既存PATCHESから生成し、MappingのField Pathは生成入力に使わない。
boto3 Session/Clientは不要。新Fixture自体の拒否条件・分離・cacheは専用fixture UTが検証する。
既存Offline/Stubberは維持し、ITはcommon/associations/batch/cli/stacks/cfn-identity/coverageの7 callback、
pytest8条件（consumer条件付き入口を含む）で実コンポーネント間の接続とSDK paginatorを担当する。
分岐・異常入力・比較値の組合せは既存check-model-aws UTへ移管した。
assertion移管と重複削除の対応は [CASES.md](CASES.md#issue-20-check-model-aws-responsibility-separation) を参照。
ローカルでは関連UTとIT構文/import/登録の静的確認だけを行い、IT実行・時間計測は行わない。
CIの10秒目標は、後続の同一条件測定で判断する。異なる環境のwall時間から改善率を計算しない。

## Blueprint Loopの責務

ITは7条件。実CLI→Validator、子プロセス・heartbeat・並列同期、対象Taskだけのsuspend、実Git staged snapshotの隔離・stale拒否、失敗後の後続と診断を保証する。
正常Model/Designと失敗時の入力は共有generated_policy seedの独立コピーを使い、Sync CLIを起動しない。
モード・引数・authorization・startup診断11条件・Windows guard・snapshot finallyは既存UTへ統合する。
全assertionの対応先は[Issue 18台帳](CASES.md#issue-18-blueprint-loopの検証責務)を参照。
ローカルでは関連UTと静的確認のみを実行し、ITのPASSと10秒以内の達成は正式CIで確認する。

## Pending environment Values

`units/environment_values-unit.checks.py` owns Mapping metadata and parser combinations,
CREATE/IMPORT permission, pending restrictions, requested-attribute resolution, typed
encoded JSON, granular desired comparison, display preservation and the Stack input guard.
Synthetic snapshots connect the existing candidate guard, reference resolver, comparison
runner, decoded-input cache and scheduler; they use no real Project Models, Git setup or AWS.
CodeBuild's existing suite retains its PLAINTEXT/link policy and validation isolation tests;
its unrelated synthetic Id is a confirmed fixture value rather than a forbidden desired
PENDING_DEPLOY. Existing component IT remains in the normal CI runner; local execution is
limited to related UT, syntax/registration, scoped validation and repository-wide Ruff.

## Common Model Reference nodes

`units/model-reference-nodes-unit.checks.py` is the dedicated typed-node UT. It uses only authored
synthetic properties and the existing catalogs/evaluator/graph. Run with the registered Python
wrapper and the existing script entrypoint. `integrations/model-reference-nodes.checks.py` adds
one artifact/Markdown round-trip to the official IT runner; do not run it locally.

Desired stores exactly `{"$modelRef":{"logicalId":"…","attribute":"…"}}`. Producer lookup is
limited to the Consumer's environment/target and rejects duplicate logical IDs. `design_document`
retains authored JSON. Both `render.generate_files` and batch `sync_runtime.generate_views`
use `generated_document` for JSON Views: resolved references become values, pending references
become PENDING_DEPLOY, and unresolved references retain their declarations with diagnostics.
Markdown keeps the existing display contract, anchors and links. Pending and unresolved Views
can generate and publish with PASS while retaining unverified reference information. Invalid
references still fail only their service and retain saved views. Strict generation inspects
inline structured values with the same View contract; it does not certify AWS readiness.
Saved policy JSON is compared against the same projection. The independent AWS input boundary
and Deploy's IaC/physical-value checks remain unchanged.

`utils/arn_values.py` owns ARN assembly for comparison and Model resolution. `ARN_SHAPES` and
`ARN_DEFAULTS` remain the sole format/default definitions; service component guards live in
`utils/arn_components.py`. Confirmed desired names (including CREATE S3 BucketName with no
observations) can resolve ARNs. Generated IDs require confirmed observations. Region/account
come from the selected Project target and Partition from the offline SDK region catalog;
no AWS existence check or acquisition occurs. Desired/observed conflicts fail resolution.
Explicit CREATE PENDING_DEPLOY retains `pending_deploy`; missing observations alone prove
neither pending deployment nor absence. The result carries `resolved`, `pending_deploy` or
`unresolved` and a reason. Markdown delegates to this same resolver.

`units/arn-values-unit.checks.py` owns assembly formats/defaults/context/generated-ID guards.
`units/model-reference-values-unit.checks.py` owns Model value resolution, concrete artifact
and display/content equality, encoded JSON, diagnostics, authority preservation, per-service
failure isolation and the existing dependency graph's propagation after BucketName changes.
Generated artifacts are compared structurally with logical Model documents; Markdown uses
the existing display projection. JSON View projection is checked with resolved, pending and unresolved values.
No derived document hash or resolved ARN is saved into authority.
No automatic Model migration is provided. LLM migration must prove the producer and attribute
and change only the proved expression under a separately authorized Model Task.

## Framework IT→UT移行（74252f5）

開始時の実数はIT 76 suite / 313登録 / 431条件、移行後は68 suite / 236登録 / 311条件。
指定6 suiteに加えてDesign Document/Route53 Import Expressionを削除し、サービス契約13補助登録とValidator補助10登録を整理した。
値/型/Schema/Enum/比較/警告/Cacheの細かな条件は既存UT内の直接検証に置く。UTファイルやRunnerは新設しない。

全68残存ITの境界、追加UT、削除根拠、Phase結果は[CASES.md](CASES.md#framework-it-to-ut-migration-74252f5-baseline)に記録する。

ITは実CLI、複数保存Model/環境の参照と依存Snapshot、実Git/Worktree、Task/Controller、Publication/Atomicity/Recoveryを所有する。
保存前の失敗遮断と旧bytes保持、実複数workerやプロセス間の隔離は、それぞれの実経路で検証する。
Validatorの入力補助はUnit aggregatorから呼び、framework-input-isolationは消費側Taskの実dispatchだけを呼ぶ。
Terraform未導入による正常return/完了Receiptは認めず、実CLIを検証できなければFAILとする。

ローカルは全UT・Ruff・Python構造規約・pytest収集・Inventory/Assertion Guard・scoped Validatorまで。
Full IT、長時間IT、ITの性能測定をローカルで実行しない。既存GitHub Actions Framework ITの全件PASSで最終検証とする。
移行の構造整合、公式CIでのUT/IT PASS、IT本体10秒以内は別の判定である。時間未測定・未実行・FAIL・skipは達成扱いにしない。

実装候補の[公式CI #137](https://github.com/wwalpha/ai-driven-infra-blueprints/actions/runs/40117696173)でUT 90/90、IT 68/68、236登録のReceipt到達性エラー0を確認した。IT runner本体236.702秒のため10秒目標は未達。開始基準の公式CIはUT/Guard失敗でIT未起動だったため、有効なBefore/After改善率は算出しない。最終Headの判定は[PR #30](https://github.com/wwalpha/ai-driven-infra-blueprints/pull/30)のchecksを参照する。

Issues Snapshot UTは旧inventory merge/state-transition UTを置換する。Scanは必須の
Human確定情報YAMLと今回の診断だけを入力にし、全Target coverageのReviewから
immutable Snapshotを作る。旧Markdown読取り禁止、決定性、Human例外/矛盾、
関連記録だけの許可付き削除、部分Scope拒否、2 report/任意Human cleanupの
Atomic Rollbackを検証する。旧部分保存CLIとそのUT/ITは削除する。


## Snapshot cache / JSON内容検証

固定入力の所有・可変辞書非Cache・行索引は `model-format-v2` UT、参照100回の
同一Snapshot再利用、非参照JSON、文書/Context/除外差分、Candidate/Rollback、
他ServiceのObserved更新・別input_context・返却結果の汚染防止は
`model-reference-values-unit` UTが所有します。入力検証→生成の共有は既存
`model-reference-classification-unit` の固定入力ケースを使います。
`deploy-lazy-inputs` は同世代のValidate Once、Observed後の参照依存検証再実行、
Desired差分、可変入力と別検証呼出しの分離を確認します。

旧JSON派生ハッシュだけを検証した `json-yaml-document-hash-unit` と専用再export
helperは削除しました。共通 `document_sha256` / `fingerprint` の仕様は既存
`json-format` UT、Import承認/封印・Deploy入力固定は各専用UTで維持します。
既存の文書編集/環境間隔離ITはJSON内容と正本traceで検証し、新しいITは追加しません。

共通配列表示は `units/array_display.checks.py` で全カタログの番号・ネスト・JSON/空配列・コメントを確認する。`model_design-unit::check_array_model_projection` はModelからの期待表示照合、元JSON表現/行順の維持、番号/所属/Value/Comment/欠落/追加の不一致とModelなしのエラーを確認する。IAM Policy、CodeBuildの型注釈、Resource linkは既存の関連UTを維持する。

## CloudFormation Export/API reads

`cloudformation-export-resolution` UT owns common Producer identity/status/Outputs, saved Value/Owner comparison, unknown-only discovery, same-boundary sharing and incomplete/ambiguous proof rejection. `aws-client` UT owns Account/Region/API rate budgets shared by eight Threads, single-attempt read transports, Throttling backoff/jitter, deadlines and complete pagination. Caller UTs retain Delivery/Create/Execute freshness, existing dependency graph (direct/transitive/planned/shared Producer/cycles/diamonds), Output/No Change/Recovery, Repair, Secrets ownership/idempotency and Destroy Resume/order/scope guards. Destroy preflight Outputs replace full list-exports; only scoped Exports receive list-imports. All fixtures are offline; local UT success does not prove live AWS throughput or deployment success.

## Logical design JSON and AWS execution

Existing reference node/value/classification UTs cover pending and confirmed design nodes,
mixed/encoded literals, stable repeated generation, invalid references and strict View generation.
Policy/display/schema UTs retain independent literal validation and saved artifact equality.
`json-format` and `cloudformation-inputs` UTs reject internal nodes before AWS submission,
including encoded JSON in Templates and Parameters, while permitting ordinary CFn expressions
only in template context. Existing sync-model IT owns pending JSON publication, Markdown/JSON
write failures and full rollback; the node round-trip IT owns artifact-backed rendering.
Run related UTs, scoped validation and repository-wide Ruff locally; long/full IT and live AWS
remain separate checks.

Dependency index tests require sealed v3 with an integer version. Legacy or invalid versions are rejected for publication, updates, inventory and Deploy; missing-index bootstrap remains separate. The offline `model/cli.py index --repository-root <root>` rebuild derives v3 from Model sources without trusting old edges. See [CASES.md](CASES.md#dependency-index-v3-only-issue-49).
