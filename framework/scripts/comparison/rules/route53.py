"""Static Route53 comparison methods; container rules include their recursive contents."""

from dataclasses import replace

from model.core import entries, literal
from utils.arn_values import context_value
from utils.cloudformation.inputs import Blocked
from utils.comparison_rows import select
from utils.iac_values import Expression, ResourceReference, cfn_resource_identity

from .. import expressions
from ..methods import OBJECT, properties


def model_property(inputs, service, identity, field):
    kind = inputs.resources[service][identity]["resourceType"]
    rows = [
        row
        for rid, row in entries(inputs.model(service).authoritative, "desired.row.")
        if rid.rpartition("-")[0] == identity
        and row.get("property") == kind + "." + field
    ]
    if len(rows) != 1 or "document" in rows[0]:
        raise Blocked("Endpoint DNS requires one explicit Model " + field)
    return literal(rows[0]["value"])


def stack_property(inputs, service, identity, field):
    resource = inputs.resources[service][identity]
    stack, logical = cfn_resource_identity(resource["cfn-logicalId"])
    units = [unit for _, unit in inputs.templates() if unit["name"] == stack]
    if len(units) != 1:
        raise Blocked("Endpoint DNS stack correspondence is unproven")
    _, (document, _, pseudo) = inputs.stack(units[0])
    if document.get("Transform") or inputs.symbol(stack, logical)["$resource"] != [
        service,
        identity,
    ]:
        raise Blocked("Endpoint DNS resource correspondence is unproven")
    scope = tuple(
        context_value(pseudo, group) for group in ("partition", "account", "region")
    )
    return inputs.evaluate(
        stack, select(document["Resources"][logical].get("Properties", {}), field)
    ), scope


def selected_reference(inputs, service, key, symbol):
    """Retain the receiving Resource for a typed DNS extraction operand."""
    number = key.split(".")[2].rpartition("-")[0]
    row = inputs.model(service).authoritative[key.rsplit(".", 1)[0] + ".property"]
    expected = (
        {"A", "AAAA"} if row == "Route53.RecordSet.AliasTarget.DNSName" else {"CNAME"}
    )
    if model_property(inputs, service, number, "Type") not in expected:
        raise Blocked("Endpoint DNS requires a compatible RecordSet Type")
    producer, producer_id = symbol["$resource"]
    if symbol["$attribute"] != "DnsEntries":
        raise Blocked("Endpoint DNS requires the DnsEntries attribute")
    if model_property(inputs, producer, producer_id, "VpcEndpointType") != "Interface":
        raise Blocked("Endpoint DNS requires an explicit Interface Endpoint")
    symbol = ResourceReference(symbol)
    symbol.dns_consumer = (service, number)
    return symbol


def dns_expression(value):
    parts = expressions.parts(value)
    if len(parts) != 1:
        raise Blocked("Endpoint DNS extraction has unproven string affixes")
    value = parts[0]
    operands = []
    for operation in ("Select", "Split", "Select"):
        if (
            not isinstance(value, Expression)
            or value.operation != operation
            or len(value.operands) != 2
        ):
            raise Blocked("Endpoint DNS extraction structure is unproven")
        first, value = value.operands
        operands.append(first)
    field, delimiter, index = operands
    if (
        type(field) is not int
        or not isinstance(delimiter, str)
        or type(index) is not int
        or index < 0
        or not isinstance(value, ResourceReference)
    ):
        raise Blocked("Endpoint DNS extraction operands are unproven")
    return value, index, delimiter, field


