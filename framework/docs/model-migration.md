# Model v2: migration, distribution and recovery

この手順は人間が手動配布するためのものです。ツールは consumer へコピーしません。
AWS API、deploy/apply、push は形式変換に不要です。
旧 Framework を上書きする前に、旧正本の完全 export と固定旧 runtime を確保します。
通常 reader に旧形式 fallback はありません。

## 1. 旧版を固定する

旧 Framework の完全 commit hash と、その requirements に一致する専用 Python を保存します。
旧 checkout は detached かつ Framework ソースが未変更のものにします。
新 runtime へ旧 module を import しません。export adapter は旧 checkout とその Python を使い、
`-I` の隔離子プロセスで旧 public reader を呼びます。
旧 reader 本体や Pystache を新しい通常 runtime へ同梱しません。

移行前の consumer の baseline commit を別に固定します。独自 helper、Framework の独自差分、
未コミットの変更、旧 Model と生成物を確認し、無関係な作業を移行候補へ混ぜません。
元の checkout を保持し、同じ baseline の独立 worktree を使って切り替えます。
バックアップは元の bytes・ファイル集合・mode を復元できる形式で外部領域に置きます。
取得中・保存中の処理を終了し、未完 journal がある場合は旧正本の通常回復を先に完了します。
export が未完 journal を検出した場合、export は未開始として停止し、読込で自動復元しません。

## 2. 上書き前に完全 export する

新 Framework の export adapter を旧 repo の外から使います。旧 repo へ新コードをコピーする必要はありません。
以下の `<...>` は作業者が固定値で置き換えます。出力先は新規の外部パスです。
macOS の `/tmp` 等の symlink は解決した実パスを使います。

```console
python3 -B <new-framework>/framework/scripts/model/cli.py migration-export --old-checkout <fixed-old-framework> --old-python <old-python> --source-root <unchanged-old-model-root> --revision <full-old-framework-commit> --output <external>/export.json
```

旧 runtime の requirements を一致検査し、export 全体の外側で旧
`publication_lock(read_only=True)` を取得します。
開始・終了の入力ファイル集合と hash、旧 Framework の同一 revision を確認します。
export は全 desired／display／observed、固定 identity、Stack placement、native JSON、表示順序、
参照 identity・形式・Property・label・使用位置、欠落／空／未観測を含みます。
旧 tpl の技術的 provenance は監査情報として残し、新正本に必要な参照の意味と分離します。
consumer.environment は旧変数を実値へ展開するだけで、参照宣言や位置追跡 marker を生成しません。
名前・タグ・JSON 内の環境名も保持します。consumer.executionAccountId と Resource／Stack の参照は保持します。
廃止した環境名参照を含む旧 export は入力検証で失敗します。固定旧 runtime と変更前の入力から
export と候補を再生成し、対応する snapshot／Review／証跡も作り直します。暗黙の読み替えはしません。

値・参照の意味を表現できる既存 WARNING は保持します。
`Expansion.complete=False` だけで一律停止しません。
未知式、未展開値、失われる identity、再構成できない参照は具体的な理由を示して停止します。
name／identifier を単なる literal に格下げして成功扱いしません。
無効な Definition や不使用の分岐から Resource を増やしません。

## 3. 外部候補を作り、厳密比較する

```console
python3 -B <new-framework>/framework/scripts/model/cli.py migration-convert --export <external>/export.json --output <external>/candidate
python3 -B <new-framework>/framework/scripts/model/cli.py migration-compare --export <external>/export.json --candidate <external>/candidate
```

候補の出力先は存在しないディレクトリにします。
変換は project の同じ bytes と全 Model を独立候補へ出力し、新 reader で検査してから確定します。
比較は reference、placementName、固定 ID、JSON の型・配列順序、Resource／Row の表示順序まで厳密です。
参照の違いを緩く許す reference_equal は使いません。
結果の `designValidation: not-run` は形式同値だけの証明です。既存の設計／IaC issue は残ります。

## 4. 手動配布 manifest を確認する

完成版 Framework の同じ revision から manifest を作ります。

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py distribution-manifest --repository-root . --baseline <old-framework-commit> --revision <completed-framework-commit> --output <external>/framework-manifest.json
```

manifest の `changes` は個別相対パスごとの add／overwrite／delete、旧新 revision、SHA-256、
bytes と Git mode を含みます。`files` は同じ revision の配布対象全体です。
framework、skills、AGENTS、README、Framework IT 設定、テスト、support、fixture、requirements を含みます。
実行中 checkout の dirty bytes は使わず、固定 commit の blob から計算します。
manifest 自体は repo の外へ保存するため、revision と自己 hash の循環がありません。

consumer 側の before hash が異なるファイルは独自差分です。無条件に上書きせず、内容を比較して
同じ Task の明示的変更へ取り込みます。独自 helper は [接続仕様](model-helper-integration.md) に従います。
追加・上書きだけでなく delete の各ファイルも処理し、旧 CLI／module／env-diff skill の削除漏れを確認します。
空になった旧 Model ディレクトリも除去します。
現行 sync-existing-files の実行だけで配布完了にはしません。
コピー後は `files` の SHA-256・mode と完全なテスト/support/fixture/config/dependency の存在を照合します。
この照合は配布の完全性です。consumer の独自 helper の正常性まで証明しません。

## 5. 形式移行専用 Task を登録する

移行 worktree の変更前に、既存 Task の仕組みで次の限定契約を登録します。
JSON の paths は旧 Model ファイルの削除と新 Model ファイルの追加／上書きの**実際の全変更**を列挙します。
services は export に含まれる全サービス集合です。
baseline は consumer の固定 Git baseline、legacyRevision は固定旧 Framework revision です。
exportPath、oldCheckout、oldPython は repo 外の絶対パスです。

```markdown
## Task contract
- Task type: `migration`
- Task status: `running`
- Workflow: `model-format-migration`
- Model format migration: `properties-v2`
- AWS API execution: `forbidden`
- deploy/apply: `forbidden`

