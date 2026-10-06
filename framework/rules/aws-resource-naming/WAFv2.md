# WAFv2 Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS WAF | Web ACL | `WAFv2.WebACL` | `Name` | `wafacl-{{application}}-{{environment}}-{{purpose}}` |
| AWS WAF | Rule group | `WAFv2.RuleGroup` | `Name` | `wafrg-{{application}}-{{environment}}-{{purpose}}` |
| AWS WAF | IP set | `WAFv2.IPSet` | `Name` | `wafip-{{application}}-{{environment}}-{{purpose}}` |

## Service-specific constraints

- AWS WAF WebACL / RuleGroup / IPSet prefixes are `wafacl` / `wafrg` / `wafip` respectively; all must contain `waf`.
