# NetworkFirewall Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Network Firewall | Firewall | `NetworkFirewall.Firewall` | `FirewallName` | `nfwl-{{application}}-{{environment}}-{{purpose}}` |
| AWS Network Firewall | Firewall policy | `NetworkFirewall.FirewallPolicy` | `FirewallPolicyName` | `nfwp-{{application}}-{{environment}}-{{purpose}}` |
| AWS Network Firewall | Rule group | `NetworkFirewall.RuleGroup` | `RuleGroupName` | `nfwr-{{application}}-{{environment}}-{{purpose}}` |
