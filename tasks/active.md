# CloudFormationデプロイ前照合の誤判定修復

## Task contract
- Task type: `governance`
- Target: frameworkのCloudFormation比較・ImportValue事前確認・Windows回帰
- Goal: viewcard-codeのCFn deployで報告された条件分岐、配列比較、参照／子resource、実行時parameter、symlink権限制約の5点を修復・再検証する。

## Validation scope
- `framework`

## Required changes
- [R1] ImportValue事前確認で条件を評価し、選択されたFn::If枝と有効なresource／Outputだけを走査する。条件の未解決・循環は停止する。
- [R2] 途中の配列と末尾の配列を区別し、QuickSight権限配列の階層・順序・件数を正しく比較する。
- [R3] KMS参照と親Key、S3 BucketPolicyの所属・内容、設計Regionの照合を確認し、不足ロジックを修復する。曖昧な照合は成功扱いにしない。
- [R4] stack別の明示実行時parameterを比較へ渡し、MWAA requirements object versionと関連Exportを同じ入力で評価する。未知stack／未宣言parameterを拒否する。
- [R5] Windows権限がなくてもsymlink拒否ロジックを検証できる回帰へ変更する。
- [R6] 5点の一致・不一致・未解決のfocused回帰を追加し、framework scopeのfull local loopを完了する。入力仕様をCloudFormation ruleへ記載する。

## Acceptance checks
- [R1] `changed:framework/scripts/cloudformation-deploy.py`
- [R1] `changed:framework/scripts/cloudformation-deploy.checks.py`
- [R2] `changed:framework/scripts/check-model-cfn.py`
- [R2] `changed:framework/scripts/check-model-cfn.checks.py`
- [R3] `changed:framework/scripts/check-model-cfn.py`
- [R3] `changed:framework/scripts/check-model-cfn.checks.py`
- [R4] `changed:framework/scripts/check-model-cfn.py`
- [R4] `changed:framework/scripts/check-model-cfn.checks.py`
- [R5] `changed:framework/scripts/model_files.checks.py`
- [R5] `changed:framework/scripts/cloudformation-deploy.checks.py`
- [R6] `changed:framework/rules/cloudformation.md`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/check-model-cfn.py`
- `framework/scripts/check-model-cfn.checks.py`
- `framework/scripts/cloudformation-deploy.py`
- `framework/scripts/cloudformation-deploy.checks.py`
- `framework/scripts/model_files.checks.py`
- `framework/rules/cloudformation.md`

## Out of scope
- consumer同期、実targetのmodel・設計・IaC・parameter・project・issues変更、値の推測、AWS API、deploy/apply、scenario、commit/push、issue gate緩和。
