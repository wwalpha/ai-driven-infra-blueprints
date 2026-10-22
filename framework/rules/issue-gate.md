# Issue Gate Rules

## Dedicated import boundary

For `/import`, [IMPORT configuration authority](model-information.md#import-configuration-authority)
replaces the design validation/completion rules below: source and display transactions
are separate, and issues runs only when explicitly requested. Other workflows retain these rules.


## Unresolved issue gate

- issues/<environment>/<alias-or-account>/issues.mdの番号付きissue（1.等）は全て未解決。fileなし/空は未解決なし。修復を明示依頼され、再検証と解消根拠がある項目だけ削除する。履歴はGitに残し、一覧の削除/書換えを解消扱いしない。0件なら「未解決issueなし」を記載できる。
- owner serviceは### service-id、issue-service comment、同targetのModel properties/詳細設計linkで特定する。AWS表示名から推測しない。owner不明、番号も0件宣言もない不正一覧はtarget全体を停止する。ただし既存のreference-only診断は先に識別しwarningとして保持し、番号/count/Issue Gateに含めない。混在項目の実ERRORは停止する。link keywordだけではwarningにしない。
- 該当environment/target/serviceの未解決issueは通常の相談・設計/save・implement・deploy/apply・scenario・migrationの開始/継続を止める。他target/serviceは止めない。複数serviceは全てValidation scopeに明示し、一つでもblockedなら停止する。全体検証scopeと実変更targetを混同しない。Framework-only governance/catalog-maintenanceはservice taskではない。
- read-only調査、Human明示issue修復、Model deletion例外、save-only例外は許可する。既存Task種別/設計境界/AWS権限は維持する。
- issue調査/saveはmigration。明示service scopeのissues.md/iac-issues.mdと当TaskだけがAllowed/変更先のsave-onlyは既存issueで停止せず、独立worktree不要。実validation ERRORはFAILと報告する。iac-issues.mdは非blocking Model→IaC比較で未解決issueに数えずIssue remediationも不要。iac stateは保存/削除対象でない。他のmigration/Model/IaC/save/AWS mutationは通常gateを維持する。
- standalone import-retargetはproducer/consumer全serviceの通常pre-task/resume/save/generation/final gateを維持する。deletion例外を継承せず、issueの変更/解消扱いは禁止。

## Reference-only Issues

Apply [Reference diagnostics](model-information.md#reference-diagnostics) to all Model
operations. Recognize known old machine diagnostic forms before resolving issue ownership;
reference-only items are nonblocking even with unknown ownership. Keep their text and
numbering. In mixed items retain the non-reference errors as blocking; a reference/link
keyword alone never changes classification. Scan artifacts, summary and detail carry
warnings, without requiring judgement, reassignment or migration saving. Never mark them
fixed or delete them merely to allow an update. IaC comparisons unable to resolve a Model
report uncompared plus warnings, not match/verified or category error.

## Model deletion exception

For an explicit Human Model deletion request, do not stop at the ordinary pre-contract
issue check. First register and validate the design /update `import-delete` contract
with exact normalized deletion sources, forbidden AWS API execution and deploy/apply,
and explicit service Validation scope containing every source and repair consumer. Keep the same Task selector and managed
worktree ownership. Then use the common task-aware issue decision (`require_no_issues`,
or `issue_gate.py --task`) on its declared scope, including resume, source saves,
generation and final/integration validation. Missing/invalid contracts, unknown operations,
scope mismatches and mismatched managed Tasks fail closed. The ordinary CLI without
`--task` retains its pre-contract gate.

Only the existing-issue stop decision for registered deletion source services is waived.
Other declared services retain their ordinary gate; do not expand the exception to
consumer-only repairs, unrelated services or other operation types. Do not require Issue remediation, delete issues.md or mark existing issues fixed.
Keep incoming-reference diagnostics and final verify_model_operation checks. Reference
analysis reports ambiguity/type mismatch/surviving links as warnings. The final candidate
guard rejects invalid surviving Resource references; intermediate leaves remain separate. Retain parse/Model/Bindings errors,
operation source existence/fixed identity, path/scope/worktree guards, AWS/deploy
prohibitions and non-reference generation/validation errors. `import-merge`, ordinary
updates, IaC/deploy and later ordinary Tasks retain the issue gate; completed deletion
contracts do not grant the exception.

## Issue remediation

- Record the target issue, cause, and repair scope in the repair task's Goal and Required changes. Place the following section in the same active contract. Entries must be subsets of the explicit Validation scope only; repair exceptions using `all` / `framework` are prohibited. The exception applies only to that service's issue repair and revalidation; do not mix in feature additions, ordinary design, other issue repairs, etc. Do not automatically resume other suspended tasks after the repair task completes.

```md
## Issue remediation

- `dev/cde/ec2`
```

## Check timing

save-only/Model deletionの明示例外以外は、target確定時、開始前、resume、設計save前、AWS mutation直前に最新一覧を確認する。開始前は次を実行し、複数serviceは同processに--serviceを繰り返す。旧Taskの修復例外で通常相談/実行を許可しない。修復依頼は停止原因を確認し、Human指定範囲の契約を登録して既存修復workflowへ進む。

```text
python framework/scripts/issue_gate.py --environment <environment> --target-directory <alias-or-account-id> --service <service-id>
```

Task validator、sync-model.py --write、deploy contextは共通判断を使う。AWS read-only contextは調査の認証確認だけで他task続行権限ではない。mutation直前は通常preflightに加えて同じgateを--task付きで確認し、そのTaskのIssue remediationだけ適用する。通常taskは修復例外なしで再確認する。
