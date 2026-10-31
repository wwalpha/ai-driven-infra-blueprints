"""Model 検証: schema。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import aws_mapping_display as _imports_aws_mapping_display
import design.layout as _dependency_design_layout
import design.layout as _imports_design_layout
import design.policy_tables as _dependency_policy_tables
import validation.design as _imports_validation_design
from design.catalog import (
    DesignSchemaCatalog,
    property_paths_with_parents,
)
from design.layout_schema import GROUPED_RESOURCE_TYPES, IMPLICIT_GROUPED_PROPERTIES
from design.services.definitions.registry import HIDDEN_PROPERTIES
from utils.aws_catalogs import catalog_outputs
from utils.json_format import policy_json
from utils.property_path import definition_path
from validation.diagnostics import InputValidationError
from validation.findings import Findings

import model.core as _imports_model_core
import model.files as _imports_model_files
from model.core import (
    entries,
    stack_model,
)
from model.literal_values import literal_errors as row_literal_errors
from model.projection import is_import_expression, resource_rows
from model.references import has_reference
from model.validations.naming import NAMING_EXEMPT_PROPERTIES, naming_errors


def validate_required_properties(
    values: dict[str, str],
    root: Path,
    *,
    warnings: list[dict] | None = None,
    properties_scope: set[str] | None = None,
) -> list[dict]:
    """対象の必須属性と参照条件を検証する。変更時は指定属性に範囲を限定する。"""
    validate_model_keys = _imports_model_core.validate_runtime_keys
    resource_row_index = _imports_model_files.resource_row_index
    if properties_scope is not None:
        values = row_rule_inputs(values, properties_scope)
    validate_model_keys(values)
    resource_row_index(values)
    if entries(values, "desired.stack."):
        _, stacks = stack_model(values)
        for _, stack in stacks:
            if errors := naming_errors(
                root,
                "CloudFormation.Stack",
                [["1", "StackName", stack["name"], "名前"]],
            ):
                raise InputValidationError("; ".join(errors))
        return []
    catalog = DesignSchemaCatalog(root)
    errors = []
    warnings = [] if warnings is None else warnings
    for identity, resource in entries(values, "desired.resource."):
        _dependency_design_layout.resource_mode(resource)
        kind = resource["resourceType"]
        rows = resource_rows(values, identity, kind, root)
        rule = _imports_aws_mapping_display.rule
        RESOURCE_REFERENCE_PROPERTIES = (
            _imports_design_layout.RESOURCE_REFERENCE_PROPERTIES
        )
        is_import_role_arn = _imports_design_layout.is_import_role_arn
        is_service_role_reference = _imports_design_layout.is_service_role_reference
        references = {
            rid
            for rid, _, _, _ in rows
            if has_reference(values[f"desired.row.{rid}.value"])
        }
        for rid, prop, value, _ in rows:
            if properties_scope is not None and prop not in properties_scope:
                continue
            owner = ".".join(prop.split(".")[:2])
            if owner not in {kind, *GROUPED_RESOURCE_TYPES.get(kind, set())}:
                raise InputValidationError(
                    f"property does not belong to resource: {identity}: {prop}"
                )
            rule(prop, root)
            if prop in RESOURCE_REFERENCE_PROPERTIES and not (
                rid in references
                or is_service_role_reference(prop, value)
                or _dependency_design_layout.resource_mode(resource) == "IMPORT"
                and (
                    prop != "Config.ConfigurationRecorder.RoleARN"
                    or _dependency_design_layout.is_import_pending_reference(
                        prop, value
                    )
                )
                or is_import_role_arn(
                    prop, value, _dependency_design_layout.resource_mode(resource)
                )
            ):
                warnings.append(
                    {
                        "code": "reference.expected_model_ref",
                        "message": f"{prop} requires $modelRef or an allowed IMPORT reference",
                        "resource": identity,
                        "property": prop,
                        "reference": value,
                    }
                )
        properties = {
            row[1]
            for row in rows
            if row[0] in references
            or (
                _dependency_design_layout.resource_mode(resource) == "IMPORT"
                and _dependency_design_layout.is_import_pending_reference(
                    row[1], row[2]
                )
            )
            or _dependency_policy_tables.literal(row[2])
            .strip()
            .strip('"')
            .strip()
            .lower()
            not in {"", "unset", "pending", "pending_deploy", "tbd", "未確定"}
        }
        if "parentProperty" in resource:
            properties.add(resource["parentProperty"])
        kinds = {kind} | {
            child
            for child in GROUPED_RESOURCE_TYPES.get(kind, set())
            if any(row[1].startswith(child + ".") for row in rows)
        }
        for schema_kind in sorted(kinds):
            present = property_paths_with_parents(
                {
                    prop.removeprefix(schema_kind + ".")
                    for prop in properties
                    if prop.startswith(schema_kind + ".")
                }
            )
            required = catalog.required_design_properties(schema_kind)
            if properties_scope is not None:
                required = {
                    prop
                    for prop in required
                    if any(
                        changed == schema_kind + "." + prop
                        or changed.startswith(schema_kind + "." + prop + ".")
                        or (schema_kind + "." + prop).startswith(changed + ".")
                        for original in properties_scope
                        for changed in [definition_path(original)]
                    )
                }
            missing = (
                required - present - IMPLICIT_GROUPED_PROPERTIES.get(schema_kind, set())
            )
            errors.extend(
                f"{resource['logicalId']}: required provider schema property missing: {schema_kind}.{prop}"
                for prop in sorted(missing)
            )
    if errors:
        raise InputValidationError("\n- ".join(errors))
    return warnings


def _callback_check_model_inputs_literal_check(
    _state_check_model_inputs_337: SimpleNamespace,
    catalog: DesignSchemaCatalog,
    definitions: Path,
    findings: Findings,
    root: Path,
    /,
) -> None:
    """参照や出力等の除外条件を守り、対象 Row のリテラルを検証する。"""
    config_role_arn = _imports_design_layout.config_role_arn
    is_service_role_reference = _imports_design_layout.is_service_role_reference
    DESIGN_ONLY_PROPERTIES = _imports_validation_design.DESIGN_ONLY_PROPERTIES

    prop, value = (
        _state_check_model_inputs_337.row["property"],
        _state_check_model_inputs_337.row.get(
            "document",
            _dependency_policy_tables.literal(
                _state_check_model_inputs_337.row["value"]
            ),
        ),
    )
    if "document" not in _state_check_model_inputs_337.row and is_import_expression(
        prop,
        _state_check_model_inputs_337.row["value"],
        _state_check_model_inputs_337.view,
    ):
        return
    if "document" not in _state_check_model_inputs_337.row and has_reference(
        _state_check_model_inputs_337.row["value"]
    ):
        return
    kind = ".".join(prop.split(".")[:2])
    if (
        prop in catalog_outputs(definitions, kind)
        or prop in NAMING_EXEMPT_PROPERTIES
        or prop in HIDDEN_PROPERTIES
        or prop in DESIGN_ONLY_PROPERTIES
        or is_service_role_reference(
            prop, _state_check_model_inputs_337.row.get("value", "")
        )
        or _dependency_design_layout.resource_mode(
            _state_check_model_inputs_337.resource
        )
        == "IMPORT"
        and (
            _dependency_design_layout.is_import_pending_reference(
                prop, _state_check_model_inputs_337.row.get("value", "")
            )
            or config_role_arn(prop, _state_check_model_inputs_337.row.get("value", ""))
        )
    ):
        return
    field = prop.removeprefix(kind + ".")
    if field == "Name" and kind in {
        "EC2.VPC",
        "EC2.Subnet",
        "EC2.RouteTable",
        "EC2.FlowLog",
    }:
        return
    for error in row_literal_errors(
        catalog,
        kind,
        field,
        value,
        _state_check_model_inputs_337.row.get("valueShape", "leaf"),
    ):
        findings.input_check(
            False,
            findings.source_path,
            f"provider schema violation: {prop}: {error}",
            location=f"desired.resource.{_state_check_model_inputs_337.identity}/{prop}",
        )


def validate_api_constraints(
    values: dict[str, str],
    kind: str,
    catalog: DesignSchemaCatalog,
    *,
    changed: set[str] | None = None,
) -> None:
    """選択された属性に関係する API 制約を検証する。"""
    if kind not in catalog.api_schemas:
        return
    required = catalog.job_rule_inputs(changed)
    inputs = {}
    for _, row in entries(values, "desired.row."):
        prop = row["property"].removeprefix(kind + ".")
        if prop not in required:
            continue
        raw = _dependency_policy_tables.literal(row.get("document", row["value"]))
        node = catalog.property_schema(kind, prop)
        inputs[prop] = (
            _dependency_policy_tables.literal(raw)
            if node.get("type") == "string"
            else policy_json(raw)
        )
    if errors := catalog.job_errors(inputs, changed=changed):
        raise InputValidationError("; ".join(errors))


def row_rule_inputs(
    values: dict[str, str], properties_scope: set[str]
) -> dict[str, str]:
    """変更属性と同じグループの Row を共通検証の入力として選択する。"""
    groups = {tuple(prop.split(".")[:3]) for prop in properties_scope}
    rows = {
        rid
        for rid, row in entries(values, "desired.row.")
        if tuple(row.get("property", "").split(".")[:3]) in groups
    }
    return {
        key: value
        for key, value in values.items()
        if not key.startswith(("desired.row.", "observed.row."))
        or key.split(".")[2] in rows
    }
