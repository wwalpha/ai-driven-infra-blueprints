# Model helper integration

Model 固有コードは `framework/scripts/model/`、import は `model.*` に統一します。
Task、Git、worktree、汎用 AWS、Deploy controller は既存の共通実装を使います。
恒久的な PYTHONPATH 設定や同じファイルの別名動的ロードは不要です。
CLI は `framework/scripts/model/cli.py` です。独自 helper の入口でも最初に
`framework/scripts` を一度だけ解決し、通常の Python import を使ってください。

## 公開 API

| API | 入出力・境界 |
| --- | --- |
| load_model(scope, read_context) | Scope または入口 Path → 不変 ModelSnapshot。実在する Model のみ読む |
| list_models(scope, read_context) | repo Path または Scope → 実在する Scope 一覧。target 登録だけで作成しない |
| prepare_edit(snapshot, candidate, policy) | Path→properties 原文／None の候補 map → 保存未実施の EditPlan |
| prepare_observed(snapshot, changes, policy) | observed.row.ID.value→文字列／None → 観測専用 EditPlan |
| publish_edit(plan, context) | 同じ一回使い切り context の検査済み候補だけを保存。消費済み・別contextは拒否 |
| render_model(snapshot, context) | Markdown／JSON の Path→文字列 map。Model を保存しない |

snapshot.authoritative は reference と placementName を含む全正本です。
values は observed metadata と document hash を導出した表示・実行用投影です。
files は所有原文、documents は物理行情報、locations はキーの場所、
dependencies は project と実際に読んだ producer を含む bytes／不存在です。
固定 identity や serializer、移行比較には authoritative を使います。

read_context は既存 `GenerationInputs` などの read／kind／select を提供する入力記録です。
同一 invocation で共有し、保存直前の fresh な照合を省きません。
Model の read dependency と writable output を分けます。producer を読んだだけで
Allowed paths に追加してはいけません。

## 保存権限

`SourceWriteContext(...)`、`EditPlan(...)` の公開 constructor は保存権限を発行しません。
policy 名、`approved=True`、ResourceMode の書き換えで権限を作れません。
既存 Task adapter が running Task、管理 worktree、未統合状態、HEAD、scope、
Modified files／Allowed paths、必要な issue gate を照合し、context を発行します。

通常の design/update は `model.adapters.task.edit_write_context`、
限定 Model-only 操作は `source_write_context` を使います。
通常編集の最後に共通 IMPORT 保持検査を行います。中間 Model-only 保存へ最終的な
設計全体の検証を追加しません。retarget の保存前検査は維持します。
生成候補や人間の編集を直接 write_text で正本へ保存する helper は接続し直してください。

```python
from model import load_model, prepare_edit, publish_edit
from model.adapters.task import edit_write_context
from task_contract import selected_task

# root、task_file、scope、candidate は呼出側が明示的に選択したもの。
with selected_task(root, task_file):
    with edit_write_context(root, {(scope.environment, scope.target, scope.service)}, task_file) as context:
        snapshot = load_model(scope, context.snapshot)
        plan = prepare_edit(snapshot, candidate, context)
        publish_edit(plan, context)
```

新しいサービス作成の候補 baseline は `model.sources.candidate_base` を明示的に使います。
これは権限付き候補の準備用で、通常 reader に不存在 Model の fallback を追加しません。
候補は外部領域で編集し、同じサービスの入口と全 parts を含めます。
`model.sources.candidate_sources` が完全候補を読み、削除した parts も明示します。

publication lock と journal は共通実装です。保存の直前に原文 bytes、存在／不存在、
parts 集合、読取依存、Task、HEAD を照合します。通常の保存失敗は原文と証跡を復元します。
プロセス中断で journal が残った場合は通常の保護された回復経路を使い、手で削除しません。

## Import と独自取得 helper

取得は `model.importing.inventory` と既存 AWS adapter、候補照合は importing.sources、
全件 Review と binding は importing.approval、外部 acquisition／receipt は importing.evidence です。
CLI の `import acquire|review|publish|resume|recover-display` は単一サービスの原子的入口です。
複数サービスの反復、照合判断、質問、対応選択、Review 提示、最終保存同意は LLM が担当します。

独自 helper は取得レコード全件、物理 ID、Name、取得状態、正式 Property と native type を保持し、
既存の inventory／evidence 境界へ渡します。取得できなかった値を空文字にしません。
add／refresh／bind／replace の保持条件、固定 ID、未取得値、非選択 Resource、CREATE 保護を維持します。
候補の参照 map は完全な after map です。提案省略は保持、空 map は削除です。
所有者は consumerKey の旧・新双方から検査し、before と merge して削除を復活させません。

LLM は全レコードの Before／After、反映先、参照の意味、除外、未取得、リスク、incoming 影響を提示し、
具体的内容への明示的な保存同意を得てから publish を呼びます。
「確認しました」や件数の了承は同意ではありません。内容変更時は全件 Review を再提示します。
取消時は保存しません。変更のない承認済み内容への同意は再要求しません。
機械テストで Review の digest が一致しても、人間との対話を実証したことにはなりません。
Host approval、署名サービス、特定 IDE の SDK は追加しません。

Model 保存と表示保存は別 transaction です。表示だけ失敗した場合は Model を保持し、
`import recover-display` で再取得・再 Import なしに回復します。
旧 acquisition／Review／checkpoint／receipt／Deploy session は形式・意味・snapshot 版の不一致を示して拒否します。

## Deploy・観測 helper

`model.adapters.observed` が既存 CloudFormation mapping と取得値の接続を担当します。
観測候補は model.observed に集約し、選択 Row の observed.value だけを保存します。
IMPORT の物理 ID を一般観測更新で変更しません。
複数 Model の観測候補も、同じ共有 publisher で一括保存します。
同じ properties の desired／display／reference や原文の整形変更を混ぜません。

Deploy 設計 digest は observed を除く全正本を含みます。
完全 snapshot は原文、observed、ファイル集合、project、実読取依存も含みます。
観測後は実際に許可された差分だけ baseline を進め、設計 digest を取り直して変更を吸収しません。
AWS 実行直前の target、Task、設計、IaC、入力と検証依存の再確認は既存 controller の責務です。


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

Import CLI の終了値は成功 0、検査・保存拒否 1、取得／表示が未完了 2、Model 保存済みで表示保存失敗 3 です。2／3 を成功扱いせず、JSON の model／markdown と元の evidence を保って復旧します。

read の JSON は warnings に参照診断を含みます。incoming は references と warnings、
status（complete／incomplete）を返します。WARNING は保存値を修正しません。
構文不正、I/O、scope 違反は失敗として返り、WARNING に読み替えません。
