"""Service-specific checks and components for ARN assembly."""

from utils.cloudformation.inputs import Blocked


def rule_group(properties, evaluate):
    group_type = evaluate(properties.get("Type"))
    if group_type not in ("STATEFUL", "STATELESS"):
        raise Blocked("rule group ARN requires a confirmed STATEFUL or STATELESS Type")
    return {"type": group_type.lower()}


COMPONENTS = {
    "NetworkFirewall.RuleGroup": rule_group,
}
