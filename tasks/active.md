# CloudFormationのS3配置とサイズ別template送信

## Task contract
- Task type: `governance`
- Target: framework CloudFormation deployment
- Goal: 設計で明示したS3配置先とローカル成果物の対応を使用し、成果物の事前配置とtemplateサイズ別の直接送信／S3送信を既存controllerへ追加する。

## Validation scope
- `framework`

## Required changes
- [R1] stack modelに任意のTemplateBucket／TemplateKeyPrefixと、StackName・resource・property・source・bucket・keyPrefixの成果物対応を追加し、生成Markdownと再解析・参照検証を維持する。
- [R2] controllerで成果物を指定bucketへ条件付きuploadして検証する。templateは51,200 bytes以下で直接送信、超過時は指定S3へ配置してvalidate/change setへ同一URLを渡し、1 MiB超は停止する。元IaCを変更せず、入力hashと配置済み成果物をsessionへ固定して再開時の変更を拒否する。
- [R3] rules、deploy/update prompt、READMEへ設定方法、権限、bootstrap、再開と保持の契約を記載する。
- [R4] 既存回帰checkへサイズ境界、複数Lambda／共有ZIP／異なるbucket、参照不一致、失敗時停止、再開と変更検出を追加し、framework full local loopを実行する。

## Acceptance checks
- [R1] `changed:framework/scripts/model_design.py`
- [R1] `changed:framework/scripts/design_layout.py`
- [R1] `changed:framework/scripts/sync-model.py`
- [R1] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/cloudformation-deploy.py`
- [R3] `changed:framework/rules/cloudformation.md`
- [R3] `changed:framework/rules/model-information.md`
- [R3] `changed:framework/rules/detailed-design.md`
- [R3] `changed:framework/prompts/codex/04_deploy.md`
- [R3] `changed:framework/prompts/codex/05_update.md`
- [R3] `changed:README.md`
- [R4] `changed:framework/scripts/cloudformation-deploy.checks.py`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/model_design.py`
- `framework/scripts/design_layout.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/cloudformation-deploy.py`
- `framework/scripts/cloudformation-deploy.checks.py`
- `framework/rules/cloudformation.md`
- `framework/rules/model-information.md`
- `framework/rules/detailed-design.md`
- `framework/prompts/codex/04_deploy.md`
- `framework/prompts/codex/05_update.md`
- `README.md`

## Out of scope
- 実targetのmodel／設計／IaC／project設定、AWS取得・変更・deploy、catalog、consumer同期、scenario、別task、commit、push。
- 完了前にframework scopeのfull local loopと差分レビューを実施する。
