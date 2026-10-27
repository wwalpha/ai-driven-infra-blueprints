"""JSON contracts shared by Model syntax, Policy/IaC readers and projections."""

import hashlib
import json
import math
import re


def exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(label + " requires exactly " + str(sorted(keys)))


class AwsDocumentError(ValueError):
    def __init__(self, pointer, expression, reason):
        super().__init__(
            f"independent AWS JSON: JSON Pointer={pointer!r}, "
            f"expression={json.dumps(expression, ensure_ascii=False)}; {reason}; "
            "correct the Model with confirmed AWS values"
        )


def _recursive_validate_aws_document_visit(value, pointer, template):
    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = (
                pointer + "/" + str(key).replace("~", "~0").replace("/", "~1")
            )
            if key == "$modelRef":
                raise AwsDocumentError(
                    child_pointer,
                    {key: child},
                    "Model reference requires a confirmed AWS value",
                )
            if (
                not template
                and isinstance(key, str)
                and (key == "Ref" or key.startswith("Fn::"))
            ):
                raise AwsDocumentError(
                    child_pointer,
                    {key: child},
                    "CloudFormation intrinsic requires template context",
                )
            _recursive_validate_aws_document_visit(key, child_pointer, template)
            _recursive_validate_aws_document_visit(child, child_pointer, template)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _recursive_validate_aws_document_visit(
                child, pointer + "/" + str(index), template
            )
    elif isinstance(value, str):
        if not template and re.search(
            r"\$\{AWS::[^}]*\}|\{\{resolve:|^(?:Fn::\w+|Ref)\s*:", value
        ):
            raise AwsDocumentError(
                pointer, value, "unresolved CloudFormation substitution/reference"
            )
        # Some AWS settings contain JSON encoded as a string; encoding is not an escape hatch.
        if value.lstrip().startswith(("{", "[")):
            try:
                encoded = policy_json(value)
            except ValueError:
                return
            _recursive_validate_aws_document_visit(encoded, pointer, template)


def validate_aws_document(document, *, template=False):
    """Reject internal nodes; only CloudFormation inputs permit AWS expressions."""
    visit = _recursive_validate_aws_document_visit
    visit(document, "", template)


def unique_object(pairs: list[tuple[str, object]], *, label="policy JSON") -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate {label} key: {key}")
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _number(raw):
    number = float(raw)
    if not math.isfinite(number):
        raise ValueError("nonfinite JSON number: " + raw)
    return number


def strict_json(value):
    return json.loads(
        value,
        object_pairs_hook=lambda pairs: unique_object(pairs, label="JSON"),
        parse_constant=invalid_constant,
        parse_float=_number,
    )


def policy_json(text):
    return json.loads(
        text, object_pairs_hook=unique_object, parse_constant=invalid_constant
    )


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def document_sha256(content) -> str:
    canonical = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