def selected_decision(inputs, left, right, path, *, export_origins):
    consumers = {
        ref.dns_consumer
        for ref in expressions.references([left, right])
        if hasattr(ref, "dns_consumer")
    }
    if not consumers:
        if path == "AliasTarget.DNSName" and expressions.references([left, right]):
            return None, "Alias Endpoint DNS consumer correspondence is unproven"
        return NotImplemented
    if len(consumers) != 1:
        return None, "Endpoint DNS consumer correspondence is unproven"
    (consumer,) = consumers
    try:
        left_ref, left_index, left_delimiter, left_field = dns_expression(left)
        right_ref, right_index, right_delimiter, right_field = dns_expression(right)
        record_type, scope = stack_property(inputs, *consumer, "Type")
        expected = {"A", "AAAA"} if path == "AliasTarget.DNSName" else {"CNAME"}
        if (
            record_type not in expected
            or model_property(inputs, *consumer, "Type") != record_type
        ):
            raise Blocked(
                "Endpoint DNS requires matching Model and IaC RecordSet Types"
            )
        origins = export_origins([left, right], inputs.export_provenance)
        direct = export_origins(
            [left, right], getattr(inputs, "select_provenance", {}), direct=True
        )
        consumer_stack, _ = cfn_resource_identity(
            inputs.resources[consumer[0]][consumer[1]]["cfn-logicalId"]
        )
        if direct and any(
            origin["stack"] != consumer_stack or origin.get("scope") != scope
            for origin in direct
        ):
            raise Blocked("Endpoint DNS Direct provenance/stack is unproven")
        if origins:
            if any(origin.get("scope") != scope for origin in origins):
                raise Blocked("Endpoint DNS Export provenance/scope is unproven")
        elif not direct:
            raise Blocked("Endpoint DNS Direct provenance/stack is unproven")
        if (
            left_ref["$attribute"] != right_ref["$attribute"]
            or left_index != right_index
            or left_delimiter != right_delimiter
            or left_field != right_field
        ):
            return False, "Endpoint DNS selection or transformation differs"
        if (
            left_ref["$attribute"] != "DnsEntries"
            or left_delimiter != ":"
            or left_field != 1
        ):
            raise Blocked("Endpoint DNS extraction contract is unproven")
        for ref in (left_ref, right_ref):
            if inputs.resource_type(ref) != "EC2.VPCEndpoint":
                raise Blocked("Endpoint DNS Producer must be EC2.VPCEndpoint")
            service, identity = ref["$resource"]
            inputs.reference(service, ref, "DnsEntries")
            endpoint_type, endpoint_scope = stack_property(
                inputs, service, identity, "VpcEndpointType"
            )
            if (
                model_property(inputs, service, identity, "VpcEndpointType")
                != "Interface"
                or endpoint_type != "Interface"
                or endpoint_scope != scope
            ):
                raise Blocked(
                    "Endpoint DNS requires same-scope Model and IaC Interface Endpoint"
                )
        if path == "AliasTarget.DNSName":
            rows = [
                (rid, row)
                for rid, row in entries(
                    inputs.model(consumer[0]).authoritative, "desired.row."
                )
                if rid.rpartition("-")[0] == consumer[1]
                and row.get("property") == "Route53.RecordSet.AliasTarget.HostedZoneId"
            ]
            if len(rows) != 1:
                raise Blocked("Alias HostedZoneId correspondence is unproven")
            rid, row = rows[0]
            model_zone = inputs.prepare_value(
                consumer[0], row, "Route53.RecordSet", stack=consumer_stack, row_id=rid
            ).require_value()
            _, logical = cfn_resource_identity(
                inputs.resources[consumer[0]][consumer[1]]["cfn-logicalId"]
            )
            unit = next(
                unit for _, unit in inputs.templates() if unit["name"] == consumer_stack
            )
            _, (document, _, _) = inputs.stack(unit)
            actual_zone = inputs.evaluate_for_comparison(
                consumer_stack,
                select(
                    document["Resources"][logical].get("Properties", {}),
                    "AliasTarget.HostedZoneId",
                ),
            )
            zone_origins = export_origins(
                [model_zone, actual_zone], inputs.export_provenance
            )
            zone_direct = export_origins(
                [model_zone, actual_zone],
                getattr(inputs, "select_provenance", {}),
                direct=True,
            )
            if (
                any(origin.get("scope") != scope for origin in zone_origins)
                or any(
                    origin.get("scope") != scope or origin["stack"] != consumer_stack
                    for origin in zone_direct
                )
                or not (zone_origins or zone_direct)
            ):
                raise Blocked("Alias HostedZoneId provenance or scope is unproven")
            for zone in (model_zone, actual_zone):
                zone_ref, zone_index, zone_delimiter, zone_field = dns_expression(zone)
                if (zone_index, zone_delimiter, zone_field) != (left_index, ":", 0):
                    raise Blocked("Alias HostedZoneId and DNSName selection differs")
                decision = inputs.reference_decision(
                    zone_ref, left_ref, "EC2.VPCEndpoint", "DnsEntries"
                )
                if decision.equal is not True:
                    raise Blocked(
                        "Alias HostedZoneId Producer correspondence is unproven"
                    )
        producer = inputs.reference_decision(
            left_ref, right_ref, "EC2.VPCEndpoint", "DnsEntries"
        )
        if producer.equal is False:
            return False, "Endpoint DNS uses different Producer Resources"
        if producer.equal is not True:
            raise Blocked("Endpoint DNS Producer correspondence is unproven")
        if (
            expressions.symbolic_same(expressions.parts(left), expressions.parts(right))
            is not True
        ):
            raise Blocked("Endpoint DNS extraction equivalence is unproven")
        return (
            True,
            "structurally equal Endpoint DNS extraction; runtime Select bounds remain unproven",
        )
    except (Blocked, KeyError, ValueError, TypeError, OSError, StopIteration) as error:
        return None, str(error)


RULES = {
    "Route53.HostedZone": properties(
        objects="""
            HostedZoneConfig
            HostedZoneTags[]
            QueryLoggingConfig
            VPCs[]
        """,
        ordered="""
            VPCs
        """,
        references="""
            VPCs[].VPCId
        """,
        scalars="""
            HostedZoneConfig.Comment
            HostedZoneTags[].Key
            HostedZoneTags[].Value
            Name
            QueryLoggingConfig.CloudWatchLogsLogGroupArn
            VPCs[].VPCRegion
        """,
        tags="""
            HostedZoneTags
        """,
    ),
    "Route53.RecordSet": properties(
        objects="""
            AliasTarget
            GeoLocation
        """,
        ordered="""
            ResourceRecords
        """,
        references="""
            HostedZoneId
        """,
        scalars="""
            AliasTarget.DNSName
            AliasTarget.EvaluateTargetHealth
            AliasTarget.HostedZoneId
            Comment
            Failover
            GeoLocation.ContinentCode
            GeoLocation.CountryCode
            GeoLocation.SubdivisionCode
            HealthCheckId
            HostedZoneName
            MultiValueAnswer
            Name
            Region
            SetIdentifier
            TTL
            Type
            Weight
        """,
    ),
}


RULES["Route53.RecordSet"]["ResourceRecords"] = replace(
    RULES["Route53.RecordSet"]["ResourceRecords"], selected_reference=selected_reference
)
RULES["Route53.RecordSet"]["ResourceRecords[]"] = replace(
    OBJECT, selected_reference=selected_reference, selected_decision=selected_decision
)

RULES["Route53.RecordSet"]["AliasTarget.DNSName"] = replace(
    RULES["Route53.RecordSet"]["AliasTarget.DNSName"],
    selected_reference=selected_reference,
    selected_decision=selected_decision,
)
