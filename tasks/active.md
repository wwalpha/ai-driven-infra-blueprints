# env-diffのサービス別要約を簡潔化

## Task contract
- Task type: `governance`
- Target: `.agents/skills/env-diff/SKILL.md`の出力ルール
- Goal: diff.mdをサービスごとの主な差異と未確認事項が分かる短い要約にし、異なる設定を「devは、…」「stgは、…」のように両環境を並べて示す。一致項目・対応確認・根拠リンクを掲載しない。

## Validation scope
- `framework`

## Required changes
- [R1] diff.mdをサービス別の簡潔な要約に統一し、差異ごとに両環境の実値・設定内容・有無を「<environment>は、…」で並べる。一致項目・照合方法・根拠リンクを除き、同じ理由の名称・参照差を集約する。未確認・比較不能範囲は具体的に残す。
- [R2] 全差分、JSON全文、resource対応表、命名確認表、分類別件数の網羅掲載要求を外す。desired比較、IMPORT除外、対応確認、命名・参照判定、保存先とtask境界は維持する。

## Acceptance checks
- [R1] `changed:.agents/skills/env-diff/SKILL.md`
- [R2] `exists:.agents/skills/env-diff/SKILL.md`

## Allowed paths
- `tasks/active.md`
- `.agents/skills/env-diff/SKILL.md`

## Out of scope
- 比較program、共通rule、catalog、consumer同期、既存diff.md、issues.md、model、設計、IaC、project.json、AWS API、deploy/apply、commit、push、別task。

## Completion
- skillのfrontmatterと出力指示の整合を確認し、framework scopeのlocal loopを実行する。
