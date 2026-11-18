"""Service-specific reference label selectors."""

from contracts.model import RESOURCE_TYPE_KEY
from services.registry import REGISTRY


def select(
    values, position, node, scope, resolver, resource, attribute, name, displayed
):
    producer = resource[RESOURCE_TYPE_KEY]
    prop = values.get(f"desired.row.{position.row_id}.property")
    receiver = ".".join(prop.split(".")[:2]) if prop else None
    for kind in dict.fromkeys((producer, receiver)):
        if kind is None or kind not in REGISTRY:
            continue
        extension = REGISTRY.display(kind)
        if extension is not None and extension.reference_label is not None:
            name = extension.reference_label(prop, producer, attribute, name, displayed)
    hook = (
        REGISTRY.presentation(receiver).contextual_reference_label if receiver else None
    )
    return (
        hook(
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
        if hook
        else name
    )


def document(values, row_id, field, raw, marked, selected, markers, scope, resolver):
    prop = values.get(f"desired.row.{row_id}.property")
    receiver = ".".join(prop.split(".")[:2]) if prop else None
    hook = REGISTRY.presentation(receiver).reference_document if receiver else None
    return (
        hook(values, row_id, field, raw, marked, selected, markers, scope, resolver)
        if hook
        else marked
    )
