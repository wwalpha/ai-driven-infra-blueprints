"""Resolve typed references from confirmed Model values without changing authority."""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from design.services.definitions.registry import POLICY_FORMATS
from utils.arn_components import ARN_COMPONENTS
from utils.arn_values import context_value, generated_attribute, named_arn
from utils.aws_catalogs import catalog_outputs
from utils.aws_sdk import aws_runtime
from utils.cloudformation.inputs import Blocked
from utils.comparison_rows import put_row
from utils.json_format import strict_json, validate_aws_document
from utils.reference_contracts import (
    ARN_DEFAULTS,
    ARN_SHAPES,
    RETURN_ATTRIBUTE_PROPERTIES,
    _arn_pattern,
    reference_attribute,
)

from model.core import ReferenceResolutionError, entries, literal, resource_link


@dataclass(frozen=True)
class ReferenceValue:
    status: Literal["resolved", "pending_deploy", "unresolved"]
    value: object = None
    reason: str = ""


class PendingDeploy(ValueError):
    pass


def resolve(node, scope, resolver, *, field=None, property_name=None, context=None):
    snapshot, number, resource = resolver.resolve_logical(node.logical_id, scope)
    operand = any(token.startswith("Fn::") for token in node.pointer.split("/"))
    resolver.validate_attribute(
        resource["resourceType"],
        node.attribute,
        field=field,
        context=context,
        operand=operand,
    )
    if field and not operand:
        resolver.validate_reference_type(
            resource["resourceType"], node.attribute, field
        )
    terminal = next(
        (
            token
            for token in reversed(node.pointer.rstrip("/").split("/"))
            if not token.isdigit()
        ),
        "",
    )
    if (
        POLICY_FORMATS.get(property_name) in {"statement", "wrapped-statement"}
        and terminal in {"Resource", "NotResource", "AWS"}
        and reference_attribute(resource["resourceType"], node.attribute)
        != reference_attribute(resource["resourceType"], "Arn")
    ):
        raise ReferenceResolutionError(
            "policy Resource/Principal requires the ARN attribute"
        )
    return snapshot, number, resource, node.attribute


@lru_cache(maxsize=None)
def partition_for(region):
    partitions = aws_runtime().sdk_loader().load_data("endpoints")["partitions"]
    matches = [part["partition"] for part in partitions if region in part["regions"]]
    return matches[0] if len(matches) == 1 else None


def confirmed(value):
    if not isinstance(value, str):
        return value
    if (
        not value
        or value.lower()
        in {"unresolved", "unset", "tbd", "todo", "pending_deploy", "未確定"}
        or resource_link(value)
    ):
        return None
    validate_aws_document(value)
    if "${" in value:
        raise ValueError("reference requires a confirmed literal")
    return value


