"""Local reference proof. Recorded observations never claim current AWS state."""

import re

from design.layout import resource_mode
from design.policy_tables import literal
from model.adapters.observed import identifier_source
from model.format import REFERENCE_NAME_SUFFIXES
from model.projection import reference_attribute
from utils.aws_catalogs import catalog_outputs
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference, cfn_resource_identity, same
from utils.reference_contracts import (
    ARN_FORMS,
    ARN_SHAPES,
    REFERENCE_PROPERTIES,
)

from . import expressions, registry
from .references import ReferenceDecision, literal_expression, reference_same


def identifier_text(inputs, kind, attribute, raw):
    """Validate a recorded identifier without treating it as an approved handoff."""
    text = literal(raw) if raw is not None else ""
    if (
        not text
        or text in {"PENDING_DEPLOY", "UNSET", "TODO", "TBD", "未確定"}
        or "${" in text
        or "{{resolve:" in text
    ):
        raise Blocked("identifier_unobserved")
    schema = inputs.catalog.property_schema(kind, attribute)
    arn = attribute == reference_attribute(kind, "Arn") or schema.get(
        "pattern", ""
    ).startswith("^arn:")
    if text.startswith("arn:") != arn or inputs.catalog.literal_errors(
        kind, attribute, text
    ):
        raise Blocked("attribute_format_unproven: recorded identifier format")
    form = ARN_FORMS.get((kind, attribute))
    if arn and form and re.fullmatch(form[1], text) is None:
        raise Blocked("attribute_format_unproven: recorded identifier format")
    if kind in ARN_SHAPES:
        fields, _, patterns = ARN_SHAPES[kind]
        fields = fields if isinstance(fields, dict) else {fields: "id"}
        if (
            attribute in fields
            and re.fullmatch(patterns[fields[attribute]], text) is None
        ):
            raise Blocked("attribute_format_unproven: recorded identifier format")
    return text


class Evidence:
    def __init__(self, inputs):
        self.inputs = inputs
        self.observed = False
        self.producers = []
        self.properties = {}

    def expand(self, value):
        kind = self.inputs.resource_type(value)
        if kind in ARN_SHAPES and value["$attribute"] == reference_attribute(
            kind, "Arn"
        ):
            return self.inputs.reference_literal(
                value, recorded=self.recorded, symbolic_arn=True
            )
        return value

    def resolve(self, value):
        inputs = self.inputs
        if isinstance(value, Expression):
            return literal_expression(value, resolve_literal=self.resolve)
        service, identity = value["$resource"]
        producer = {
            "producer": service + "/" + identity,
            "attribute": value["$attribute"],
        }
        if not any(
            item["producer"] == producer["producer"]
            and item["attribute"] == producer["attribute"]
            for item in self.producers
        ):
            self.producers.append(producer)
        result = inputs.reference_literal(value, recorded=self.recorded)
        kind = inputs.resource_type(value)
        if kind in ARN_SHAPES and value["$attribute"] == reference_attribute(
            kind, "Arn"
        ):
            fields = ARN_SHAPES[kind][0]
            sources = [
                self.properties[service, identity, field]
                for field in (fields if isinstance(fields, dict) else [fields])
                if (service, identity, field) in self.properties
            ]
            if sources:
                for item in self.producers:
                    if (
                        item["producer"] == producer["producer"]
                        and item["attribute"] == producer["attribute"]
                    ):
                        form = inputs.kms_format(result)
                        item.update(
                            source_property=",".join(sources),
                            evidence_type="recorded_observed",
                            derived_format="Arn" if form == "invalid" else form,
                            current_aws_verified=False,
                        )
        return result

    def recorded(self, value):
        inputs = self.inputs
        service, identity = value["$resource"]
        resource = inputs.resources[service][identity]
        kind, attribute = resource["resourceType"], value["$attribute"]
        if resource_mode(resource) == "IMPORT":
            raise Blocked("attribute_format_unproven: IMPORT requires approved handoff")
        prop = kind + "." + attribute
        outputs = catalog_outputs(inputs.root, kind)
        if prop not in outputs:
            stack, logical = cfn_resource_identity(resource["cfn-logicalId"])
            if not same(inputs.symbol(stack, logical), value):
                raise Blocked("attribute_format_unproven: not an identifier output")
            candidates = [
                candidate
                for candidate in outputs
                if identifier_source(
                    inputs.catalog,
                    resource,
                    outputs,
                    logical,
                    candidate,
                    {"proof": {"Ref": logical}},
                )[1]
            ]
            if len(candidates) != 1:
                raise Blocked(
                    "attribute_format_unproven: Ref identifier output is unproven"
                )
            prop = candidates[0]
        self.properties[(service, identity, attribute)] = prop
        rows = [
            (rid, row)
            for rid, row in inputs.rows[service][identity]
            if row["property"] == prop
        ]
        if len(rows) != 1:
            raise Blocked(
                "identifier_unobserved: missing or ambiguous identifier Property"
            )
        raw = inputs.model(service).authoritative.get(
            f"observed.row.{rows[0][0]}.value"
        )
        text = identifier_text(inputs, kind, attribute, raw)
        self.observed = True
        return text


