"""KMS adapter contract fixtures."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from aws_mapping_compare import value as mapping_value
from model.importing import cli, inventory
from model.importing.adapter_contract_cases.core import (
    bind_fixture_parent,
    clear_fetch,
    fixture_context,
    fixture_properties,
    fixture_resource,
    missing_values,
)
from model.importing.adapter_contract_cases.fake_sdk import FakeCalls


class KMSCalls(FakeCalls):
    key_id = "12345678-1234-1234-1234-123456789012"
    aliases = ("alias/fixture",)
    conflicting = False
    duplicate = False

    def pages(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) != ("kms", "list_aliases", {}):
            raise ValueError("KMS alias request differs from fixture")
        entries = [
            {"AliasName": name, "TargetKeyId": self.key_id} for name in self.aliases
        ]
        return self.response(
            api, operation, {"Aliases": entries * (2 if self.duplicate else 1)}
        )

    def call(self, api: str, operation: str, **inputs: Any) -> dict[str, Any]:
        self.request(api, operation, inputs)
        if self.error:
            raise self.error
        if (api, operation, inputs) == (
            "cloudcontrol",
            "get_resource",
            {"TypeName": "AWS::KMS::Key", "Identifier": self.key_id},
        ):
            return self.response(
                api,
                operation,
                {
                    "ResourceDescription": {
                        "Identifier": self.key_id,
                        "Properties": json.dumps({"KeyId": self.key_id}),
                    }
                },
            )
        if api != "kms" or inputs.get("KeyId") not in (self.key_id, *self.aliases):
            raise ValueError("KMS key selector differs from fixture")
        if operation == "describe_key" and set(inputs) == {"KeyId"}:
            metadata = deepcopy(self.payload)
            if self.conflicting and inputs["KeyId"] == "alias/other":
                metadata["KeyId"] = "87654321-4321-4321-4321-210987654321"
            return self.response(api, operation, {"KeyMetadata": metadata})
        if operation == "get_key_rotation_status" and inputs == {"KeyId": self.key_id}:
            return self.response(
                api,
                operation,
                {"KeyRotationEnabled": True, "RotationPeriodInDays": 365},
            )
        if operation == "get_key_policy" and inputs == {
            "KeyId": self.key_id,
            "PolicyName": "default",
        }:
            return self.response(
                api,
                operation,
                {"Policy": json.dumps({"Version": "2012-10-17", "Statement": []})},
            )
        raise ValueError("Unexpected KMS operation or policy name")


def kms_fixture(root: Path, mapping: Any, properties: list[str]) -> dict[str, Any]:
    kind = ".".join(properties[0].split(".")[:2])
    getter = mapping.properties[properties[0]].field.getter
    payload = {
        "KeyId": KMSCalls.key_id,
        "Description": "fixture key",
        "Enabled": True,
        "KeySpec": "SYMMETRIC_DEFAULT",
        "KeyUsage": "ENCRYPT_DECRYPT",
        "MultiRegion": False,
        "Origin": "AWS_KMS",
    }
    ctx, fake = fixture_context(root, "kms", KMSCalls, payload)
    source = inventory.inventory_for(ctx)
    _, mapped = source.mapping("kms")
    record = source.cloud_record(
        "kms",
        "KMS.Key",
        {"Identifier": fake.key_id, "Properties": json.dumps({"KeyId": fake.key_id})},
        source.schema("KMS.Key"),
        mapping,
        mapped,
    )
    key = fixture_resource(root, ctx, "kms", record, "key")
    key.model._anchor_resources = {"key": [("key", {"anchor": "key"})]}
    ctx.models[key.model.path.resolve()] = key.model
    aliases = []
    for number, name in enumerate(("alias/fixture", "alias/other")):
        alias = cli.selector_resource(
            key.model,
            "alias" + str(number),
            {"kind": "KMS.Alias", "getters": {"alias": {"AliasName": name}}},
            mapped,
        )
        bind_fixture_parent(alias, key, "KeyId")
        aliases.append(alias)
    key.model.resources = [key, *aliases[:1]]
    resource = aliases[0] if kind == "KMS.Alias" else key
    cases = {name: (name, "typed", value) for name, value in payload.items()}
    cases.update(
        {
            "AliasName": ("AliasName", "typed", "alias/fixture"),
            "EnableKeyRotation": ("KeyRotationEnabled", "typed", True),
            "RotationPeriodInDays": ("RotationPeriodInDays", "typed", 365),
            "KeyPolicy": (
                "Policy",
                "policy",
                {"Version": "2012-10-17", "Statement": []},
            ),
        }
    )
    items = fixture_properties(
        ctx, resource, mapping, properties, kind, cases, ["normal", "access-denied"]
    )
    if kind == "KMS.Key" and getter == "base":
        missing_values(
            ctx, fake, resource, mapping, items, payload, required=("KeyId",)
        )
    clear_fetch(ctx)
    fake.error = cli.comparator().AcquisitionError("kms", "AccessDenied")
    try:
        resource.module.fetch(ctx, resource, getter)
    except cli.comparator().AcquisitionError:
        pass
    else:
        raise ValueError("KMS API failure was swallowed")
    fake.error = None
    if kind == "KMS.Alias":
        fake.aliases = ()
        try:
            resource.module.fetch(ctx, resource, getter)
        except cli.comparator().AcquisitionError:
            pass
        else:
            raise ValueError("Absent alias was accepted")
        fake.aliases = ("alias/fixture",)
        fake.duplicate = True
        try:
            resource.module.fetch(ctx, resource, getter)
        except cli.comparator().Unresolved:
            pass
        else:
            raise ValueError("Ambiguous alias was accepted")
        fake.duplicate = False
        fake.payload = {**payload, "KeyId": "87654321-4321-4321-4321-210987654321"}
        clear_fetch(ctx)
        if (
            resource.module.fetch(ctx, resource, getter).get("ParentMismatch")
            is not True
        ):
            raise ValueError("Alias parent mismatch was lost")
        branches = ["missing-alias", "ambiguous-alias", "parent-mismatch"]
    else:
        key.rows[:] = []
        for key_property in properties:
            clear_fetch(ctx)
            _, raw = mapping_value(
                ctx, resource, mapping, mapping.properties[key_property], key_property
            )
            if (
                cli.comparator().normalize(
                    ctx, raw, mapping.properties[key_property].field.norm
                )
                != cases[key_property.removeprefix(kind + ".")][2]
            ):
                raise ValueError("Alias-resolved key value differs")
        key.model.resources = [key]
        try:
            resource.module.fetch(ctx, resource, getter)
        except cli.comparator().Unresolved:
            pass
        else:
            raise ValueError("Missing key and aliases were accepted")
        key.model.resources = [key, *aliases]
        fake.aliases = ("alias/fixture", "alias/other")
        fake.conflicting = True
        try:
            resource.module.fetch(ctx, resource, getter)
        except cli.comparator().Unresolved:
            pass
        else:
            raise ValueError("Conflicting aliases were accepted")
        fake.conflicting = False
        resource.module.fetch(ctx, resource, getter)
        branches = [
            "alias-selector",
            "missing-selector",
            "conflicting-aliases",
            "multiple-aliases-one-key",
        ]
    for item in items.values():
        if item["status"] == "verified":
            item["branches"].extend(branches)
    return items


CONTRACTS = (
    (("KMS.Key", "base"), kms_fixture, "kms.describe_key", ("KeyId", "AliasName")),
    (
        ("KMS.Key", "policy"),
        kms_fixture,
        "kms.get_key_policy",
        ("KeyId", "AliasName"),
        ("kms.describe_key",),
    ),
    (
        ("KMS.Key", "rotation"),
        kms_fixture,
        "kms.get_key_rotation_status",
        ("KeyId", "AliasName"),
        ("kms.describe_key",),
    ),
    (
        ("KMS.Alias", "alias"),
        kms_fixture,
        "kms.list_aliases",
        ("AliasName", "parent"),
        ("kms.describe_key",),
    ),
)
