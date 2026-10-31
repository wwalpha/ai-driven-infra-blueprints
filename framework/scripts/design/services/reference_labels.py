"""Service-specific reference label selectors."""

from design.services import kms

SELECTORS = (kms.reference_label,)


def select(
    values, position, node, scope, resolver, resource, attribute, name, displayed
):
    for selector in SELECTORS:
        name = selector(
            values,
            position,
            node,
            scope,
            resolver,
            resource,
            attribute,
            name,
            displayed,
        )
    return name
