"""Static EC2 comparison methods; container rules include their recursive contents."""

import re
from functools import partial

from utils.cloudformation.inputs import Blocked, output_value, resolve_value
from utils.iac_values import ResourceReference
from utils.reference_contracts import CONTEXT_PROPERTIES, row_contexts

from ..contracts import ResourceContract
from ..methods import properties


def ref_attribute(vpc, document, parameters, pseudo, resource_type, evaluate):
    condition_inputs = {
        key: value
        for key, value in parameters.items()
        if value not in ("PENDING_DEPLOY", "UNSET", "TODO", "TBD", "未確定")
    }
    vpc = output_value(document, condition_inputs, pseudo, vpc)
    if isinstance(vpc, dict) and set(vpc) == {"Fn::Sub"}:
        argument = vpc["Fn::Sub"]
        if isinstance(argument, str):
            match = re.fullmatch(r"\$\{([A-Za-z][A-Za-z0-9]*)\}", argument)
            if match:
                vpc = {"Ref": match.group(1)}
        elif isinstance(argument, list) and len(argument) == 2:
            template, mapping = argument
            if isinstance(template, str) and isinstance(mapping, dict):
                match = re.fullmatch(r"\$\{([A-Za-z][A-Za-z0-9]*)\}", template)
                if match and set(mapping) == {match.group(1)}:
                    value = mapping[match.group(1)]
                    if isinstance(value, dict) and set(value) == {"Ref"}:
                        vpc = value
    if isinstance(vpc, dict) and set(vpc) == {"Fn::Join"}:
        argument = vpc["Fn::Join"]
        if (
            isinstance(argument, list)
            and len(argument) == 2
            and argument[0] == ""
            and isinstance(argument[1], list)
            and len(argument[1]) == 1
            and isinstance(argument[1][0], dict)
            and set(argument[1][0]) == {"Ref"}
        ):
            vpc = argument[1][0]
    if isinstance(vpc, dict) and len(vpc) == 1:
        definitions = document.get("Parameters", {})
        if not isinstance(definitions, dict):
            definitions = {}
        if "Ref" in vpc:
            name = vpc["Ref"]
            if (
                isinstance(name, str)
                and parameters.get(name) == "PENDING_DEPLOY"
                and isinstance(definitions.get(name), dict)
                and definitions[name].get("Type") in {"String", "AWS::EC2::VPC::Id"}
            ):
                return "GroupId"
        if "Fn::ImportValue" in vpc:
            argument = vpc["Fn::ImportValue"]
            name = evaluate(argument)
            declared = {
                key: value
                for key, value in condition_inputs.items()
                if key in definitions
            }
            if (
                not isinstance(name, str)
                or not name
                or name in {"PENDING_DEPLOY", "UNSET", "TODO", "TBD", "未確定"}
                or resolve_value(
                    argument,
                    declared,
                    pseudo,
                    conditions=document.get("Conditions", {}),
                )
                != name
            ):
                raise Blocked("ImportValue name is unresolved")
            try:
                vpc = evaluate(vpc)
            except Blocked as error:
                cause = getattr(error, "iac_cause", {})
                if (
                    cause.get("kind") == "import-unresolved"
                    and cause.get("matches") == 0
                ):
                    return "GroupId"
                raise
        elif "Fn::Sub" in vpc:
            argument = vpc["Fn::Sub"]
            if (
                isinstance(argument, list)
                and len(argument) == 2
                and isinstance(argument[1], dict)
            ):
                mapping = {
                    key: output_value(document, condition_inputs, pseudo, value)
                    for key, value in argument[1].items()
                }
                for value in mapping.values():
                    evaluate(value)
                vpc = {"Fn::Sub": [argument[0], mapping]}
            result = evaluate(vpc)
            substitutions = {
                key: "a" if value == "PENDING_DEPLOY" else value
                for key, value in parameters.items()
                if isinstance(definitions.get(key), dict)
                and definitions[key].get("Type") in {"String", "AWS::EC2::VPC::Id"}
            }
            if isinstance(result, str) and "PENDING_DEPLOY" in result:
                result = resolve_value(
                    vpc,
                    substitutions,
                    pseudo,
                    conditions=document.get("Conditions", {}),
                )
            vpc = result
        else:
            vpc = evaluate(vpc)
    else:
        vpc = evaluate(vpc)
    if isinstance(vpc, ResourceReference):
        confirmed = resource_type(vpc) == "EC2.VPC" and vpc["$attribute"] == "VpcId"
    else:
        confirmed = isinstance(vpc, str) and re.fullmatch(r"vpc-[0-9a-f]+", vpc)
    if not confirmed:
        raise Blocked(
            "SecurityGroup Ref requires a proven explicit VpcId; group name is not a group ID"
        )
    return "GroupId"


