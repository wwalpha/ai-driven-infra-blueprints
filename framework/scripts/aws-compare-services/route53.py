"""route53: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('Route53.HostedZone', 'Route53.RecordSet')
APIS = {('route53', 'list_resource_record_sets'), ('route53', 'list_hosted_zones'), ('route53', 'get_hosted_zone')}
IDENTITIES = {'Route53.HostedZone': ('zone', 'Id', None, 'Name'), 'Route53.RecordSet': ('record', 'Name', None, 'Name')}
FIELDS = {}
FIELDS.update(fields('Route53.HostedZone', 'zone', {
    'HostedZoneConfig.Comment': 'Config.Comment',
    'Id': 'Id',
    'Name': 'Name',
}, norms={'Name': 'dns'}))
FIELDS.update(fields('Route53.HostedZone', 'vpcs', {
    'VPCs[].VPCRegion': 'VPCs[].VPCRegion',
    'VPCs[].VPCId': 'VPCs[].VPCId',
}, norms={'VPCs[].VPCId': 'id'}))
FIELDS.update(fields('Route53.RecordSet', 'record', {
    'AliasTarget.DNSName': 'AliasTarget.DNSName',
    'AliasTarget.EvaluateTargetHealth': 'AliasTarget.EvaluateTargetHealth',
    'AliasTarget.HostedZoneId': 'AliasTarget.HostedZoneId',
    'HostedZoneId': 'HostedZoneId',
    'Name': 'Name',
    'ResourceRecords': 'ResourceRecords[].Value',
    'TTL': 'TTL',
    'Type': 'Type',
}, norms={'HostedZoneId': 'id', 'Name': 'dns', 'AliasTarget.DNSName': 'dns', 'ResourceRecords': 'set'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if r.kind=='Route53.HostedZone':
        current=r.current('Id')
        if not current:
            name=r.value('Name').rstrip('.').lower()
            candidates=[v for v in ctx.pages('route53','list_hosted_zones').get('HostedZones',[]) if v['Name'].rstrip('.').lower()==name]
            # Same DNS name can identify both public and private zones. Preserve VPC association.
            if r.rows_for('VPCs[].VPCId'):
                desired={r.parse(row,'id') for _,row in r.rows_for('VPCs[].VPCId')}
                candidates=[v for v in candidates if desired=={item['VPCId'] for item in ctx.call('route53','get_hosted_zone',Id=v['Id']).get('VPCs',[])}]
            current=one(candidates,'route53.list_hosted_zones')['Id']
        result=ctx.call('route53','get_hosted_zone',Id=current)
        if getter=='vpcs':
            return result
        return dict(result['HostedZone'],Id=result['HostedZone']['Id'].removeprefix('/hostedzone/'))
    zone=r.value('HostedZoneId','id').removeprefix('/hostedzone/')
    name=r.value('Name').rstrip('.').lower();kind=r.value('Type')
    records=ctx.pages('route53','list_resource_record_sets',HostedZoneId=zone).get('ResourceRecordSets',[])
    record=one([v for v in records if v['Name'].rstrip('.').lower()==name and v['Type']==kind], 'route53.list_resource_record_sets')
    return dict(record,HostedZoneId=zone)
