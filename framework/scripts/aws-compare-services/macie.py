"""macie: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('Macie.ClassificationJob', 'Macie.Session')
APIS = {('macie2', 'list_classification_jobs'), ('macie2', 'get_macie_session'), ('macie2', 'describe_classification_job')}
IDENTITIES = {'Macie.Session': ('session', 'AwsAccountId', None, None), 'Macie.ClassificationJob': ('job', 'jobId', 'jobArn', 'name')}
FIELDS = {}
FIELDS.update(fields('Macie.Session', 'session', {
    'AwsAccountId': 'AwsAccountId',
    'Status': 'status',
    'FindingPublishingFrequency': 'findingPublishingFrequency',
}))
FIELDS.update(fields('Macie.ClassificationJob', 'job', {
    'initialRun': 'initialRun',
    'jobId': 'jobId',
    'jobType': 'jobType',
    'managedDataIdentifierIds': 'managedDataIdentifierIds',
    'managedDataIdentifierSelector': 'managedDataIdentifierSelector',
    'name': 'name',
    's3JobDefinition': 's3JobDefinition',
    'samplingPercentage': 'samplingPercentage',
    'scheduleFrequency': 'scheduleFrequency',
}, norms={'s3JobDefinition': 'json', 'managedDataIdentifierIds': 'set'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if getter=='session':
        return dict(ctx.call('macie2','get_macie_session'),AwsAccountId=ctx.target.get('awsExecutionAccountId',ctx.target['awsAccountId']))
    current=r.current('jobId')
    if not current:
        names=ctx.pages('macie2','list_classification_jobs',filterCriteria={'includes':[{'key':'NAME','comparator':'EQ','values':[r.value('name')]}]}).get('items',[])
        current=one([v for v in names if v['name']==r.value('name')], 'macie2.list_classification_jobs')['jobId']
    return ctx.call('macie2','describe_classification_job',jobId=current)
