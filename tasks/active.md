# CodeBuild・CodePipeline・CodeCommitの命名規則

## Task contract

- Task type: `governance`
- Target: framework共通 / AWS resource naming rules
- Goal: humanが採用した4文字prefixによるCodeBuild、CodePipeline、CodeCommitの命名規則を追加する。

## Required changes

- [R1] CodeBuild Projectの`Name`を`cbld-{{application}}-{{environment}}-{{purpose}}`、CodePipeline Pipelineの`Name`を`cpln-{{application}}-{{environment}}-{{purpose}}`、CodeCommit Repositoryの`RepositoryName`を`ccmt-{{application}}[-{{environment}}]-{{purpose}}`として命名表へ追加する。CodeCommitのenvironmentは環境共有repositoryでは省略し、環境別repositoryでは含める。

## Acceptance checks

- [R1] `changed:framework/rules/aws-resource-naming.md`

## Allowed paths

- `tasks/active.md`
- `framework/rules/aws-resource-naming.md`

## Out of scope

- 既存名称の変更、target設計、model、IaC、AWS操作、scenario、catalog、validatorの変更は行わない。
