"""cloudwatch logs comparison contracts and projections."""

REF_ATTRIBUTES = {'Logs.LogGroup': 'LogGroupName'}

KMS_FORMS = {'Logs.LogGroup.KmsKeyId': {'KeyArn', 'AliasArn'}}

SUB_ARN_KINDS = {'Logs.LogGroup'}
NAMED_ARN = ('LogGroupName', r'[.\-_/#A-Za-z0-9]{1,512}', 'logs', 'log-group:', ':*')