def validate_declaration(inputs, reference):
    service, identity = reference["$resource"]
    prop = reference.saved_property
    rows = [
        (rid, row)
        for rid, row in inputs.rows[service][identity]
        if row["property"] == prop
    ]
    if len(rows) != 1:
        raise Blocked(
            "attribute_format_unproven: declared Property absent or ambiguous"
        )
    rid, row = rows[0]
    if reference.declared_format == "name":
        if not prop.endswith(REFERENCE_NAME_SUFFIXES):
            raise Blocked("attribute_format_unproven: not a name Property")
        raw = row["value"]
    else:
        if prop not in catalog_outputs(inputs.root, inputs.resource_type(reference)):
            raise Blocked(
                "attribute_format_unproven: not a recorded identifier Property"
            )
        raw = inputs.model(service).authoritative.get(f"observed.row.{rid}.value")
    if raw is None or literal(raw) in {
        "",
        "PENDING_DEPLOY",
        "UNSET",
        "TBD",
        "TODO",
        "未確定",
    }:
        raise Blocked("identifier_unobserved")
    if literal(raw) != reference.saved_literal:
        raise Blocked(
            "recorded_identifier_mismatch: declaration and Producer Property differ"
        )


def validate_source(inputs, proof, reference):
    validate_declaration(inputs, reference)
    if (
        proof.resolve(reference) != reference.saved_literal
        or reference.declared_format == "identifier"
        and reference.saved_literal.startswith("arn:")
    ):
        raise Blocked(
            "recorded_identifier_mismatch: declaration and saved value differ"
        )


def compare_expression(inputs, left, right, kind, path):
    sources = expressions.references([left, right])
    declared = [source for source in sources if hasattr(source, "saved_literal")]
    if not declared or not any(
        isinstance(value, Expression) for value in (left, right)
    ):
        return ReferenceDecision(NotImplemented)
    proof = Evidence(inputs)
    failures = []
    for source in declared:
        try:
            validate_source(inputs, proof, source)
        except Blocked as error:
            failures.append(str(error))
    equal, reason = None, "; ".join(dict.fromkeys(failures))
    if not failures:
        try:
            left_concrete = expressions.string(left, proof.resolve)
            right_concrete = expressions.string(right, proof.resolve)
            allowed = (
                registry.property_rule(kind, path).forms
                if inputs.local_comparison
                else None
            )
            if allowed:
                _, format_reason = registry.property_rule(kind, path).form_compare(
                    left_concrete,
                    right_concrete,
                    allowed,
                    resolve_literal=inputs.reference_literal,
                    format_of=inputs.kms_format,
                )
                if format_reason:
                    raise Blocked(format_reason)
            left_parts = expressions.parts(left, inputs.resource_type, proof.expand)
            right_parts = expressions.parts(right, inputs.resource_type, proof.expand)
            equal = expressions.symbolic_same(left_parts, right_parts)
            if equal is None:
                equal = aligned_difference(left_parts, right_parts)
            reason = (
                "logical_reference"
                if equal is True
                else (
                    "different Producer or fixed expression parts"
                    if equal is False
                    else "expression Producer or attribute equivalence is unproven; recorded_observed cannot prove physical identity"
                )
            )
        except Blocked as error:
            reason = str(error)
            if reason.startswith("KMS format"):
                equal = False
    detail = inputs.reference_diagnostic(left, right, kind, path, reason)
    detail.update(
        local_comparison="matched"
        if equal is True
        else "difference"
        if equal is False
        else "uncompared",
        evidence_type="logical_reference"
        if equal is not None
        else "recorded_observed"
        if proof.observed
        else "local_evaluation",
        current_aws_verified=False,
        producers=proof.producers,
        declarations=[
            {
                "producer": "/".join(source["$resource"]),
                "property": source.saved_property,
            }
            for source in declared
        ],
    )
    return ReferenceDecision(equal, (inputs.redacted(detail),), equal is True)


