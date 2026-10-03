# 小規模修復の対象照合・生成・検証手順を明確化

## Task contract
- Task type: `governance`
- Target: `framework/prompts/codex/03_implement.md`、`framework/prompts/codex/05_update.md`
- Goal: 小規模修復で範囲と終了地点を先に確定し、既存IaCとの照合、必要な変更だけの契約、service指定の生成と重複しない検証を明記する。

## Validation scope
- `framework`

## Required changes
- [R1] implementで対象propertyを既存IaCと先に照合し、一致する箇所は確認対象として保持する。必要な変更だけを契約へ記載し、static validationとlocal loopを各一回にする。
- [R2] updateの適用条件で手動model差分と明示issue修復を区別し、終了地点とtask boundaryを維持する。生成を対象serviceへ限定し、無関係な再読・追加検証を避ける。

## Acceptance checks
- [R1] `changed:framework/prompts/codex/03_implement.md`
- [R2] `changed:framework/prompts/codex/05_update.md`

## Allowed paths
- `tasks/active.md`
- `framework/prompts/codex/03_implement.md`
- `framework/prompts/codex/05_update.md`

## Out of scope
- framework実行コード・rules・skills・validator・issue gateの変更、consumer repositoryへの同期、model・設計・IaC・issues・project・catalog変更、AWS API、deploy/apply、commit、push、別task。

## Completion
- python3 -B framework/scripts/blueprint-loop.py --mode fullを一回実行し、Requirement/Acceptance、framework regression、差分checkの結果を報告して終了する。
