# CloudFormationの別stack resource参照をexport/importへ移行する

## Task contract

- Task type: `governance`
- Target: framework共通 / CloudFormation cross-stack reference workflow
- Goal: template外のstack-owned resourceを参照または文字列で使用する場合、既存exportを調査し、必要ならproducer stackへexportを追加・deployしてからconsumer templateでImportValueを使用する。

## Required changes

- [R1] CloudFormation ruleに、外部resource参照の特定、exportの調査、producer deploy後のconsumer importの順序を規定する。
- [R2] implement promptに、引用・文字列内の参照の発見とproducer/consumerの実装境界を規定する。
- [R3] deploy promptに、deployed exportのread-only確認とproducer先行deployの検証を規定する。
- [R4] update promptに、同じtaskで扱えるproducer export追加・deploy後のconsumer ImportValue変更・deploy順を規定する。

## Acceptance checks

- [R1] `changed:framework/rules/cloudformation.md`
- [R2] `changed:framework/prompts/codex/03_implement.md`
- [R3] `changed:framework/prompts/codex/04_deploy.md`
- [R4] `changed:framework/prompts/codex/05_update.md`

## Allowed paths

- `tasks/active.md`
- `framework/rules/cloudformation.md`
- `framework/prompts/codex/03_implement.md`
- `framework/prompts/codex/04_deploy.md`
- `framework/prompts/codex/05_update.md`

## Out of scope

- target、design/model、IaC、AWS操作、scenario、commit/pushは変更・実行しない。未追跡`CMD.md`は保持する。
