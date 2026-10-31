"""Resolve typed references from confirmed Model values without changing authority."""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

from design.services.definitions.registry import POLICY_FORMATS
from utils.arn_components import ARN_COMPONENTS
from utils.arn_values import context_value, generated_attribute, named_arn
from utils.aws_sdk import aws_runtime
from utils.cloudformation.inputs import Blocked
from utils.comparison_rows import put_row
from utils.json_format import AwsDocumentError, strict_json, validate_aws_document
from utils.reference_contracts import (
    ARN_DEFAULTS,
    ARN_SHAPES,
    RETURN_ATTRIBUTE_PROPERTIES,
    VALUE_IDENTITIES,
    _arn_pattern,
    contract,
    reference_attribute,
)

import model.environment_values as environment_values
import model.reference_nodes as reference_nodes
from model.core import (
    FrameworkUnsupportedError,
    ModelNeedsFixError,
    ReferenceDiagnosticError,
    ReferenceResolutionError,
    entries,
    literal,
)


@dataclass(frozen=True)
class ReferenceValue:
    status: Literal["resolved", "pending_deploy", "logical_only", "unresolved"]
    value: object = None
    reason: str = ""
    diagnostic: dict = field(default_factory=dict)

    @property
    def category(self):
        return self.diagnostic.get("category", "RESOLVED")


