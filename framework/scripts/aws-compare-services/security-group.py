"""security-group: selected properties -> read-only SDK responses; inputs in fetch()."""

from model.adapters.aws import one, select

APIS = {('ec2', 'describe_security_groups'), ('ec2', 'describe_security_group_rules')}


def sensitive(prop):
    return False




def _fetch_permissions(items, egress):
    result = []
    for item in items:
        base = {k: item[k] for k in ('IpProtocol', 'FromPort', 'ToPort') if k in item}
        for entry in item.get('IpRanges', []):
            result.append(dict(base, **entry))
        for entry in item.get('UserIdGroupPairs', []):
            result.append(dict(base, **{'DestinationSecurityGroupId' if egress else 'SourceSecurityGroupId': entry['GroupId']}, **{'Description': entry['Description']} if 'Description' in entry else {}))
    return result


def fetch(ctx, r, getter):
    if getter=='group':
        current=r.current('Id')
        inputs={'GroupIds':[current]} if current else {'Filters':[{'Name':'group-name','Values':[r.value('GroupName')]},{'Name':'vpc-id','Values':[r.value('VpcId','id')]}]}
        record=dict(one(ctx.pages('ec2','describe_security_groups',**inputs).get('SecurityGroups',[]),'ec2.describe_security_groups'))
        permissions = _fetch_permissions
        record['SecurityGroupIngress']=permissions(record.get('IpPermissions',[]),False)
        record['SecurityGroupEgress']=permissions(record.get('IpPermissionsEgress',[]),True)
        return record
    parent=r.parent()
    group=parent.identity()
    current=r.current('Id')
    inputs={'SecurityGroupRuleIds':[current]} if current else {'Filters':[{'Name':'group-id','Values':[group]}]}
    records=ctx.pages('ec2','describe_security_group_rules',**inputs).get('SecurityGroupRules',[])
    egress=r.kind.endswith('Egress')
    candidates=[v for v in records if v['GroupId']==group and v['IsEgress']==egress]
    if not current:
        expected={row['property'].removeprefix(r.kind+'.'):r.parse(row,'id' if row['property'].endswith('SecurityGroupId') else 'typed') for _,row in r.rows if not row['property'].endswith('.Id')}
        rename={'CidrIp':'CidrIpv4','SourceSecurityGroupId':'ReferencedGroupInfo.GroupId','DestinationSecurityGroupId':'ReferencedGroupInfo.GroupId'}
        candidates=[v for v in candidates if all(select(v,rename.get(k,k))==value for k,value in expected.items())]
    return one(candidates,'ec2.describe_security_group_rules')
