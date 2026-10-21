"""Check horizontal SG rules, catalog validation, model ownership and references."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from support.model_sources import write_model

import model.projection as model_projection

import tempfile

from support.validator import load

from design_layout import LAYOUTS, expanded_design, layout_errors

from security_group_tables import COMMENTS, DIRECTIONS, port_properties, security_group_table_lines

REPOSITORY = Path(__file__).resolve().parents[4]

VALIDATOR = load("validate-blueprint")

DESIGN = """# Security Group 詳細設計

- Design service ID: `security-group`
- Owned catalog resource types: `EC2.SecurityGroup`, `EC2.SecurityGroupIngress`, `EC2.SecurityGroupEgress`

## リソース一覧

### EC2.SecurityGroup

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [GroupOne](#resource-EC2_SecurityGroup_001) | アプリケーションの通信を制御するSG |
| 2 | [GroupTwo](#resource-EC2_SecurityGroup_002) | アプリケーションの通信を制御するSG |

## リソース詳細

<!-- resource-logical-id: EC2_SecurityGroup_001 -->
<a id="resource-EC2_SecurityGroup_001"></a>

### EC2.SecurityGroup: GroupOne

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Id | `sg-00000001` | 一意に識別するID |
| 2 | GroupDescription | `Application access` | 用途の説明 |
| 3 | GroupName | `group-one` | 名前 |
| 4 | VpcId | [vpc-00000001](vpc.md#vpc-vpc-app-dev) | 所属するVPCのID |

| Direction | IpProtocol | Port | CidrIp | CidrIpv6 | SourcePrefixListId | SourceSecurityGroupOwnerId | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Inbound <a id="resource-EC2_SecurityGroupIngress_001"></a><!-- logical-id: EC2_SecurityGroupIngress_001 --><!-- rule-id: `sgr-00000001` --> <!-- security-group-id: [PENDING_DEPLOY](#resource-EC2_SecurityGroup_002) --> | `tcp` | `443` | — | — | — | `123456789012` | `Application access` |
| Inbound <a id="resource-EC2_SecurityGroupIngress_002"></a><!-- logical-id: EC2_SecurityGroupIngress_002 --><!-- rule-id: `PENDING_DEPLOY` --> | `icmpv6` | `Type=128, Code=0` | — | `2001:db8::/64` | — | — | — |
| Inbound <a id="resource-EC2_SecurityGroupIngress_003"></a><!-- logical-id: EC2_SecurityGroupIngress_003 --><!-- rule-id: `PENDING_DEPLOY` --> | `udp` | `1000-2000` | — | — | `pl-00000001` | — | `Prefix Listからの通信` |
| Inbound | `icmp` | `Type=8, Code=0` | `10.0.0.0/24` | — | — | — | — |
| Outbound <a id="resource-EC2_SecurityGroupEgress_001"></a><!-- logical-id: EC2_SecurityGroupEgress_001 --><!-- rule-id: `PENDING_DEPLOY` --> <!-- security-group-id: [sg-00000001](#resource-EC2_SecurityGroup_001) --> | `-1` | — | — | — | — | — | `Security Group内の通信` |
| Outbound | `-1` | — | `0.0.0.0/0` | — | — | — | `IPv4 outbound` |
| Outbound | `-1` | — | `10.1.0.0/16` | — | — | — | — |

<!-- resource-logical-id: EC2_SecurityGroup_002 -->
<a id="resource-EC2_SecurityGroup_002"></a>

### EC2.SecurityGroup: GroupTwo

<!-- security-group-tags: [{"Key":"Project","Value":"app"},{"Key":"Environment","Value":"dev"}] -->

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Id | `PENDING_DEPLOY` | 一意に識別するID |
| 2 | GroupDescription | `No selected rules` | 用途の説明 |
| 3 | VpcId | [vpc-00000001](vpc.md#vpc-vpc-app-dev) | 所属するVPCのID |

"""

VPC_DESIGN = """# Amazon VPC 詳細設計

- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`

## リソース一覧

### EC2.VPC

| No. | ResourceName | Comment |
| ---: | --- | --- |
| 1 | [vpc-app-dev](#vpc-vpc-app-dev) | アプリケーションのネットワーク |

## リソース詳細

<a id="vpc-vpc-app-dev"></a>

### EC2.VPC: vpc-app-dev

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | Name | vpc-app-dev | VPCを識別する名前 |
| 2 | VpcId | `vpc-00000001` | VPCを一意に識別するID |
| 3 | CidrBlock | `10.0.0.0/16` | VPCで使用するIPv4アドレス範囲 |
"""


__all__ = ['COMMENTS', 'DESIGN', 'DIRECTIONS', 'LAYOUTS', 'Path', 'REPOSITORY', 'VALIDATOR', 'VPC_DESIGN', 'expanded_design', 'layout_errors', 'load', 'model_projection', 'port_properties', 'security_group_table_lines', 'sys', 'tempfile', 'write_model']
