# EC2 Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| Amazon VPC | VPC | `EC2.VPC` | `EC2.VPC.Name` | `vpc-{{application}}-{{environment}}` |
| Amazon VPC | Subnet | `EC2.Subnet` | `EC2.Subnet.Name` | `sbnt-{{application}}-{{environment}}-{{subnet_type}}-{{route_type}}-{{zone}}-{{number}}` |
| Amazon VPC | Route table | `EC2.RouteTable` | `EC2.RouteTable.Name` | `rtb-{{application}}-{{environment}}-{{subnet_type}}-{{route_type}}[-{{zone}}]-{{number}}` |
| Amazon VPC | Flow Log | `EC2.FlowLog` | `EC2.FlowLog.Name` | `flowlog-{{application}}-{{environment}}[-{{target_alias}}]` |
| Amazon VPC | VPC peering connection | `EC2.VPCPeeringConnection` | Name tag | `pcx-{{requester_vpc}}-to-{{accepter_vpc}}-{{number}}` |
| Amazon VPC | Internet gateway | `EC2.InternetGateway` | Name tag | `igw-{{application}}-{{environment}}` |
| Amazon VPC | VPC endpoint | `EC2.VPCEndpoint` | Name tag | `vpce-{{application}}-{{environment}}-{{service}}` |
| Amazon VPC | Block Public Access exclusion | `EC2.VPCBlockPublicAccessExclusion` | Name tag | `vbpe-{{application}}-{{environment}}-{{purpose}}` |
| Amazon VPC | NAT gateway | `EC2.NatGateway` | Name tag | `natgw-{{application}}-{{environment}}-{{zone}}` |
| Amazon VPC | Elastic IP address | `EC2.EIP` | Name tag | `eip-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon VPC | Transit gateway | `EC2.TransitGateway` | Name tag | `tgw-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon VPC | Transit gateway attachment | `EC2.TransitGatewayVpcAttachment` | Name tag | `tgwa-{{application}}-{{environment}}-{{vpc_token}}-{{number}}` |
| Amazon VPC | Transit gateway route table | `EC2.TransitGatewayRouteTable` | Name tag | `tgwrtb-{{application}}-{{environment}}-{{purpose}}-{{number}}` |
| Amazon VPC | Workload transit gateway attachment | `EC2.TransitGatewayVpcAttachment` | Name tag | `tgwa-{{account_id}}-{{target_alias}}` |
| Amazon VPC | Workload transit gateway route table | `EC2.TransitGatewayRouteTable` | Name tag | `tgwrtb-{{account_id}}-{{target_alias}}` |
| Amazon VPC | Customer gateway | `EC2.CustomerGateway` | Name tag | `cgw-{{dc_location}}-{{number}}` |
| Amazon VPC | Site-to-Site VPN connection | `EC2.VPNConnection` | Name tag | `s2s-{{dc_location}}-{{number}}` |
| Amazon EC2 | Instance | `EC2.Instance` | Name tag | `{{application}}-{{environment}}-{{purpose}}[-{{number}}]` |
| Amazon EC2 | Security group | `EC2.SecurityGroup` | `GroupName` | `{{environment}}-{{application}}-{{service}}-{{purpose}}-{{number}}-sg` |
| Amazon EC2 | Security group | `EC2.SecurityGroup` | Name tag | `{{environment}}-{{application}}-{{service}}-{{purpose}}-{{number}}-sg` |
| Amazon EC2 | Launch template | `EC2.LaunchTemplate` | `LaunchTemplateName` | `aslt-{{application}}-{{environment}}-{{purpose}}-{{number}}` |

## Service-specific constraints

- Amazon EC2 InstanceのName tagはapplication・environment・purposeの順とする。`number`はoptionalとし、単体では省略する。同じapplication・environment・purposeの複数台を区別する場合だけ、`-01`からの2桁連番を使用できる。例：単体は`venusinf-stg-vulnerability-scan`、複数台で番号を使用する場合は`venusinf-stg-vulnerability-scan-01`、`venusinf-stg-vulnerability-scan-02`。
- VPC Block Public Access Optionsは名称propertyを持たないため命名patternを要求しない。Exclusionの`Name` tagはhumanが選択した場合だけ`vbpe` patternを適用し、必須化しない。
- Amazon EC2 security groupの`GroupName`は`sg-`で開始できないため、このruleでは`-sg` suffixを使う。
