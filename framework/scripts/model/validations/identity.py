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
    identity_catalog = DesignSchemaCatalog(definitions_root or definition_root(root))
    if target.get("iacEngine") == "terraform":
        _validate_terraform_identities(resources)
        return
    stack_names = None
    for identity, resource in resources:
        # CloudFormation 専用の必須条件は確定したエンジンからのみ検証する。
        if target.get("iacEngine") == "cloudformation":
            _validate_cloudformation_identities(
                root, stack_source, identity, resource, identity_catalog
            )
        elif "cfn-logicalId" in resource:
            # エンジン未解決でも宣言済み Identity の共通検証は維持する。
            _validate_declared_identity(identity, resource, identity_catalog)
        if "cfn-logicalId" in resource:
            stack_names = _validate_identity_stack(
                root, stack_source, identity, resource, resources, stack_names
            )


def _validate_terraform_identities(
    resources: list[tuple[str, dict[str, str]]],
) -> None:
    """Terraform では CloudFormation Identity を許可しない。"""
    for identity, resource in resources:
        if "cfn-logicalId" in resource:
            raise InputValidationError(
                f"{identity}: cfn-logicalId is forbidden for Terraform"
            )


def _validate_cloudformation_identities(
    root: Path,
    stack_source: Path | None,
    identity: str,
    resource: dict[str, str],
    identity_catalog: DesignSchemaCatalog,
) -> None:
    """CloudFormation Resource の Identity と Stack 宣言を必須検証する。"""
    if "cfn-logicalId" not in resource:
        # IMPORT と API 専用 Resource は必須 Identity の対象外。
        if _dependency_design_layout.resource_mode(resource) != "CREATE":
            return
        try:
            cfn_type = identity_catalog.cloudformation_type(resource["resourceType"])
        except ValueError:
            return
        if cfn_type:
            raise InputValidationError(
                f"{identity}: cfn-logicalId required for CloudFormation CREATE resource"
            )
        return
    _validate_declared_identity(identity, resource, identity_catalog)
    # IMPORT 選択中の Stack 確認は共通の配置名解決に委ねる。
    if (
        _imports_model_importing_scope.selected(root) is not None
        and stack_source is not None
    ):
        return
    if stack_source is None or not input_is_file(stack_source):
        raise InputValidationError(
            f"{identity}: cfn-logicalId requires authoritative cloudformation-stacks.properties"
        )


def _validate_declared_identity(
    identity: str,
    resource: dict[str, str],
    identity_catalog: DesignSchemaCatalog,
) -> None:
    """宣言済み Identity のモードと正式な CFn 型を共通検証する。"""
    if _dependency_design_layout.resource_mode(resource) != "CREATE":
        raise InputValidationError(
            f"{identity}: cfn-logicalId requires CREATE with a formal CFn type"
        )
    identity_catalog.cloudformation_type(resource["resourceType"])


def _validate_identity_stack(
    root: Path,
    stack_source: Path | None,
    identity: str,
    resource: dict[str, str],
    resources: list[tuple[str, dict[str, str]]],
    stack_names: set[str] | None,
) -> set[str] | None:
    """宣言済み Identity の Stack 参照を確認し解決済み配置名を返す。"""
    if (
        _imports_model_importing_scope.selected(root) is not None
        and stack_source is not None
    ):
        if stack_names is None:
            stack_names = _imports_model_importing_scope.placement_names(
                stack_source,
                {
                    iac_values.cfn_resource_identity(spec["cfn-logicalId"])[0]
                    for _, spec in resources
                    if spec.get("cfn-logicalId")
                },
            )[0]
    elif stack_source is not None and input_is_file(stack_source):
        if stack_names is None:
            _, stacks = stack_model(
                properties(_imports_model_files.read_model(stack_source))
            )
            stack_names = set(
                _imports_model_projection.bound_stack_names(stack_source)
            ) or {stack["name"] for _, stack in stacks}
    else:
        # エンジン未解決時の Stack ファイル欠落は従来どおり許容する。
        return stack_names
    if (
        iac_values.cfn_resource_identity(resource["cfn-logicalId"])[0]
        not in stack_names
    ):
        raise ReferenceResolutionError(
            f"{identity}: cfn-logicalId references an undeclared stack"
        )
    return stack_names
