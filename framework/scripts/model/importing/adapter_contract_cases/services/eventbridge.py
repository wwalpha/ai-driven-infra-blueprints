"""Offline eventbridge adapter fixtures."""

from pathlib import Path
from typing import Any

from model.importing.adapter_contract_cases.core import (
    direct_properties,
    direct_resource,
    failure_branches,
)


def direct_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    api, selector, envelope = "events", "Name", "$"
    getter = mapping.properties[properties[0]].field.getter
    operation = "describe_rule" if getter == "base" else "list_targets_by_rule"
    argument = "Name" if getter == "base" else "Rule"
    cloud = {
        "Name": "fixture",
        "Arn": "arn:aws:events:ap-northeast-1:123456789012:rule/fixture",
    }
    if getter == "base":
        payload = {
            "Name": "fixture",
            "State": "ENABLED",
            "EventBusName": "default",
            "EventPattern": '{"source":["fixture.event"]}',
        }
        cases = {
            "Name": ("Name", "typed", "fixture"),
            "State": ("State", "typed", "ENABLED"),
            "EventBusName": ("EventBusName", "typed", "default"),
            "EventPattern": ("EventPattern", "json", {"source": ["fixture.event"]}),
        }
    else:
        payload = {
            "Targets": [
                {
                    "Id": "target",
                    "Arn": "arn:aws:lambda:ap-northeast-1:123456789012:function:fixture",
                    "DeadLetterConfig": {
                        "Arn": "arn:aws:sqs:ap-northeast-1:123456789012:fixture"
                    },
                    "RetryPolicy": {
                        "MaximumEventAgeInSeconds": 3600,
                        "MaximumRetryAttempts": 3,
                    },
                }
            ]
        }
        cases = {
            "Targets[].Id": ("Targets[].Id", "typed", ["target"]),
            "Targets[].Arn": (
                "Targets[].Arn",
                "arn",
                ["arn:aws:lambda:ap-northeast-1:123456789012:function:fixture"],
            ),
            "Targets[].DeadLetterConfig.Arn": (
                "Targets[].DeadLetterConfig.Arn",
                "arn",
                ["arn:aws:sqs:ap-northeast-1:123456789012:fixture"],
            ),
            "Targets[].RetryPolicy.MaximumEventAgeInSeconds": (
                "Targets[].RetryPolicy.MaximumEventAgeInSeconds",
                "typed",
                [3600],
            ),
            "Targets[].RetryPolicy.MaximumRetryAttempts": (
                "Targets[].RetryPolicy.MaximumRetryAttempts",
                "typed",
                [3],
            ),
        }
    ctx, fake, resource = direct_resource(
        root,
        mapping,
        kind,
        api,
        operation,
        {argument: "fixture", "EventBusName": "default"},
        envelope,
        cloud,
        payload,
    )
    items = direct_properties(
        ctx,
        fake,
        resource,
        mapping,
        properties,
        kind,
        cases,
        payload,
        (
            "Name",
            "repositoryName",
            "InstanceProfileName",
            "RoleName",
            "UserName",
            "Roles",
        ),
    )
    if not fake.calls:
        return items
    if kind == "Events.Rule":
        resource.rows.append(
            (
                "fixture-999",
                {"property": "Events.Rule.EventBusName", "value": "`custom-bus`"},
            )
        )
        fake.inputs = {argument: "fixture", "EventBusName": "custom-bus"}
        if getter == "base":
            fake.payload = {**payload, "EventBusName": "custom-bus"}
        fake.calls.clear()
        response = resource.module.fetch(ctx, resource, getter)
        if fake.calls != [(api, operation, fake.inputs)]:
            raise ValueError("Explicit event bus request differs from fixture")
        if getter == "base" and response.get("EventBusName") != "custom-bus":
            raise ValueError("Explicit event bus response differs from fixture")
        resource.rows[:] = [row for row in resource.rows if row[0] != "fixture-999"]
        fake.inputs = {argument: "fixture", "EventBusName": "default"}
        fake.payload = payload
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].append("explicit-event-bus")
    failure_branches(
        ctx, fake, resource, mapping, properties[0], api + "." + operation, selector
    )
    return items


def schedule_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    api, operation, selector, argument, envelope = (
        "scheduler",
        "get_schedule",
        "Name",
        "Name",
        "$",
    )
    cloud = {"Name": "fixture", "GroupName": "default"}
    payload = {
        "Name": "fixture",
        "State": "ENABLED",
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "ScheduleExpression": "rate(1 hour)",
        "ScheduleExpressionTimezone": "UTC",
        "Target": {
            "Arn": "arn:aws:lambda:ap-northeast-1:123456789012:function:fixture",
            "RoleArn": "arn:aws:iam::123456789012:role/fixture",
            "RetryPolicy": {
                "MaximumEventAgeInSeconds": 3600,
                "MaximumRetryAttempts": 3,
            },
        },
    }
    cases = {
        "Name": ("Name", "typed", "fixture"),
        "State": ("State", "typed", "ENABLED"),
        "FlexibleTimeWindow.Mode": ("FlexibleTimeWindow.Mode", "typed", "OFF"),
        "ScheduleExpression": ("ScheduleExpression", "typed", "rate(1 hour)"),
        "ScheduleExpressionTimezone": (
            "ScheduleExpressionTimezone",
            "typed",
            "UTC",
        ),
        "Target.Arn": ("Target.Arn", "arn", payload["Target"]["Arn"]),
        "Target.RoleArn": ("Target.RoleArn", "arn", payload["Target"]["RoleArn"]),
        "Target.RetryPolicy.MaximumEventAgeInSeconds": (
            "Target.RetryPolicy.MaximumEventAgeInSeconds",
            "typed",
            3600,
        ),
        "Target.RetryPolicy.MaximumRetryAttempts": (
            "Target.RetryPolicy.MaximumRetryAttempts",
            "typed",
            3,
        ),
    }
    ctx, fake, resource = direct_resource(
        root,
        mapping,
        kind,
        api,
        operation,
        {argument: "fixture", "GroupName": "default"},
        envelope,
        cloud,
        payload,
    )
    items = direct_properties(
        ctx,
        fake,
        resource,
        mapping,
        properties,
        kind,
        cases,
        payload,
        ("Name", "repositoryName", "FlexibleTimeWindow", "Target"),
    )
    if not fake.calls:
        return items
    failure_branches(
        ctx, fake, resource, mapping, properties[0], api + "." + operation, selector
    )
    return items


CONTRACTS = (
    (
        ("Scheduler.Schedule", "schedule"),
        schedule_fixture,
        "scheduler.get_schedule",
        ("Name",),
    ),
    (
        ("Events.Rule", "base"),
        direct_fixture,
        "events.describe_rule",
        ("Name", "EventBusName"),
    ),
    (
        ("Events.Rule", "targets"),
        direct_fixture,
        "events.list_targets_by_rule",
        ("Name", "EventBusName"),
    ),
)
