"""codepipeline: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('CodePipeline.Pipeline',)
APIS = {('codepipeline', 'get_pipeline')}
IDENTITIES = {'CodePipeline.Pipeline': ('base', 'name', 'PipelineArn', 'Name')}
FIELDS = {}
FIELDS.update(fields('CodePipeline.Pipeline', 'base', {
    'ArtifactStore.EncryptionKey.Id': 'artifactStore.encryptionKey.id',
    'ArtifactStore.EncryptionKey.Type': 'artifactStore.encryptionKey.type',
    'ArtifactStore.Location': 'artifactStore.location',
    'ArtifactStore.Type': 'artifactStore.type',
    'ExecutionMode': 'executionMode',
    'Name': 'name',
    'PipelineType': 'pipelineType',
    'RoleArn': 'roleArn',
    'Stages[].Actions[].ActionTypeId.Category': 'stages[].actions[].actionTypeId.category',
    'Stages[].Actions[].ActionTypeId.Owner': 'stages[].actions[].actionTypeId.owner',
    'Stages[].Actions[].ActionTypeId.Provider': 'stages[].actions[].actionTypeId.provider',
    'Stages[].Actions[].ActionTypeId.Version': 'stages[].actions[].actionTypeId.version',
    'Stages[].Actions[].Configuration': 'stages[].actions[].configuration',
    'Stages[].Actions[].InputArtifacts[].Name': 'stages[].actions[].inputArtifacts[].name',
    'Stages[].Actions[].Name': 'stages[].actions[].name',
    'Stages[].Actions[].OutputArtifacts[].Name': 'stages[].actions[].outputArtifacts[].name',
    'Stages[].Actions[].RunOrder': 'stages[].actions[].runOrder',
    'Stages[].Name': 'stages[].name',
    'Variables[].Name': 'variables[].name',
}, norms={'ArtifactStore.EncryptionKey.Id': 'kms', 'ArtifactStore.Location': 'name', 'RoleArn': 'arn', 'Stages[].Actions[].Configuration': 'json', 'Stages[].Actions[].ActionTypeId.Version': 'string'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    result=ctx.call('codepipeline', 'get_pipeline', name=r.value('Name'))
    return dict(result['pipeline'],PipelineArn=result.get('metadata',{}).get('pipelineArn',MISSING))
