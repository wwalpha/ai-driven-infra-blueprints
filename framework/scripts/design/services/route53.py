"""Route 53 endpoint DNS reference presentation."""

import model.references as references
from model.core import ReferenceDiagnosticError
from model.reference_nodes import nodes, parse
from model.reference_values import reference_value

PROPERTY = "Route53.RecordSet.AliasTarget.DNSName"
POINTER = "/Fn::Select/1/Fn::Split/1/Fn::Select/1"


def endpoint_node(values, row_id, field, raw):
    if field != "value" or values.get(f"desired.row.{row_id}.property") != PROPERTY:
        return None
    found = list(nodes(raw, errors=[]))
    if (
        len(found) != 1
        or found[0].pointer != POINTER
        or found[0].attribute != "DnsEntries"
    ):
        return None
    node = found[0]
    target = {"$modelRef": {"logicalId": node.logical_id, "attribute": node.attribute}}
    expected = {"Fn::Select": [1, {"Fn::Split": [":", {"Fn::Select": [0, target]}]}]}
    return node if raw == expected else None


def endpoint_id(node, scope, resolver):
    try:
        value = reference_value(
            resolver,
            scope,
            parse({"$modelRef": {"logicalId": node.logical_id, "attribute": "Id"}}),
        )
    except ReferenceDiagnosticError:
        return None
    return (
        value.value
        if value.status == "resolved" and isinstance(value.value, str)
        else None
    )


def reference_label(
    values, position, node, scope, resolver, resource, attribute, name, displayed
):
    if resource["resourceType"] != "EC2.VPCEndpoint" or position.pointer != POINTER:
        return name
    raw, structured = references._json(
        f"desired.row.{position.row_id}.{position.source_field}",
        values[f"desired.row.{position.row_id}.{position.source_field}"],
    )
    if (
        not structured
        or endpoint_node(values, position.row_id, position.source_field, raw) != node
    ):
        return name
    return endpoint_id(node, scope, resolver) or name


def document(values, row_id, field, raw, marked, selected, markers, scope, resolver):
    node = endpoint_node(values, row_id, field, raw)
    if node is None or endpoint_id(node, scope, resolver) is None or len(selected) != 1:
        return marked
    return markers.get(selected[0].position, marked)
