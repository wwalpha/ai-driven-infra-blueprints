"""Model 検証: change_inputs。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from validation.findings import Findings

if TYPE_CHECKING:
    from model.change_plan import ServiceChange

from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

import aws_mapping_display as _imports_aws_mapping_display
import design.layout as _imports_design_layout
import validation.design as _imports_validation_design
import validation.findings as _imports_validation_findings
from design.catalog import (
    DesignSchemaCatalog,
)
from utils.aws_mappings import definition_root

import model.core as _imports_model_core
import model.sources as _imports_model_sources
from model.core import (
    entries,
)
from model.format import owner as owner_for_change
from model.projection import design_target
from model.references import codebuild_reference_errors
from model.validations.identity import validate_resource_identities
from model.validations.json_settings import validate_json_settings
from model.validations.naming import _callback_check_model_inputs_names
from model.validations.policies import (
    check_policy_settings,
    validate_kms_policy_accounts,
)
from model.validations.schema import (
    _callback_check_model_inputs_literal_check,
    validate_api_constraints,
    validate_required_properties,
)
from model.validations.stacks import validate_changed_stacks


def _select_changed_inputs(
    authority: dict[str, str],
    change: ServiceChange,
) -> tuple[dict[str, dict[str, str]], dict[str, str], dict[str, str]]:
    """変更 Resource と構造検証に必要な文脈を選択する。"""
    resources = dict(
        _imports_model_core.structural_entries(authority, "desired.resource.")
    )
    selected_resources = {
        rid: resource
        for rid, resource in resources.items()
        if resource.get("logicalId") in change.resources
    }
    # 既存メタデータは文脈として使い、Change では変更項目と必須 Identity だけを検証する。
    metadata = {
        key: value
        for key, value in authority.items()
        if not key.startswith("desired.resource.")
        or key.rsplit(".", 1)[-1] in {"resourceType", "logicalId"}
        or resources[key.split(".")[2]].get("logicalId") in change.added
        or key in change.keys
    }
    selected = {
        key: value
        for key, value in metadata.items()
        if (
            not key.startswith(
                (
                    "desired.resource.",
                    "desired.row.",
                    "observed.row.",
                    "display.resource.",
                    "desired.reference.",
                    "desired.stack.",
                    "display.stack.",
                    "desired.artifact.",
                    "desired.deployment.",
                )
            )
            or key.startswith("desired.resource.")
            and key.split(".")[2] in selected_resources
            or key.startswith(("desired.row.", "observed.row."))
            and key.split(".")[2] in change.rows
        )
    }
    return selected_resources, metadata, selected


def _check_changed_resources(
    authority: dict[str, str],
    values: dict[str, str],
    change: ServiceChange,
    selected_resources: dict[str, dict[str, str]],
    rows: dict[str, dict[str, str]],
    definitions: Path,
    root: Path,
    view: Path,
    catalog: DesignSchemaCatalog | None,
    findings: Findings,
) -> None:
    """変更 Resource の必須・Schema・Mapping・命名・Identity・Literal を検証する。"""
    for number, resource in selected_resources.items():
        logical, kind = resource["logicalId"], resource["resourceType"]
        resource_values = {
            key: value
            for key, value in values.items()
            if owner_for_change(key, authority) == ("resource", number)
        }
        changed_properties = {
            prop for identity, prop in change.properties if identity == logical
        }
        findings.evaluate(
            "change.required." + logical,
            None,
            lambda resource_values=resource_values,
            logical=logical,
            changed_properties=changed_properties: validate_required_properties(
                resource_values,
                definitions,
                warnings=findings.warnings,
                # 新規 Resource は全必須属性を確認し、既存 Resource は変更属性に限定する。
                properties_scope=None
                if logical in change.added
                else changed_properties,
            ),
        )
        findings.evaluate(
            "change.api-constraints." + logical,
            None,
            lambda resource_values=resource_values,
            kind=kind,
            changed_properties=changed_properties: validate_api_constraints(
                resource_values,
                kind,
                catalog,
                changed={prop.removeprefix(kind + ".") for prop in changed_properties},
            ),
        )
        findings.evaluate(
            "change.mapping." + logical,
            None,
            lambda resource_values=resource_values: _imports_aws_mapping_display.validate_mappings(
                resource_values, definitions
            ),
        )
        name_fields = _imports_design_layout.configured_name_fields(definitions, kind)
        # 新規 Resource または命名に関わる変更だけを検証し、既存の無関係なエラーは除く。
        if logical in change.added or any(
            prop == kind + "." + name
            or prop.startswith(kind + ".Tags")
            or prop.startswith(kind + ".HostedZoneTags")
            for prop in changed_properties
            for name in name_fields
        ):
            state = _CallbackState(identity=number, resource=resource)
            findings.evaluate(
                "change.naming." + logical,
                None,
                _bind_framework_callback(
                    _callback_check_model_inputs_names,
                    state,
                    definitions,
                    findings,
                    values,
                ),
            )
        if logical in change.identity_resources:
            findings.evaluate(
                "change.identity." + logical,
                None,
                lambda number=number,
                resource=resource,
                resource_values=resource_values: validate_resource_identities(
                    view,
                    resource_values,
                    root,
                    [(number, resource)],
                    definitions_root=definitions,
                ),
            )
        for rid in change.rows:
            if rid.rpartition("-")[0] != number:
                continue
            state = _CallbackState(
                identity=number, resource=resource, row=rows[rid], view=view
            )
            findings.evaluate(
                "change.literal." + rid,
                None,
                _bind_framework_callback(
                    _callback_check_model_inputs_literal_check,
                    state,
                    catalog,
                    definitions,
                    findings,
                    root,
                ),
            )


def _check_changed_documents(
    authority: dict[str, str],
    values: dict[str, str],
    change: ServiceChange,
    path: Path,
    root: Path,
    view: Path,
    findings: Findings,
) -> None:
    """変更行に対して Policy・JSON・参照とコメントを検証する。"""
    selected_rows = {
        key: value
        for key, value in values.items()
        if not key.startswith(("desired.row.", "observed.row."))
        or key.split(".")[2] in change.rows
    }
    for key in change.keys:
        if (
            key.startswith("desired.row.")
            and key.endswith(".comment")
            and key in authority
        ):
            findings.check(
                _imports_validation_design.JAPANESE_TEXT_PATTERN.search(authority[key])
                is not None,
                "Source / Comment must be Japanese: " + key.split(".")[2],
            )
    check_policy_settings(selected_rows, findings, path)
    account_rows = change.rows | {
        key.split(".")[2]
        for key in change.keys
        if key.startswith("desired.row.") and key.endswith(".comment")
    }
    account_inputs = {
        key: value
        for key, value in values.items()
        if not key.startswith(("desired.row.", "observed.row."))
        or key.split(".")[2] in account_rows
    }
    findings.evaluate(
        "change.policy-accounts",
        None,
        lambda: validate_kms_policy_accounts(account_inputs, design_target(view, root)),
    )
    prohibited = codebuild_reference_errors(
        path, selected_rows, findings=findings, context_values=values
    )
    findings.evaluate(
        "change.json-settings",
        None,
        lambda: validate_json_settings(
            selected_rows,
            path,
            warnings=findings.warnings,
            excluded_references=prohibited,
            reference_values=authority,
        ),
    )


def check_change_inputs(
    path: Path,
    authority: dict[str, str],
    root: Path,
    change: ServiceChange,
    *,
    definitions_root: Path | None = None,
) -> Findings:
    """変更対象と新規 Resource を選択し、無関係な既存エラーを検証しない。"""
    definitions = definitions_root or definition_root(root)
    findings = _imports_validation_findings.Findings(root, source_path=path)
    selected_resources, metadata, selected = _select_changed_inputs(authority, change)
    findings.evaluate(
        "change.keys",
        None,
        lambda: _imports_model_core.validate_model_keys(
            {key: authority[key] for key in change.keys if key in authority}
        ),
    )
    findings.evaluate(
        "change.structure",
        None,
        lambda: _imports_model_core.validate_authority(selected),
    )
    findings.evaluate(
        "change.stacks", None, lambda: validate_changed_stacks(authority, change)
    )
    # 構造や Stack が不正なら、それらを前提とする後続検証を停止する。
    if findings.errors:
        return findings
    quality_values = {
        key: value
        for key, value in metadata.items()
        if not key.startswith(("desired.resource.", "display.resource."))
        or key.split(".")[2] in selected_resources
    }
    # 命名・参照の既存条件を保つため、対象 Resource の CREATE／IMPORT 情報は文脈に残す。
    quality_values.update(
        (key, value)
        for key, value in authority.items()
        if key.startswith("desired.resource.")
        and key.endswith((".resourceMode", ".anchor"))
        and key.split(".")[2] in selected_resources
    )
    values = _imports_model_sources.projected_values(quality_values)
    rows = {rid: row for rid, row in entries(values, "desired.row.")}
    catalog = DesignSchemaCatalog(definitions) if selected_resources else None
    view = (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
    # 既存 Resource は変更属性のみ、新規 Resource は必須属性全体を検証する。
    _check_changed_resources(
        authority,
        values,
        change,
        selected_resources,
        rows,
        definitions,
        root,
        view,
        catalog,
        findings,
    )
    _check_changed_documents(authority, values, change, path, root, view, findings)
    # 観測値は変更された行だけを対象にする。
    if change.observed_rows:
        observations = {
            key: value
            for key, value in values.items()
            if not key.startswith("observed.row.")
            or key.split(".")[2] in change.observed_rows
        }
        _imports_validation_design.check_observed_values(
            [path],
            findings=findings,
            root=root,
            scope=None,
            design_sources={view: observations},
        )
    for warning in findings.warnings:
        findings.warn(warning)
    return findings
