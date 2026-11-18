"""Fixed ec2 design definitions; no display-engine dependencies."""

import re

REQUIRED_NAME_TAG_TYPES = {"EC2.VPCEndpoint", "EC2.Instance"}

POLICY_FORMATS = {
    "EC2.VPCEndpoint.PolicyDocument": "statement",
}

COLLAPSED_POLICY_DOCUMENTS = {"EC2.VPCEndpoint.PolicyDocument"}

SECURITY_GROUP_TYPES = {
    "EC2.SecurityGroup",
    "EC2.SecurityGroupIngress",
    "EC2.SecurityGroupEgress",
}

EC2_BLOCK_DEVICE = "EC2.Instance.BlockDeviceMappings[]."

EC2_NAME_TAG = re.compile(r"^<!-- ec2-name-tag: (.+?) -->\s*")

SECURITY_GROUP = "EC2.SecurityGroup"

DIRECTIONS = {"Inbound": "Ingress", "Outbound": "Egress"}

TAGS_PREFIX = "<!-- security-group-tags:"

SECURITY_GROUP_ID_PREFIX = "<!-- security-group-id:"

IDENTITY = re.compile(
    r'^(Inbound|Outbound) <a id="([A-Za-z0-9_.-]+)"></a><!-- logical-id: ([A-Za-z0-9][A-Za-z0-9_.-]*) --><!-- rule-id: ([^<>]+) -->$'
)

COMMENTS = {
    "Id": "一意に識別するID",
    "IpProtocol": "通信を許可するIP protocol",
    "FromPort": "許可するport範囲の開始値、またはICMP type",
    "ToPort": "許可するport範囲の終了値、またはICMP code",
    "CidrIp": "通信を許可するIPv4アドレス範囲",
    "CidrIpv6": "通信を許可するIPv6アドレス範囲",
    "SourcePrefixListId": "通信元として許可するPrefix ListのID",
    "SourceSecurityGroupId": "通信元として許可するSecurity GroupのID",
    "SourceSecurityGroupOwnerId": "通信元Security Groupを所有するAWS account ID",
    "DestinationPrefixListId": "通信先として許可するPrefix ListのID",
    "DestinationSecurityGroupId": "通信先として許可するSecurity GroupのID",
    "Description": "用途の説明",
}

GROUP_COMMENTS = {
    "Id": "一意に識別するID",
    "GroupDescription": "用途の説明",
    "GroupName": "名前",
    "VpcId": "所属するVPCのID",
    "Tags[].Key": "付与するタグのキー",
    "Tags[].Value": "付与するタグの値",
}

ADDITIONAL_RESOURCE_NAME_FIELDS = {"EC2.SecurityGroup": ("GroupName",)}
REQUIRED_CREATE_NAME_TYPES = {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}
RULE_TABLE_LAYOUTS = {
    kind: {
        "parent": "EC2.SecurityGroup",
        "parentProperty": "GroupId",
        "maxCount": None,
        "identityProperty": "Id",
        "display": "rule-table",
    }
    for kind in ("EC2.SecurityGroupIngress", "EC2.SecurityGroupEgress")
}

MODEL_ONLY_PROPERTIES = {kind + ".Name" for kind in REQUIRED_CREATE_NAME_TYPES}
REQUIRED_DISPLAY_LINKS = {
    "EC2.SecurityGroup.VpcId": "Security Group VpcId must link to its VPC"
}


CATALOG_EXEMPT_NAMES = {
    "EC2.VPC.Name",
    "EC2.Subnet.Name",
    "EC2.RouteTable.Name",
    "EC2.FlowLog.Name",
}
