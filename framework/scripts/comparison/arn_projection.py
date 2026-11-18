"""Project a complete ARN expression onto its proven Producer's ARN attribute."""

from services.reference_engine import REFERENCES
from utils.cloudformation.inputs import Blocked
from utils.iac_values import ResourceReference

from .expressions import parts, references


def project(value, *, resource_type, producer_scope, symbolic_arn=None):
    """Return an existing reference type only after shape and owning scope agree."""
    try:
        tokens = parts(value)
        sources = [token for token in tokens if isinstance(token, ResourceReference)]
        if (
            len(sources) != 1
            or references(value) != sources
            or any(not isinstance(token, (str, ResourceReference)) for token in tokens)
        ):
            return None
        (source,) = sources
        kind = resource_type(source)
        arn = REFERENCES.arn(kind)
        if arn is None or arn.shape is None:
            return None
        identifier, template, _ = arn.shape
        attribute = REFERENCES.formal_attribute(kind, "Arn")
        projected = ResourceReference(dict(source, **{"$attribute": attribute}))
        if source["$attribute"] in arn.verified_symbolic_attributes:
            if symbolic_arn is not None and tokens == parts(symbolic_arn(projected)):
                return projected
            return None
        scope = producer_scope(source)
        if len(tokens) == 1 and source["$attribute"] == attribute:
            return ResourceReference(source)
        # A single identity field has one unambiguous symbolic substitution.
        if not isinstance(identifier, str) or source[
            "$attribute"
        ] != REFERENCES.formal_attribute(kind, identifier):
            return None
        prefix, suffix = template.split("{id}")
        expected = [
            part
            for part in (prefix.format(**scope), source, suffix.format(**scope))
            if part != ""
        ]
        if tokens != expected:
            return None
        return projected
    except (Blocked, ValueError, KeyError, TypeError):
        return None
