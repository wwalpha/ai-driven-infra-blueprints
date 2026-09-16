# CloudFormation YAMLアンカー禁止の検証を統一する

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation YAML rule and validator
- Goal: YAML anchor/alias/hash merge禁止を正とし、検証器のアンカー要求との矛盾を解消する。

## Required changes

- [R1] CloudFormation YAML ruleで同一の信頼ポリシーの明示記載を維持し、アンカー禁止を明確にする。
- [R2] validatorから同一信頼ポリシーのアンカー要求を除き、YAML anchor/alias/hash mergeを拒否する。
- [R3] focused checkで同一信頼ポリシーの明示記載を許容し、禁止構文を拒否する。

## Acceptance checks

- [R1] `changed:framework/rules/cloudformation.md`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/validate-blueprint.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/cloudformation.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validate-blueprint.checks.py`

## Out of scope

- design/model、IaC、AWS操作、scenario、その他のframeworkは変更しない。未追跡`CMD.md`は保持する。
