"""Classify AWS CLI and SDK failures without returning diagnostic prose."""

import json
import subprocess
import sys


def classify_aws_failure(error):
    """Return the error code, category, and classification source."""
    if hasattr(error, "failure_category"):
        return error.code, error.failure_category, error.classification_source

    stderr = ""
    cli_error = isinstance(error, subprocess.CalledProcessError)
    if cli_error:
        code = "AwsCliError"
        stderr = error.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        try:
            detail = json.loads(stderr)
        except (TypeError, ValueError):
            detail = None
        if isinstance(detail, dict):
            code = detail.get("Code", code)
    else:
        response = getattr(error, "response", None)
        detail = response.get("Error") if isinstance(response, dict) else None
        code = getattr(error, "code", type(error).__name__)
        if isinstance(detail, dict):
            code = detail.get("Code", code)
    if not (
        isinstance(code, str)
        and 0 < len(code) <= 128
        and code.isascii()
        and all(char.isalnum() or char in "._-" for char in code)
    ):
        code = "AwsCliError" if cli_error else "Unknown"

    codes = {
        "authentication": {
            "ExpiredToken", "ExpiredTokenException", "InvalidClientTokenId",
            "UnrecognizedClientException", "InvalidAccessKeyId", "SignatureDoesNotMatch",
            "NoCredentialsError", "PartialCredentialsError", "ProfileNotFound",
        },
        "access_denied": {
            "AccessDenied", "AccessDeniedException", "UnauthorizedOperation",
            "UnauthorizedException",
        },
        "endpoint_unreachable": {
            "EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError",
            "ConnectionClosedError", "ProxyConnectionError", "SSLError",
        },
        "request_timeout": {"TimeoutExpired", "OperationDeadlineExceeded"},
    }
    if code == "AccountMismatch":
        return code, "account_mismatch", "account_validation"
    if code == "InvalidIdentity":
        return code, "unknown", "account_validation"
    for category, members in codes.items():
        if code in members:
            return code, category, "structured_error"
    if code == "AwsCliError" and isinstance(stderr, str):
        hints = {
            "endpoint_unreachable": (
                "Could not connect to the endpoint URL:", "Connect timeout on endpoint URL:",
                "Read timeout on endpoint URL:", "Failed to connect to proxy URL:",
                "SSL validation failed for ",
            ),
            "authentication": (
                "Unable to locate credentials", "The security token included in the request is expired",
                "The config profile (",
            ),
        }
        for category, patterns in hints.items():
            if any(pattern in stderr for pattern in patterns):
                return code, category, "diagnostic_hint"
        for category in ("authentication", "access_denied"):
            if any(f"An error occurred ({name})" in stderr for name in codes[category]):
                return code, category, "diagnostic_hint"
    return code, "unknown", "unknown"


def aws_failure_fields(error):
    _, category, source = classify_aws_failure(error)
    return {"failureCategory": category, "classificationSource": source}


def format_aws_failure(api, error):
    code, category, source = classify_aws_failure(error)
    return f"{api} failed ({code}; {category}, {source})"


if __name__ == "__main__":
    failure = subprocess.CalledProcessError(1, "aws", stderr=sys.stdin.buffer.read())
    code, category, source = classify_aws_failure(failure)
    print(json.dumps({"code": code, "failureCategory": category, "classificationSource": source}))
