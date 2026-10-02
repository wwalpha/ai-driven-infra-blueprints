# Security Group・Glueの命名規則追加と名称チェック除外

## Task contract

- Task type: `governance`
- Target: frameworkのAWS resource命名規則と共通命名検証
- Goal: Security Groupの任意Nameタグに既存GroupNameと同じ規則、Glue Catalogにglct規則を追加し、Secrets Manager・Glue Database・Glue Tableの名称を命名規則チェック対象外にする。

## Validation scope

- `framework`

## Required changes

- [R1] `EC2.SecurityGroup`のName tagへGroupNameと同じpatternを登録し、`Glue.Catalog.Name`へ`glct-{{application}}-{{environment}}-{{purpose}}`を登録する。
- [R2] `SecretsManager.Secret.Name`、`Glue.Database.DatabaseInput.Name`、`Glue.Table.TableInput.Name`を命名規則coverage checkから除外する。提示された名称形式とTableの業務名保持をruleへ記載し、名称確定・provider schema・Name tagの検証は維持する。
- [R3] 追加規則と除外のformal/short property、生成・設計検証、除外境界の回帰checkを実行する。

## Acceptance checks

- [R1] `changed:framework/rules/aws-resource-naming.md`
- [R2] `changed:framework/scripts/model_design.py`
- [R3] `changed:framework/scripts/model_design.checks.py`
- [R3] `check:framework.focused-check-runner`

## Allowed paths

- `tasks/active.md`
- `framework/rules/aws-resource-naming.md`
- `framework/scripts/model_design.py`
- `framework/scripts/model_design.checks.py`

## Out of scope

- consumer repository、既存design/model、IaC、project.json、catalog/lock、scenario/resultは変更しない。
- Security GroupのName tagを必須化せず、既存名称を自動変更しない。
- AWS API、deploy/apply、別task作成・実行へ進まない。
- 対応するfocused checksを含むgovernance local loopと差分checkを実行して終了する。
