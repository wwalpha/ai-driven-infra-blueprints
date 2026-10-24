"""Check horizontal SG rules, catalog validation, model ownership and references."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import tempfile

import model.projection as model_projection
from design.layout import expanded_design, layout_errors
from design.layout_schema import LAYOUTS
from design.services.ec2.security_groups import (
    COMMENTS,
    DIRECTIONS,
    port_properties,
    security_group_table_lines,
)
from support.model_sources import write_model
from support.validator import load

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

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


GENERATED_MODEL = """# Synthetic authoritative Model fixture.
desired.service.identity.lastAllocated={"EC2.SecurityGroup":2,"EC2.SecurityGroupIngress":3,"EC2.SecurityGroupEgress":1}
desired.service.security-group.serviceId=security-group
desired.service.security-group.ownedCatalogResourceTypes=EC2.SecurityGroup,EC2.SecurityGroupIngress,EC2.SecurityGroupEgress
desired.resource.001.resourceType=EC2.SecurityGroup
desired.resource.001.logicalId=EC2_SecurityGroup_001
desired.resource.001.anchor=resource-EC2_SecurityGroup_001
desired.row.001-001.property=EC2.SecurityGroup.Id
desired.row.001-001.value=[EC2_SecurityGroup_001](security-group.md#resource-EC2_SecurityGroup_001)
desired.row.001-001.comment=一意に識別するID
observed.row.001-001.property=EC2.SecurityGroup.Id
observed.row.001-001.value=`sg-00000001`
observed.row.001-001.comment=一意に識別するID
desired.row.001-002.property=EC2.SecurityGroup.GroupDescription
desired.row.001-002.value=`Application access`
desired.row.001-002.comment=用途の説明
desired.row.001-003.property=EC2.SecurityGroup.GroupName
desired.row.001-003.value=`group-one`
desired.row.001-003.comment=名前
desired.row.001-004.property=EC2.SecurityGroup.VpcId
desired.row.001-004.value=[EC2_VPC_001](vpc.md#resource-EC2_VPC_001)
desired.row.001-004.comment=所属するVPCのID
observed.row.001-004.property=EC2.SecurityGroup.VpcId
observed.row.001-004.value=vpc-00000001
observed.row.001-004.comment=所属するVPCのID
desired.row.001-005.property=EC2.SecurityGroup.SecurityGroupIngress[].IpProtocol
desired.row.001-005.value=`icmp`
desired.row.001-005.comment=通信を許可するIP protocol
desired.row.001-006.property=EC2.SecurityGroup.SecurityGroupIngress[].FromPort
desired.row.001-006.value=`8`
desired.row.001-006.comment=許可するport範囲の開始値、またはICMP type
desired.row.001-007.property=EC2.SecurityGroup.SecurityGroupIngress[].ToPort
desired.row.001-007.value=`0`
desired.row.001-007.comment=許可するport範囲の終了値、またはICMP code
desired.row.001-008.property=EC2.SecurityGroup.SecurityGroupIngress[].CidrIp
desired.row.001-008.value=`10.0.0.0/24`
desired.row.001-008.comment=通信を許可するIPv4アドレス範囲
desired.row.001-009.property=EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol
desired.row.001-009.value=`-1`
desired.row.001-009.comment=通信を許可するIP protocol
desired.row.001-010.property=EC2.SecurityGroup.SecurityGroupEgress[].CidrIp
desired.row.001-010.value=`0.0.0.0/0`
desired.row.001-010.comment=通信を許可するIPv4アドレス範囲
desired.row.001-011.property=EC2.SecurityGroup.SecurityGroupEgress[].Description
desired.row.001-011.value=`IPv4 outbound`
desired.row.001-011.comment=用途の説明
desired.row.001-012.property=EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol
desired.row.001-012.value=`-1`
desired.row.001-012.comment=通信を許可するIP protocol
desired.row.001-013.property=EC2.SecurityGroup.SecurityGroupEgress[].CidrIp
desired.row.001-013.value=`10.1.0.0/16`
desired.row.001-013.comment=通信を許可するIPv4アドレス範囲
desired.resource.002.resourceType=EC2.SecurityGroupIngress
desired.resource.002.logicalId=EC2_SecurityGroupIngress_001
desired.resource.002.anchor=resource-EC2_SecurityGroupIngress_001
desired.resource.002.parentProperty=EC2.SecurityGroupIngress.GroupId
desired.resource.002.parentReference=[EC2_SecurityGroup_001](security-group.md#resource-EC2_SecurityGroup_001)
desired.row.002-001.property=EC2.SecurityGroupIngress.Id
desired.row.002-001.value=[EC2_SecurityGroupIngress_001](security-group.md#resource-EC2_SecurityGroupIngress_001)
desired.row.002-001.comment=一意に識別するID
observed.row.002-001.property=EC2.SecurityGroupIngress.Id
observed.row.002-001.value=`sgr-00000001`
observed.row.002-001.comment=一意に識別するID
desired.row.002-002.property=EC2.SecurityGroupIngress.IpProtocol
desired.row.002-002.value=`tcp`
desired.row.002-002.comment=通信を許可するIP protocol
desired.row.002-003.property=EC2.SecurityGroupIngress.FromPort
desired.row.002-003.value=`443`
desired.row.002-003.comment=許可するport範囲の開始値、またはICMP type
desired.row.002-004.property=EC2.SecurityGroupIngress.ToPort
desired.row.002-004.value=`443`
desired.row.002-004.comment=許可するport範囲の終了値、またはICMP code
desired.row.002-005.property=EC2.SecurityGroupIngress.SourceSecurityGroupId
desired.row.002-005.value=[EC2_SecurityGroup_002](security-group.md#resource-EC2_SecurityGroup_002)
desired.row.002-005.comment=通信元として許可するSecurity GroupのID
observed.row.002-005.property=EC2.SecurityGroupIngress.SourceSecurityGroupId
observed.row.002-005.value=PENDING_DEPLOY
observed.row.002-005.comment=通信元として許可するSecurity GroupのID
desired.row.002-006.property=EC2.SecurityGroupIngress.SourceSecurityGroupOwnerId
desired.row.002-006.value=`123456789012`
desired.row.002-006.comment=通信元Security Groupを所有するAWS account ID
desired.row.002-007.property=EC2.SecurityGroupIngress.Description
desired.row.002-007.value=`Application access`
desired.row.002-007.comment=用途の説明
desired.resource.003.resourceType=EC2.SecurityGroupIngress
desired.resource.003.logicalId=EC2_SecurityGroupIngress_002
desired.resource.003.anchor=resource-EC2_SecurityGroupIngress_002
desired.resource.003.parentProperty=EC2.SecurityGroupIngress.GroupId
desired.resource.003.parentReference=[EC2_SecurityGroup_001](security-group.md#resource-EC2_SecurityGroup_001)
desired.row.003-001.property=EC2.SecurityGroupIngress.Id
desired.row.003-001.value=[EC2_SecurityGroupIngress_002](security-group.md#resource-EC2_SecurityGroupIngress_002)
desired.row.003-001.comment=一意に識別するID
observed.row.003-001.property=EC2.SecurityGroupIngress.Id
observed.row.003-001.value=`PENDING_DEPLOY`
observed.row.003-001.comment=一意に識別するID
desired.row.003-002.property=EC2.SecurityGroupIngress.IpProtocol
desired.row.003-002.value=`icmpv6`
desired.row.003-002.comment=通信を許可するIP protocol
desired.row.003-003.property=EC2.SecurityGroupIngress.FromPort
desired.row.003-003.value=`128`
desired.row.003-003.comment=許可するport範囲の開始値、またはICMP type
desired.row.003-004.property=EC2.SecurityGroupIngress.ToPort
desired.row.003-004.value=`0`
desired.row.003-004.comment=許可するport範囲の終了値、またはICMP code
desired.row.003-005.property=EC2.SecurityGroupIngress.CidrIpv6
desired.row.003-005.value=`2001:db8::/64`
desired.row.003-005.comment=通信を許可するIPv6アドレス範囲
desired.resource.004.resourceType=EC2.SecurityGroupIngress
desired.resource.004.logicalId=EC2_SecurityGroupIngress_003
desired.resource.004.anchor=resource-EC2_SecurityGroupIngress_003
desired.resource.004.parentProperty=EC2.SecurityGroupIngress.GroupId
desired.resource.004.parentReference=[EC2_SecurityGroup_001](security-group.md#resource-EC2_SecurityGroup_001)
desired.row.004-001.property=EC2.SecurityGroupIngress.Id
desired.row.004-001.value=[EC2_SecurityGroupIngress_003](security-group.md#resource-EC2_SecurityGroupIngress_003)
desired.row.004-001.comment=一意に識別するID
observed.row.004-001.property=EC2.SecurityGroupIngress.Id
observed.row.004-001.value=`PENDING_DEPLOY`
observed.row.004-001.comment=一意に識別するID
desired.row.004-002.property=EC2.SecurityGroupIngress.IpProtocol
desired.row.004-002.value=`udp`
desired.row.004-002.comment=通信を許可するIP protocol
desired.row.004-003.property=EC2.SecurityGroupIngress.FromPort
desired.row.004-003.value=`1000`
desired.row.004-003.comment=許可するport範囲の開始値、またはICMP type
desired.row.004-004.property=EC2.SecurityGroupIngress.ToPort
desired.row.004-004.value=`2000`
desired.row.004-004.comment=許可するport範囲の終了値、またはICMP code
desired.row.004-005.property=EC2.SecurityGroupIngress.SourcePrefixListId
desired.row.004-005.value=`pl-00000001`
desired.row.004-005.comment=通信元として許可するPrefix ListのID
desired.row.004-006.property=EC2.SecurityGroupIngress.Description
desired.row.004-006.value=`Prefix Listからの通信`
desired.row.004-006.comment=用途の説明
desired.resource.005.resourceType=EC2.SecurityGroupEgress
desired.resource.005.logicalId=EC2_SecurityGroupEgress_001
desired.resource.005.anchor=resource-EC2_SecurityGroupEgress_001
desired.resource.005.parentProperty=EC2.SecurityGroupEgress.GroupId
desired.resource.005.parentReference=[EC2_SecurityGroup_001](security-group.md#resource-EC2_SecurityGroup_001)
desired.row.005-001.property=EC2.SecurityGroupEgress.Id
desired.row.005-001.value=[EC2_SecurityGroupEgress_001](security-group.md#resource-EC2_SecurityGroupEgress_001)
desired.row.005-001.comment=一意に識別するID
observed.row.005-001.property=EC2.SecurityGroupEgress.Id
observed.row.005-001.value=`PENDING_DEPLOY`
observed.row.005-001.comment=一意に識別するID
desired.row.005-002.property=EC2.SecurityGroupEgress.IpProtocol
desired.row.005-002.value=`-1`
desired.row.005-002.comment=通信を許可するIP protocol
desired.row.005-003.property=EC2.SecurityGroupEgress.DestinationSecurityGroupId
desired.row.005-003.value=[EC2_SecurityGroup_001](security-group.md#resource-EC2_SecurityGroup_001)
desired.row.005-003.comment=通信先として許可するSecurity GroupのID
observed.row.005-003.property=EC2.SecurityGroupEgress.DestinationSecurityGroupId
observed.row.005-003.value=sg-00000001
observed.row.005-003.comment=通信先として許可するSecurity GroupのID
desired.row.005-004.property=EC2.SecurityGroupEgress.Description
desired.row.005-004.value=`Security Group内の通信`
desired.row.005-004.comment=用途の説明
desired.resource.006.resourceType=EC2.SecurityGroup
desired.resource.006.logicalId=EC2_SecurityGroup_002
desired.resource.006.anchor=resource-EC2_SecurityGroup_002
desired.row.006-001.property=EC2.SecurityGroup.Id
desired.row.006-001.value=[EC2_SecurityGroup_002](security-group.md#resource-EC2_SecurityGroup_002)
desired.row.006-001.comment=一意に識別するID
observed.row.006-001.property=EC2.SecurityGroup.Id
observed.row.006-001.value=`PENDING_DEPLOY`
observed.row.006-001.comment=一意に識別するID
desired.row.006-002.property=EC2.SecurityGroup.GroupDescription
desired.row.006-002.value=`No selected rules`
desired.row.006-002.comment=用途の説明
desired.row.006-003.property=EC2.SecurityGroup.GroupName
desired.row.006-003.value=GroupTwo
desired.row.006-003.comment=タグとは独立したCREATEの正式名
desired.row.006-008.property=EC2.SecurityGroup.VpcId
desired.row.006-008.value=[EC2_VPC_001](vpc.md#resource-EC2_VPC_001)
desired.row.006-008.comment=所属するVPCのID
observed.row.006-008.property=EC2.SecurityGroup.VpcId
observed.row.006-008.value=vpc-00000001
observed.row.006-008.comment=所属するVPCのID
desired.row.006-004.property=EC2.SecurityGroup.Tags[].Key
desired.row.006-004.value=Project
desired.row.006-004.comment=付与するタグのキー
desired.row.006-005.property=EC2.SecurityGroup.Tags[].Value
desired.row.006-005.value=app
desired.row.006-005.comment=付与するタグの値
desired.row.006-006.property=EC2.SecurityGroup.Tags[].Key
desired.row.006-006.value=Environment
desired.row.006-006.comment=付与するタグのキー
desired.row.006-007.property=EC2.SecurityGroup.Tags[].Value
desired.row.006-007.value=dev
desired.row.006-007.comment=付与するタグの値
"""
