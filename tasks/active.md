# Lambda Permissionの統合表示

## Task contract
- Task type: `governance`
- Target: framework Lambda.Permission Markdown display
- Goal: Lambda.Permissionを所属Lambda.Functionの同じ詳細表へ統合し、Permission.*でpropertyを表示する。Id、FunctionName、独立heading/table/一覧を表示せず、modelの識別・desired/observed・所属を保持する。

## Validation scope
- `framework`

## Required changes
- [R1] 既存の親子統合処理を使用し、PermissionをFunctionの表へまとめ、独立一覧を生成しない。
- [R2] Permission.*表示とId／FunctionNameの非表示を生成・読戻し両方で対応し、複数Permissionと非表示識別情報をlosslessに保持する。不正marker、所属、重複を拒否する。
- [R3] 表示とmodel保持のルールを明記し、生成・読戻し・validation・失敗時保存保護の回帰checkとframework local loopを実行する。

## Acceptance checks
- [R1] `changed:framework/rules/resource-layout.json`
- [R1] `changed:framework/scripts/model_design.py`
- [R2] `changed:framework/scripts/design_layout.py`
- [R3] `changed:framework/rules/detailed-design.md`
- [R3] `changed:framework/rules/model-information.md`
- [R3] `exists:framework/scripts/lambda_permission.checks.py`

## Allowed paths
- `tasks/active.md`
- `framework/rules/resource-layout.json`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/scripts/model_design.py`
- `framework/scripts/design_layout.py`
- `framework/scripts/lambda_permission.checks.py`

## Out of scope
- catalog/schema、実targetの設計/model/IaC/project、AWS操作、consumer同期、scenario、commit、push、index変更、元worktreeの変更。
