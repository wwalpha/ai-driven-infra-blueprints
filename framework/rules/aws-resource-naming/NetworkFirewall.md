# NetworkFirewall Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS Network Firewall | Firewall | `NetworkFirewall.Firewall` | `FirewallName` | `nfwl-{{application}}-{{environment}}-{{purpose}}` |
| AWS Network Firewall | Firewall policy | `NetworkFirewall.FirewallPolicy` | `FirewallPolicyName` | `nfwp-{{application}}-{{environment}}-{{purpose}}` |
| AWS Network Firewall | Rule group | `NetworkFirewall.RuleGroup` | `RuleGroupName` | `nfwr-{{application}}-{{environment}}-{{purpose}}` |
