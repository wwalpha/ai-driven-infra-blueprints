"""Service ARN identity conditions, shared by all ARN assembly callers."""

import re

from utils.cloudformation.inputs import Blocked


def public_domain(properties, evaluate):
    configuration = evaluate(properties.get("EndpointConfiguration", {}))
    types = (
        configuration.get("Types", ["EDGE"])
        if isinstance(configuration, dict)
        else None
    )
    if (
        not isinstance(types, list)
        or len(types) != 1
        or types[0] not in ("EDGE", "REGIONAL")
    ):
        raise Blocked(
            "domain ARN requires a proven public endpoint; private domains need an AWS-generated identifier"
        )
    return {}


def event_rule(properties, evaluate):
    bus = evaluate(properties.get("EventBusName", "default"))
    components = {}
    if isinstance(bus, str) and bus.startswith("arn:"):
        match = re.fullmatch(
            r"arn:([^:]+):events:([^:]+):([0-9]{12}):event-bus/([A-Za-z0-9._-]{1,256})",
            bus,
        )
        if match is None:
            raise Blocked("rule ARN requires a valid EventBus ARN")
        partition, region, account, bus = match.groups()
        components = dict(partition=partition, region=region, account=account)
    if (
        not isinstance(bus, str)
        or bus in {"UNSET", "PENDING_DEPLOY", "TBD", "TODO", "未確定"}
        or re.fullmatch(r"[A-Za-z0-9._-]{1,256}", bus) is None
    ):
        raise Blocked("rule ARN requires a confirmed event bus name")
    return dict(components, bus="" if bus == "default" else bus + "/")


def rule_group(properties, evaluate):
    group_type = evaluate(properties.get("Type"))
    if group_type not in ("STATEFUL", "STATELESS"):
        raise Blocked("rule group ARN requires a confirmed STATEFUL or STATELESS Type")
    return {"type": group_type.lower()}


def glue_name(properties, evaluate):
    # The newer top-level names must agree with the nested creation name.
    for field, container in [("DatabaseName", "DatabaseInput"), ("Name", "TableInput")]:
        if field in properties and container in properties:
            if evaluate(properties[field]) != evaluate(
                properties[container].get("Name")
            ):
                raise Blocked("Glue ARN requires one confirmed creation name")
    return {}


ARN_COMPONENTS = {
    "ApiGateway.DomainName": (public_domain, ("EndpointConfiguration",)),
    "Events.Rule": (event_rule, ("EventBusName",)),
    "NetworkFirewall.RuleGroup": (rule_group, ("Type",)),
    **dict.fromkeys(
        (
            "Glue.Connection",
            "Glue.SecurityConfiguration",
            "Glue.Job",
            "Glue.Crawler",
            "Glue.Database",
            "Glue.Table",
        ),
        (glue_name, ("DatabaseName", "DatabaseInput.Name", "Name", "TableInput.Name")),
    ),
}
