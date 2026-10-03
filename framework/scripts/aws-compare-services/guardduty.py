"""guardduty: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('GuardDuty.Detector', 'GuardDuty.MalwareProtectionPlan')
APIS = {('guardduty', 'get_malware_protection_plan'), ('guardduty', 'get_detector'), ('guardduty', 'list_malware_protection_plans'), ('guardduty', 'list_detectors')}
IDENTITIES = {'GuardDuty.Detector': ('detector', 'DetectorId', None, None), 'GuardDuty.MalwareProtectionPlan': ('plan', 'MalwareProtectionPlanId', 'Arn', None)}
FIELDS = {}
FIELDS.update(fields('GuardDuty.Detector', 'detector', {
    'DataSources.Kubernetes.AuditLogs.Enable': 'DataSources.Kubernetes.AuditLogs.Enable',
    'DataSources.MalwareProtection.ScanEc2InstanceWithFindings.EbsVolumes': 'DataSources.MalwareProtection.ScanEc2InstanceWithFindings.EbsVolumes',
    'DataSources.S3Logs.Enable': 'DataSources.S3Logs.Enable',
    'Enable': 'Enabled',
    'Features[].Name': 'Features[].Name',
    'Features[].Status': 'Features[].Status',
    'FindingPublishingFrequency': 'FindingPublishingFrequency',
}))
FIELDS.update(fields('GuardDuty.Detector', 'detector', {
    'Id': 'DetectorId',
}))
FIELDS.update(fields('GuardDuty.MalwareProtectionPlan', 'plan', {
    'Actions.Tagging.Status': 'Actions.Tagging.Status',
    'MalwareProtectionPlanId': 'MalwareProtectionPlanId',
    'ProtectedResource.S3Bucket.BucketName': 'ProtectedResource.S3Bucket.BucketName',
    'ProtectedResource.S3Bucket.ObjectPrefixes[]': 'ProtectedResource.S3Bucket.ObjectPrefixes[]',
    'Role': 'Role',
}, norms={'ProtectedResource.S3Bucket.BucketName': 'name', 'Role': 'arn'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if getter=='detector':
        current=r.current('Id')
        if not current:
            current=one(ctx.pages('guardduty','list_detectors').get('DetectorIds',[]), 'guardduty.list_detectors')
        record=dict(ctx.call('guardduty','get_detector',DetectorId=current),DetectorId=current)
        record['Enabled']=record.get('Status')=='ENABLED'
        malware=record.get('DataSources',{}).get('MalwareProtection',{}).get('ScanEc2InstanceWithFindings',{})
        if 'EbsVolumes' in malware and isinstance(malware['EbsVolumes'],dict):
            record=dict(record,DataSources=dict(record.get('DataSources',{})))
            record['DataSources']['MalwareProtection']={'ScanEc2InstanceWithFindings':{'EbsVolumes':malware['EbsVolumes'].get('Status')=='ENABLED'}}
        # Legacy DataSources report Status, while desired catalog uses Enable.
        import copy
        record=copy.deepcopy(record)
        for path in [('S3Logs',),('Kubernetes','AuditLogs')]:
            node=record.get('DataSources',{})
            for part in path:
                node=node.get(part,{})
            if 'Status' in node:
                node['Enable']=node['Status']=='ENABLED'
        return record
    current=r.current('MalwareProtectionPlanId')
    if not current:
        bucket=r.value('ProtectedResource.S3Bucket.BucketName','name')
        plans=ctx.pages('guardduty','list_malware_protection_plans').get('MalwareProtectionPlans',[])
        candidates=[]
        for plan in plans:
            ident=plan['MalwareProtectionPlanId']
            v=ctx.call('guardduty','get_malware_protection_plan',MalwareProtectionPlanId=ident)
            if v.get('ProtectedResource',{}).get('S3Bucket',{}).get('BucketName')==bucket:
                candidates.append(dict(v,MalwareProtectionPlanId=ident))
        return one(candidates,'guardduty.list_malware_protection_plans')
    return dict(ctx.call('guardduty','get_malware_protection_plan',MalwareProtectionPlanId=current),MalwareProtectionPlanId=current)
