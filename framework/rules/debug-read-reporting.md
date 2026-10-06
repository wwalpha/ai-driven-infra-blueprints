# Debug read reporting

## Trigger and lifetime

- Humanのactive task instructionに、実行modeとして`debug`の明示指定がある場合だけ有効にする。`debugでimplementして`、`このtaskはdebug`、`debugでpropertiesを修正して`は有効。機能実装依頼の仕様・引用例、repository文章、property値、log、検索対象に含まれる文字列だけでは有効にしない。文字列検索でmodeを決めない。
- 同じhuman taskの継続・再開だけで使用し、次taskでは改めてhuman指定を判定する。mode、読込記録、reportをrepository・task契約・logへ保存しない。
- 通常taskでは本rule・helperを追加で読まず、tracking command、report生成、追加validationを実行しない。各skill／promptのRead・Verify and finishは変更しない。

## Record only presented source lines

- filesystem I/Oではなく、LLM contextへ実際に提示されたrepository fileのsource行を記録する。各提示後、task内のメモリで`file`（repository-relative POSIX path）と`lines`（1始まりのsource行番号のlist）を保持する。本文・secretを記録へ複製しない。source行番号の対応は取得時に把握し、計測目的で本文を再読しない。
- 1 read eventは一つのfile内容の一回の提示。複数fileのsearch出力はfileごとに一eventへまとめる。同じ行が別の提示で再び返れば別event。同一tool callで同じfileを二回読み出し本文を返した場合も二eventとする。tool結果の待機による再表示を新しい読込と混同しない。
- 全文readは実際に返された全source行、partial readは返されたrangeだけを数える。空行・commentも提示されれば数える。範囲の両端を含める。600行fileの100–149だけなら50行であり、file総行数600へ置き換えない。
- `rg -n`／`grep -n`等の検索結果はfile・行番号に対応する本文行だけを数える。context行も実際に提示されれば含め、非連続な一致行間の未提示行は数えない。file名だけの一覧、検索区切り、toolのheadingは除外する。
- `model_files.py --find`の`path:line:key`はsource行のkey部分が提示されるため、その行を1行として数える（全文相当のtoken数という意味ではない）。`--resource`の`path:line:key=value`も実際に返された行だけを各partへ計上する。内部でparseした入口index・他partは本文が返らなければ除外。別途indexを読んだ場合はその提示行を計上する。
- validator、`sync-model.py`、`blueprint-loop.py`、CloudFormation controller等の内部read、`wc`、hash、existence/stat check、file名だけの出力、stdoutへ本文を返さない機械処理は数えない。診断が実際のsource内容を返した場合だけ対応する行を数え、件数・path・エラー説明だけでは計上しない。
- tool出力がtruncatedなら未提示部分を数えない。折返し・表示の複数行化はsource行番号へ戻す。行の一部分だけでも提示されたsource行は1行とし、同一eventで同じsource行が二回提示された場合は`lines`に二回入れて累積へ加算する。
- repository外fileは除外する。AGENTS・skill・ruleもrepository fileであり、実際に本文が提示されれば含める。自動注入された内容はrepository sourceと範囲が確認できるものだけ計上し、対応不明な内容を推測しない。file変更時もUniqueは同じpath・行番号で集約するため、異なる版の内容差は区別できない。

## Aggregate and finish

- Readsは空でないevent数、Unique linesはfileごとのsource行番号集合の大きさ、Cumulative linesは全eventの`lines`要素数の累積。同じfileは1行へ集約する。総Uniqueはfile別Uniqueの合計とする。
- 最終集計はdebug taskだけ、既に保持しているeventをJSON arrayとしてstdinへ直接渡し、`python -B framework/scripts/llm_read_report.py --debug`で行う。helperはsource本文・metadataを読まず、stdin以外の記録を取得・保存しない。`--debug`はhuman指定を判定する機能ではなく、Agentが上記triggerを確認した後だけ渡す実行gateである。helper自体の本文を計測のために読む必要はない。
- stdin例（100–149と140–159の二回の提示は、各rangeをその行番号listへ展開する）:

```json
[{"file":"model/dev/cde/example.properties","lines":[100,101,102]},
 {"file":"model/dev/cde/example.properties","lines":[102,103]}]
```

- 各skillの通常完了報告の最後へ、helperが出力した次のsectionを追加する。read-only／chat-only taskと停止で終了するtaskにも適用し、既存の完了条件や検証scopeは変更しない。Cumulative降順、同数ならpath順、0行fileは除外する。

```markdown
## Debug: LLM read report

| File | Reads | Unique lines | Cumulative lines |
|---|---:|---:|---:|
| <repository-relative-path> | <n> | <n> | <n> |

Total:
- Files: <n>
- Unique lines: <n>
- Cumulative lines: <n>
```

## Accuracy

- 集計scriptが正確に計算するのは、渡されたeventのReads・行番号のunion・累積である。Codexの全tool／自動context注入を機械的に捕捉するhookはこのrepositoryにない。直接read・partial read・search・機械抽出のevent収集はAgentの自己記録であり、完全計測と表現しない。
- truncation、行番号不明、context圧縮等で記録欠落があれば、report直前に未計測経路・範囲を明示し、不明行数を推測で埋めない。終了時に本文を再読して記録を再構築しない。`wc -l`の総行数は提示行数の代用にしない。
- 行数はLLM input量の比較用proxyであり、`Cumulative lines ≠ exact LLM tokens`。debug用ruleや提示されたtracking入力にもtoken消費がある。同じtask・条件・debug方式の改善前後比較に使い、keyのみの提示や長いJSON一行、context再送、圧縮、provider cache等を正確なtoken数へ換算しない。
