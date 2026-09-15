# 既存ファイル同期へ .agents を含める

## Task contract

- Task type: `governance`
- Target: framework 共通 / 既存repositoryへの同期script
- Goal: `sync-existing-files.py`で`framework/`に加えて`.agents/`も同期する。
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 同期scriptの対象へrootの`.agents/**`を追加する。
- [R2] focused checkで`.agents`のコピーを確認する。
- [R3] READMEの同期範囲を実際の挙動に合わせる。

## Acceptance checks

- [R1] `changed:framework/scripts/sync-existing-files.py`
- [R2] `changed:framework/scripts/sync-existing-files.checks.py`
- [R3] `changed:README.md`

## Allowed paths

- `tasks/active.md`
- `framework/scripts/sync-existing-files.py`
- `framework/scripts/sync-existing-files.checks.py`
- `README.md`

## Out of scope

- 実targetへの同期、target固有のdesign/model/IaC、AWS操作、scenario、commit/pushへ進まない。未追跡`CMD.md`を保持する。
