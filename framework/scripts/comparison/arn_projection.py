"""Project a complete ARN expression onto its proven Producer's ARN attribute."""

from utils.cloudformation.inputs import Blocked
from utils.iac_values import ResourceReference
from utils.reference_contracts import ARN_SHAPES, reference_attribute

from .expressions import parts, references


def project(value, *, resource_type, producer_scope):
    """Return an existing reference type only after shape and owning scope agree."""
    try:
        tokens = parts(value)
        sources = [token for token in tokens if isinstance(token, ResourceReference)]
        if (len(sources) != 1 or references(value) != sources
                or any(not isinstance(token, (str, ResourceReference)) for token in tokens)):
            return None
        source, = sources
        kind = resource_type(source)
        if kind not in ARN_SHAPES:
            return None
        identifier, template, _ = ARN_SHAPES[kind]
        attribute = reference_attribute(kind, 'Arn')
        scope = producer_scope(source)
        if len(tokens) == 1 and source['$attribute'] == attribute:
            return ResourceReference(source)
        # A single identity field has one unambiguous symbolic substitution.
        if not isinstance(identifier, str) or source['$attribute'] != reference_attribute(kind, identifier):
            return None
        prefix, suffix = template.split('{id}')
        expected = [part for part in (prefix.format(**scope), source, suffix.format(**scope)) if part != '']
        if tokens != expected:
            return None
        return ResourceReference(dict(source, **{'$attribute': attribute}))
    except (Blocked, ValueError, KeyError, TypeError):
        return None
