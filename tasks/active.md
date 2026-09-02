# S3詳細設計のBucket表示contract更新

## Task contract

- Task type: `governance`
- Goal: S3 Bucketのblock構成、KMS alias参照、bucket単位のregion表示をわかりやすく一貫して生成するframework contractへ更新する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] S3.BucketPolicyを対応するS3.Bucketのtableへ含め、独立headingを作らず、S3.Bucket.BucketNameをtable先頭へ置く詳細設計生成ruleとchatbot promptへ更新する。
- [R2] validatorが上記S3専用grouping、BucketName順序、BucketPolicyの自己参照を検証し、group内の各resource typeをprovider schemaで検証する。
- [R3] grouped S3 tableが一つのresource blockとして全rowとpolicy artifact hashをgenerated service modelへ保持するfocused checkとmodel contractを追加する。
- [R4] S3.BucketのKMSMasterKeyIDはKMS.Keyのgenerated KeyIdではなく、対応するKMS.AliasのAliasNameを表示するresource linkとする。
- [R5] 各S3.Bucket tableの2行目にhuman-confirmedのbucket配置regionをdesign-only `S3.Bucket.Region` rowとして必須化し、project.jsonのtarget region以外も許可する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/validate-blueprint.checks.py`
- [R2] `check:framework.schema-backed-design-validation`
- [R3] `changed:framework/rules/model-information.md`
- [R3] `changed:framework/scripts/sync-model.checks.py`
- [R3] `check:framework.generated-service-model`
- [R4] `changed:framework/rules/detailed-design.md`
- [R4] `changed:framework/scripts/validate-blueprint.checks.py`
- [R5] `changed:framework/prompts/chatbot/service-design.md`
- [R5] `changed:framework/scripts/validate-blueprint.py`
- [R5] `check:framework.schema-backed-design-validation`

## Allowed paths

- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`
- `framework/scripts/sync-model.checks.py`
- `tasks/active.md`

## Out of scope

- consumer repositoryの`docs/designs/**`と`model/**`の移行
- `framework/materials/aws/**`、IaC、scenario、resultの変更
- AWS API、AWS mutation、deploy/apply
- S3以外のresource grouping変更
