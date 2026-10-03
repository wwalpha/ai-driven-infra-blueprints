# Subnet一覧の1要素1行表示

## Task contract
- Task type: `governance`
- Target: framework subnet-list Markdown generation and validation
- Goal: 全14リソース型のSubnet配列とSecrets Managerのカンマ区切りSubnet一覧を、CodeBuildと同じ1始まりの連番付き1要素1行表示へ統一する。正式property、値、順序、desired/observedを維持する。

## Validation scope
- `framework`

## Required changes
- [R1] 共通表示・逆変換を実装する。正式property末尾の[]だけを表示用[N]へ置き換え、property内で1から連番とする。既存JSON配列／カンマ区切り値も表示時に分割し、正本モデルを上書きせずlosslessに検証する。
- [R2] 欠番・重複・0始まり・不正値・誤ったresource型や別targetへの参照を拒否する。CodeBuildのSecurityGroupIdsと固有表示順を維持する。
- [R3] 全対象の生成・逆変換、既存値保持、複数resourceでの連番リセット、失敗時の保存済み表示保護を回帰検証し、表示・モデル・chatbotルールを更新する。
- [R4] humanが指示したmasterへのmergeを行う。最新masterの既存変更を保持して競合を解消し、統合済みstaged snapshotで全framework local loopを実行する。

## Acceptance checks
- [R1] `changed:framework/scripts/model_design.py`
- [R1] `changed:framework/scripts/design_layout.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/design_layout.checks.py`
- [R3] `changed:framework/scripts/model_design.checks.py`
- [R3] `changed:framework/rules/detailed-design.md`
- [R3] `changed:framework/rules/model-information.md`
- [R3] `changed:framework/prompts/chatbot/service-design.md`
- [R4] `changed:tasks/active.md`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/model_design.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/design_layout.checks.py`
- `framework/scripts/model_design.checks.py`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/prompts/chatbot/service-design.md`

## Out of scope
- catalog/schema変更、単一SubnetIdやSubnetMappings等object配列の形式変更、実targetのdesign/model/IaC/project、consumer同期、AWS操作、scenario、push。

## Git operations
- humanの明示指示により、今回の変更のstage・commit、最新masterとの競合解消、元checkoutのmasterへのmergeを許可する。
