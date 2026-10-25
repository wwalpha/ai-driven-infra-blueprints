---
name: issue-fix
description: Investigate existing issues.md for a specified AWS Blueprint environment/target and delegate confirmed Model corrections, Human facts and generated-view synchronization to existing workflows. Excludes Framework/IaC repair and Model/IaC differences.
---

# Issue の調査と修正委譲

`issues.md` を調査の入口とし、現在の Model と根拠を確認してから、既存 Skill と保存・生成・検証 API へ委譲する。これは新しい修正エンジンではない。Framework と IaC は読み取り対象の必要箇所を除き変更禁止とし、Model/IaC 差分は調査・修正しない。

## 入力と対象

- Environment、Target は必須。Service と Issue ID は任意。省略時は指定 Target の全 Service、対象 Service の全 Issue を選ぶ。
- [project-configuration](../../../framework/rules/project-configuration.md#topology) と `project.json` で Environment/Target を一意に確認する。Target directory は alias 優先、なければ awsAccountId。awsExecutionAccountId をパスに使わない。未登録・曖昧な対象は確認が済むまで停止し、別環境へ広げない。
- 入力は `issues/<environment>/<target-directory>/issues.md`。存在しなければ報告して停止し、新規生成しない。`iac-issues.md` は読み込まない。
- 現在の Service 見出しと Issue ID を照合する。ID がない旧記述は Service と項目位置・内容で対象を示し、曖昧な指定や見つからない ID を推測で対応付けない。Issue ID を Resource の固定 ID や diagnostic_id と同一視しない。
- Issue 一覧の読み取りだけなら契約不要。Skill 呼び出しだけで未確定の修正値、例外、識別子変更や次 Task を承認されたとは扱わない。

## 読み込む規約

最初に `AGENTS.md`、[Model sources](../../../framework/rules/model-templates.md)、[Task transition](../../../framework/rules/task-contract.md#task-transition)、[Task boundary](../../../framework/rules/task-contract.md#task-boundary)、[Acceptance contract](../../../framework/rules/task-contract.md#acceptance-contract)、[Retry and stop](../../../framework/rules/task-contract.md#retry-and-stop)、[Issue responsibilities](../../../framework/rules/issues-investigation.md#scope-and-responsibilities)、[Human confirmations](../../../framework/rules/issues-investigation.md#independent-human-confirmations) を読む。

変更前に [Local loop / Validation policy](../../../framework/rules/loop-engineering.md#local-loop)、[Validation scope](../../../framework/rules/loop-engineering.md#validation-scope) と、選択した委譲先 Skill の mandatory/conditional Read および完了条件を読む。Model 修正には [update](../update/SKILL.md) とその正本 [05_update](../../../framework/prompts/codex/05_update.md) の Ordinary Model correction を使う。参照限定操作時だけ [model-retarget](../model-retarget/SKILL.md) と [Standalone reference contract](../../../framework/rules/task-contract.md#standalone-model-reference-retarget) を追加する。

View 同期時は [Properties-first generation](../../../framework/rules/model-information.md#properties-first-updates-and-display-generation)、[Model helper API](../../../framework/docs/model-helper-integration.md)、既存 [sync-model.py](../../../framework/scripts/sync-model.py) の現在の引数・保存ガード、および [Other task completion](../../../framework/rules/loop-engineering.md#other-task-completion) を確認する。Human ファイル保存にも同完了条件を使う。命名問題では [Naming rules](../../../framework/rules/aws-resource-naming.md) と該当 namespace の規則、観測値の問題では [observed-values](../../../framework/rules/observed-values.md) を追加する。

変更 Task の作成・検証・統合は [worktree](../worktree/SKILL.md) に従う。[issues](../issues/SKILL.md) は再報告が明示依頼された別 Task のみで使う。独自 Python/CLI、重複する読み込み・参照解決・修正・保存処理を追加しない。

## Phase 1: 現在の原因を調査・分類する

1. 選択した Issue ごとに、Service / Resource / Property / Issue 内容 / 診断根拠 / Human 判断の要否 / 修正対象ファイル / 修正可能性を整理する。Issue が集約している対象を落とさず、診断件数と Resource 数を区別する。記載時点の根拠と現在確認した根拠を区別し、Issue の記述だけで修正を決定しない。
2. `model/<environment>/<target-directory>/<service>.properties` と実際の parts を `model.sources.load_model` で読む。キーの所在は既存 CLI の `trace <service.properties> <key>` で特定する。既存 `model.references` の usages/incoming/diagnose と Model 検証を必要範囲で使い、固定 Resource/Row/Stack ID、logicalId、placementName、参照先・型・Property、必要な incoming Consumer を確認する。同名や同じ物理値だけで参照先を断定しない。
3. 旧 Model が不正なら、その失敗を示して ordinary correction の `model.sources.edit_base` による候補修正経路を検討する。旧 Model 全体の有効性や旧 identity/layout の不変を通常修正の前提にしない。専用操作の raw 保持比較が必要な場合は `model.sources.raw_model` を使い、その操作の保持条件を守る。読み取り失敗を「問題なし」にしない。
4. `issues` は生成表示の完全同期を検査しない。Model の正当性とは別に、対象を指定した既存の読み取り専用 `sync-model.py` または共通 Validator の同期検証で Markdown/JSON の古さを確認する。生成 View は正本として読まず、保存された表示との差を確認する用途に限る。read dependency だけでは変更権限を得ない。

各対象に次の主分類を一つ付け、理由と不足入力を残す。同じ Issue の Model 修正と付随生成は二重計上しない。

| 分類 | 次の処理 |
| --- | --- |
| Human 判断が必要 | Phase 2 の選択肢を提示し、未承認の変更は保留 |
| Model 修正可能 | 値・参照先・影響・権限が確定した場合のみ Phase 3 |
| Markdown/JSON 同期可能 | Model が正しく表示だけ古い場合に Phase 4 ケース B |
| Framework 起因の疑い | 再現条件、該当 API/診断、根拠を報告して修正しない |
| 未確定・修正不可 | 欠ける根拠、未対応の形式、失敗したチェックを報告 |
| 対象外 | 選択範囲外、現在は原因が存在しないもの、正常な待機等を理由付きで報告 |

`PENDING_DEPLOY`、正常な deferred/excluded、Warning だけを根拠に自動修正しない。欠落・空文字・PENDING_DEPLOY を同一視せず、未実行/比較不能を一致としない。Model/IaC 不一致は入口で対象外と説明し、上記の分類・修正件数から除外して別途件数を示す。差分の方向判断や IaC 比較のための Scan を開始しない。

## Phase 2: Human の判断を確認する

Human 判断が必要な場合は、次を含む選択肢を提示する。同一原因かつ同一判断で解消する複数 Issue は対象を全て列挙してまとめる。

- 対象 Issue、Environment/Target/Service/Resource/Property、現在の値または参照先。
- 具体的な問題と現在の診断根拠。
- 修正候補それぞれの変更後の値・参照先、副作用と影響 Consumer/ファイル。
- 「保留（変更しない）」の選択肢。

回答がない、曖昧、または候補を確定できない場合は保留する。承認済み内容に追加の推測を混ぜず、承認済み範囲の同じ操作への再承認は求めない。設定値の確定と例外による診断除外は別の判断として確認する。

**A. Model 設定値が確定した場合:** exact Resource/Property と変更前後・影響を明示して `update` の Ordinary Model correction に渡す。必ず Model-only の `design` / Workflow `update`、AWS API execution と deploy/apply は `forbidden`。Infrastructure 分岐へ進まない。

**B. Human 確定事実・例外の保存を依頼された場合:** 独立して承認された `migration` Task だけで `issues/<environment>/<target-directory>/human-confirmations.yaml` を変更する。Model 修正 Task に混ぜない。schema v2 の version/environment/target/confirmations と、各 confirmation の id/service/fact/scope.resource/scope.property/exceptions/evidence を使う。例外の rule/diagnostic_id/condition は現在の構造化診断と正確に一致させる。既存の確定事実を保持し、変更・削除も明示承認範囲に限る。未承認の例外、wildcard、推測の identity、Issue 履歴・実行結果・生成 runtime 値を保存しない。既存 strict YAML reader で検証し、欠落・不正版を自動移行しない。

確定事実だけで診断が除外されたとは扱わない。構造化 identity/Rule/diagnostic_id/condition が一致しない例外や矛盾は未解決のまま示す。CodeBuild PLAINTEXT の Resource リンク禁止など確定的な仕様違反を任意の Human 例外で無効にしない。

## Phase 3: Model 修正を委譲する

対象例は Resource 参照不整合、logicalId と参照の不整合、必須 Property/Name Tag 不足、適用される命名規則違反、CodeBuild PLAINTEXT Resource リンク違反。いずれも次の四条件を満たす場合だけ修正する。

1. 正しい値または固定参照先が現在の根拠で確定している。
2. 対象 Resource/Property、実ファイルと Consumer への影響が特定できる。
3. Human 判断が必要な変更は具体的な内容が承認されている。
4. 選択した Task がその Resource とフィールドの変更を明示的に許可している。

通常は `update` の guarded edit API に委譲する。CREATE/IMPORT の双方が対象で、AWS 再取得はしない。Resource 削除・統合・置換、未承認の識別子変更、observed の推測変更は行わない。Name の不足・命名違反や PLAINTEXT 違反から正しい置換値を推測しない。観測値の取得や AWS 上の Resource の取得・更新が必要なら未対応範囲として返し、`import` や `aws-check` を自動開始しない。

`model-retarget` は明示承認された参照限定変更で standalone `import-retarget` 契約を満たす場合だけ使う。`update` が同一 worktree に running design/update 親契約、正確な Model reference changes、両 producer と consumer の scope を登録し、その全宣言を leaf の一回の guarded save に渡す。既存 IMPORT producer 間の完全な value/document scalar 参照変更に限り、JSON pointer や反復 Property は契約の正確な指定を使う。設定値・observed・producer・固定 ID・非宣言参照を保持する。partial string、構造 parentReference、存在しない producer や他の設定修正をこの leaf に流さない。条件外は権限内の ordinary correction を検討し、根拠や承認が足りなければ保留する。leaf は親に返し、生成・完了・統合を独自に実行しない。

## Phase 4: Model を正本に View を同期する

### ケース A: Model 修正を伴う

同じ `update` Model-only design Task で、正本の修正後、既存 guarded generation API により必要な Markdown/JSON を生成し、対象 Service と必要な Consumer を検証する。source save の成功と View 生成・最終検証の成功を分けて扱う。生成だけで Model 修正完了とはしない。完了/統合の順序は選択した update 分岐と worktree に従い、専用 Model-only final-candidate 経路に独自の二重完了・二重 final loop を加えない。

### ケース B: Model は正しく、View だけ古い

1. 現在の Model が正しいことと対象 View の同期差分を既存検証で確認する。現在の Task 契約と保存ガードが View-only `migration` を許可するか、実装を読んで先に確認する。`issues_save_only()` の報告専用例外を流用しない。
2. 承認済みの View 同期専用 `migration` Task を登録する。Modified files/Allowed paths は exact 生成先と自契約のみ、Validation scope は対象 Service と必要な Consumer。Model 入口/parts は読み取り専用とし、変更前の原文 bytes と file set を保持する。
3. Task を `BLUEPRINT_TASK_FILE` で明示し、既存 `sync-model.py --write --environment <environment> --alias <alias> --service <service-id>` を使う。alias なしは `--aws-account-id <awsAccountId>` に置き換える。同一対象の複数 Service は `--service` を反復する。managed worktree の全 Python 実行は `python3 -B framework/scripts/run-python.py -B` 経由にする。無指定の全件生成や `--all` へ広げない。
4. 生成後、Model 原文・parts 集合と内容が変更されていないことを確認し、既存の同期検証と migration の必須検証を実行する。

View-only 契約・生成・保存が拒否されたら、その理由と未対応範囲を示して停止する。Framework、Task type、権限、ガードを変更して通さない。Model のダミー変更、generated Markdown/JSON の手編集、独自の生成・保存経路は禁止する。

## Phase 5: Task と worktree の境界

- Model 修正は `update`、条件を満たす参照限定修正はその親から `model-retarget`、Human ファイル変更と View-only 同期はそれぞれ独立した承認済み `migration`。Task type/Goal が異なる作業を混ぜない。
- 各変更 Task は `worktree` の管理下で最初の repository 変更として登録する。自契約、実際の入口/parts、生成物、必要な変更 Consumer の exact paths を Modified files/Allowed paths に登録し、影響 Consumer を Validation scope に含める。読み取りだけの producer を書き込み対象にしない。
- 同一責務・同一スコープで一括対応できる Issue はまとめる。Resource ごとに不必要な Task/worktree/commit を作らない。
- 調査・候補整理は次 Task の実行許可ではない。既存契約が許さない次 Task は自動開始しない。別の Goal/種類への移行が必要なら、今回の範囲と次の具体的候補を示し、既に明示された承認がなければ待つ。完了後に別 Task や次フェーズへ自動移行しない。
- 編集を終えてから生成・検証を実行する。同一 worktree の入力・契約・生成先を並行編集せず、publication lock、最終入力比較、rollback を既存 API に任せる。入力変更を検出したら保存を止め、外部変更を保持する。

## Phase 6: 検証と完了

委譲先の Validation policy と Task 固有の必須検証を全て満たす。対象 Issue の現在の原因解消、修正後の Model identity/参照/placementName、Markdown/JSON 同期、必要な Consumer、Human 承認との一致、変更 scope を確認する。差分で Framework・IaC と両 Issue 報告ファイルが変更されていないことも確認する。必須検証が Model/IaC 診断を出しても修正対象には追加せず、診断を隠して PASS にしない。

検証失敗・未実行・未確定を修正済みと報告しない。自 Task の suspend/理由記録、保持・再開・retry/stop は既存規約に従う。source save 済みでも生成失敗や final validation 失敗ならその状態を明示し、完了/統合しない。

`issues.md` と `iac-issues.md` は直接更新・削除しない。修正後も元の Issue 記述は残る。全件報告の再生成は、Human が別途明示依頼した `issues` Task に委譲し、その全 Target Snapshot/Review と報告専用契約に従う。issue-fix 内から Scan/save を自動実行しない。

## 結果報告

対象 Issue 単位で重複しない最終分類を集計する。集約 Issue の対象数と診断数は必要に応じて別記する。Human 確定と修正の両方を行った Issue は「Human 確定・反映済み」に一度だけ計上し、保存だけで原因解消未確認なら修正済みには含めない。

| 分類 | 件数 |
| --- | --- |
| 修正済み | N |
| Human 確定・反映済み | N |
| Human 判断保留 | N |
| Framework 起因の疑い | N |
| 未解決・修正不可 | N |
| 対象外 | N |
| 検証失敗 | N |

修正済み項目は Issue / Service / Resource / Property / 変更前後・変更内容 / 使用 Skill を示す。Human ファイル保存のみの結果、source/View/検証/統合の実施状態、除外した Model/IaC 差分件数、Framework 疑いの根拠、未実施範囲・残存リスクと必要な次の Human 判断もチャットで報告する。恒久的な実行履歴や独自 sidecar は作らない。

## 禁止事項

`framework/**` と IaC の変更、Model/IaC 差分の修正、AWS API 実行・更新・Deploy/Apply、未承認値・識別子・参照先・observed の推測補完、Resource 削除・統合・置換の自動実行、生成 Markdown/JSON の直接編集、Issue 報告の手修正、既存契約・検証ガードの迂回、重複する Python/CLI 修正エンジン、Legacy 互換処理の追加を禁止する。既存機能で実現できなければ代替実装を追加せず、制約と未対応範囲を報告する。
