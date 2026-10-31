"""eventbridge: selected properties -> read-only SDK responses; inputs in fetch()."""

from datetime import datetime, timezone

APIS = {
    ("events", "describe_rule"),
    ("events", "list_targets_by_rule"),
    ("scheduler", "get_schedule"),
}


def sensitive(prop):
    return prop == "Scheduler.Schedule.Target.Input"


def rename_keys(value, names):
    if isinstance(value, dict):
        for source, destination in names.items():
            if source in value:
                value[destination] = value.pop(source)


def normalize_date(value):
    if value is None:
        return value
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Schedule date must include a timezone")
    return value.astimezone(timezone.utc).isoformat()


def normalize_schedule(response):
    for key in ("StartDate", "EndDate"):
        if response.get(key) is not None:
            response[key] = normalize_date(response[key])
    target = response.get("Target")
    ecs = target.get("EcsParameters") if isinstance(target, dict) else None
    if not isinstance(ecs, dict):
        return response
    network = ecs.get("NetworkConfiguration")
    if isinstance(network, dict):
        rename_keys(network, {"awsvpcConfiguration": "AwsvpcConfiguration"})
    for name, keys in (
        (
            "CapacityProviderStrategy",
            {
                "capacityProvider": "CapacityProvider",
                "weight": "Weight",
                "base": "Base",
            },
        ),
        ("PlacementConstraints", {"type": "Type", "expression": "Expression"}),
        ("PlacementStrategy", {"type": "Type", "field": "Field"}),
    ):
        items = ecs.get(name)
        if isinstance(items, list):
            for item in items:
                rename_keys(item, keys)
    return response


def fetch(ctx, r, getter):
    if getter == "schedule":
        inputs = {"Name": r.value("Name")}
        group = r.optional("GroupName")
        if group is not None:
            inputs["GroupName"] = group
        return normalize_schedule(ctx.call("scheduler", "get_schedule", **inputs))
    inputs = {
        "Name" if getter == "base" else "Rule": r.value("Name"),
        "EventBusName": r.optional("EventBusName", "default"),
    }
    if getter == "targets":
        return ctx.pages("events", "list_targets_by_rule", **inputs)
    return ctx.call("events", "describe_rule", **inputs)