def aligned_difference(left, right):
    """Only aligned symbols and equal-length literal slots prove a fixed contradiction."""
    if len(left) != len(right):
        return None
    different = False
    for a, b in zip(left, right, strict=True):
        if isinstance(a, ResourceReference) and isinstance(b, ResourceReference):
            if a["$attribute"] != b["$attribute"]:
                return None
            different |= a["$resource"] != b["$resource"]
        elif isinstance(a, str) and isinstance(b, str) and len(a) == len(b):
            different |= a != b
        else:
            return None
    return False if different else None


def compare(inputs, left, right, kind, path):
    expression = compare_expression(inputs, left, right, kind, path)
    if expression.equal is not NotImplemented:
        return expression
    original_left, original_right = left, right
    if hasattr(right, "saved_literal") and not hasattr(left, "saved_literal"):
        left, right = right, left
    if (
        isinstance(right, str)
        and isinstance(left, (ResourceReference, Expression))
        and not hasattr(left, "saved_literal")
    ):
        left, right = right, left
    declared = getattr(left, "saved_literal", None)
    raw = declared if declared is not None else left
    if declared is not None:
        baseline = reference_same(
            raw,
            right,
            kind,
            path,
            local_comparison=inputs.local_comparison,
            forms_for=inputs.reference_forms,
            resolve_literal=inputs.reference_literal,
            resource_type=inputs.resource_type,
            kms_format=inputs.kms_format,
            diagnostic=inputs.reference_diagnostic,
        )
        if baseline.equal is False:
            return baseline
    if not isinstance(raw, str) or not isinstance(
        right, (ResourceReference, Expression)
    ):
        if declared is not None:
            equal = same(raw, right)
            if left.declared_format != "name":
                try:
                    validate_declaration(inputs, left)
                except Blocked as error:
                    return ReferenceDecision(
                        None,
                        (
                            inputs.reference_diagnostic(
                                original_left, original_right, kind, path, str(error)
                            ),
                        ),
                    )
                detail = inputs.reference_diagnostic(
                    original_left,
                    original_right,
                    kind,
                    path,
                    "recorded_observed cannot prove current or next-deploy physical identity",
                )
                detail.update(
                    evidence_type="recorded_observed",
                    current_aws_verified=False,
                    local_comparison="uncompared",
                )
                return ReferenceDecision(None, (detail,))
            if equal:
                try:
                    validate_declaration(inputs, left)
                except Blocked as error:
                    return ReferenceDecision(
                        None,
                        (
                            inputs.reference_diagnostic(
                                original_left, original_right, kind, path, str(error)
                            ),
                        ),
                    )
            return ReferenceDecision(equal)
        return ReferenceDecision(NotImplemented)
    proof = Evidence(inputs)
    reason, equal = "", None
    try:
        if declared is not None:
            validate_source(inputs, proof, left)
            if hasattr(right, "saved_literal"):
                validate_source(inputs, proof, right)
            if (
                isinstance(right, ResourceReference)
                and left["$resource"] != right["$resource"]
            ):
                return ReferenceDecision(
                    False,
                    (
                        inputs.reference_diagnostic(
                            original_left,
                            original_right,
                            kind,
                            path,
                            "different producer Resources",
                        ),
                    ),
                )
        if isinstance(right, ResourceReference):
            refkind = inputs.resource_type(right)
            contract = REFERENCE_PROPERTIES.get(kind + "." + path)
            if contract and refkind not in (
                contract[0] if isinstance(contract[0], tuple) else (contract[0],)
            ):
                return ReferenceDecision(
                    False,
                    (
                        inputs.reference_diagnostic(
                            original_left,
                            original_right,
                            kind,
                            path,
                            "resource_type_mismatch",
                        ),
                    ),
                )
            forms = (
                inputs.reference_forms(kind, path)
                if registry.property_rule(kind, path).forms is None
                else None
            )
            if forms and right["$attribute"] not in {
                reference_attribute(refkind, form) for form in forms
            }:
                return ReferenceDecision(
                    False,
                    (
                        inputs.reference_diagnostic(
                            original_left,
                            original_right,
                            kind,
                            path,
                            "attribute_format_mismatch",
                        ),
                    ),
                )
            if (
                forms
                and "Arn" in forms
                and raw.startswith("arn:")
                and right["$attribute"] != reference_attribute(refkind, "Arn")
            ):
                raise Blocked(
                    "attribute_format_unproven: alternative allowed literal format"
                )
        concrete = proof.resolve(right)
        allowed = (
            registry.property_rule(kind, path).forms
            if inputs.local_comparison
            else None
        )
        if allowed:
            result, reason = registry.property_rule(kind, path).form_compare(
                raw,
                concrete,
                allowed,
                resolve_literal=inputs.reference_literal,
                format_of=inputs.kms_format,
            )
            if reason:
                return ReferenceDecision(
                    result,
                    (
                        inputs.reference_diagnostic(
                            original_left, original_right, kind, path, reason
                        ),
                    ),
                )
        if (
            declared is not None
            and isinstance(right, ResourceReference)
            and left["$attribute"] != right["$attribute"]
        ):
            left_key = (*left["$resource"], left["$attribute"])
            right_key = (*right["$resource"], right["$attribute"])
            if not proof.properties.get(left_key) or proof.properties[
                left_key
            ] != proof.properties.get(right_key):
                raise Blocked("attribute_format_unproven: declared attribute differs")
        logical = (
            declared is not None
            and isinstance(right, ResourceReference)
            and left["$resource"] == right["$resource"]
        )
        equal = True if logical else None if proof.observed else raw == concrete
        if logical:
            reason = "logical_reference"
        elif proof.observed:
            reason = (
                "recorded_observed cannot prove current or next-deploy physical identity"
                if raw == concrete
                else "recorded_identifier_mismatch: historical value cannot prove an IaC difference"
            )
        else:
            reason = "iac_concrete"
    except Blocked as error:
        reason = str(error)
    detail = inputs.reference_diagnostic(
        original_left, original_right, kind, path, reason
    )
    if declared is not None:
        detail["model_literal"] = inputs.redacted(raw, kind + "." + path)
    detail.update(
        local_comparison="matched"
        if equal is True
        else "difference"
        if equal is False
        else "uncompared",
        evidence_type="logical_reference"
        if reason == "logical_reference"
        else "recorded_observed"
        if proof.observed
        else "local_evaluation",
        current_aws_verified=False,
        producers=proof.producers,
    )
    return ReferenceDecision(equal, (inputs.redacted(detail),), equal is True)


def export_origins(value, provenance):
    result = []
    entry = provenance.get(id(value))
    if entry is not None and entry[0] is value:
        result.extend(entry[1])
    children = (
        value.operands
        if isinstance(value, Expression)
        else value.values()
        if isinstance(value, dict)
        else value
        if isinstance(value, list)
        else ()
    )
    for child in children:
        for origin in export_origins(child, provenance):
            if origin not in result:
                result.append(origin)
    return result