## Validation scope
- `qa/team-a/network`

## Model format migration
- {"baseline":"<40-hex-consumer-baseline>","legacyRevision":"<40-hex-old-framework>","oldCheckout":"<absolute-old-checkout>","oldPython":"<absolute-old-python>","exportPath":"<absolute-export.json>","exportSha256":"<64-hex-export-sha256>","fromVersion":1,"toVersion":2,"services":["qa/team-a/network"],"paths":["<each-exact-old-or-new-Model-path>"]}

## Required changes
- [R1] Model 正本の意味同値な形式移行

## Acceptance checks
- [R1] `check:model.format-migration`
```

同じ Task の Modified files／Allowed paths へ自身の Task と全変更パスを明記します。
Framework 配布も含める場合はその個別変更パスも契約へ追加します。
project、infra、issues は変更しません。dependency detach 契約へ偽装しません。

保存／検証境界は baseline、対象集合、旧新形式、列挙パス、export hash を照合します。
旧 base を専用 adapter から隔離旧 reader で再 export し、保存 export の入力 hash と意味を照合します。
さらに新 reader の全正本と比較します。汎用 force／skip はありません。
既存 issue の停止例外はこの限定的な同値移行だけに適用し、issue の削除・修正を許しません。
最新 local base が固定 baseline から進んだ場合は停止し、新しい export／契約が必要です。

通常の managed worktree 最終候補経路で、その HEAD／base／Task と同じ候補を検証してから統合します。
形式移行のチェックは設計全体・IaC 正常性の代わりになりません。
独自 helper の関連テストと配布対象 Framework の必要なオフライン検証も実施します。
旧 acquisition、Review、checkpoint、receipt、Deploy session は再利用しません。

## 切替と確認

旧処理を止めたまま、検査済み候補の Model 入口・全 parts を配置し、列挙した旧 Model ファイルを削除します。
project と IaC と issues の bytes／集合を再確認し、旧 authority が残っていないことを確認します。
新 runtime を新 requirements でセットアップし、旧 runtime は復旧用に別に保持します。
新 CLI の read／trace／render、厳密意味比較と Task の最終候補検証をオフラインで実施します。
表示保存だけが失敗した Import は保存済み Model を保持して recover-display を使います。
新たな AWS 取得や Import で上書きしません。

## 復旧

失敗した worktree と外部 export／Review／ログを保持し、push／deploy を進めません。
保存中断の journal は正規のロック付き回復経路で扱います。手で削除しません。

切替を取り消す場合は、固定した旧 Framework・対応 Python・旧 Model の元 bytes とファイル集合を
一緒に復元します。追加した新入口・parts の削除漏れを確認し、旧版の read と入力 hash を照合します。
project／IaC／issues は移行前と同じままです。旧 runtime と新 Model、または新 runtime と旧正本を混ぜません。
切替後に新しい設計変更を保存した場合は、移行前バックアップの単純復元でその変更が失われます。
その差分を別に保持してから、元の移行同値候補へ戻すか新しい限定移行を検討します。
この手順は Model／Framework のローカル復旧であり、AWS 実体の操作は含みません。


Interrupted Import source/display transactions are restored through the same journal,
including the external receipt. Read-only analysis never performs this recovery.
Use the matching running managed Task and original acquisition/HEAD:

```console
python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py import recover-transaction --environment <environment> --target <target> --service <service> --evidence <original-acquisition.json> --task-file tasks/<task-name>.md
```

Recovery verifies the receipt's Task and every journal output against the selected scope
and registered paths. It contacts no AWS API and grants no new edit rights. After source
rollback the unchanged acquisition/Review can be retried; after display rollback keep
the saved Model and use recover-display. A different Task, HEAD or acquisition stops.

## Framework のオフライン移行回帰

テスト配布にも新 revision の tests/support/fixture をすべて含めます。固定旧版は
`d0c5824fed507db234a7532a309b3c8c3482fb60` です。consumer 自身の Git 履歴へこの
Framework commit があると仮定せず、テスト前に `BLUEPRINT_LEGACY_FRAMEWORK` と
`BLUEPRINT_LEGACY_PYTHON` を外部の固定旧 checkout／対応 Python に設定します。
両方必須で、片方だけの指定は拒否します。export が旧 requirements の版も検査します。
Framework 自身の履歴があるローカル開発だけは sparse な固定旧 clone と現在の
対応済み Python を使えます。テストは新 runtime に旧 module を import しません。
新 requirements と初回セットアップは Pystache を要求しません。CI は固定旧版用
Python を別に作成し、旧 requirements をそこへだけインストールします。
これらのテストは合成 fixture を使い、consumer の project.json／model を読みません。
