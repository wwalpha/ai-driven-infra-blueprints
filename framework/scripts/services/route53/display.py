"""Route 53 endpoint DNS reference presentation."""

import json
import re
from importlib import import_module

from contracts.model import (
    MODEL_PENDING_DEPLOY,
    MODEL_REF_KEY,
    REFERENCE_LOGICAL_ID_KEY,
    RESOURCE_TYPE_KEY,
    row_resource,
)
from model.core import ModelNeedsFixError, ReferenceDiagnosticError, literal
from model.reference_nodes import is_reference, parse
from model.reference_values import confirmed, reference_value

import model as _model_api

from ..contracts import DisplayExtension

ALIAS_PROPERTY = "Route53.RecordSet.AliasTarget.DNSName"
ALIAS_ZONE_PROPERTY = "Route53.RecordSet.AliasTarget.HostedZoneId"
RECORD_PROPERTY = "Route53.RecordSet.ResourceRecords"
POINTER = "/Fn::Select/1/Fn::Split/1/Fn::Select/1"
UNCONFIRMED_DNS = "未確認"
ENDPOINT_DESCRIPTION = "接続先 Endpoint: "


def record_property(property_name):
    return re.fullmatch(
        r"(?:Route53\.RecordSet\.)?ResourceRecords(?:\[[1-9]\d*\])?", property_name
    )


def cname_record(values, row_id):
    prop = values.get(f"desired.row.{row_id}.property")
    if prop not in {RECORD_PROPERTY, RECORD_PROPERTY + "[]"}:
        return False
    rows = _model_api.ModelView(values).row_index().get(row_resource(row_id), ())
    return any(
        row["property"] == "Route53.RecordSet.Type" and literal(row["value"]) == "CNAME"
        for _, row in rows
    )


def endpoint_dns_operand(value, pointer="", *, field_index=1):
    """Recognize a DnsEntries extraction without evaluating a runtime index."""
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
            and field == field_index
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
        ALIAS_ZONE_PROPERTY,
        RECORD_PROPERTY,
        RECORD_PROPERTY + "[]",
    }:
        return []
    if isinstance(raw, list):
        if prop != RECORD_PROPERTY:
            return []
        candidates = enumerate(raw)
    elif prop in {ALIAS_PROPERTY, ALIAS_ZONE_PROPERTY, RECORD_PROPERTY + "[]"}:
        candidates = [(None, raw)]
    else:
        return []
    result = []
    for index, item in candidates:
        operand = endpoint_dns_operand(
            item,
            f"/{index}" if index is not None else "",
            field_index=0 if prop == ALIAS_ZONE_PROPERTY else 1,
        )
        if operand is not None and (
            prop == ALIAS_ZONE_PROPERTY
            or operand[0] == 0
            or cname_record(values, row_id)
        ):
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
    if values.get(
        f"desired.row.{position.row_id}.property"
    ) == ALIAS_ZONE_PROPERTY or cname_record(values, position.row_id):
        return name
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
    cname = cname_record(values, row_id)
    for index, node in endpoint_nodes(values, row_id, field, raw):
        position = positions.get(node.pointer)
        if position is None or not cname and endpoint_id(node, scope, resolver) is None:
            continue
        marker = markers[position]
        if index is None:
            return marker
        marked[index] = marker
    return marked


def recorded_dns(values, row_id, index, count):
    raw = literal(values.get(f"observed.row.{row_id}.value", ""))
    if raw.startswith("["):
        try:
            items = json.loads(raw)
        except ValueError:
            return None
        raw = items[index] if isinstance(items, list) and len(items) == count else None
    elif count != 1:
        return None
    return confirmed(raw) if isinstance(raw, str) else None


def reference_row(row, presentation):
    row_id, prop, value, description = row
    if value not in presentation.marker_links or not cname_record(
        presentation.values, row_id
    ):
        return row
    position = next(
        pos for pos, marker in presentation.markers.items() if marker == value
    )
    key = f"desired.row.{row_id}.value"
    raw, _ = _model_api.parse_reference_field(key, presentation.values[key])
    index = int(position.pointer.split("/")[1]) if isinstance(raw, list) else 0
    item = raw[index] if isinstance(raw, list) else raw
    operand = endpoint_dns_operand(item)
    if operand is not None:
        entry, node = operand
    elif is_reference(item):
        entry, node = None, parse(item)
    else:
        return row
    if node.attribute != "DnsEntries":
        return row
    _, _, endpoint = presentation.resolver.resolve_logical(
        node.logical_id, presentation.scope
    )
    if endpoint[RESOURCE_TYPE_KEY] != "EC2.VPCEndpoint":
        return row
    dns = recorded_dns(
        presentation.values, row_id, index, len(raw) if isinstance(raw, list) else 1
    )
    entries = presentation.references[position].value
    if (
        dns is None
        and entry is not None
        and isinstance(entries, list)
        and entry < len(entries)
    ):
        if isinstance(entries[entry], str):
            fields = entries[entry].split(":")
            if len(fields) == 2:
                dns = confirmed(fields[1])
    if presentation.marker_links[value] not in description:
        description = (
            (description + "<br>" if description else "") + ENDPOINT_DESCRIPTION + value
        )
    return [row_id, prop, import_module("design.common").code(dns or UNCONFIRMED_DNS), description]


EXTENSIONS = {
    "Route53.RecordSet": DisplayExtension(
        reference_document=document,
        contextual_reference_label=reference_label,
        reference_row=reference_row,
    ),
    "Route53.HostedZone": DisplayExtension(),
}
