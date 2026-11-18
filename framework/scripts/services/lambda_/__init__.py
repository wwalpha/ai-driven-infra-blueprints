"""Lambda service registration."""

from importlib import import_module

from ..contracts import DisplayExtension
from ..import_contracts import ConditionalCapture, ImportProfile, inventory_handler
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display() -> DisplayExtension:
    return import_module("services.lambda_.display").EXTENSION


def load_function_display() -> DisplayExtension:
    return import_module("services.lambda_.display").FUNCTION_DISPLAY


DECLARATION = ServiceDeclaration(
    "lambda",
    (
        "Lambda.EventInvokeConfig",
        "Lambda.EventSourceMapping",
        "Lambda.Function",
        "Lambda.Permission",
    ),
    REFERENCES,
    design=design,
    displays={
        "Lambda.Permission": load_display,
        "Lambda.Function": load_function_display,
    },
    package="lambda_",
    aws_adapters={"lambda": "aws"},
    import_profiles={
        "Lambda.Function": ImportProfile(
            conditional_capture=ConditionalCapture(
                paths={
                    "Lambda.Function.Code.S3Bucket": "Code.ResolvedS3Object.S3Bucket",
                    "Lambda.Function.Code.S3Key": "Code.ResolvedS3Object.S3Key",
                },
                contract=inventory_handler(
                    "services.lambda_.inventory", "capture_contract"
                ),
                capture=inventory_handler(
                    "services.lambda_.inventory", "classify_capture"
                ),
                valid=inventory_handler("services.lambda_.inventory", "valid_capture"),
                invalid_contract="Lambda code-source limitation contract is invalid",
                unknown_identity="Lambda identity is unknown",
                missing_reason="Lambda Image uses an image source",
            ),
            addition_issue=inventory_handler(
                "services.lambda_.inventory", "addition_issue"
            ),
            allows_missing=inventory_handler(
                "services.lambda_.inventory", "allows_missing_code"
            ),
        ),
    },
)
