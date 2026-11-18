"""KMS service registration."""

from importlib import import_module

from ..contracts import AccountPolicyCheck, DisplayExtension
from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES


def load_display() -> DisplayExtension:
    return import_module("services.kms.display").KEY_DISPLAY


def load_alias_display() -> DisplayExtension:
    return import_module("services.kms.display").ALIAS_DISPLAY


def load_account_policy() -> AccountPolicyCheck:
    return import_module("services.kms.validation").validate_kms_policy_accounts


DECLARATION = ServiceDeclaration(
    "kms",
    (
        "KMS.Alias",
        "KMS.Key",
    ),
    REFERENCES,
    design=design,
    displays={"KMS.Key": load_display, "KMS.Alias": load_alias_display},
    account_policies={"KMS.Key": load_account_policy},
    aws_adapters={"kms": "aws"},
)
