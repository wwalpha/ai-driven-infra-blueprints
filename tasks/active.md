# Codex Task: Align renamed chatbot framework directory

## Task contract

- Task type: `migration`
- Goal: committed `framework/chatbot` renameへframework referenceとvalidationを整合させる
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] repository structure説明を`framework/chatbot`へ更新する。
- [R2] required framework file validationを`framework/chatbot`へ更新する。
- [R3] 複数resource typeを持つservice model metadataを空白なしの決定的形式で生成する。

## Acceptance checks

- [R1] `changed:README.md`
- [R1] `exists:framework/chatbot/personal-custom-instructions.md`
- [R1] `absent:framework/copilot`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/sync-model.py`
- [R3] `changed:framework/scripts/sync-model.checks.py`

## Allowed paths

- `README.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/sync-model.checks.py`
- `tasks/active.md`

## Out of scope

- framework directory rename以外のbehavior変更
- project固有fileの変更
- AWS API、deploy、apply
