# Blueprint検証の重複削減・結果再利用・サービス並列化

## Task contract
- Task type: `governance`
- Target: framework local blueprint validation
- Goal: 必須検証と明示scopeを維持し、反復処理の削減、入力が一致する成功結果の再利用、サービス単位の最大4並列により通常の再検証を60秒以内へ近づける。

## Validation scope
- `framework`

## Required changes
- [R1] カタログ一覧、resource別model行、表示用pathを一回の処理内で再利用し、異なる入力や後続実行へ古い値を持ち越さない。
- [R2] 内容hashと入力file集合で成功したcatalog/service検証だけをrepository外へ保存・再利用する。参照先、part、JSON、project、validator/rule/catalog変更で無効化し、破損・不明dependency・実行中変更は再検証またはFAILとする。
- [R3] 同一targetの複数serviceも最大4並列で検証し、指定順の診断、scope全体の所有権チェック、生成後の参照整合性、失敗service保護を維持する。
- [R4] 毎回の契約・issue・変更範囲・Acceptance・IaC/安全確認を維持し、fresh検証と計測をrunnerから指定できるようにする。再利用条件をrule/READMEへ記載する。
- [R5] cache無効化、serial/parallel一致、同一target並列、失敗・中断、scopeと参照境界の回帰検証とframework full local loopを実行する。

## Acceptance checks
- [R1] `changed:framework/scripts/design_catalog.py`
- [R1] `changed:framework/scripts/model_design.py`
- [R1] `changed:framework/scripts/design_layout.py`
- [R1] `changed:framework/scripts/sync-model.py`
- [R2] `exists:framework/scripts/validation_cache.py`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R3] `changed:framework/scripts/validation_scope.checks.py`
- [R4] `changed:framework/scripts/blueprint-loop.py`
- [R4] `changed:framework/rules/loop-engineering.md`
- [R4] `changed:README.md`
- [R5] `exists:framework/scripts/validation_cache.checks.py`
- [R5] `changed:framework/scripts/blueprint-loop.checks.py`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/validation_cache.py`
- `framework/scripts/validation_cache.checks.py`
- `framework/scripts/design_catalog.py`
- `framework/scripts/model_design.py`
- `framework/scripts/design_layout.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/validation_scope.checks.py`
- `framework/scripts/blueprint-loop.py`
- `framework/scripts/blueprint-loop.checks.py`
- `framework/rules/loop-engineering.md`
- `README.md`

## Out of scope
- 実targetのmodel／設計／IaC／project、AWS API・mutation・deploy、catalog内容、consumer同期、scenario、commit、push、index変更。
- 検証を60秒で打ち切ってPASSと扱う変更、scope不足時の全体検証fallback、未成功結果の再利用。
- 27サービスの計測には指定済みdev/cde scopeのrepository外copyだけを使用し、実consumerを変更しない。
