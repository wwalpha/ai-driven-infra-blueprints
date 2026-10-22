# Project Configuration Rules

## Topology

- After initialization, the machine-readable source of truth is `project.json`. The target directory is the alias if present, otherwise `awsAccountId`.

- Do not include `project.json` in the uninitialized distribution state.
- `framework/prompts/codex/01_initialize.md` may be used regardless of whether `docs/system-overview.md` has been created or filled in. Codex asks for necessary confirmed values and creates `project.json` and target paths.
- Initialization registers only targets whose required values are currently confirmed. Do not register not-yet-created targets or targets with unconfirmed required values using guesses or placeholders; add them after confirmation via migration using `framework/prompts/codex/02_add-target.md`.
- Do not fix the number or names of environments or the number of AWS accounts.
- Do not assign an alias when an environment has only one target. If there are multiple targets, human-confirmed aliases are mandatory for all targets; the same AWS account ID may be assigned to multiple aliases. Aliases must be unique lower-kebab-case within the same environment; values consisting only of 12 digits are prohibited.
- The `IaC engine` for 1 environment/AWS account must be exactly one of `cloudformation` or `terraform`, consistent across aliases with the same AWS account ID.
- Do not require the human to directly edit `project.json`. Codex performs topology changes in explicit initialization or migration tasks.
- Each `project.json` target may have an optional `suffix`. It must be a confirmed non-empty lower-kebab-case string; different values may be configured per environment/alias. Use the selected target's value only when the naming pattern contains `{{suffix}}`; do not automatically append it to patterns without it. It may be confirmed during initialization/target addition; adding/changing/removing it on an existing target requires a human-explicit `migration` task. Do not automatically change existing names.

## Credentials and account

- project.json targetのawsProfileをCLI/SDK/Terraform provider/backendで共用する。未設定時だけ明示profile、さらに未指定ならdefault credential chainを使う。明示値が設定と違えば実行前に停止。認証失敗後のprofile/account切替・fallback・自動AssumeRoleは禁止。
- awsProfileは確定した非空文字列のみ。前後空白/newline/NUL/UNSETは禁止。未指定keyは省略しcredential値を保存しない。targetごとのprofileはalias/account/Region/engine制約を変えない。
- awsAccountIdは明示ID設定・作成時名称・target identityの正本。directory/selector/Taskはalias（なければawsAccountId）を維持する。
- awsExecutionAccountIdは任意のASCII 12桁文字列。未指定keyは省略しawsAccountIdを使う。STS caller、CLI/SDK、CFn、Terraform、既存取得、observed、AWS比較、scenarioはexecution account/明示Regionを確認し、不一致・認証失敗で停止する。ID設定だけではcredentialを切り替えない。
- AWS暗黙account/ownerとAWS::AccountIdはexecution accountを使う。Modelの明示account/cross-account設計は書き換えない。作成時名称等がawsAccountIdを必要とし両IDが異なるなら独立parameterを渡す。IDを設定するだけでResourceの実AWS所属を変更できない。
- 同target作成Resourceのowner/source policyはawsExecutionAccountId（未指定ならawsAccountId）を使い、作成時名称/明示ID設定と区別する。VPC Flow Logs trustのaws:SourceAccountとaws:SourceArnのaccount、permission Resource ARN/Principalも実owner参照に合わせる。Human明示cross-accountは保ち一括置換しない。
- 同environment/resource accountのengineはalias間で一つとし、同environment/execution accountでも整合させる。execution IDはinitialize/add-targetで確認、既存targetの追加/変更/削除は明示migrationだけ。awsAccountId/alias/path/設計/IaCを暗黙変更せず、local loopはproject.jsonと不整合なpath/IaCを拒否する。local検証はAWS接続なし。
- /importだけHuman明示--no-profileでconfigured profileをその呼出しに限り省略し、継承環境を含むAWS CLI default chainを使える。project設定/値検証/他workflowを変更せず、明示RegionとSTS execution account確認を維持。自動選択・再試行では使わない。
