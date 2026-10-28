"""Model 検証: full_inputs。"""

from __future__ import annotations

import copy
from collections.abc import Collection
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

import aws_mapping_display as _imports_aws_mapping_display
import validation.design as _imports_validation_design
import validation.findings as _imports_validation_findings
from design.catalog import (
    DesignSchemaCatalog,
)
from utils.aws_mappings import definition_root
from utils.input_cache import memo_table
from validation.findings import Findings

import model.core as _imports_model_core
import model.files as _imports_model_files
import model.format as _imports_model_format
import model.importing.scope as _imports_model_importing_scope
import model.render as _imports_model_render
import model.sources as _imports_model_sources
from model.core import (
    SnapshotValues,
    entries,
)
from model.references import codebuild_reference_errors
from model.validations.identity import validate_resource_identities
from model.validations.json_settings import validate_json_settings
from model.validations.naming import _callback_check_model_inputs_names
from model.validations.policies import _kms_policy_account_check, check_policy_settings
from model.validations.presentation import _callback_check_model_inputs_presentation
from model.validations.references import _callback_check_model_inputs_references
from model.validations.schema import (
    _callback_check_model_inputs_literal_check,
    validate_api_constraints,
    validate_required_properties,
)
from model.validations.structure import _callback_check_model_inputs_structure


def _callback_check_model_inputs_json_settings(
    values: dict[str, str],
    path: Path,
    findings: Findings,
    prohibited: Collection[tuple[str, str, str]],
) -> None:
    """JSON 設定と Policy を順に検証し、警告を Findings に反映する。"""
    validate_json_settings(
        values, path, warnings=findings.warnings, excluded_references=prohibited
    )
    check_policy_settings(values, findings, path)
    for warning in findings.warnings:
        findings.warn(warning)


def check_model_inputs(
    path: Path,
    values: dict[str, str],
    root: Path,
    *,
    definitions_root: Path | None = None,
) -> Findings:
    """Full 検証を実行し、既存のセッションキャッシュを再利用する。"""
    shared = _imports_model_sources.session_reads(root)
    if shared is None or not isinstance(values, SnapshotValues):
        return _check_model_inputs(
            path, values, root, definitions_root=definitions_root
        )
    memo = memo_table()
    invocation = None
    if memo is not None:
        invocation = memo.setdefault(check_model_inputs, object())
    key = (
        "desired-validation",
        invocation,
        _imports_model_importing_scope.read_context(root),
        shared.canonical(path),
        definitions_root,
        id(values),
        shared.reference_revision,
    )
    with shared.lock:
        if key not in shared.checks:
            # JSON・参照・表示の診断は producer の観測値にも依存するため、同じ参照リビジョン内だけで再利用する。
            shared.checks[key] = (
                values,
                _check_model_inputs(
                    path,
                    values,
                    root,
                    definitions_root=definitions_root,
                ),
            )
        return copy.deepcopy(shared.checks[key][1])


def _check_full_resources(
    values: dict[str, str],
    resources: list[tuple[str, dict[str, str]]],
    root: Path,
    definitions: Path,
    findings: Findings,
    state: _CallbackState,
    catalog: DesignSchemaCatalog | None,
) -> None:
    """全 Resource の必須・Schema・Mapping・命名・Literal を順に検証する。"""
    owner = _imports_model_format.owner
    validate_mappings = _imports_aws_mapping_display.validate_mappings
    resource_values = None
    for (
        state.identity,
        state.resource,
    ) in resources:
        if resource_values is None:
            resource_values = {}
            for key, value in values.items():
                kind, number = owner(key, values)
                if kind == "resource":
                    resource_values.setdefault(number, {})[key] = value
        selected = dict(resource_values.get(state.identity, {}))
        findings.evaluate(
            "model.required." + state.identity,
            None,
            lambda *, selected=selected: validate_required_properties(
                selected, definitions, warnings=findings.warnings
            ),
        )
        findings.evaluate(
            "model.api-constraints." + state.identity,
            None,
            lambda selected=selected,
            kind=state.resource["resourceType"]: validate_api_constraints(
                selected, kind, catalog
            ),
        )
        findings.evaluate(
            "model.mapping." + state.identity,
            None,
            lambda *, selected=selected: validate_mappings(selected, definitions),
        )
        names = _bind_framework_callback(
            _callback_check_model_inputs_names,
            state,
            definitions,
            findings,
            values,
        )
        findings.evaluate("model.naming." + state.identity, None, names)
        for row_id, state.row in entries(selected, "desired.row."):
            literal_check = _bind_framework_callback(
                _callback_check_model_inputs_literal_check,
                state,
                catalog,
                definitions,
                findings,
                root,
            )
            findings.evaluate("model.literal." + row_id, None, literal_check)


