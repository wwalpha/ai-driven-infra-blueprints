# FMS Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Firewall Manager | Policy | `FMS.Policy` | `PolicyName` | `fmsp-{{application}}-{{environment}}-{{purpose}}` |
