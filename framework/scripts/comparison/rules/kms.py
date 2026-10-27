"""Static KMS comparison methods; container rules include their recursive contents."""

import re

from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference, same
from utils.reference_contracts import reference_attribute

from ..contracts import ResourceContract
from ..expressions import parts, references
from ..methods import properties


def kms_format(value, resources, *, project_arn=None):
    if isinstance(value, ResourceReference):
        service, identity = value["$resource"]
        kind = resources.get(service, {}).get(identity, {}).get("resourceType")
        if kind is None:
            return None
        return {
            ("KMS.Key", "KeyId"): "KeyId",
            ("KMS.Key", "Arn"): "KeyArn",
            ("KMS.Alias", "AliasName"): "AliasName",
            ("KMS.Alias", "AliasArn"): "AliasArn",
        }.get((kind, value["$attribute"]), "invalid")
    if isinstance(value, Expression):
        try:
            tokens = parts(value)
        except (Blocked, ValueError, KeyError, TypeError):
            return None
        if len(tokens) == 1 and isinstance(tokens[0], ResourceReference):
            return kms_format(tokens[0], resources)
        if all(isinstance(token, str) for token in tokens):
            return kms_format("".join(tokens), resources)
        projected = project_arn(value) if project_arn is not None else None
        return kms_format(projected, resources) if projected is not None else None
    if not isinstance(value, str):
        return "invalid"
    if "{{resolve:" in value or "${" in value:
        return None
    key = (
        r"(?:[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}|mrk-[a-fA-F0-9]{32})"
    )
    alias = r"alias/[A-Za-z0-9:/_-]+"
    arn = r"arn:[a-z0-9-]+:kms:[a-z0-9-]+:\d{12}:"
    for form, pattern in [
        ("KeyId", key),
        ("KeyArn", arn + "key/" + key),
        ("AliasName", alias),
        ("AliasArn", arn + alias),
    ]:
        if re.fullmatch(pattern, value):
            return form
    return "invalid"


def identity_same(left, right, forms):
    if left["$resource"] != right["$resource"]:
        return False, None, False
    if forms is not None:
        if (
            left["$attribute"] == right["$attribute"]
            and left["$attribute"] not in forms
        ):
            return (
                None,
                "same reference identity; both attributes are outside the allowed property forms",
                False,
            )
        equal = left["$attribute"] in forms and right["$attribute"] in forms
        return equal, None, bool(equal and left["$attribute"] != right["$attribute"])
    if left["$attribute"] == right["$attribute"]:
        return True, None, False
    return (
        None,
        "same reference identity; no property contract proves equivalence of these attributes",
        False,
    )


def compare_forms(
    left, right, allowed, *, resolve_literal, format_of, project_arn=None
):
    forms = format_of(left), format_of(right)
    reason = None
    if any(form is not None and form not in allowed for form in forms):
        result, reason = (
            False,
            f"KMS format outside allowed forms: model={forms[0]}, iac={forms[1]}",
        )
    elif None in forms:
        result, reason = None, "KMS format is unproven"
    elif forms[0] != forms[1]:
        result, reason = False, f"KMS format mismatch: model={forms[0]}, iac={forms[1]}"
    elif isinstance(left, ResourceReference) and isinstance(right, ResourceReference):
        result = same(left, right)
    elif references(left) or references(right):
        if references(left) and references(right):
            projected = [
                project_arn(value) if project_arn is not None else None
                for value in (left, right)
            ]
            if any(value is None for value in projected):
                result, reason = (
                    None,
                    "KMS ARN Producer, attribute or owning scope is unproven",
                )
            else:
                result = same(*projected)
                reason = (
                    "same KMS ARN Producer and owning scope"
                    if result
                    else "different KMS ARN Producer Resources"
                )
        else:
            symbol = left if references(left) else right
            if isinstance(symbol, Expression) and (
                project_arn is None or project_arn(symbol) is None
            ):
                result, reason = (
                    None,
                    "KMS ARN Producer, attribute or owning scope is unproven",
                )
            else:
                # Physical literals must retain the caller's Reference Evidence checks.
                result, reason = (
                    NotImplemented,
                    "same KMS format; physical value is unproven",
                )
    else:
        try:
            values = [
                resolve_literal(value)
                if isinstance(value, (ResourceReference, Expression))
                else value
                for value in (left, right)
            ]
            result = same(*values)
        except (Blocked, ValueError, KeyError, TypeError, OSError):
            result, reason = None, "same KMS format; physical value is unproven"
    return result, reason


RULES = {
    "KMS.Alias": properties(
        resource=ResourceContract(
            identity_same=identity_same,
            arn_attribute=reference_attribute("KMS.Alias", "Arn"),
        ),
        references="""
            TargetKeyId
        """,
        scalars="""
            AliasName
        """,
    ),
    "KMS.Key": properties(
        resource=ResourceContract(
            identity_same=identity_same,
            arn_attribute=reference_attribute("KMS.Key", "Arn"),
        ),
        objects="""
            KeyPolicy
            Tags[]
        """,
        scalars="""
            BypassPolicyLockoutSafetyCheck
            Description
            EnableKeyRotation
            Enabled
            KeySpec
            KeyUsage
            MultiRegion
            Origin
            PendingWindowInDays
            RotationPeriodInDays
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
}
