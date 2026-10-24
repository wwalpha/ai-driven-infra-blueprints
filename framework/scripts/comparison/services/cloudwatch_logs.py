"""cloudwatch logs comparison contracts and projections."""

from utils.reference_contracts import KMS_FORMS as _KMS_FORMS

REF_ATTRIBUTES = {'Logs.LogGroup': 'LogGroupName'}

KMS_FORMS = {prop: forms for prop, forms in _KMS_FORMS.items() if prop.startswith('Logs.')}

SUB_ARN_KINDS = {'Logs.LogGroup'}
NAMED_ARN = ('LogGroupName', r'[.\-_/#A-Za-z0-9]{1,512}', 'logs', 'log-group:', ':*')