def _check_full_observed_identity_presentation(
    path: Path,
    values: dict[str, str],
    root: Path,
    definitions: Path,
    resources: list[tuple[str, dict[str, str]]],
    findings: Findings,
    state: _CallbackState,
    observations: bool,
) -> None:
    """Observed、Identity、Presentation と警告を既存順で集約する。"""
    check_observed_values = _imports_validation_design.check_observed_values
    resource_details = _imports_model_render.resource_details
    model = (
        (root / "model" / path.relative_to(root / "docs/designs")).with_suffix(
            ".properties"
        )
        if path.is_relative_to(root / "docs/designs")
        else path
    )
    state.view = (
        root / "docs/designs" / model.relative_to(root / "model")
    ).with_suffix(".md")
    if observations:
        findings.evaluate(
            "model.observed",
            None,
            lambda: check_observed_values(
                [model],
                findings=findings,
                root=root,
                scope=None,
                design_sources={state.view: values},
            ),
        )
    service = path.stem
    owned = values.get(
        f"desired.service.{service}.ownedCatalogResourceTypes", ""
    ).split(",")
    presentation = _bind_framework_callback(
        _callback_check_model_inputs_presentation,
        definitions,
        findings,
        owned,
        path,
        resource_details,
        resources,
        root,
        service,
        values,
    )
    kms_policy_check = _kms_policy_account_check()
    for (
        state.identity,
        state.resource,
    ) in resources:
        findings.evaluate(
            "model.identity." + state.identity,
            None,
            lambda *,
            identity=state.identity,
            resource=state.resource: validate_resource_identities(
                state.view,
                values,
                root,
                [(identity, resource)],
                definitions_root=definitions,
                _kms_policy_check=kms_policy_check,
            ),
        )
    findings.evaluate("model.presentation", None, presentation)
    for warning in findings.warnings:
        warning.setdefault(
            "scope", "/".join((*model.relative_to(root / "model").parts[:2], service))
        )
        warning.setdefault("source", str(model.relative_to(root)))


def _check_model_inputs(
    path: Path,
    values: dict[str, str],
    root: Path,
    *,
    definitions_root: Path | None = None,
    observations: bool = True,
) -> Findings:
    """Full 検証を既存の順序で集約し、構造エラー時は後続を停止する。"""
    _state_check_model_inputs_337 = _CallbackState()
    Findings = _imports_validation_findings.Findings

    validate_model_keys = _imports_model_core.validate_runtime_keys
    resource_row_index = _imports_model_files.resource_row_index
    runtime_values = _imports_model_sources.runtime_values
    values = runtime_values(values)

    definitions = definitions_root or definition_root(root)
    _state_check_model_inputs_337.view = (
        (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
        if path.is_relative_to(root / "model")
        else path
    )
    model_path = (
        (root / "model" / path.relative_to(root / "docs/designs")).with_suffix(
            ".properties"
        )
        if path.is_relative_to(root / "docs/designs")
        else path
    )
    findings = Findings(root, source_path=model_path)
    structure = _bind_framework_callback(
        _callback_check_model_inputs_structure,
        resource_row_index,
        validate_model_keys,
        values,
    )
    # 構造が不正な場合、後続処理に不正なキーを渡さない。
    if findings.evaluate("model.structure", None, structure).errors:
        return findings
    prohibited = codebuild_reference_errors(model_path, values, findings=findings)
    findings.evaluate(
        "model.json-settings",
        None,
        _bind_framework_callback(
            _callback_check_model_inputs_json_settings,
            values,
            model_path,
            findings,
            prohibited,
        ),
    )
    # Stack 入力は Resource 検証に進まず、従来の必須属性検証で終了する。
    if entries(values, "desired.stack."):
        findings.evaluate(
            "model.stacks",
            None,
            lambda: validate_required_properties(values, definitions),
        )
        return findings
    resources = entries(values, "desired.resource.")
    references = _bind_framework_callback(
        _callback_check_model_inputs_references,
        _state_check_model_inputs_337,
        findings,
        root,
        values,
    )
    findings.evaluate("model.references", None, references)
    try:
        catalog = DesignSchemaCatalog(definitions) if resources else None
    except (OSError, ValueError) as error:
        findings.processing_failure(
            "model.catalog", None, error, source_path=model_path
        )
        return findings
    # Full は全 Resource を対象とし、各 Resource 内の検証順序を維持する。
    _check_full_resources(
        values,
        resources,
        root,
        definitions,
        findings,
        _state_check_model_inputs_337,
        catalog,
    )
    _check_full_observed_identity_presentation(
        path,
        values,
        root,
        definitions,
        resources,
        findings,
        _state_check_model_inputs_337,
        observations,
    )
    return findings
