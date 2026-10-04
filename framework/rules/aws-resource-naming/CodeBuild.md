# CodeBuild Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS CodeBuild | Project | `CodeBuild.Project` | `Name` | `cbld-{{application}}-{{environment}}-{{purpose}}` |
