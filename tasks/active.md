# Glue Job・SecurityConfigurationの命名ルールを追加する

## Task contract

- Task type: `governance`
- Target: framework共通 / Glue.Job.Name、Glue.SecurityConfiguration.Name
- Goal: 承認されたglue／glsc prefixの命名patternをtarget_aliasなしで命名表へ追加する。

## Required changes

- [R1] Glue.Job.Nameをglue-{{application}}-{{environment}}-{{purpose}}、Glue.SecurityConfiguration.Nameをglsc-{{application}}-{{environment}}-{{purpose}}として登録する。
- [R2] 両名称をlower-kebab-case・1〜255文字とし、purposeはhuman-confirmedな用途識別tokenであることを明記する。

## Acceptance checks

- [R1] `changed:framework/rules/aws-resource-naming.md`
- [R2] `changed:framework/rules/aws-resource-naming.md`

## Allowed paths

- `tasks/active.md`
- `framework/rules/aws-resource-naming.md`

## Out of scope

- 指定2 property以外の命名ルール、validator実装、catalog/provider schema、consumer repository、docs/modelの設計値、IaC、AWS API、deploy/apply、scenario、別taskの作成・実行。
- 既存のresource名と詳細設計の名称は変更しない。
- governance local loopとgit diff --checkを実行する。verification outputは完了報告だけに記載する。