class ProducerValues:
    def __init__(self, snapshot, number, resource, resolver):
        self.snapshot, self.number, self.resource, self.resolver = (
            snapshot,
            number,
            resource,
            resolver,
        )
        self.kind = resource["resourceType"]
        self.rows = [
            (rid, row)
            for rid, row in entries(snapshot.authoritative, "desired.row.")
            if rid.rpartition("-")[0] == number
        ]
        self.schema = resolver.catalog.schema(self.kind)

    def value(self, field, *, recorded=False):
        rows = [
            (rid, row)
            for rid, row in self.rows
            if row["property"] == self.kind + "." + field
        ]
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("ambiguous Producer property: " + field)
        rid, row = rows[0]
        desired = confirmed(literal(row["value"]))
        observed = self.snapshot.authoritative.get(f"observed.row.{rid}.value")
        if observed is not None:
            observed = literal(observed)
            if observed == "PENDING_DEPLOY":
                if self.resource.get("resourceMode", "CREATE") == "CREATE":
                    raise PendingDeploy("explicit PENDING_DEPLOY: " + field)
                raise ValueError(
                    "PENDING_DEPLOY is not a confirmed IMPORT value: " + field
                )
            observed = confirmed(observed)
        if desired is not None and observed is not None and desired != observed:
            raise ValueError("desired and observed conflict: " + field)
        value = observed if observed is not None else None if recorded else desired
        if value is None:
            return None
        errors = self.resolver.catalog.literal_errors(self.kind, field, value)
        if errors:
            raise ValueError(
                "invalid Producer property " + field + ": " + "; ".join(errors)
            )
        node = self.resolver.catalog.property_schema(self.kind, field)
        expected = node.get("type")
        return (
            value
            if expected == "string"
            or isinstance(expected, list)
            and "string" in expected
            else strict_json(value)
        )

    def pending(self):
        outputs = catalog_outputs(self.resolver.root, self.kind)
        states = [
            literal(self.snapshot.authoritative.get(f"observed.row.{rid}.value", ""))
            for rid, row in self.rows
            if row["property"] in outputs
        ]
        return (
            self.resource.get("resourceMode", "CREATE") == "CREATE"
            and states
            and all(state == "PENDING_DEPLOY" for state in states)
        )

    def arn(self, attribute):
        direct = self.value(attribute)
        identifier, _, _ = ARN_SHAPES[self.kind]
        fields = identifier if isinstance(identifier, dict) else {identifier: "id"}
        target = self.resolver.target(self.snapshot.scope)
        pseudo = {
            "AWS::Partition": partition_for(target.get("awsRegion")),
            "AWS::Region": target.get("awsRegion"),
            "AWS::AccountId": target.get(
                "awsExecutionAccountId", target.get("awsAccountId")
            ),
        }
        properties = {}
        needed = tuple(fields) + ARN_COMPONENTS.get(self.kind, (None, ()))[1]
        for _, row in self.rows:
            field = row["property"].removeprefix(self.kind + ".")
            if not any(
                field == prop or field.startswith(prop + ".") for prop in needed
            ):
                continue
            raw = literal(row["value"])
            if raw.lstrip().startswith(("{", "[")) and not resource_link(raw):
                try:
                    raw = strict_json(raw)
                except ValueError:
                    pass
            put_row(properties, field, raw)
        values = {}
        for field in fields:
            values[field] = self.value(
                field, recorded=generated_attribute(self.schema, field)
            )
            if values[field] is None and not any(
                row["property"] == self.kind + "." + field for _, row in self.rows
            ):
                values[field] = ARN_DEFAULTS.get((self.kind, field))
            put = properties
            tokens = field.split(".")
            for token in tokens[:-1]:
                put = put.setdefault(token, {})
            put[tokens[-1]] = values[field]
        if direct is not None:
            matched = re.fullmatch(_arn_pattern(ARN_SHAPES[self.kind]), direct)
            if matched is None:
                raise ValueError("invalid recorded ARN: " + attribute)
            components = matched.groupdict()
            for field, group in fields.items():
                if (
                    values[field] is not None
                    and str(values[field]) != components[group]
                ):
                    raise ValueError("desired/observed ARN identity conflict: " + field)
            for group in ("partition", "region", "account"):
                if (
                    group in components
                    and context_value(pseudo, group) != components[group]
                ):
                    raise ValueError(
                        "recorded ARN and confirmed " + group + " conflict"
                    )
            if any(value is None for value in values.values()):
                return direct
        assembled = named_arn(
            self.kind,
            properties,
            pseudo,
            evaluate=confirmed,
            schema=self.schema,
            recorded=values.get,
        )
        if direct is not None and direct != assembled:
            raise ValueError("desired and observed ARN conflict")
        return assembled


def reference_value(resolver, scope, node, **contract):
    try:
        snapshot, number, resource, attribute = resolve(
            node, scope, resolver, **contract
        )
        producer = ProducerValues(snapshot, number, resource, resolver)
        if producer.pending():
            raise PendingDeploy("explicit Producer output PENDING_DEPLOY")
        attribute = reference_attribute(resource["resourceType"], attribute)
        value = (
            producer.arn(attribute)
            if resource["resourceType"] in ARN_SHAPES
            and attribute == reference_attribute(resource["resourceType"], "Arn")
            else producer.value(
                RETURN_ATTRIBUTE_PROPERTIES.get(
                    (resource["resourceType"], attribute), attribute
                )
            )
        )
        if value is None:
            return ReferenceValue(
                "unresolved", reason="no confirmed desired or observed value"
            )
        return ReferenceValue("resolved", value)
    except PendingDeploy as error:
        return ReferenceValue("pending_deploy", reason=str(error))
    except (Blocked, ValueError, KeyError) as error:
        return ReferenceValue("unresolved", reason=str(error))
