"""athena comparison contracts and projections."""

from utils.reference_contracts import KMS_FORMS as _KMS_FORMS

REF_ATTRIBUTES = {'Athena.WorkGroup': 'Name'}

KMS_FORMS = {prop: forms for prop, forms in _KMS_FORMS.items() if prop.startswith('Athena.')}
