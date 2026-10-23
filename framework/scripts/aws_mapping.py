"""Catalog-keyed AWS Mapping Registry shared by validation and AWS Compare."""

from pathlib import Path

import aws_mapping_catalog as _imports_aws_mapping_catalog
import utils.aws_catalogs as _imports_utils_aws_catalogs
import utils.aws_mappings as _imports_utils_aws_mappings
import utils.aws_schemas as _imports_utils_aws_schemas
import utils.aws_sdk as _imports_utils_aws_sdk
from utils.input_cache import memoized
from utils.mapping_types import NORMALIZATIONS as NORMALIZATIONS
from utils.mapping_types import Identity as Identity
from utils.mapping_types import Property as Property
from utils.mapping_types import Registry as Registry
from utils.mapping_types import mapping_path as mapping_path
from utils.mapping_types import readonly as readonly
from utils.mapping_types import response_shape as response_shape
from utils.mapping_types import text as text
from utils.yaml_format import yaml_read as yaml_read


@memoized
def registry(root: Path, service: str) -> Registry:
    """Reuse full static validation, retaining this caller's root/input-scope view."""
    catalog_properties = _imports_aws_mapping_catalog.catalog_properties
    catalogs_for = _imports_utils_aws_catalogs.catalogs_for
    mappings_for = _imports_utils_aws_mappings.mappings_for
    schemas_for = _imports_utils_aws_schemas.schemas_for
    sdk_for = _imports_utils_aws_sdk.sdk_for
    validated = mappings_for(root).validated(service, sdk_for(root), schemas_for(root),
                                             catalogs_for(root), catalog_properties)
    return validated.at_root(root)


def runtime_registry(root: Path, service: str) -> Registry:
    mappings_for = _imports_utils_aws_mappings.mappings_for
    return mappings_for(root).get(service)
