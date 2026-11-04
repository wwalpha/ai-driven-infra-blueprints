"""Route 53 endpoint DNS reference presentation."""

from contracts.model import (
    MODEL_PENDING_DEPLOY,
    MODEL_REF_KEY,
    REFERENCE_LOGICAL_ID_KEY,
    RESOURCE_TYPE_KEY,
)
from model.core import ModelNeedsFixError, ReferenceDiagnosticError
from model.reference_nodes import is_reference, parse
from model.reference_values import reference_value

import model as _model_api

ALIAS_PROPERTY = "Route53.RecordSet.AliasTarget.DNSName"
RECORD_PROPERTY = "Route53.RecordSet.ResourceRecords"
POINTER = "/Fn::Select/1/Fn::Split/1/Fn::Select/1"


def endpoint_dns_operand(value, pointer=""):
    """Recognize the documented DNS extraction without evaluating a runtime index."""
    match value:
        case {
            "Fn::Select": [
                field,
                {
                    "Fn::Split": [
                        ":",
                        {"Fn::Select": [entry, target], **inner_extra},
                    ],
                    **split_extra,
                },
            ],
            **outer_extra,
        } if (
            type(field) is int
            and field == 1
            and type(entry) is int
            and entry >= 0
            and not (outer_extra or split_extra or inner_extra)
            and is_reference(target)
        ):
            try:
                node = parse(target, pointer + POINTER)
            except ModelNeedsFixError:
                return None
            if node.attribute == "DnsEntries":
                return entry, node
    return None


def endpoint_nodes(values, row_id, field, raw):
    prop = values.get(f"desired.row.{row_id}.property")
    if field != "value" or prop not in {
        ALIAS_PROPERTY,
        RECORD_PROPERTY,
        RECORD_PROPERTY + "[]",
    }:
        return []
    if isinstance(raw, list):
        if prop != RECORD_PROPERTY:
            return []
        candidates = enumerate(raw)
    elif prop in {ALIAS_PROPERTY, RECORD_PROPERTY + "[]"}:
        candidates = [(None, raw)]
    else:
        return []
    result = []
    for index, item in candidates:
        operand = endpoint_dns_operand(item, f"/{index}" if index is not None else "")
        if operand is not None and operand[0] == 0:
            result.append((index, operand[1]))
    return result


def endpoint_id(node, scope, resolver):
    try:
        value = reference_value(
            resolver,
            scope,
            parse(
                {
                    MODEL_REF_KEY: {
                        REFERENCE_LOGICAL_ID_KEY: node.logical_id,
                        "attribute": "Id",
                    }
                }
            ),
        )
    except ReferenceDiagnosticError:
        return None
    if value.status in {"pending_deploy", "logical_only"}:
        return MODEL_PENDING_DEPLOY
    return (
        value.value
        if value.status == "resolved" and isinstance(value.value, str)
        else None
    )


def reference_label(
    values, position, node, scope, resolver, resource, attribute, name, displayed
):
    if resource[
        RESOURCE_TYPE_KEY
    ] != "EC2.VPCEndpoint" or not position.pointer.endswith(POINTER):
        return name
    raw, structured = _model_api.parse_reference_field(
        f"desired.row.{position.row_id}.{position.source_field}",
        values[f"desired.row.{position.row_id}.{position.source_field}"],
    )
    if not structured or node not in [
        item
        for _, item in endpoint_nodes(
            values, position.row_id, position.source_field, raw
        )
    ]:
        return name
    return endpoint_id(node, scope, resolver) or name


def document(values, row_id, field, raw, marked, selected, markers, scope, resolver):
    positions = {ref.position.pointer: ref.position for ref in selected}
    for index, node in endpoint_nodes(values, row_id, field, raw):
        position = positions.get(node.pointer)
        if position is None or endpoint_id(node, scope, resolver) is None:
            continue
        marker = markers[position]
        if index is None:
            return marker
        marked[index] = marker
    return marked
