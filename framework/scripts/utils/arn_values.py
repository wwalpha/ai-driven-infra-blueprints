"""Confirmed ARN assembly shared by Model projections and comparison."""

import re
from string import Formatter

from utils.arn_components import ARN_COMPONENTS
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression
from utils.reference_contracts import ARN_DEFAULTS, ARN_SHAPES


def generated_attribute(schema, field):
    path = "/properties/" + field.replace(".", "/")
    return any(
        path == pointer or path.startswith(pointer.rstrip("/") + "/")
        for pointer in schema.get("readOnlyProperties", ())
    )


def context_value(pseudo, group):
    field, pattern = {
        "partition": ("Partition", r"aws(?:-[a-z]+)*"),
        "region": ("Region", r"[a-z]{2}(?:-[a-z]+)+-\d+"),
        "account": ("AccountId", r"[0-9]{12}"),
    }[group]
    value = pseudo.get("AWS::" + field)
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise Blocked("reference requires a confirmed " + field)
    return value


def named_arn(
    kind, properties, pseudo, *, evaluate, schema, recorded=None, reference=None
):
    """Concretize a proven Producer using the shared ARN identity contract."""
    identifier, template, patterns = ARN_SHAPES[kind]
    fields = identifier if isinstance(identifier, dict) else {identifier: "id"}
    generated = [field for field in fields if generated_attribute(schema, field)]
    if generated:
        if recorded is None:
            raise Blocked(
                "ARN requires a proven generated identifier: " + ", ".join(generated)
            )
    components = {}
    for field, group in fields.items():
        if field in generated:
            explicit = recorded(field)
        else:
            explicit = properties
            for token in field.split("."):
                explicit = (
                    explicit.get(token, ARN_DEFAULTS.get((kind, field)))
                    if isinstance(explicit, dict)
                    else None
                )
            explicit = evaluate(explicit)
        if (
            not isinstance(explicit, str)
            or explicit in {"UNSET", "PENDING_DEPLOY", "TBD", "TODO", "未確定"}
            or re.fullmatch(patterns[group], explicit) is None
            or any(token in explicit for token in ("*", "?", "${", "{{resolve:"))
        ):
            raise Blocked(
                (
                    "attribute_format_unproven: recorded ARN identifier format: "
                    if field in generated
                    else "ARN requires a valid explicit resource "
                )
                + field
            )
        components[group] = explicit
    provider = ARN_COMPONENTS.get(kind)
    if provider:
        components.update(provider[0](properties, evaluate))
    for group in ("partition", "region", "account"):
        if "{" + group + "}" not in template:
            continue
        value = context_value(pseudo, group)
        if group in components and components[group] != value:
            raise Blocked("ARN identifier and confirmed " + group + " differ")
        components[group] = value
    if reference is None:
        return template.format(**components)
    for field, group in fields.items():
        if group not in {"partition", "region", "account"}:
            components[group] = reference(field)
    parts = []
    for text, field, _, _ in Formatter().parse(template):
        parts.append(text)
        if field is not None:
            parts.append(components[field])
    return Expression("Join", ["", parts])
