# VPC Endpoint Name tag必須化

## Task contract

- Task type: `governance`
- Target: framework共通 / EC2.VPCEndpointのName tag・表示契約
- Goal: VPC EndpointのName tagを必須とし、その値を詳細設計の一覧・見出し・通常の参照リンクの表示名として使用する。

## Required changes

- [R1] naming ruleのEndpointをRequiredへ変更し、詳細設計rule・関連promptの必須対象と既存resource取得項目へ追加する。既存patternを維持し、Name tagがなければ推測せず停止する。
- [R2] Endpointは正式なTags[].Key=Nameと対応するTags[].Valueを保持する。設計専用Endpoint.Nameを追加せず、既存4種類の.Name表示、非表示logical ID、desired logical reference／observed identifierの分離を維持する。表示labelで必須tagを代替しない。
- [R3] 共通helperでcase-sensitiveなName keyと対応する確定済みnon-empty Valueを検証し、設計検証・生成へ適用する。表示名由来anchor・参照表示の整合を維持する。
- [R4] focused checksで欠落・不正値の拒否、正常値の受理、表示名・logical ID・observed IDと両経路の同じ判定を確認し、FWサンプル・fixturesを更新する。

## Acceptance checks

- [R1] `changed:framework/rules/aws-resource-naming.md`
- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/prompts/chatbot/service-design.md`
- [R2] `changed:framework/rules/model-information.md`
- [R2] `changed:framework/scripts/design_layout.py`
- [R3] `changed:framework/scripts/validate-blueprint.py`
- [R4] `changed:framework/scripts/model_design.checks.py`
- [R4] `changed:framework/rules/detailed-design-samples.md`

## Allowed paths

- `tasks/active.md`
- `framework/rules/aws-resource-naming.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/rules/loop-engineering.md`
- `framework/rules/detailed-design-samples.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/scripts/design_layout.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/model_design.checks.py`

## Out of scope

- framework/materials/aws/、consumer repositoryのdocs/model/IaC、AWS API、tag付与、deploy/apply、resource rename、既存設計のPending値、scenario、別taskの作成・実行。
- verification outputはtests/results/やtasks/へ保存しない。governance local loopとgit diff --checkを実行し、focused checksと既存設計のName tag不足による失敗を分けて報告する。必須checkが失敗・未実行なら完了扱いにしない。
