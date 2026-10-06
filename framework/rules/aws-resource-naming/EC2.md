# EC2 Resource Naming Rules

Follow the [common rules](../aws-resource-naming.md) for the common scope, exclusions, Name tag policy, and component rules.

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
| Amazon EC2 | Security group | `EC2.SecurityGroup` | `GroupName` | `{{application}}-{{environment}}-{{service}}-{{purpose}}[-{{number}}]-sg` |
| Amazon EC2 | Security group | `EC2.SecurityGroup` | Name tag | `{{application}}-{{environment}}-{{service}}-{{purpose}}[-{{number}}]-sg` |
| Amazon EC2 | Launch template | `EC2.LaunchTemplate` | `LaunchTemplateName` | `aslt-{{application}}-{{environment}}-{{purpose}}-{{number}}` |

## Service-specific constraints

- Amazon EC2 Instance Name tags use application, environment, and purpose in that order. `number` is optional and omitted for a single instance. A two-digit sequence starting at `-01` may be used only when distinguishing multiple instances with the same application, environment, and purpose. Examples: a single instance: `venusinf-stg-vulnerability-scan`; multiple instances with numbering: `venusinf-stg-vulnerability-scan-01`, `venusinf-stg-vulnerability-scan-02`.
- VPC Block Public Access Options have no name property and do not require a naming pattern. Apply the `vbpe` pattern to an Exclusion's `Name` tag only when selected by the human; do not make it mandatory.
- Amazon EC2 security group `GroupName` cannot start with `sg-`, so this rule uses the `-sg` suffix.
- Security group `GroupName` and human-selected Name tags use application, environment, service, and purpose in that order; `number` is optional. Examples: without a number: `app-dev-glue-data-sg`; with a number: `app-dev-glue-data-01-sg`.