def resolve(node, scope, resolver, *, field=None, property_name=None, context=None):
    snapshot, number, resource = resolver.resolve_logical(node.logical_id, scope)
    try:
        operand = any(token.startswith("Fn::") for token in node.pointer.split("/"))
        resolver.validate_attribute(
            resource["resourceType"],
            node.attribute,
            field=field,
            context=context,
            operand=operand,
        )
        if operand and node.pointer.endswith("/Fn::Select/1"):
            kind = resource["resourceType"]
            if (
                field
                in {
                    "Route53.RecordSet.ResourceRecords",
                    "Route53.RecordSet.ResourceRecords[]",
                    "Route53.RecordSet.AliasTarget.DNSName",
                }
                and "/Fn::Split/" in node.pointer
                and (kind, node.attribute) != ("EC2.VPCEndpoint", "DnsEntries")
            ):
                raise ModelNeedsFixError(
                    "Endpoint DNS extraction requires EC2.VPCEndpoint.DnsEntries",
                    code="MODEL_REF_INVALID_ATTRIBUTE",
                )
            try:
                schema = resolver.catalog.property_schema(
                    kind, reference_attribute(kind, node.attribute)
                )
            except KeyError as error:
                raise FrameworkUnsupportedError(
                    "Fn::Select reference array type is unproven"
                ) from error
            if schema.get("type") != "array" or (
                "/Fn::Split/" in node.pointer
                and schema.get("items", {}).get("type") != "string"
            ):
                raise ModelNeedsFixError(
                    "Fn::Select reference must be an array of the required type",
                    code="MODEL_REF_TYPE_MISMATCH",
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
    except ReferenceDiagnosticError as error:
        error.diagnostic["producerModel"] = str(snapshot.scope.path)
        if isinstance(error, ModelNeedsFixError):
            error.diagnostic["fixModels"] = [str(scope.path)]
        raise
    return snapshot, number, resource, node.attribute


@lru_cache(maxsize=None)
def partition_for(region):
    partitions = aws_runtime().sdk_loader().load_data("endpoints")["partitions"]
    matches = [part["partition"] for part in partitions if region in part["regions"]]
    return matches[0] if len(matches) == 1 else None


def confirmed(value):
    if not isinstance(value, str):
        return value
    if not value or value.lower() in {
        "unresolved",
        "unset",
        "tbd",
        "todo",
        "pending_deploy",
        "未確定",
    }:
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
        self.environment_pending_fields = set()
        self.observed_fields = set()
        self.drift_fields = set()
        self.missing_outputs = ()
        self.symbolic_fields = set()
        self.unresolved_fields = set()

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
            mapping = environment_values.mapping_for(
                self.snapshot.scope.root, self.kind
            )
            contexts = environment_values.row_contexts(self.kind, self.rows, mapping)
            if environment_values.pending_errors(
                self.kind,
                row["property"],
                desired_raw,
                mapping,
                context=contexts.get(rid),
            ):
                raise ModelNeedsFixError(
                    "invalid desired PENDING_DEPLOY: " + field,
                    code="MODEL_REF_INVALID_PENDING_STATE",
                    modelKey=f"desired.row.{rid}.value",
                )
            self.pending_fields.add(field)
            self.environment_pending_fields.add(field)
        if desired_raw.lstrip().startswith("{"):
            document = strict_json(desired_raw)
        else:
            document = desired_raw
        reference_unconfirmed = False
        if reference_nodes.is_reference(document):
            node = reference_nodes.parse(document)
            _, _, target, attribute = resolve(
                node, self.snapshot.scope, self.resolver, field=row["property"]
            )
            if (
                target["logicalId"] == self.resource["logicalId"]
                and RETURN_ATTRIBUTE_PROPERTIES.get(
                    (self.kind, reference_attribute(self.kind, attribute)),
                    reference_attribute(self.kind, attribute),
                )
                == field
            ):
                desired = None
                self.symbolic_fields.add(field)
            else:
                result = reference_value(
                    self.resolver,
                    self.snapshot.scope,
                    node,
                    field=row["property"],
                )
                reference_unconfirmed = result.status != "resolved"
                desired = result.value if result.status == "resolved" else None
                if result.status == "logical_only":
                    self.symbolic_fields.add(field)
                elif result.status == "unresolved":
                    self.unresolved_fields.add(field)
                if result.status == "pending_deploy":
                    self.pending_fields.add(field)
        else:
            desired = confirmed(desired_raw)
        observed = self.snapshot.authoritative.get(f"observed.row.{rid}.value")
        if observed is not None:
            observed = literal(observed)
            if observed == "PENDING_DEPLOY":
                self.pending_fields.add(field)
                observed = None
            else:
                observed = confirmed(observed)
                if observed is not None:
                    self.observed_fields.add(field)
        for source, value in (("desired", desired), ("observed", observed)):
            if value is None:
                continue
            identity_pattern = VALUE_IDENTITIES.get(
                (self.kind, reference_attribute(self.kind, field))
            )
            if identity_pattern and re.fullmatch(identity_pattern, str(value)) is None:
                raise ModelNeedsFixError(
                    "invalid Producer identifier: " + field,
                    code="MODEL_REF_INVALID_VALUE",
                    modelKey=f"{source}.row.{rid}.value",
                )
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
            if reference_nodes.is_reference(document):
                raise ModelNeedsFixError(
                    "Desired and Observed differ: " + field,
                    code="MODEL_REF_VALUE_CONFLICT",
                )
        if reference_unconfirmed:
            return None
        value = (
            observed
            if observed is not None
            else None
            if recorded or generated_attribute(self.schema, field)
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

    def waiting(self, fields):
        return bool(fields) and all(
            field in self.pending_fields
            and (
                field in self.environment_pending_fields
                or generated_attribute(self.schema, field)
            )
            for field in fields
        )

    def logical_only(self, fields: tuple[str, ...]) -> bool:
        if not fields or not all(
            generated_attribute(self.schema, field) for field in fields
        ):
            return False
        for _, row in self.rows:
            prop = row["property"]
            if not prop.startswith(self.kind + ".") or "[" in prop:
                continue
            name = prop.removeprefix(self.kind + ".")
            try:
                schema = self.resolver.catalog.property_schema(self.kind, name)
            except KeyError:
                continue
            if schema.get("type") == "string":
                self.value(name)
        for required in self.resolver.catalog.required_design_properties(self.kind):
            rows = [
                (rid, row)
                for rid, row in self.rows
                if row["property"] == self.kind + "." + required
            ]
            if len(rows) != 1:
                return False
            rid, row = rows[0]
            refs = tuple(reference_nodes.nodes(literal(row["value"])))
            if refs and not contract(row["property"]):
                raise FrameworkUnsupportedError(
                    "reference contract unproven: " + row["property"]
                )
            if (
                refs
                and f"observed.row.{rid}.value" in self.snapshot.authoritative
                and confirmed(
                    literal(self.snapshot.authoritative[f"observed.row.{rid}.value"])
                )
                is None
            ):
                return False
            value = self.value(required)
            if (
                required in self.unresolved_fields
                or (value is None and required not in self.symbolic_fields)
                or required in self.symbolic_fields
                and f"observed.row.{rid}.value" in self.snapshot.authoritative
            ):
                return False
        return not self.drift_fields

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
            if raw.lstrip().startswith(("{", "[")):
                try:
                    raw = strict_json(raw)
                except ValueError:
                    pass
            if environment_values.pending_errors(self.kind, row["property"], raw, {}):
                raise ModelNeedsFixError(
                    "invalid ARN component PENDING_DEPLOY: " + field,
                    code="MODEL_REF_INVALID_PENDING_STATE",
                )
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
            # Validate independent components even while generated identity is absent.
            provider = ARN_COMPONENTS.get(self.kind)
            if provider:
                provider[0](properties, confirmed)
            for group in ("partition", "region", "account"):
                if "{" + group + "}" in ARN_SHAPES[self.kind][1]:
                    context_value(pseudo, group)
            self.missing_outputs = tuple(missing)
            raise ReferenceResolutionError(
                "no confirmed ARN components: " + ", ".join(missing),
                category="REFERENCE_PENDING_DEPLOY"
                if self.waiting(missing)
                else "REFERENCE_UNRESOLVED",
                code="REFERENCE_PENDING_DEPLOY"
                if self.waiting(missing)
                else "reference.unresolved",
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
    active = getattr(resolver, "active_values", set())
    resolver.active_values = active
    key = (scope.environment, scope.target, node.logical_id, node.attribute)
    if key in active:
        raise ModelNeedsFixError(
            "cyclic Producer reference",
            code="MODEL_REF_CYCLE",
            targetLogicalId=node.logical_id,
            attribute=node.attribute,
        )
    active.add(key)
    try:
        snapshot, number, resource, attribute = resolve(
            node, scope, resolver, **contract
        )
        producer = ProducerValues(snapshot, number, resource, resolver)
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
            if producer.drift_fields:
                raise ReferenceResolutionError(
                    "Desired and Observed differ: "
                    + ", ".join(sorted(producer.drift_fields))
                ) from None
            if error.diagnostic[
                "category"
            ] == "REFERENCE_UNRESOLVED" and producer.logical_only(
                producer.missing_outputs
            ):
                return ReferenceValue("logical_only")
            raise
        except Blocked as error:
            raise FrameworkUnsupportedError(str(error)) from error
        if producer.drift_fields:
            raise ReferenceResolutionError(
                "Desired and Observed differ: "
                + ", ".join(sorted(producer.drift_fields)),
                action="Confirm the intended and observed producer identity before regenerating.",
            )
        if value is None:
            field = RETURN_ATTRIBUTE_PROPERTIES.get(
                (resource["resourceType"], attribute), attribute
            )
            pending = producer.waiting([field])
            if not pending and producer.logical_only((field,)):
                return ReferenceValue("logical_only")
            raise ReferenceResolutionError(
                "explicit Producer output PENDING_DEPLOY"
                if pending
                else "no confirmed desired or observed value",
                category="REFERENCE_PENDING_DEPLOY"
                if pending
                else "REFERENCE_UNRESOLVED",
                code="REFERENCE_PENDING_DEPLOY" if pending else "reference.unresolved",
            )
        return ReferenceValue("resolved", value)
    except ReferenceDiagnosticError as error:
        if producer is not None:
            error.diagnostic["producerModel"] = str(producer.snapshot.scope.path)
            if isinstance(error, ModelNeedsFixError):
                error.diagnostic["fixModels"] = [str(producer.snapshot.scope.path)]
        if "modelKey" in error.diagnostic and "producerModel" in error.diagnostic:
            error.diagnostic["producerModelKey"] = error.diagnostic.pop("modelKey")
        error.diagnostic.update(
            model=str(scope.path),
            targetLogicalId=node.logical_id,
            attribute=node.attribute,
            pointer=node.pointer,
        )
        if not isinstance(error, ReferenceResolutionError):
            raise
        return ReferenceValue(
            "pending_deploy"
            if error.diagnostic["category"] == "REFERENCE_PENDING_DEPLOY"
            else "unresolved",
            reason=error.diagnostic["message"],
            diagnostic=error.diagnostic,
        )
    finally:
        active.remove(key)
