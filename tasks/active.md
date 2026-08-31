# Codex Task: Refresh catalog count and hash

## Task contract

- Task type: `catalog-maintenance`
- Goal: `EC2.VPC.InstanceTenancy`削除後のcatalog件数とSHA-256 manifestをcurrent catalogに一致させる
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] current `framework/materials/aws/`からcatalog metadataの件数を再計算する。
- [R2] current catalog contentsからSHA-256 manifestを再生成する。

## Acceptance checks

- [R1] `changed:framework/materials/catalog.properties`
- [R2] `changed:framework/materials/catalog.sha256`

## Allowed paths

- `framework/materials/catalog.properties`
- `framework/materials/catalog.sha256`
- `tasks/active.md`

## Out of scope

- `framework/materials/aws/**`の追加変更
- framework rules、prompts、scriptsの変更
- AWS API、deploy、applyの実行
