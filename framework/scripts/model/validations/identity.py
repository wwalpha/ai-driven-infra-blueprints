"""Model 検証: identity。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import design.layout as _dependency_design_layout
from design.catalog import (
    DesignSchemaCatalog,
)
from utils import iac_values
from utils.aws_mappings import definition_root
from utils.input_cache import input_is_file
from validation.diagnostics import InputValidationError

import model.files as _imports_model_files
import model.importing.scope as _imports_model_importing_scope
import model.projection as _imports_model_projection
import model.validations.policies as policies
from model.core import (
    ReferenceResolutionError,
    properties,
    stack_model,
)
from model.projection import design_target


def validate_resource_identities(
    path: Path,
    values: dict[str, str],
    root: Path,
    resources: list[tuple[str, dict[str, str]]],
    *,
    definitions_root: Path | None = None,
    _kms_policy_check: Callable[[dict[str, str], dict], None] | None = None,
) -> None:
    """Resource の配置と CloudFormation Identity を検証する。"""
    relative = (
        path.parent.relative_to(root / "docs/designs")
        if path.is_relative_to(root / "docs/designs")
        else None
    )
    target = design_target(path, root)
    (_kms_policy_check or policies.validate_kms_policy_accounts)(values, target)
    stack_source = (
        root / "model" / relative / "cloudformation-stacks.properties"
        if relative is not None
        else None
    )
    stack_names = None
    identity_catalog = DesignSchemaCatalog(definitions_root or definition_root(root))
    for identity, resource in resources:
        if "cfn-logicalId" not in resource:
            if (
                target.get("iacEngine") == "cloudformation"
                and _dependency_design_layout.resource_mode(resource) == "CREATE"
            ):
                try:
                    cfn_type = identity_catalog.cloudformation_type(
                        resource["resourceType"]
                    )
                except ValueError:
                    cfn_type = None  # API 専用 Resource は CFn Identity を持たない。
                if cfn_type:
                    raise InputValidationError(
                        f"{identity}: cfn-logicalId required for CloudFormation CREATE resource"
                    )
            continue
        if target.get("iacEngine") == "terraform":
            raise InputValidationError(
                f"{identity}: cfn-logicalId is forbidden for Terraform"
            )
        if _dependency_design_layout.resource_mode(resource) != "CREATE":
            raise InputValidationError(
                f"{identity}: cfn-logicalId requires CREATE with a formal CFn type"
            )
        identity_catalog.cloudformation_type(resource["resourceType"])
        placement_names = _imports_model_importing_scope.placement_names
        import_selection = _imports_model_importing_scope.selected
        if import_selection(root) is not None and stack_source is not None:
            if stack_names is None:
                stack_names = placement_names(
                    stack_source,
                    {
                        iac_values.cfn_resource_identity(spec["cfn-logicalId"])[0]
                        for _, spec in resources
                        if spec.get("cfn-logicalId")
                    },
                )[0]
            if (
                iac_values.cfn_resource_identity(resource["cfn-logicalId"])[0]
                not in stack_names
            ):
                raise ReferenceResolutionError(
                    f"{identity}: cfn-logicalId references an undeclared stack"
                )
            continue
        if target.get("iacEngine") == "cloudformation" and (
            stack_source is None or not input_is_file(stack_source)
        ):
            raise InputValidationError(
                f"{identity}: cfn-logicalId requires authoritative cloudformation-stacks.properties"
            )
        if stack_source is not None and input_is_file(stack_source):
            if stack_names is None:
                read_model = _imports_model_files.read_model
                _, stacks = stack_model(properties(read_model(stack_source)))
                bound_stack_names = _imports_model_projection.bound_stack_names
                stack_names = set(bound_stack_names(stack_source)) or {
                    stack["name"] for _, stack in stacks
                }
            if (
                iac_values.cfn_resource_identity(resource["cfn-logicalId"])[0]
                not in stack_names
            ):
                raise ReferenceResolutionError(
                    f"{identity}: cfn-logicalId references an undeclared stack"
                )
