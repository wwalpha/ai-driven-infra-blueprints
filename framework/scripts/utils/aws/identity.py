"""Pure AWS authentication decisions; callers own STS retrieval and connection caches."""

import re
from collections.abc import Mapping


class IdentityError(ValueError):
    """A pure authentication failure, retaining its code for CLI reports."""

    def __init__(self, message: str, code: str = "InvalidIdentity") -> None:
        super().__init__(message)
        self.code = code


def validate_profile(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or value == "UNSET"
        or any(char in value for char in "\r\n\0")
    ):
        raise IdentityError("target AWS profile is invalid")
    return value


def select_profile(target: Mapping[str, object], profile: object = None) -> str | None:
    configured = (
        validate_profile(target["awsProfile"]) if "awsProfile" in target else None
    )
    explicit = validate_profile(profile) if profile is not None else None
    if configured is not None and explicit is not None and explicit != configured:
        raise IdentityError("explicit AWS profile does not match target awsProfile")
    return configured if configured is not None else explicit


def import_profile(
    target: Mapping[str, object], *, no_profile: bool = False
) -> str | None:
    """Only Import may explicitly omit a valid configured profile for this invocation."""
    configured = select_profile(target)
    return None if no_profile else configured


def validate_account_id(value: object, field: str = "AWS account ID") -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{12}", value) is None:
        raise IdentityError(f"{field} is invalid")
    return value


def execution_account(target: Mapping[str, object]) -> str:
    if "awsExecutionAccountId" in target:
        return validate_account_id(
            target["awsExecutionAccountId"], "target AWS execution account ID"
        )
    return validate_account_id(target.get("awsAccountId"), "target AWS account ID")


def verify_account(target: Mapping[str, object], caller_account: object) -> str:
    expected = execution_account(target)
    if caller_account != expected:
        raise IdentityError(
            f"AWS account mismatch: expected {expected}, actual {caller_account or 'unknown'}",
            "AccountMismatch",
        )
    return expected
