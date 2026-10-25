"""IMPORT waits and normal exclusions within the six comparison categories."""

from design.policy_tables import literal
from utils.cloudformation.inputs import Blocked

from .reference_evidence import identifier_text

CATEGORIES = ('matched', 'difference', 'deferred', 'uncompared', 'error', 'excluded')
PHASES = ('unobserved', 'pending_deploy', 'awaiting_handoff')


class ImportReferenceDeferred(Blocked):
    def __init__(self, phase, service, identity, resource_type, attribute, consumer_property):
        if phase not in PHASES:
            raise ValueError('invalid IMPORT deferral phase')
        self.iac_cause = dict(kind='import-reference-excluded' if phase == 'pending_deploy' else 'import-reference-deferred', phase=phase,
            producer=dict(service=service, resource=identity, resourceType=resource_type, attribute=attribute),
            consumer_property=consumer_property)
        super().__init__('IMPORT reference comparison excluded: pending_deploy' if phase == 'pending_deploy' else
                         'IMPORT reference comparison deferred: ' + phase + '; approved handoff required')


def failure_category(error):
    if isinstance(error, ImportReferenceDeferred):
        return 'excluded' if error.iac_cause['phase'] == 'pending_deploy' else 'deferred'
    return 'uncompared' if isinstance(error, (Blocked, KeyError)) else 'error'


def defer_import_reference(inputs, symbol, resource, consumer_property):
    """Called only after producer and receiving contracts, and existing exceptions, pass."""
    if not inputs.local_comparison or consumer_property is None:
        raise Blocked('IMPORT reference requires a proven receiving contract and approved handoff; no physical ID inference')
    service, identity = symbol['$resource']
    kind, attribute = resource['resourceType'], symbol['$attribute']
    rows = [(rid, row) for rid, row in inputs.rows[service][identity] if row['property'] == kind + '.' + attribute]
    if len(rows) > 1:
        raise Blocked('identifier Property is ambiguous')
    authority = inputs.models[service].authoritative
    key = f'observed.row.{rows[0][0]}.value' if rows else None
    if key not in authority:
        phase = 'unobserved'
    elif literal(authority[key]) == 'PENDING_DEPLOY':
        phase = 'pending_deploy'
    else:
        identifier_text(inputs, kind, attribute, authority[key])
        phase = 'awaiting_handoff'
    raise ImportReferenceDeferred(phase, service, identity, kind, attribute, consumer_property)


def validate_cause(cause):
    if (not isinstance(cause, dict)
            or cause.get('kind') != ('import-reference-excluded' if cause.get('phase') == 'pending_deploy' else 'import-reference-deferred')
            or cause.get('phase') not in PHASES
            or not isinstance(cause.get('consumer_property'), str) or not cause['consumer_property']
            or not isinstance(cause.get('producer'), dict)
            or any(not isinstance(cause['producer'].get(key), str) or not cause['producer'][key]
                   for key in ('service', 'resource', 'resourceType', 'attribute'))):
        raise ValueError('invalid IMPORT comparison cause')
