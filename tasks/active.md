# 全環境の比較不能を1,500件以下へ減らす

## Task contract
- Task type: `governance`
- Target: 共通properties／CloudFormation比較
- Goal: viewcard-codeの全6 target・全91比較serviceについて比較不能3,137件の原因を調べ、根拠のある比較・欠落判定を実装して1,500件以下へ減らす。根拠のないmismatch化、除外、成功扱いはしない。

## Validation scope
- `framework`

## Required changes
- [R1] target regionから確定するAWS::PartitionとS3.Region、KMS Aliasの名称参照と親Keyへの所属、identityなしの統合resourceを比較する。policy Conditionを組込み関数と誤認せず、modelとCFnのpolicy式を同条件で評価する。生成Nameを名称選択から除外し、確定NameのRefと暗号化Key selectorを意味で比較する。S3／Logsの確定Name由来ARNをlocalで評価し、未解決の生成値とliteralの差だけをmismatchにしない。名称・Name tag・Aliasによる一意な対応を確認し、曖昧な対応や入力不足を成功扱いにしない。
- [R2] 全宣言stackの読込・型coverageを確認し、実装欠落を根拠付きで判定する。coverage不明、曖昧な対応、未確定identifierは比較不能のまま保持し、参照先の欠落と比較処理の未対応を区別する。
- [R4] 上記の一致、不一致、修正後の再比較、曖昧な対応・入力不足・欠落判定の回帰を既存focused checksへ追加する。全6 targetのbefore/afterと原因内訳をrepository外へ保存して件数を確認する。
- [R3] issuesスキルに原因修復後の再比較と一致確認の完了条件、対象限定local validationとの区別を明記する。

## Acceptance checks
- [R1] `changed:framework/scripts/check-model-cfn.py`
- [R2] `changed:framework/scripts/check-model-cfn.py`
- [R4] `changed:framework/scripts/check-model-cfn.checks.py`
- [R3] `changed:.agents/skills/issues/SKILL.md`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/check-model-cfn.py`
- `framework/scripts/check-model-cfn.checks.py`
- `.agents/skills/issues/SKILL.md`

## Out of scope
- consumer同期、実targetのmodel・設計・IaC・project・issues変更、未確定parameterの補完、AWS API、deploy/apply、scenario、commit/push、issue gateの緩和。
