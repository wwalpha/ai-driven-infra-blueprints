"""ec2: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('EC2.Instance',)
APIS = {('ec2', 'describe_instances'), ('ec2', 'describe_volumes')}
IDENTITIES = {'EC2.Instance': ('base', 'InstanceId', None, None)}
FIELDS = {}
FIELDS.update(fields('EC2.Instance', 'base', {
    'AvailabilityZone': 'Placement.AvailabilityZone',
    'IamInstanceProfile': 'IamInstanceProfile.Arn',
    'ImageId': 'ImageId',
    'InstanceId': 'InstanceId',
    'InstanceType': 'InstanceType',
    'SecurityGroupIds': 'SecurityGroups[].GroupId',
    'SubnetId': 'SubnetId',
    'Tags[].Key': 'Tags[].Key',
    'Tags[].Value': 'Tags[].Value',
}, norms={'IamInstanceProfile': 'arn', 'SecurityGroupIds': 'id', 'SubnetId': 'id'}))
FIELDS.update(fields('EC2.Instance', 'volumes', {
    'BlockDeviceMappings[].DeviceName': 'BlockDeviceMappings[].DeviceName',
    'BlockDeviceMappings[].Ebs.DeleteOnTermination': 'BlockDeviceMappings[].Ebs.DeleteOnTermination',
    'BlockDeviceMappings[].Ebs.Encrypted': 'BlockDeviceMappings[].Ebs.Encrypted',
    'BlockDeviceMappings[].Ebs.KmsKeyId': 'BlockDeviceMappings[].Ebs.KmsKeyId',
    'BlockDeviceMappings[].Ebs.VolumeSize': 'BlockDeviceMappings[].Ebs.VolumeSize',
    'BlockDeviceMappings[].Ebs.VolumeType': 'BlockDeviceMappings[].Ebs.VolumeType',
}, norms={'BlockDeviceMappings[].Ebs.KmsKeyId': 'kms'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    current = r.current('InstanceId')
    if current:
        inputs = {'InstanceIds':[current]}
    else:
        tag_rows = r.rows
        names = [r.parse(tag_rows[i+1][1]) for i,(_,row) in enumerate(tag_rows[:-1]) if row['property'].endswith('Tags[].Key') and row['value'].strip('`') == 'Name']
        if len(names)!=1:
            raise Unresolved('instance requires confirmed InstanceId or one Name tag')
        inputs = {'Filters':[{'Name':'tag:Name','Values':names},{'Name':'subnet-id','Values':[r.value('SubnetId','id')]},{'Name':'instance-state-name','Values':['pending','running','stopping','stopped']} ]}
    record = one([v for reservation in ctx.pages('ec2','describe_instances',**inputs).get('Reservations',[]) for v in reservation.get('Instances',[])], 'ec2.describe_instances')
    if getter == 'base':
        return record
    mappings = record.get('BlockDeviceMappings',[])
    ids = [v['Ebs']['VolumeId'] for v in mappings if 'Ebs' in v]
    volumes = ctx.pages('ec2','describe_volumes',VolumeIds=ids).get('Volumes',[]) if ids else []
    index = {v['VolumeId']:v for v in volumes}
    result=[]
    for item in mappings:
        entry = dict(item)
        if 'Ebs' in entry:
            volume = index.get(entry['Ebs']['VolumeId'])
            if not volume:
                raise AcquisitionError('ec2.describe_volumes','AttachedVolumeMissing')
            entry['Ebs'] = dict(entry['Ebs'], **{k:volume[k] for k in ('Encrypted','KmsKeyId','VolumeType') if k in volume}, VolumeSize=volume['Size'])
        result.append(entry)
    return {'BlockDeviceMappings':result}
