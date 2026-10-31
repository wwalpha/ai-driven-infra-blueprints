"""Route 53 endpoint DNS reference presentation."""

import model.references as references
from model.core import ReferenceDiagnosticError
from model.reference_nodes import nodes, parse
from model.reference_values import reference_value

ALIAS_PROPERTY = "Route53.RecordSet.AliasTarget.DNSName"
RECORD_PROPERTY = "Route53.RecordSet.ResourceRecords"
POINTER = "/Fn::Select/1/Fn::Split/1/Fn::Select/1"


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
        found = list(nodes(item, errors=[]))
        if (
            len(found) != 1
            or found[0].pointer != POINTER
            or found[0].attribute != "DnsEntries"
        ):
            continue
        node = found[0]
        target = {
            "$modelRef": {"logicalId": node.logical_id, "attribute": node.attribute}
        }
        expected = {
            "Fn::Select": [1, {"Fn::Split": [":", {"Fn::Select": [0, target]}]}]
        }
        if item == expected:
            result.append(
                (
                    index,
                    parse(target, (f"/{index}" if index is not None else "") + POINTER),
                )
            )
    return result


def endpoint_id(node, scope, resolver):
    try:
        value = reference_value(
            resolver,
            scope,
            parse({"$modelRef": {"logicalId": node.logical_id, "attribute": "Id"}}),
        )
    except ReferenceDiagnosticError:
        return None
    if value.status in {"pending_deploy", "logical_only"}:
        return "PENDING_DEPLOY"
    return (
        value.value
        if value.status == "resolved" and isinstance(value.value, str)
        else None
    )


def reference_label(
    values, position, node, scope, resolver, resource, attribute, name, displayed
):
    if resource["resourceType"] != "EC2.VPCEndpoint" or not position.pointer.endswith(
        POINTER
    ):
        return name
    raw, structured = references._json(
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
