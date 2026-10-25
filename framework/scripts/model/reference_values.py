"""Resolve typed references from confirmed Model values without changing authority."""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

from design.services.definitions.registry import POLICY_FORMATS
from utils.arn_components import ARN_COMPONENTS
from utils.arn_values import context_value, generated_attribute, named_arn
from utils.aws_catalogs import catalog_outputs
from utils.aws_sdk import aws_runtime
from utils.cloudformation.inputs import Blocked
from utils.comparison_rows import put_row
from utils.json_format import AwsDocumentError, strict_json, validate_aws_document
from utils.reference_contracts import (
    ARN_DEFAULTS,
    ARN_SHAPES,
    RETURN_ATTRIBUTE_PROPERTIES,
    _arn_pattern,
    reference_attribute,
)

from model.core import (
    FrameworkUnsupportedError,
    ModelNeedsFixError,
    ReferenceDiagnosticError,
    ReferenceResolutionError,
    entries,
    literal,
    resource_link,
)


@dataclass(frozen=True)
class ReferenceValue:
    status: Literal["resolved", "pending_deploy", "unresolved"]
    value: object = None
    reason: str = ""
    diagnostic: dict = field(default_factory=dict)

    @property
    def category(self):
        return self.diagnostic.get("category", "RESOLVED")


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
        raise ModelNeedsFixError(
            "policy Resource/Principal requires the ARN attribute",
            code="MODEL_REF_INVALID_ATTRIBUTE",
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
    try:
        validate_aws_document(value)
    except AwsDocumentError as error:
        raise ModelNeedsFixError(str(error), code="MODEL_REF_INVALID_VALUE") from error
    if "${" in value:
        raise ModelNeedsFixError(
            "reference requires a confirmed literal", code="MODEL_REF_INVALID_VALUE"
        )
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
        self.pending_fields = set()
        self.observed_fields = set()
        self.drift_fields = set()

    def value(self, field, *, recorded=False):
        rows = [
            (rid, row)
            for rid, row in self.rows
            if row["property"] == self.kind + "." + field
        ]
        if not rows:
            return None
        if len(rows) != 1:
            raise ModelNeedsFixError(
                "ambiguous Producer property: " + field, code="MODEL_REF_VALUE_CONFLICT"
            )
        rid, row = rows[0]
        desired_raw = literal(row["value"])
        if desired_raw == "PENDING_DEPLOY":
            raise ModelNeedsFixError(
                "PENDING_DEPLOY belongs only to CREATE observations: " + field,
                code="MODEL_REF_INVALID_PENDING_STATE",
            )
        desired = confirmed(desired_raw)
        observed = self.snapshot.authoritative.get(f"observed.row.{rid}.value")
        if observed is not None:
            observed = literal(observed)
            if observed == "PENDING_DEPLOY":
                if self.resource.get("resourceMode", "CREATE") != "CREATE":
                    raise ModelNeedsFixError(
                        "PENDING_DEPLOY is not a confirmed IMPORT value: " + field,
                        code="MODEL_REF_INVALID_PENDING_STATE",
                    )
                self.pending_fields.add(field)
                observed = None
            else:
                observed = confirmed(observed)
                if observed is not None:
                    self.observed_fields.add(field)
        for source, value in (("desired", desired), ("observed", observed)):
            if value is None:
                continue
            shape = ARN_SHAPES.get(self.kind)
            if shape:
                identifier, _, patterns = shape
                group = (
                    identifier.get(field)
                    if isinstance(identifier, dict)
                    else "id"
                    if field == identifier
                    else None
                )
                if group and re.fullmatch(patterns[group], str(value)) is None:
                    raise ModelNeedsFixError(
                        "invalid ARN identifier: " + field,
                        code="MODEL_REF_INVALID_VALUE",
                        modelKey=f"{source}.row.{rid}.value",
                    )
            errors = self.resolver.catalog.literal_errors(self.kind, field, value)
            if errors:
                raise ModelNeedsFixError(
                    "invalid Producer property " + field + ": " + "; ".join(errors),
                    code="MODEL_REF_INVALID_VALUE",
                    model=str(self.snapshot.scope.path),
                    modelKey=f"{source}.row.{rid}.value",
                )
        if desired is not None and observed is not None and desired != observed:
            self.drift_fields.add(field)
        value = (
            observed
            if observed is not None
            else None
            if recorded or field in self.pending_fields
            else desired
        )
        if value is None:
            return None
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
        for rid, row in self.rows:
            desired = literal(row["value"])
            observed = literal(
                self.snapshot.authoritative.get(f"observed.row.{rid}.value", "")
            )
            if desired == "PENDING_DEPLOY" or (
                observed == "PENDING_DEPLOY"
                and self.resource.get("resourceMode", "CREATE") != "CREATE"
            ):
                raise ModelNeedsFixError(
                    "invalid Producer PENDING_DEPLOY state",
                    code="MODEL_REF_INVALID_PENDING_STATE",
                    model=str(self.snapshot.scope.path),
                    modelKey=f"desired.row.{rid}.value"
                    if desired == "PENDING_DEPLOY"
                    else f"observed.row.{rid}.value",
                )
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
                raise ModelNeedsFixError(
                    "invalid recorded ARN: " + attribute, code="MODEL_REF_INVALID_VALUE"
                )
            components = matched.groupdict()
            for field, group in fields.items():
                if (
                    values[field] is not None
                    and str(values[field]) != components[group]
                ):
                    if (attribute in self.observed_fields) == (
                        field in self.observed_fields
                    ):
                        raise ModelNeedsFixError(
                            "confirmed ARN identity conflict: " + field,
                            code="MODEL_REF_VALUE_CONFLICT",
                        )
                    self.drift_fields.add(field)
            for group in ("partition", "region", "account"):
                if (
                    group in components
                    and context_value(pseudo, group) != components[group]
                ):
                    raise ModelNeedsFixError(
                        "recorded ARN and confirmed " + group + " conflict",
                        code="MODEL_REF_VALUE_CONFLICT",
                    )
            return direct
        missing = [field for field, value in values.items() if value is None]
        if missing:
            raise ReferenceResolutionError(
                "no confirmed ARN components: " + ", ".join(missing)
            )
        try:
            assembled = named_arn(
                self.kind,
                properties,
                pseudo,
                evaluate=confirmed,
                schema=self.schema,
                recorded=values.get,
            )
        except Blocked as error:
            raise FrameworkUnsupportedError(str(error)) from error
        return assembled


def reference_value(resolver, scope, node, **contract):
    producer = None
    try:
        snapshot, number, resource, attribute = resolve(
            node, scope, resolver, **contract
        )
        producer = ProducerValues(snapshot, number, resource, resolver)
        pending = producer.pending()
        attribute = reference_attribute(resource["resourceType"], attribute)
        try:
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
        except ReferenceResolutionError as error:
            value = None
            reason = error.diagnostic["message"]
        else:
            reason = "no confirmed desired or observed value"
        if pending or producer.pending_fields:
            raise ReferenceResolutionError(
                "explicit CREATE Producer output PENDING_DEPLOY",
                category="REFERENCE_PENDING_DEPLOY",
                code="REFERENCE_PENDING_DEPLOY",
                action="Deploy the CREATE producer, synchronize observations, then regenerate.",
            )
        if producer.drift_fields:
            raise ReferenceResolutionError(
                "Desired and Observed differ: "
                + ", ".join(sorted(producer.drift_fields)),
                action="Confirm the intended and observed producer identity before regenerating.",
            )
        if value is None:
            raise ReferenceResolutionError(reason)
        return ReferenceValue("resolved", value)
    except ReferenceDiagnosticError as error:
        if "modelKey" in error.diagnostic:
            error.diagnostic["producerModelKey"] = error.diagnostic.pop("modelKey")
        error.diagnostic.update(
            model=str(scope.path),
            targetLogicalId=node.logical_id,
            attribute=node.attribute,
            pointer=node.pointer,
        )
        if producer is not None:
            error.diagnostic["producerModel"] = str(producer.snapshot.scope.path)
        if not isinstance(error, ReferenceResolutionError):
            raise
        return ReferenceValue(
            "pending_deploy"
            if error.diagnostic["category"] == "REFERENCE_PENDING_DEPLOY"
            else "unresolved",
            reason=error.diagnostic["message"],
            diagnostic=error.diagnostic,
        )
