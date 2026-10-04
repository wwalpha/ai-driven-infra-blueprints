# WAFv2 Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS WAF | Web ACL | `WAFv2.WebACL` | `Name` | `wafacl-{{application}}-{{environment}}-{{purpose}}` |
| AWS WAF | Rule group | `WAFv2.RuleGroup` | `Name` | `wafrg-{{application}}-{{environment}}-{{purpose}}` |
| AWS WAF | IP set | `WAFv2.IPSet` | `Name` | `wafip-{{application}}-{{environment}}-{{purpose}}` |

## Service-specific constraints

- AWS WAFのWebACL／RuleGroup／IPSetのprefixはそれぞれ`wafacl`／`wafrg`／`wafip`とし、すべて`waf`を含める。