RULES = {
    "EC2.EIP": properties(
        objects="""
            Tags[]
        """,
        scalars="""
            Domain
            NetworkBorderGroup
            PublicIpv4Pool
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.FlowLog": properties(
        resource=ResourceContract(
            name_tag=True,
            contexts=partial(row_contexts, "EC2.FlowLog"),
            context_properties={
                "ResourceId": {
                    CONTEXT_PROPERTIES["EC2.FlowLog.ResourceId"][0].rsplit(".", 1)[1]
                }
            },
        ),
        objects="""
            DestinationOptions
            TagFieldSpecifications[]
            Tags[]
        """,
        ordered="""
            TagFieldSpecifications
            TagFieldSpecifications[].TagKeys
        """,
        references="""
            LogGroupName
        """,
        scalars="""
            DeliverCrossAccountRole
            DeliverLogsPermissionArn
            DestinationOptions.FileFormat
            DestinationOptions.HiveCompatiblePartitions
            DestinationOptions.PerHourPartition
            LogDestination
            LogDestinationType
            LogFormat
            MaxAggregationInterval
            ResourceId
            ResourceType
            TagFieldSpecifications[].ResourceType
            Tags[].Key
            Tags[].Value
            TrafficType
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.Instance": properties(
        objects="""
            BlockDeviceMappings[]
            BlockDeviceMappings[].Ebs
            BlockDeviceMappings[].NoDevice
            CpuOptions
            MetadataOptions
            NetworkInterfaces[]
            NetworkInterfaces[].PrivateIpAddresses[]
            PrivateDnsNameOptions
            Tags[]
        """,
        ordered="""
            BlockDeviceMappings
            NetworkInterfaces
            NetworkInterfaces[].GroupSet
            NetworkInterfaces[].PrivateIpAddresses
            SecurityGroupIds
        """,
        references="""
            BlockDeviceMappings[].Ebs.KmsKeyId
            IamInstanceProfile
            SubnetId
        """,
        scalars="""
            AvailabilityZone
            BlockDeviceMappings[].DeviceName
            BlockDeviceMappings[].Ebs.DeleteOnTermination
            BlockDeviceMappings[].Ebs.Encrypted
            BlockDeviceMappings[].Ebs.Iops
            BlockDeviceMappings[].Ebs.SnapshotId
            BlockDeviceMappings[].Ebs.VolumeSize
            BlockDeviceMappings[].Ebs.VolumeType
            BlockDeviceMappings[].VirtualName
            CpuOptions.CoreCount
            CpuOptions.ThreadsPerCore
            DisableApiTermination
            EbsOptimized
            ImageId
            InstanceInitiatedShutdownBehavior
            InstanceType
            KeyName
            MetadataOptions.HttpEndpoint
            MetadataOptions.HttpProtocolIpv6
            MetadataOptions.HttpPutResponseHopLimit
            MetadataOptions.HttpTokens
            MetadataOptions.InstanceMetadataTags
            Monitoring
            NetworkInterfaces[].AssociatePublicIpAddress
            NetworkInterfaces[].DeleteOnTermination
            NetworkInterfaces[].Description
            NetworkInterfaces[].DeviceIndex
            NetworkInterfaces[].NetworkInterfaceId
            NetworkInterfaces[].PrivateIpAddress
            NetworkInterfaces[].PrivateIpAddresses[].Primary
            NetworkInterfaces[].PrivateIpAddresses[].PrivateIpAddress
            NetworkInterfaces[].SecondaryPrivateIpAddressCount
            NetworkInterfaces[].SubnetId
            PrivateDnsNameOptions.EnableResourceNameDnsAAAARecord
            PrivateDnsNameOptions.EnableResourceNameDnsARecord
            PrivateDnsNameOptions.HostnameType
            PrivateIpAddress
            PropagateTagsToVolumeOnCreation
            SourceDestCheck
            Tags[].Key
            Tags[].Value
            Tenancy
            UserData
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.InternetGateway": properties(
        objects="""
            Tags[]
        """,
        scalars="""
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.LaunchTemplate": properties(
        objects="""
            LaunchTemplateData
            LaunchTemplateData.BlockDeviceMappings[]
            LaunchTemplateData.BlockDeviceMappings[].Ebs
            LaunchTemplateData.CapacityReservationSpecification
            LaunchTemplateData.CapacityReservationSpecification.CapacityReservationTarget
            LaunchTemplateData.CpuOptions
            LaunchTemplateData.CreditSpecification
            LaunchTemplateData.EnclaveOptions
            LaunchTemplateData.HibernationOptions
            LaunchTemplateData.IamInstanceProfile
            LaunchTemplateData.InstanceMarketOptions
            LaunchTemplateData.InstanceMarketOptions.SpotOptions
            LaunchTemplateData.InstanceRequirements
            LaunchTemplateData.InstanceRequirements.AcceleratorCount
            LaunchTemplateData.InstanceRequirements.AcceleratorTotalMemoryMiB
            LaunchTemplateData.InstanceRequirements.BaselineEbsBandwidthMbps
            LaunchTemplateData.InstanceRequirements.BaselinePerformanceFactors
            LaunchTemplateData.InstanceRequirements.BaselinePerformanceFactors.Cpu
            LaunchTemplateData.InstanceRequirements.BaselinePerformanceFactors.Cpu.References[]
            LaunchTemplateData.InstanceRequirements.MemoryGiBPerVCpu
            LaunchTemplateData.InstanceRequirements.MemoryMiB
            LaunchTemplateData.InstanceRequirements.NetworkBandwidthGbps
            LaunchTemplateData.InstanceRequirements.NetworkInterfaceCount
            LaunchTemplateData.InstanceRequirements.TotalLocalStorageGB
            LaunchTemplateData.InstanceRequirements.VCpuCount
            LaunchTemplateData.LicenseSpecifications[]
            LaunchTemplateData.MaintenanceOptions
            LaunchTemplateData.MetadataOptions
            LaunchTemplateData.Monitoring
            LaunchTemplateData.NetworkInterfaces[]
            LaunchTemplateData.NetworkInterfaces[].ConnectionTrackingSpecification
            LaunchTemplateData.NetworkInterfaces[].EnaSrdSpecification
            LaunchTemplateData.NetworkInterfaces[].EnaSrdSpecification.EnaSrdUdpSpecification
            LaunchTemplateData.NetworkInterfaces[].Ipv4Prefixes[]
            LaunchTemplateData.NetworkInterfaces[].Ipv6Addresses[]
            LaunchTemplateData.NetworkInterfaces[].Ipv6Prefixes[]
            LaunchTemplateData.NetworkInterfaces[].PrivateIpAddresses[]
            LaunchTemplateData.NetworkPerformanceOptions
            LaunchTemplateData.Placement
            LaunchTemplateData.PrivateDnsNameOptions
            LaunchTemplateData.TagSpecifications[]
            LaunchTemplateData.TagSpecifications[].Tags[]
            TagSpecifications[]
            TagSpecifications[].Tags[]
        """,
        ordered="""
            LaunchTemplateData.BlockDeviceMappings
            LaunchTemplateData.InstanceRequirements.AcceleratorManufacturers
            LaunchTemplateData.InstanceRequirements.AcceleratorNames
            LaunchTemplateData.InstanceRequirements.AcceleratorTypes
            LaunchTemplateData.InstanceRequirements.AllowedInstanceTypes
            LaunchTemplateData.InstanceRequirements.BaselinePerformanceFactors.Cpu.References
            LaunchTemplateData.InstanceRequirements.CpuManufacturers
            LaunchTemplateData.InstanceRequirements.ExcludedInstanceTypes
            LaunchTemplateData.InstanceRequirements.InstanceGenerations
            LaunchTemplateData.InstanceRequirements.LocalStorageTypes
            LaunchTemplateData.LicenseSpecifications
            LaunchTemplateData.NetworkInterfaces
            LaunchTemplateData.NetworkInterfaces[].Groups
            LaunchTemplateData.NetworkInterfaces[].Ipv4Prefixes
            LaunchTemplateData.NetworkInterfaces[].Ipv6Addresses
            LaunchTemplateData.NetworkInterfaces[].Ipv6Prefixes
            LaunchTemplateData.NetworkInterfaces[].PrivateIpAddresses
            LaunchTemplateData.SecurityGroupIds
            LaunchTemplateData.SecurityGroups
            LaunchTemplateData.TagSpecifications
            TagSpecifications
        """,
        scalars="""
            LaunchTemplateData.BlockDeviceMappings[].DeviceName
            LaunchTemplateData.BlockDeviceMappings[].Ebs.DeleteOnTermination
            LaunchTemplateData.BlockDeviceMappings[].Ebs.EbsCardIndex
            LaunchTemplateData.BlockDeviceMappings[].Ebs.Encrypted
            LaunchTemplateData.BlockDeviceMappings[].Ebs.Iops
            LaunchTemplateData.BlockDeviceMappings[].Ebs.KmsKeyId
            LaunchTemplateData.BlockDeviceMappings[].Ebs.SnapshotId
            LaunchTemplateData.BlockDeviceMappings[].Ebs.Throughput
            LaunchTemplateData.BlockDeviceMappings[].Ebs.VolumeInitializationRate
            LaunchTemplateData.BlockDeviceMappings[].Ebs.VolumeSize
            LaunchTemplateData.BlockDeviceMappings[].Ebs.VolumeType
            LaunchTemplateData.BlockDeviceMappings[].NoDevice
            LaunchTemplateData.BlockDeviceMappings[].VirtualName
            LaunchTemplateData.CapacityReservationSpecification.CapacityReservationPreference
            LaunchTemplateData.CapacityReservationSpecification.CapacityReservationTarget.CapacityReservationId
            LaunchTemplateData.CapacityReservationSpecification.CapacityReservationTarget.CapacityReservationResourceGroupArn
            LaunchTemplateData.CpuOptions.AmdSevSnp
            LaunchTemplateData.CpuOptions.CoreCount
            LaunchTemplateData.CpuOptions.NestedVirtualization
            LaunchTemplateData.CpuOptions.ThreadsPerCore
            LaunchTemplateData.CreditSpecification.CpuCredits
            LaunchTemplateData.DisableApiStop
            LaunchTemplateData.DisableApiTermination
            LaunchTemplateData.EbsOptimized
            LaunchTemplateData.EnclaveOptions.Enabled
            LaunchTemplateData.HibernationOptions.Configured
            LaunchTemplateData.IamInstanceProfile.Arn
            LaunchTemplateData.IamInstanceProfile.Name
            LaunchTemplateData.ImageId
            LaunchTemplateData.InstanceInitiatedShutdownBehavior
            LaunchTemplateData.InstanceMarketOptions.MarketType
            LaunchTemplateData.InstanceMarketOptions.SpotOptions.BlockDurationMinutes
            LaunchTemplateData.InstanceMarketOptions.SpotOptions.InstanceInterruptionBehavior
            LaunchTemplateData.InstanceMarketOptions.SpotOptions.MaxPrice
            LaunchTemplateData.InstanceMarketOptions.SpotOptions.SpotInstanceType
            LaunchTemplateData.InstanceMarketOptions.SpotOptions.ValidUntil
            LaunchTemplateData.InstanceRequirements.AcceleratorCount.Max
            LaunchTemplateData.InstanceRequirements.AcceleratorCount.Min
            LaunchTemplateData.InstanceRequirements.AcceleratorManufacturers[]
            LaunchTemplateData.InstanceRequirements.AcceleratorNames[]
            LaunchTemplateData.InstanceRequirements.AcceleratorTotalMemoryMiB.Max
            LaunchTemplateData.InstanceRequirements.AcceleratorTotalMemoryMiB.Min
            LaunchTemplateData.InstanceRequirements.AcceleratorTypes[]
            LaunchTemplateData.InstanceRequirements.AllowedInstanceTypes[]
            LaunchTemplateData.InstanceRequirements.BareMetal
            LaunchTemplateData.InstanceRequirements.BaselineEbsBandwidthMbps.Max
            LaunchTemplateData.InstanceRequirements.BaselineEbsBandwidthMbps.Min
            LaunchTemplateData.InstanceRequirements.BaselinePerformanceFactors.Cpu.References[].InstanceFamily
            LaunchTemplateData.InstanceRequirements.BurstablePerformance
            LaunchTemplateData.InstanceRequirements.CpuManufacturers[]
            LaunchTemplateData.InstanceRequirements.ExcludedInstanceTypes[]
            LaunchTemplateData.InstanceRequirements.InstanceGenerations[]
            LaunchTemplateData.InstanceRequirements.LocalStorage
            LaunchTemplateData.InstanceRequirements.LocalStorageTypes[]
            LaunchTemplateData.InstanceRequirements.MaxSpotPriceAsPercentageOfOptimalOnDemandPrice
            LaunchTemplateData.InstanceRequirements.MemoryGiBPerVCpu.Max
            LaunchTemplateData.InstanceRequirements.MemoryGiBPerVCpu.Min
            LaunchTemplateData.InstanceRequirements.MemoryMiB.Max
            LaunchTemplateData.InstanceRequirements.MemoryMiB.Min
            LaunchTemplateData.InstanceRequirements.NetworkBandwidthGbps.Max
            LaunchTemplateData.InstanceRequirements.NetworkBandwidthGbps.Min
            LaunchTemplateData.InstanceRequirements.NetworkInterfaceCount.Max
            LaunchTemplateData.InstanceRequirements.NetworkInterfaceCount.Min
            LaunchTemplateData.InstanceRequirements.OnDemandMaxPricePercentageOverLowestPrice
            LaunchTemplateData.InstanceRequirements.RequireHibernateSupport
            LaunchTemplateData.InstanceRequirements.SpotMaxPricePercentageOverLowestPrice
            LaunchTemplateData.InstanceRequirements.TotalLocalStorageGB.Max
            LaunchTemplateData.InstanceRequirements.TotalLocalStorageGB.Min
            LaunchTemplateData.InstanceRequirements.VCpuCount.Max
            LaunchTemplateData.InstanceRequirements.VCpuCount.Min
            LaunchTemplateData.InstanceType
            LaunchTemplateData.KernelId
            LaunchTemplateData.KeyName
            LaunchTemplateData.LicenseSpecifications[].LicenseConfigurationArn
            LaunchTemplateData.MaintenanceOptions.AutoRecovery
            LaunchTemplateData.MetadataOptions.HttpEndpoint
            LaunchTemplateData.MetadataOptions.HttpProtocolIpv6
            LaunchTemplateData.MetadataOptions.HttpPutResponseHopLimit
            LaunchTemplateData.MetadataOptions.HttpTokens
            LaunchTemplateData.MetadataOptions.InstanceMetadataTags
            LaunchTemplateData.Monitoring.Enabled
            LaunchTemplateData.NetworkInterfaces[].AssociateCarrierIpAddress
            LaunchTemplateData.NetworkInterfaces[].AssociatePublicIpAddress
            LaunchTemplateData.NetworkInterfaces[].ConnectionTrackingSpecification.TcpEstablishedTimeout
            LaunchTemplateData.NetworkInterfaces[].ConnectionTrackingSpecification.UdpStreamTimeout
            LaunchTemplateData.NetworkInterfaces[].ConnectionTrackingSpecification.UdpTimeout
            LaunchTemplateData.NetworkInterfaces[].DeleteOnTermination
            LaunchTemplateData.NetworkInterfaces[].Description
            LaunchTemplateData.NetworkInterfaces[].DeviceIndex
            LaunchTemplateData.NetworkInterfaces[].EnaQueueCount
            LaunchTemplateData.NetworkInterfaces[].EnaSrdSpecification.EnaSrdEnabled
            LaunchTemplateData.NetworkInterfaces[].EnaSrdSpecification.EnaSrdUdpSpecification.EnaSrdUdpEnabled
            LaunchTemplateData.NetworkInterfaces[].Groups[]
            LaunchTemplateData.NetworkInterfaces[].InterfaceType
            LaunchTemplateData.NetworkInterfaces[].Ipv4PrefixCount
            LaunchTemplateData.NetworkInterfaces[].Ipv4Prefixes[].Ipv4Prefix
            LaunchTemplateData.NetworkInterfaces[].Ipv6AddressCount
            LaunchTemplateData.NetworkInterfaces[].Ipv6Addresses[].Ipv6Address
            LaunchTemplateData.NetworkInterfaces[].Ipv6PrefixCount
            LaunchTemplateData.NetworkInterfaces[].Ipv6Prefixes[].Ipv6Prefix
            LaunchTemplateData.NetworkInterfaces[].NetworkCardIndex
            LaunchTemplateData.NetworkInterfaces[].NetworkInterfaceId
            LaunchTemplateData.NetworkInterfaces[].PrimaryIpv6
            LaunchTemplateData.NetworkInterfaces[].PrivateIpAddress
            LaunchTemplateData.NetworkInterfaces[].PrivateIpAddresses[].Primary
            LaunchTemplateData.NetworkInterfaces[].PrivateIpAddresses[].PrivateIpAddress
            LaunchTemplateData.NetworkInterfaces[].SecondaryPrivateIpAddressCount
            LaunchTemplateData.NetworkInterfaces[].SubnetId
            LaunchTemplateData.NetworkPerformanceOptions.BandwidthWeighting
            LaunchTemplateData.Placement.Affinity
            LaunchTemplateData.Placement.AvailabilityZone
            LaunchTemplateData.Placement.GroupId
            LaunchTemplateData.Placement.GroupName
            LaunchTemplateData.Placement.HostId
            LaunchTemplateData.Placement.HostResourceGroupArn
            LaunchTemplateData.Placement.PartitionNumber
            LaunchTemplateData.Placement.SpreadDomain
            LaunchTemplateData.Placement.Tenancy
            LaunchTemplateData.PrivateDnsNameOptions.EnableResourceNameDnsAAAARecord
            LaunchTemplateData.PrivateDnsNameOptions.EnableResourceNameDnsARecord
            LaunchTemplateData.PrivateDnsNameOptions.HostnameType
            LaunchTemplateData.RamDiskId
            LaunchTemplateData.SecurityGroupIds[]
            LaunchTemplateData.SecurityGroups[]
            LaunchTemplateData.TagSpecifications[].ResourceType
            LaunchTemplateData.TagSpecifications[].Tags[].Key
            LaunchTemplateData.TagSpecifications[].Tags[].Value
            LaunchTemplateData.UserData
            LaunchTemplateName
            TagSpecifications[].ResourceType
            TagSpecifications[].Tags[].Key
            TagSpecifications[].Tags[].Value
            VersionDescription
        """,
        tags="""
            LaunchTemplateData.TagSpecifications[].Tags
            TagSpecifications[].Tags
        """,
    ),
    "EC2.NatGateway": properties(
        objects="""
            Tags[]
        """,
        ordered="""
            SecondaryAllocationIds
            SecondaryPrivateIpAddresses
        """,
        scalars="""
            AllocationId
            ConnectivityType
            MaxDrainDurationSeconds
            PrivateIpAddress
            SecondaryPrivateIpAddressCount
            SubnetId
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.Route": properties(
        scalars="""
            DestinationCidrBlock
            DestinationPrefixListId
            GatewayId
            NatGatewayId
            RouteTableId
            TransitGatewayId
            VpcEndpointId
        """,
    ),
    "EC2.RouteTable": properties(
        resource=ResourceContract(name_tag=True),
        objects="""
            Tags[]
        """,
        references="""
            VpcId
        """,
        scalars="""
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.SecurityGroup": properties(
        resource=ResourceContract(ref_attribute=ref_attribute, ref_property="VpcId"),
        objects="""
            SecurityGroupEgress[]
            SecurityGroupIngress[]
            Tags[]
        """,
        ordered="""
            SecurityGroupEgress
            SecurityGroupIngress
        """,
        references="""
            SecurityGroupEgress[].DestinationSecurityGroupId
            VpcId
        """,
        scalars="""
            GroupDescription
            GroupName
            SecurityGroupEgress[].CidrIp
            SecurityGroupEgress[].CidrIpv6
            SecurityGroupEgress[].Description
            SecurityGroupEgress[].DestinationPrefixListId
            SecurityGroupEgress[].FromPort
            SecurityGroupEgress[].IpProtocol
            SecurityGroupEgress[].ToPort
            SecurityGroupIngress[].CidrIp
            SecurityGroupIngress[].CidrIpv6
            SecurityGroupIngress[].Description
            SecurityGroupIngress[].FromPort
            SecurityGroupIngress[].IpProtocol
            SecurityGroupIngress[].SourcePrefixListId
            SecurityGroupIngress[].SourceSecurityGroupId
            SecurityGroupIngress[].SourceSecurityGroupOwnerId
            SecurityGroupIngress[].ToPort
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.SecurityGroupEgress": properties(
        references="""
            DestinationSecurityGroupId
            GroupId
        """,
        scalars="""
            CidrIp
            CidrIpv6
            Description
            DestinationPrefixListId
            FromPort
            IpProtocol
            ToPort
        """,
    ),
    "EC2.SecurityGroupIngress": properties(
        references="""
            GroupId
            SourceSecurityGroupId
        """,
        scalars="""
            CidrIp
            CidrIpv6
            Description
            FromPort
            IpProtocol
            SourcePrefixListId
            SourceSecurityGroupOwnerId
            ToPort
        """,
    ),
    "EC2.Subnet": properties(
        resource=ResourceContract(name_tag=True),
        objects="""
            PrivateDnsNameOptionsOnLaunch
            Tags[]
        """,
        references="""
            VpcId
        """,
        scalars="""
            AvailabilityZone
            CidrBlock
            MapPublicIpOnLaunch
            PrivateDnsNameOptionsOnLaunch.EnableResourceNameDnsAAAARecord
            PrivateDnsNameOptionsOnLaunch.EnableResourceNameDnsARecord
            PrivateDnsNameOptionsOnLaunch.HostnameType
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.SubnetRouteTableAssociation": properties(
        references="""
            RouteTableId
        """,
        scalars="""
            SubnetId
        """,
    ),
    "EC2.TransitGateway": properties(
        objects="""
            Tags[]
        """,
        ordered="""
            TransitGatewayCidrBlocks
        """,
        scalars="""
            AmazonSideAsn
            AutoAcceptSharedAttachments
            DefaultRouteTableAssociation
            DefaultRouteTablePropagation
            Description
            DnsSupport
            EncryptionSupport
            SecurityGroupReferencingSupport
            Tags[].Key
            Tags[].Value
            VpnEcmpSupport
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.TransitGatewayRoute": properties(
        scalars="""
            Blackhole
            DestinationCidrBlock
            TransitGatewayAttachmentId
            TransitGatewayRouteTableId
        """,
    ),
    "EC2.TransitGatewayRouteTable": properties(
        objects="""
            Tags[]
        """,
        scalars="""
            Tags[].Key
            Tags[].Value
            TransitGatewayId
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.TransitGatewayRouteTableAssociation": properties(
        scalars="""
            TransitGatewayAttachmentId
            TransitGatewayRouteTableId
        """,
    ),
    "EC2.TransitGatewayRouteTablePropagation": properties(
        scalars="""
            TransitGatewayAttachmentId
            TransitGatewayRouteTableId
        """,
    ),
    "EC2.TransitGatewayVpcAttachment": properties(
        objects="""
            Options
            Tags[]
        """,
        ordered="""
            SubnetIds
        """,
        references="""
            VpcId
        """,
        scalars="""
            Options.ApplianceModeSupport
            Options.DnsSupport
            Options.SecurityGroupReferencingSupport
            Tags[].Key
            Tags[].Value
            TransitGatewayId
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.VPC": properties(
        resource=ResourceContract(name_tag=True),
        objects="""
            Tags[]
        """,
        scalars="""
            CidrBlock
            EnableDnsHostnames
            EnableDnsSupport
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.VPCBlockPublicAccessExclusion": properties(
        objects="""
            Tags[]
        """,
        scalars="""
            InternetGatewayExclusionMode
            SubnetId
            Tags[].Key
            Tags[].Value
            VpcId
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.VPCBlockPublicAccessOptions": properties(
        scalars="""
            InternetGatewayBlockMode
        """,
    ),
    "EC2.VPCEndpoint": properties(
        objects="""
            DnsOptions
            PolicyDocument
            Tags[]
        """,
        ordered="""
            RouteTableIds
            SecurityGroupIds
            SubnetIds
        """,
        references="""
            VpcId
        """,
        scalars="""
            DnsOptions.DnsRecordIpType
            DnsOptions.PrivateDnsOnlyForInboundResolverEndpoint
            IpAddressType
            PrivateDnsEnabled
            ServiceName
            ServiceRegion
            Tags[].Key
            Tags[].Value
            VpcEndpointType
        """,
        tags="""
            Tags
        """,
    ),
    "EC2.VPCGatewayAttachment": properties(
        scalars="""
            InternetGatewayId
            VpcId
        """,
    ),
}
