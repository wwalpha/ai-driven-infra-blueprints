"""Shared model contract values."""

from typing import Final

MODEL_PENDING_DEPLOY: Final[str] = "PENDING_DEPLOY"
MODEL_UNSET: Final[str] = "UNSET"
REFERENCE_PENDING_DEPLOY: Final[str] = "REFERENCE_PENDING_DEPLOY"
REFERENCE_UNRESOLVED: Final[str] = "REFERENCE_UNRESOLVED"
RESOURCE_MODE_CREATE: Final[str] = "CREATE"
RESOURCE_MODE_IMPORT: Final[str] = "IMPORT"

RESOURCE_TYPE_KEY: Final[str] = "resourceType"
RESOURCE_LOGICAL_ID_KEY: Final[str] = "logicalId"
REFERENCE_LOGICAL_ID_KEY: Final[str] = "logicalId"
CFN_LOGICAL_ID_KEY: Final[str] = "cfn-logicalId"
MODEL_REF_KEY: Final[str] = "$modelRef"
REFERENCE_RESOURCE_TYPE_KEY: Final[str] = "resourceType"
