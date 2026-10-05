# Issue Gate Rules

## Unresolved issue gate

- issue一覧は`issues/<environment>/<target-directory>/issues.md`とする。target directoryはproject.jsonのalias、aliasなしはAWS account IDとする。fileがない場合または空の場合は未解決issueなしとして扱う。
- 一覧に残っている番号付きissue（`1. ...`）はすべて未解決とする。修復・再検証が成功したissueだけを明示された修復scope内で一覧から除去する。解決履歴はGitで保持し、一覧削除・書換えだけで修復済みと扱わない。issueが0件なら`未解決issueなし`と記載してよい。
- serviceは`### <service-id>`、`<!-- issue-service: <service-id> -->`、または同じtargetのmodel properties／詳細設計Markdownへの根拠linkで特定する。AWS serviceの表示名だけでは推測しない。所属を特定できないissueや番号付きissue／0件宣言のない不正な一覧はtarget全体を停止する。
- 対象environment/target/serviceに未解決issueがある間、設計相談・設計保存・implement・deploy/apply・scenario・target migrationなど他taskを開始・継続しない。別environment、別target、別serviceは停止しない。複数serviceを変更・実装・deployする場合は関係する全serviceをValidation scopeへ明記し、一件でもblockedならそのtaskを停止する。全体validationとtask対象を混同しない。
- issue調査のread-only操作、humanが明示したissue修復、および以下の保存限定taskだけを許可する。新しいtask typeは作らず、design／infrastructureなど既存task boundaryとAWS execution許可を維持する。frameworkだけのgovernance／catalog-maintenanceはservice対象taskではないため、consumer issueでは停止しない。
- issue調査・保存およびdesiredの環境比較・diff保存は`migration` taskとし、明示service Validation scopeのtargetの`issues/<environment>/<target-directory>/issues.md`／`diff.md`と今回の`tasks/<task-name>.md`だけをAllowed pathsと変更対象にする。この条件を満たす保存限定taskは既存issueによる停止判定を適用せず、調査・比較・AI分類・保存・local validationを続ける。diff.mdの項目は未解決issueとして数えず、既存issues.mdの修復やIssue remediationの追加を要求しない。通常migration、設計・model・IaC変更、model保存、AWS mutationのissue gateは維持する。調査で検知した実際のvalidation errorは引き続きFAILとして報告する。
## Issue remediation

- 修復taskのGoalとRequired changesに対象issue、原因、修復scopeを記載する。同じactive contractに次のsectionを置く。entryは明示されたValidation scopeの部分集合だけとし、`all`／`framework`による修復例外は禁止する。例外はそのserviceのissue修復と再検証だけに適用し、機能追加・通常の設計・別issueの修復などを混ぜない。修復task完了後に停止中の他taskを自動再開しない。

```md
## Issue remediation

- `dev/cde/ec2`
```

## Check timing

- 保存限定taskを除き、対象を確定した時点、task開始前、再開時、設計保存前、AWS mutation前に最新のissue一覧を確認する。開始前は次のcheckを実行する。このcheckは古いactive contractの修復例外を使わない。修復依頼なら停止理由を確認し、humanの依頼scopeに限った修復contractを作成して既存workflowで処理する。既存のactive contractが残っていても、chat-only設計相談のissue停止を解除しない。

```text
python framework/scripts/issue_gate.py --environment <environment> --target-directory <alias-or-account-id> --service <service-id>
```

`--service`は関係する全serviceについて繰り返す。task validator、`sync-model.py --write`、deploy contextは共通issue判定を実行する。AWS read-only contextはissue調査に使用できるが、通常taskの続行許可を意味しない。deploy/applyは既存preflightに加え、実行直前にも同じissue checkを再実行する。実行直前のcheckには`--task`を付け、同じactive contractのIssue remediationを用いる。通常taskは修復例外なしで再確認する。
