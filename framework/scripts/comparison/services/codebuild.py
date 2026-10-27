"""codebuild comparison contracts and projections."""

from functools import partial as _bind_framework_callback

from utils.cloudformation.inputs import Blocked
from utils.iac_values import ResourceReference, same
from utils.reference_contracts import contract, reference_error, row_contexts


def contexts(rows):
    return row_contexts("CodeBuild.Project", rows)


def reference_contract(path, attribute, context):
    if path != "Environment.EnvironmentVariables[].Value":
        return NotImplemented
    if error := reference_error("CodeBuild.Project." + path, context):
        raise Blocked(error)
    declared = contract("CodeBuild.Project." + path, context)
    if declared:
        (kind,) = declared
        forms = declared[kind]
        return kind, attribute if attribute in forms else forms[0]
    raise Blocked(
        "reference property contract unproven: CodeBuild environment Type is required"
    )


def _callback_reference_compare_secret_value(
    path, reference, resolve_literal, resource_type, record, /, a, b, p
):
    if p == path:
        return NotImplemented
    if p.endswith(".Value") and isinstance(a, ResourceReference) != isinstance(
        b, ResourceReference
    ):
        symbol, text = (a, b) if isinstance(a, ResourceReference) else (b, a)
        if (
            resource_type(symbol) == "SecretsManager.Secret"
            and isinstance(text, str)
            and not text.startswith("arn:")
        ):
            try:
                name = resolve_literal(
                    ResourceReference(dict(symbol, **{"$attribute": "Name"}))
                )
            except (Blocked, ValueError, KeyError, TypeError, OSError):
                return None
            return record(a, b, p, same(name, text))
    return reference(a, b, p)


def reference_compare(
    left, right, path, resolve_literal, kms_format, resource_type, reference, *, record
):
    if path == "Environment.EnvironmentVariables[].Value":
        if isinstance(left, ResourceReference) and isinstance(right, ResourceReference):
            return same(left, right)
        if isinstance(left, ResourceReference) != isinstance(right, ResourceReference):
            symbol, other = (
                (left, right) if isinstance(left, ResourceReference) else (right, left)
            )
            if isinstance(other, str):
                forms = kms_format(symbol), kms_format(other)
                if (
                    all(form not in {None, "invalid"} for form in forms)
                    and forms[0] != forms[1]
                ):
                    return False
                try:
                    return same(resolve_literal(symbol), other)
                except (Blocked, ValueError, KeyError, TypeError, OSError):
                    return None
    if (
        path.endswith("EnvironmentVariables[]")
        and isinstance(left, dict)
        and isinstance(right, dict)
        and left.get("Type") == right.get("Type") == "SECRETS_MANAGER"
    ):
        secret_value = _bind_framework_callback(
            _callback_reference_compare_secret_value,
            path,
            reference,
            resolve_literal,
            resource_type,
            record,
        )
        return same(left, right, reference=secret_value, path=path)
    return NotImplemented


DIRECT_ATTRIBUTES = {"CodeBuild.Project.ServiceRole": "Arn"}
