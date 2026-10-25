"""Executable Mapping parsing, independent of design/catalog validation imports."""

import utils.mapping_types as _imports_aws_mapping
from utils.script_loader import module


def runtime_properties(root, service, document):
    """Parse executable mappings; catalog coverage and display quality stay in catalog_properties."""
    NORMALIZATIONS = _imports_aws_mapping.NORMALIZATIONS
    Property = _imports_aws_mapping.Property
    comparator = module("model/adapters/aws.py", "model.adapters.aws")
    if document.get("version") != 3 or document.get("service") != service:
        raise ValueError("Mapping service/version mismatch")
    result = {}
    for resource, item in document["resourceTypes"].items():
        for path, definition in item["properties"].items():
            key = resource + "." + path
            include = definition["model"]["include"]
            if type(include) is not bool:
                raise ValueError("Mapping model.include must be boolean: " + key)
            source = definition.get("source", {})
            extraction = definition.get("aws", source.get("extraction"))
            if extraction is not None:
                getter = extraction["getter"]
                if (
                    getter not in document["getters"]
                    or extraction["normalize"] not in NORMALIZATIONS
                    or not isinstance(extraction["path"], str)
                ):
                    raise ValueError("unusable Mapping extraction: " + key)
                field = comparator.Field(
                    getter,
                    extraction["path"],
                    extraction["normalize"],
                    extraction.get("default", comparator.MISSING),
                )
            else:
                field = comparator.Field(
                    classification=source["classification"],
                    reason=source.get("constraint", ""),
                )
            transform = definition.get("aws", {}).get("transform", "identity")
            if transform not in {"identity", "present", "unique"}:
                raise ValueError("unusable Mapping transform: " + key)
            display = definition.get("display", {})
            result[key] = Property(
                field,
                include,
                display.get("show", True),
                display.get("name", path),
                source.get("kind", "aws"),
                source.get("constraint", ""),
                transform,
            )
    return result
