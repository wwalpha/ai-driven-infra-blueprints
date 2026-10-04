# CodeCommit Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS CodeCommit | Repository | `CodeCommit.Repository` | `RepositoryName` | `ccmt-{{application}}[-{{environment}}]-{{purpose}}` |

## Service-specific constraints

- AWS CodeCommit repositoryの`environment`は、環境間で同じrepositoryを共有する場合は省略し、環境ごとにrepositoryを分ける場合は含める。
