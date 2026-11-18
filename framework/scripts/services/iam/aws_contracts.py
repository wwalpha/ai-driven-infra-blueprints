"""Offline iam adapter fixtures."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aws_mapping_compare import value as mapping_value
from model.importing import cli, inventory
from model.importing.adapter_contract_cases.core import (
    clear_fetch,
    direct_properties,
    direct_resource,
    failure_branches,
    fixture_context,
    fixture_properties,
    fixture_resource,
)
from model.importing.adapter_contract_cases.fake_sdk import FakeCalls


class IAMPolicyCalls(FakeCalls):
    subject = ""
    getter = ""
    failure_operation = ""
    empty = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        subject = self.subject.lower()
        selector = self.subject + "Name"
        expected = (
            "list_attached_" + subject + "_policies"
            if self.getter == "attached"
            else "list_" + subject + "_policies"
        )
        if (api, operation, inputs) != ("iam", expected, {selector: "fixture"}):
            raise ValueError("IAM policy listing selector differs from fixture")
        if self.getter == "attached":
            values = (
                []
                if self.empty
                else [
                    {
                        "PolicyName": "fixture-policy",
                        "PolicyArn": "arn:aws:iam::123456789012:policy/fixture-policy",
                    }
                ]
            )
            return self.response(api, operation, {"AttachedPolicies": values})
        return self.response(
            api, operation, {"PolicyNames": [] if self.empty else ["fixture-policy"]}
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) == (
            "cloudcontrol",
            "get_resource",
            {"TypeName": "AWS::IAM::" + self.subject, "Identifier": "fixture"},
        ):
            return self.response(
                api,
                operation,
                {
                    "ResourceDescription": {
                        "Identifier": "fixture",
                        "Properties": json.dumps({self.subject + "Name": "fixture"}),
                    }
                },
            )
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        selector = self.subject + "Name"
        if (api, operation, inputs) != (
            "iam",
            "get_" + self.subject.lower() + "_policy",
            {selector: "fixture", "PolicyName": "fixture-policy"},
        ):
            raise ValueError("IAM policy detail selector differs from fixture")
        return self.response(
            api,
            operation,
            {
                selector: "fixture",
                "PolicyName": "fixture-policy",
                "PolicyDocument": json.dumps(
                    {"Version": "2012-10-17", "Statement": []}
                ),
            },
        )


class IAMManagedCalls(FakeCalls):
    failure_operation = ""
    duplicate = False
    empty_roles = False
    arn = "arn:aws:iam::123456789012:policy/fixture-policy"

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        if (api, operation, inputs) == ("iam", "list_policies", {"Scope": "Local"}):
            policy = {
                "PolicyName": "fixture",
                "PolicyId": "ANPA12345678901234567",
                "Arn": self.arn,
                "DefaultVersionId": "v1",
                "Path": "/",
            }
            return self.response(
                api, operation, {"Policies": [policy] * (2 if self.duplicate else 1)}
            )
        if (api, operation, inputs) == (
            "iam",
            "list_entities_for_policy",
            {"PolicyArn": self.arn, "EntityFilter": "Role"},
        ):
            roles = (
                []
                if self.empty_roles
                else [{"RoleName": "fixture-role", "RoleId": "AROA12345678901234567"}]
            )
            return self.response(api, operation, {"PolicyRoles": roles})
        raise ValueError("IAM managed policy listing differs from fixture")

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if (api, operation, inputs) == (
            "cloudcontrol",
            "get_resource",
            {"TypeName": "AWS::IAM::ManagedPolicy", "Identifier": self.arn},
        ):
            return self.response(
                api,
                operation,
                {
                    "ResourceDescription": {
                        "Identifier": self.arn,
                        "Properties": json.dumps(
                            {"ManagedPolicyName": "fixture", "PolicyArn": self.arn}
                        ),
                    }
                },
            )
        if self.error and (
            not self.failure_operation or self.failure_operation == operation
        ):
            raise self.error
        if (api, operation, inputs) != (
            "iam",
            "get_policy_version",
            {"PolicyArn": self.arn, "VersionId": "v1"},
        ):
            raise ValueError("IAM policy version selector differs from fixture")
        return self.response(
            api,
            operation,
            {
                "PolicyVersion": {
                    "VersionId": "v1",
                    "IsDefaultVersion": True,
                    "Document": json.dumps({"Version": "2012-10-17", "Statement": []}),
                }
            },
        )


def iam_managed_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = "IAM.ManagedPolicy"
    getter = mapping.properties[properties[0]].field.getter
    ctx, fake = fixture_context(root, "iam", IAMManagedCalls, {})
    cloud = {"ManagedPolicyName": "fixture", "PolicyArn": fake.arn}
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("iam")
    record = source.cloud_record(
        "iam",
        kind,
        {"Identifier": fake.arn, "Properties": json.dumps(cloud)},
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "iam", record)
    cases = {
        "ManagedPolicyName": ("PolicyName", "typed", "fixture"),
        "PolicyDocument": (
            "Document",
            "policy",
            {"Version": "2012-10-17", "Statement": []},
        ),
        "Roles": ("Roles", "name", ["fixture-role"]),
    }
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["normal", "missing-selector", "access-denied", "ambiguous-policy"],
    )
    fake.duplicate = True
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().Unresolved:
        pass
    else:
        raise ValueError("Duplicate IAM managed policies were accepted")
    fake.duplicate = False
    if getter == "entities":
        fake.empty_roles = True
        clear_fetch(ctx)
        key = properties[0]
        _, raw = mapping_value(ctx, resource, mapping, mapping.properties[key], key)
        if raw != []:
            raise ValueError("Empty IAM policy roles were not preserved")
        fake.empty_roles = False
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].append("empty-roles")
    if getter in {"document", "entities"}:
        fake.error = cli.comparator().AcquisitionError(
            "iam.policy-detail", "AccessDenied"
        )
        fake.failure_operation = (
            "get_policy_version" if getter == "document" else "list_entities_for_policy"
        )
        clear_fetch(ctx)
        try:
            mapping_value(
                ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
            )
        except cli.comparator().AcquisitionError as error:
            if error.code != "AccessDenied":
                raise ValueError(
                    "IAM managed policy detail failure was changed"
                ) from error
        else:
            raise ValueError("IAM managed policy detail failure was swallowed")
        fake.error, fake.failure_operation = None, ""
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].append("detail-access-denied")
    failure_branches(
        ctx,
        fake,
        resource,
        mapping,
        properties[0],
        "iam.list_policies",
        "ManagedPolicyName",
    )
    return items


def iam_policy_fixture(
    root: Path, mapping: Any, properties: list[str]
) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    subject = kind.split(".")[1]
    getter = mapping.properties[properties[0]].field.getter
    ctx, fake = fixture_context(root, "iam", IAMPolicyCalls, {})
    fake.subject, fake.getter = subject, getter
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("iam")
    cloud = {subject + "Name": "fixture"}
    record = source.cloud_record(
        "iam",
        kind,
        {"Identifier": "fixture", "Properties": json.dumps(cloud)},
        source.schema(kind),
        mapping,
        mapped,
    )
    resource = fixture_resource(root, ctx, "iam", record)
    policy = {"Version": "2012-10-17", "Statement": []}
    cases = (
        {
            "ManagedPolicyArns": (
                "Arns",
                "arn",
                ["arn:aws:iam::123456789012:policy/fixture-policy"],
            )
        }
        if getter == "attached"
        else {
            "Policies[].PolicyName": (
                "Policies[].PolicyName",
                "typed",
                ["fixture-policy"],
            ),
            "Policies[].PolicyDocument": (
                "Policies[].PolicyDocument",
                "policy",
                [policy],
            ),
        }
    )
    items = fixture_properties(
        ctx,
        resource,
        mapping,
        properties,
        kind,
        cases,
        ["normal", "missing-selector", "access-denied", "empty"],
    )
    fake.empty = True
    clear_fetch(ctx)
    for key, item in items.items():
        if item["status"] != "verified":
            continue
        _, raw = mapping_value(ctx, resource, mapping, mapping.properties[key], key)
        if raw != []:
            item.update(
                status="broken", reason="Empty IAM policy list was not preserved"
            )
    fake.empty = False
    if getter == "inline":
        fake.error = cli.comparator().AcquisitionError("iam.get_policy", "AccessDenied")
        fake.failure_operation = "get_" + subject.lower() + "_policy"
        clear_fetch(ctx)
        try:
            mapping_value(
                ctx, resource, mapping, mapping.properties[properties[0]], properties[0]
            )
        except cli.comparator().AcquisitionError as error:
            if error.code != "AccessDenied":
                raise ValueError("IAM policy detail failure was changed") from error
        else:
            raise ValueError("IAM policy detail failure was swallowed")
        fake.error, fake.failure_operation = None, ""
        for item in items.values():
            if item["status"] == "verified":
                item["branches"].append("detail-access-denied")
    failure_branches(
        ctx, fake, resource, mapping, properties[0], "iam.policy-list", subject + "Name"
    )
    return items


def direct_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    api = "iam"
    item = kind.split(".")[1]
    selector = {
        "InstanceProfile": "InstanceProfileName",
        "Role": "RoleName",
        "User": "UserName",
    }[item]
    operation = {
        "InstanceProfile": "get_instance_profile",
        "Role": "get_role",
        "User": "get_user",
    }[item]
    argument, envelope = selector, item
    cloud = {selector: "fixture"}
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    if item == "InstanceProfile":
        role = {
            "Path": "/",
            "RoleName": "fixture-role",
            "RoleId": "AROA12345678901234567",
            "Arn": "arn:aws:iam::123456789012:role/fixture-role",
            "CreateDate": stamp,
        }
        payload = {
            "Path": "/",
            "InstanceProfileName": "fixture",
            "InstanceProfileId": "AIPA12345678901234567",
            "Arn": "arn:aws:iam::123456789012:instance-profile/fixture",
            "CreateDate": stamp,
            "Roles": [role],
        }
        cases = {
            "InstanceProfileName": ("InstanceProfileName", "typed", "fixture"),
            "Roles": ("Roles[].RoleName", "name", ["fixture-role"]),
        }
    elif item == "Role":
        policy = {"Version": "2012-10-17", "Statement": []}
        payload = {
            "Path": "/",
            "RoleName": "fixture",
            "RoleId": "AROA12345678901234567",
            "Arn": "arn:aws:iam::123456789012:role/fixture",
            "CreateDate": stamp,
            "Description": "fixture role",
            "AssumeRolePolicyDocument": json.dumps(policy),
        }
        cases = {
            "RoleName": ("RoleName", "typed", "fixture"),
            "Description": ("Description", "typed", "fixture role"),
            "AssumeRolePolicyDocument": (
                "AssumeRolePolicyDocument",
                "policy",
                policy,
            ),
        }
    else:
        payload = {
            "Path": "/",
            "UserName": "fixture",
            "UserId": "AIDA12345678901234567",
            "Arn": "arn:aws:iam::123456789012:user/fixture",
            "CreateDate": stamp,
        }
        cases = {"UserName": ("UserName", "typed", "fixture")}
    ctx, fake, resource = direct_resource(
        root,
        mapping,
        kind,
        api,
        operation,
        {argument: "fixture"},
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
    failure_branches(
        ctx, fake, resource, mapping, properties[0], api + "." + operation, selector
    )
    return items


CONTRACTS = (
    (
        ("IAM.InstanceProfile", "base"),
        direct_fixture,
        "iam.get_instance_profile",
        ("InstanceProfileName",),
    ),
    (("IAM.Role", "base"), direct_fixture, "iam.get_role", ("RoleName",)),
    (("IAM.User", "base"), direct_fixture, "iam.get_user", ("UserName",)),
    (
        ("IAM.Role", "attached"),
        iam_policy_fixture,
        "iam.list_attached_role_policies",
        ("RoleName",),
    ),
    (
        ("IAM.Role", "inline"),
        iam_policy_fixture,
        "iam.list_role_policies",
        ("RoleName",),
        ("iam.get_role_policy",),
    ),
    (
        ("IAM.User", "attached"),
        iam_policy_fixture,
        "iam.list_attached_user_policies",
        ("UserName",),
    ),
    (
        ("IAM.User", "inline"),
        iam_policy_fixture,
        "iam.list_user_policies",
        ("UserName",),
        ("iam.get_user_policy",),
    ),
    (
        ("IAM.ManagedPolicy", "base"),
        iam_managed_fixture,
        "iam.list_policies",
        ("ManagedPolicyName",),
    ),
    (
        ("IAM.ManagedPolicy", "document"),
        iam_managed_fixture,
        "iam.list_policies",
        ("ManagedPolicyName",),
        ("iam.get_policy_version",),
    ),
    (
        ("IAM.ManagedPolicy", "entities"),
        iam_managed_fixture,
        "iam.list_policies",
        ("ManagedPolicyName",),
        ("iam.list_entities_for_policy",),
    ),
)
