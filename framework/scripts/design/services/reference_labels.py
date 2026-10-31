"""Service-specific reference label selectors."""

from design.services import kms, route53

SELECTORS = (kms.reference_label, route53.reference_label)


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


def document(values, row_id, field, raw, marked, selected, markers, scope, resolver):
    return route53.document(
        values, row_id, field, raw, marked, selected, markers, scope, resolver
    )
