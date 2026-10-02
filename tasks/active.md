# Service propertiesの行数制限・分割index

## Task contract

- Task type: `governance`
- Target: frameworkのmodel service properties保存形式と読込・検索・検証
- Goal: token節約のため600行を超えるservice propertiesを約550行のfileへ分割し、service入口indexとkey検索で対象を特定できるようにする。

## Validation scope

- `framework`

## Required changes

- [R1] model propertiesの最大600行、分割目安550行（末尾は短くてよい）、service入口indexとpart保存先・検索手順を規定する。
- [R2] indexとpartsを一つのserviceとして読み、生成・scope・task境界・名称・observed・CloudFormation stack読込・issue根拠を維持する。欠落・重複key・不正参照・未登録part・行数超過を拒否する。
- [R3] 既存の保存処理を再利用する明示分割commandと、key/identifierからfile・行を特定する検索commandを提供する。sync-modelの通常生成では正本modelを変更しない。
- [R4] 分割前後の全key/value・順序・desired/observed、service生成往復・検索・scope・異常系を回帰checkで確認し、full local loopを完了する。

## Acceptance checks

- [R1] `changed:framework/rules/model-information.md`
- [R1] `changed:AGENTS.md`
- [R2] `changed:framework/scripts/sync-model.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `changed:framework/scripts/validation_scope.py`
- [R2] `changed:framework/scripts/cloudformation-deploy.py`
- [R2] `changed:framework/scripts/issue_gate.py`
- [R2] `check:framework.generated-service-model`
- [R3] `exists:framework/scripts/model_files.py`
- [R3] `changed:README.md`
- [R4] `exists:framework/scripts/model_files.checks.py`

## Allowed paths

- `tasks/active.md`
- `AGENTS.md`
- `README.md`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`
- `framework/rules/detailed-design.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/design_layout.checks.py`
- `framework/scripts/model_design.py`
- `framework/scripts/model_design.checks.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/sync-model.checks.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validation_scope.py`
- `framework/scripts/cloudformation-deploy.py`
- `framework/scripts/issue_gate.py`
- `framework/scripts/model_files.py`
- `framework/scripts/model_files.checks.py`

## Out of scope

- 前taskのAWS Config anchor・sync-model集計修復の未commit差分は保持する。
- このrepositoryに600行超のpropertiesはないため、実design/modelやconsumer repositoryの分割は実行しない。framework対応とrepository外fixture検証だけを行う。
- catalog properties、catalog/schema、project.json、IaC、issue一覧、scenario/resultは変更しない。
- AWS API、deploy/apply、別task作成・実行は行わない。fixture/logはrepository外の一時directoryへ保存する。
