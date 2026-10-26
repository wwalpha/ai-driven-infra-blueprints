"""Explicit design validation over canonical metadata and runtime fields."""

from __future__ import annotations

import copy
import re
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace
from types import SimpleNamespace as _CallbackState

import aws_mapping_display as _imports_aws_mapping_display
import design.array_display as _imports_array_display
import design.layout as _dependency_design_layout
import design.layout as _imports_design_layout
import design.policy_tables as _dependency_policy_tables
import design.services.codepipeline as _imports_codepipeline
import json_intrinsics as _imports_json_intrinsics
import utils.aws_catalogs as _compat_utils_aws_catalogs
import validation.design as _imports_validation_design
import validation.findings as _imports_validation_findings
from design.catalog import (
    DesignSchemaCatalog,
    property_paths_with_parents,
    selected_properties,
)
from design.layout_schema import GROUPED_RESOURCE_TYPES, IMPLICIT_GROUPED_PROPERTIES
from design.layout_schema import resource_anchor as resource_anchor
from design.services.definitions.registry import HIDDEN_PROPERTIES
from utils import iac_values
from utils.aws_mappings import definition_root
from utils.input_cache import input_is_file, memo_table, memoized
from utils.input_cache import input_scope as input_scope
from utils.json_format import policy_json
from utils.reference_contracts import action_contexts, reference_error, row_contexts
from validation.diagnostics import Diagnostic, service_scope

import model.core as _imports_model_core
import model.environment_values as environment_values
import model.files as _imports_model_files
import model.format as _imports_model_format
import model.identity as _dependency_model_identity
import model.identity as _imports_model_identity
import model.importing.scope as _imports_model_importing_scope
import model.projection as _dependency_model_projection
import model.projection as _imports_model_projection
import model.references as _imports_model_references
import model.render as _imports_model_render
import model.sources as _imports_model_sources
from model.core import (
    LINK,
    ReferenceResolutionError,
    SnapshotValues,
    entries,
    properties,
    require_reference_diagnostics,
    stack_model,
)
from model.reference_nodes import context_at, nodes, receiving_property

NAMING_EXEMPT_PROPERTIES = {
    "Config.ConfigurationRecorder.Name",
    "Config.DeliveryChannel.Name",
    "Glue.Connection.ConnectionInput.Name",
    "Glue.Database.DatabaseInput.Name",
    "Glue.Table.TableInput.Name",
    "GuardDuty.Detector.Name",
    "IAM.ManagedPolicy.ManagedPolicyName",
    "IAM.User.UserName",
    "IAM.InstanceProfile.InstanceProfileName",
    "Route53.HostedZone.Name",
    "Route53.RecordSet.Name",
}


def configuration_context(values, row_id, root):
    """Use the existing lossless Stage/Action projection for split Model rows."""
    number = row_id.rpartition("-")[0]
    kind = "CodePipeline.Pipeline"
    rows = [
        [
            rid,
            row["property"].removeprefix(kind + "."),
            row["value"],
            row.get("comment", ""),
        ]
        for rid, row in entries(values, "desired.row.")
        if rid.rpartition("-")[0] == number
    ]
    indexed = _imports_array_display.indexed_rows(
        _imports_codepipeline.pipeline_rows(rows), kind, root
    )
    contexts = action_contexts(
        [(rid, {"property": prop, "value": value}) for rid, prop, value, _ in indexed]
    )
    properties = {rid: prop for rid, prop, _, _ in indexed}
    parent = properties[row_id].split(".Configuration.", 1)[0]
    return contexts.get(parent, {})


def reference_context_for(values, row_id, row, value, pointer, root):
    """Share the existing split-row and nested JSON receiving-context contract."""
    context = (
        configuration_context(values, row_id, root)
        if row["property"].startswith(
            "CodePipeline.Pipeline.Stages[].Actions[].Configuration"
        )
        and not isinstance(value, list)
        else None
    )
    if context is None:
        kind = ".".join(row["property"].split(".")[:2])
        number = row_id.rpartition("-")[0]
        contexts = row_contexts(
            kind,
            [
                (rid, item)
                for rid, item in _imports_model_projection._resource_row_entries(values)
                if rid.rpartition("-")[0] == number
            ],
        )
        prop = row["property"].removeprefix(kind + ".")
        context = contexts.get(
            row_id, contexts.get(prop, contexts.get(prop.rsplit(".", 1)[0]))
        )
    context = context_at(value, row["property"], pointer, context)
    return context


def validate_json_settings(
    values, model_path, *, warnings=None, excluded_references=(), reference_values=None
):
    """Validate JSON links and intrinsic structure without rewriting Model authority."""
    reference_tokens = _imports_model_identity.reference_tokens
    _json = _imports_model_references._json
    string_leaves = _imports_model_references.string_leaves
    path = Path(model_path)
    if path.suffix == ".md" and path.parents[2].name == "designs":
        path = (
            path.parents[4]
            / "model"
            / path.relative_to(path.parents[4] / "docs/designs")
        ).with_suffix(".properties")
    validate_environment_settings(
        values, path, warnings=warnings, reference_values=reference_values
    )
    resolver = None
    diagnostics = []
    for row_id, row in entries(values, "desired.row."):
        for field in ("value", "document"):
            if field not in row:
                continue
            value, structured = _json(f"desired.row.{row_id}.{field}", row[field])
            if not structured:
                if any(nodes(value)):
                    raise ValueError(
                        "JSON Model references in .value require the existing JSON backtick notation"
                    )
                continue
            if resolver is None:
                scope = _imports_model_sources.scope_for(path)
                resolver = _imports_model_projection.reference_resolver(
                    values if reference_values is None else reference_values,
                    scope,
                    scope.root,
                )
            _, row_diagnostics = _imports_model_projection.document_references(
                value,
                resolver=resolver,
                scope=scope,
                property_name=row["property"],
                logical_id=values.get(
                    f"desired.resource.{row_id.rpartition('-')[0]}.logicalId"
                ),
                model_key=f"desired.row.{row_id}.{field}",
                context=reference_context_for(
                    values, row_id, row, value, "", scope.root
                ),
                excluded_references=tuple(
                    pointer
                    for identity, source_field, pointer in excluded_references
                    if (identity, source_field) == (row_id, field)
                ),
            )
            diagnostics.extend(row_diagnostics)
            if row_diagnostics:
                continue
            number = row_id.rpartition("-")[0]
            resource = values.get(f"desired.resource.{number}.logicalId", number)
            for pointer, text in string_leaves(value):
                if (row_id, field, pointer) in excluded_references:
                    continue
                if any(reference_tokens(text)):
                    raise ValueError(
                        f"JSON setting contains a Markdown Resource link: Model={model_path}, "
                        f"Resource={resource} ({number}), Property={row['property']}, "
                        f"JSON Pointer={pointer!r}; use confirmed AWS values and external desired.reference metadata"
                    )
            project_document = _imports_json_intrinsics.project_document
            project_document(
                value,
                warnings=warnings,
                model_path=model_path,
                logical_id=resource,
                property_name=row["property"],
            )

    try:
        require_reference_diagnostics(diagnostics)
    except ReferenceResolutionError as error:
        if warnings is not None:
            warnings.extend(error.diagnostics)


def validate_environment_settings(
    values, path, *, warnings=None, reference_values=None
):
    root = _imports_model_sources.scope_for(path).root
    authority = values if reference_values is None else dict(reference_values, **values)
    resources = dict(entries(authority, "desired.resource."))
    rows = entries(values, "desired.row.")
    context_rows = entries(authority, "desired.row.")
    contexts, mappings = {}, {}
    selected_kinds = {
        rid.rpartition("-")[0]: ".".join(row["property"].split(".")[:2])
        for rid, row in rows
    }
    for number, kind in selected_kinds.items():
        mapping = mappings.setdefault(kind, environment_values.mapping_for(root, kind))
        contexts.update(
            environment_values.row_contexts(
                kind,
                [
                    (rid, row)
                    for rid, row in context_rows
                    if rid.rpartition("-")[0] == number
                ],
                mapping,
            )
        )
    for rid, row in rows:
        kind = selected_kinds[rid.rpartition("-")[0]]
        field = "document" if "document" in row else "value"
        value, structured = _imports_model_references._json(
            f"desired.row.{rid}.{field}", row[field]
        )
        if not structured:
            value = _imports_model_core.literal(value)
        invalid = environment_values.pending_errors(
            kind, row["property"], value, mappings[kind], context=contexts.get(rid)
        )
        logical = resources.get(rid.rpartition("-")[0], {}).get("logicalId")
        if invalid:
            raise _imports_model_core.ModelNeedsFixError(
                "PENDING_DEPLOY is permitted only in environment Values, not this desired field",
                code="MODEL_REF_INVALID_PENDING_STATE",
                model=str(path),
                modelKey=f"desired.row.{rid}.{field}",
                property=row["property"],
                pointer=invalid[0],
                resourceLogicalId=logical,
            )
        if warnings is not None:
            for item in environment_values.inspect(
                kind, row["property"], value, mappings[kind], context=contexts.get(rid)
            ):
                if item.value == "PENDING_DEPLOY":
                    warnings.append(
                        dict(
                            category="REFERENCE_PENDING_DEPLOY",
                            code="ENVIRONMENT_VALUE_PENDING",
                            message=item.reason,
                            model=str(path),
                            modelKey=f"desired.row.{rid}.{field}",
                            property=row["property"],
                            pointer=item.pointer,
                            resolutionState=item.status,
                            resourceLogicalId=logical,
                            status="WARNING",
                        )
                    )


@memoized
def naming_rule_files(root: Path, namespace: str | None = None) -> tuple[Path, ...]:
    """Read the common entry and only explicitly indexed service rules."""
    root = definition_root(root)
    path = root / "framework/rules/aws-resource-naming.md"
    files = [path]
    for name, reference in re.findall(
        r"^\| `([A-Za-z0-9]+)` \| \[[^\]]+\]\((aws-resource-naming/[A-Za-z0-9]+\.md)\) \|$",
        path.read_text(encoding="utf-8"),
        re.MULTILINE,
    ):
        if namespace is None or name == namespace:
            files.append(path.parent / reference)
    return tuple(files)


def naming_target_matches(
    prop: str, targets: set[str], kind: str | None = None
) -> bool:
    """Match a Naming Target at its declared root or exact nested property path."""
    normalized = {
        target.removeprefix(kind + ".") if kind else target for target in targets
    }
    return prop in normalized


@memoized
def naming_targets(root: Path, namespace: str | None = None) -> dict[str, set[str]]:
    targets: dict[str, set[str]] = {}
    for path in naming_rule_files(root, namespace):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if (
                len(cells) in {5, 6}
                and cells[2].startswith("`")
                and re.fullmatch(r"`[^`]+`", cells[4])
            ):
                for kind in re.findall(r"`([^`]+)`", cells[2]):
                    targets.setdefault(kind, set()).add(cells[3].strip("`"))
    return targets


def naming_coverage_errors(
    root: Path,
    kind: str,
    selected: set[str],
    name_tag: bool = False,
    mode: str = "CREATE",
) -> list[str]:
    """Check rule existence without requiring any design values."""
    if mode not in {"CREATE", "IMPORT"}:
        raise ValueError(f"resourceMode must be CREATE or IMPORT: {mode!r}")
    if mode == "IMPORT":
        return []
    targets = naming_targets(root, kind.partition(".")[0])
    expected = selected & set(_dependency_design_layout.resource_name_fields(kind))
    expected.update(
        field
        for field in selected
        if naming_target_matches(field, targets.get(kind, set()), kind)
    )
    if name_tag:
        expected.add("Name tag")
    return [
        f"naming rule missing: {kind}: {field}"
        for field in sorted(expected)
        if kind + "." + field not in NAMING_EXEMPT_PROPERTIES
        and not naming_target_matches(field, targets.get(kind, set()), kind)
    ]


def design_naming_errors(
    root: Path, kind: str, mode: str = "CREATE", name_tag: bool = False
) -> list[str]:
    """Preflight a selected resource type before asking for design values."""
    # Deployment StackName is a model input, not a catalog resource property.
    selected = (
        {"StackName"}
        if kind == "CloudFormation.Stack"
        else set(selected_properties(root, kind))
    )
    if not selected:
        raise ValueError(f"catalog resource type missing: {kind}")
    selected -= {
        field.removeprefix(kind + ".") for field in catalog_outputs(root, kind)
    }
    if name_tag and not selected.intersection(
        {"Tags", "Tags[].Key", "HostedZoneTags", "HostedZoneTags[].Key"}
    ):
        raise ValueError(f"Name tag is not selectable: {kind}")
    if kind in {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}:
        selected.add("Name")
    if kind in {"EC2.VPCEndpoint", "EC2.Instance"}:
        name_tag = True
    return naming_coverage_errors(root, kind, selected, name_tag, mode)


def naming_errors(
    root: Path, kind: str, rows: list[list[str]], mode: str = "CREATE"
) -> list[str]:
    if kind in {"CodeBuild.Project", "IAM.Role"}:
        field = "RoleName" if kind == "IAM.Role" else "Name"
        names = [
            row[2].strip('`"')
            for row in rows
            if row[1].removeprefix(kind + ".") == field
        ]
        if len(names) != 1:
            return [f"{kind}.{field} must appear exactly once"]
        value = names[0]
        if (
            not value.strip()
            or value.strip().lower()
            in {"unset", "pending", "pending_deploy", "tbd", "n/a", "none", "未確定"}
            or value.startswith("[")
            or "{{" in value
        ):
            return [f"{kind}.{field} must be confirmed and non-empty"]
    if mode == "IMPORT":
        return []  # Confirmed actual names above and provider/schema checks remain mandatory.
    outputs = catalog_outputs(root, kind)
    selected = {
        row[1].removeprefix(kind + ".")
        for row in rows
        if kind + "." + row[1].removeprefix(kind + ".") not in outputs
    }
    tag_rows = [
        row
        for row in rows
        if row[1].removeprefix(kind + ".").startswith(("Tags", "HostedZoneTags"))
    ]
    return naming_coverage_errors(
        root,
        kind,
        selected,
        _dependency_design_layout.resource_display_name(kind, tag_rows, root=root)
        is not None,
        mode,
    )


def validate_required_properties(
    values: dict[str, str], root: Path, *, warnings=None
) -> list[dict]:
    """Reject missing required model inputs before producing any view or artifact."""
    validate_model_keys = _imports_model_core.validate_runtime_keys
    resource_row_index = _imports_model_files.resource_row_index
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
                raise ValueError("; ".join(errors))
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
            if _dependency_model_identity.resource_link(
                values[f"desired.row.{rid}.value"]
            )
        }
        for rid, prop, value, _ in rows:
            rule(prop, root)
            owner = ".".join(prop.split(".")[:2])
            if owner not in {kind, *GROUPED_RESOURCE_TYPES.get(kind, set())}:
                raise ValueError(
                    f"property does not belong to resource: {identity}: {prop}"
                )
            if prop in RESOURCE_REFERENCE_PROPERTIES and not (
                rid in references
                or (
                    LINK.fullmatch(value)
                    or _dependency_model_identity.resource_link(value)
                )
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
                        "code": "reference.expected_link",
                        "message": f"{prop} must be a resource link or an allowed IMPORT reference",
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
            missing = (
                catalog.required_design_properties(schema_kind)
                - present
                - IMPLICIT_GROUPED_PROPERTIES.get(schema_kind, set())
            )
            errors.extend(
                f"{resource['logicalId']}: required provider schema property missing: {schema_kind}.{prop}"
                for prop in sorted(missing)
            )
    if errors:
        raise ValueError("\n- ".join(errors))
    return warnings


def validate_kms_policy_accounts(values: dict[str, str], target: dict) -> None:
    """Check local KMS account principals without rewriting explicit external grants."""
    if not target:
        return
    execution = target.get("awsExecutionAccountId", target["awsAccountId"])
    keys = {
        identity
        for identity, resource in entries(values, "desired.resource.")
        if resource["resourceType"] == "KMS.Key"
        and _dependency_design_layout.resource_mode(resource) == "CREATE"
    }
    for identity, row in entries(values, "desired.row."):
        if (
            not any(identity.startswith(key + "-") for key in keys)
            or row.get("property") != "KMS.Key.KeyPolicy"
            or "document" not in row
        ):
            continue
        external = set(
            re.findall(
                r"\bcross-account:(arn:[A-Za-z0-9_+=,.@:/-]+)(?=$|[\s`])",
                row.get("comment", ""),
            )
        )
        document = policy_json(row["document"])
        if not isinstance(document, dict):
            raise ValueError(
                f"KMS.Key.KeyPolicy {identity}: document must be an object"
            )
        statements = document.get("Statement", [])
        for number, statement in enumerate(
            statements if isinstance(statements, list) else [statements], 1
        ):
            if not isinstance(statement, dict):
                raise ValueError(
                    f"KMS.Key.KeyPolicy {identity} Statement[{number}]: must be an object"
                )
            if statement.get("Effect") != "Allow":
                continue
            principal = statement.get("Principal", {})
            principals = principal.get("AWS", []) if isinstance(principal, dict) else []
            for arn in principals if isinstance(principals, list) else [principals]:
                match = re.fullmatch(
                    r"arn:[^:]+:iam::([0-9]{12}):(root|role/aws-service-role/macie(?:\.[a-z0-9-]+)?\.amazonaws\.com/AWSServiceRoleForAmazonMacie)",
                    str(arn),
                )
                if match and match[1] != execution and arn not in external:
                    raise ValueError(
                        f"KMS.Key.KeyPolicy {identity} Statement[{number}] Principal.AWS: {arn}: "
                        f"must use AWS execution account {execution}; explicit cross-account grant requires "
                        f"cross-account:{arn} in the policy row comment"
                    )


def _callback__kms_policy_account_check_check(
    _state__kms_policy_account_check_266, /, values, target
):
    pass
    inputs = (tuple(values.items()), tuple(target.items()))
    if inputs != _state__kms_policy_account_check_266.successful:
        validate_kms_policy_accounts(values, target)
        _state__kms_policy_account_check_266.successful = inputs


def _kms_policy_account_check():
    """Reuse only the last successful ordered inputs within one service check."""
    _state__kms_policy_account_check_266 = _CallbackState()
    _state__kms_policy_account_check_266.successful = None

    check = _bind_framework_callback(
        _callback__kms_policy_account_check_check, _state__kms_policy_account_check_266
    )

    return check


def validate_resource_identities(
    path, values, root, resources, *, definitions_root=None, _kms_policy_check=None
):
    relative = (
        path.parent.relative_to(root / "docs/designs")
        if path.is_relative_to(root / "docs/designs")
        else None
    )
    target = design_target(path, root)
    (_kms_policy_check or validate_kms_policy_accounts)(values, target)
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
                    cfn_type = None  # API-only design resources have no CFn identity.
                if cfn_type:
                    raise ValueError(
                        f"{identity}: cfn-logicalId required for CloudFormation CREATE resource"
                    )
            continue
        if target.get("iacEngine") == "terraform":
            raise ValueError(f"{identity}: cfn-logicalId is forbidden for Terraform")
        if _dependency_design_layout.resource_mode(resource) != "CREATE":
            raise ValueError(
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
            raise ValueError(
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


def codebuild_reference_errors(path, values, *, findings=None):
    """Check source references before resolution or display can fail."""
    errors = {}
    rows = entries(values, "desired.row.")
    for identity, resource in entries(values, "desired.resource."):
        if resource["resourceType"] != "CodeBuild.Project":
            continue
        selected = [
            (rid, row) for rid, row in rows if rid.rpartition("-")[0] == identity
        ]
        contexts = row_contexts("CodeBuild.Project", selected)
        for rid, row in selected:
            prop = row["property"]
            if not prop.startswith("CodeBuild.Project.Environment"):
                continue
            for source_field in ("value", "document"):
                if source_field not in row:
                    continue
                try:
                    value, _ = _imports_model_references._json(
                        "desired.row." + rid + "." + source_field, row[source_field]
                    )
                    occurrences = [(node.pointer, True) for node in nodes(value)]
                except (ValueError, TypeError):
                    continue  # JSON validation reports syntax errors independently.
                occurrences.extend(
                    (pointer, bool(_dependency_model_identity.resource_link(text)))
                    for pointer, text in _imports_model_references.string_leaves(value)
                )
                for pointer, linked in occurrences:
                    if not linked:
                        continue
                    field = receiving_property(prop, pointer)
                    context = context_at(value, prop, pointer, contexts.get(rid, {}))
                    if error := reference_error(field, context):
                        errors[rid, source_field, pointer] = (
                            f"Model={path}, Resource={resource['logicalId']} ({identity}), "
                            f"Name={context.get('Name', '')}, Type=PLAINTEXT, Property={field}: {error}"
                        )
    if findings is not None:
        for (row, source_field, pointer), message in errors.items():
            findings.add_diagnostic(
                Diagnostic.create(
                    findings.canonical_root,
                    code="codebuild.plaintext-reference",
                    check_id="model.reference-policy",
                    service=service_scope(findings.canonical_root, path),
                    source_path=path,
                    location=f"desired.row.{row}.{source_field}{pointer}",
                    message=message,
                )
            )
    return errors


def _callback_check_model_inputs_json_settings(values, path, findings, prohibited):
    validate_json_settings(
        values, path, warnings=findings.warnings, excluded_references=prohibited
    )
    for warning in findings.warnings:
        findings.warn(warning)


def _callback_check_model_inputs_structure(
    resource_row_index, validate_model_keys, values, /
):
    validate_model_keys(values)
    resource_row_index(values)


def _callback_check_model_inputs_presentation(
    definitions,
    findings,
    owned,
    path,
    resource_details,
    resources,
    root,
    service,
    values,
    /,
):
    scope_for = _imports_model_sources.scope_for
    view = (
        (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
        if path.is_relative_to(root / "model")
        else path
    )
    scope = scope_for(
        (root / "model" / view.relative_to(root / "docs/designs")).with_suffix(
            ".properties"
        )
    )
    resource_details(
        values,
        definitions,
        service,
        owned,
        resources,
        bound_resource_anchors(view),
        findings=findings,
        scope=scope,
    )


def _callback_check_model_inputs_references(
    _state_check_model_inputs_337, findings, root, values, /
):
    diagnose = _imports_model_references.diagnose
    scope_for = _imports_model_sources.scope_for
    model_path = (
        root
        / "model"
        / _state_check_model_inputs_337.view.relative_to(root / "docs/designs")
    ).with_suffix(".properties")
    candidate = SimpleNamespace(
        scope=scope_for(model_path), authoritative=values, dependencies={}
    )
    warnings, _ = diagnose(candidate, errors=findings.errors)
    findings.warnings.extend(warnings)


def _callback_check_model_inputs_names(
    _state_check_model_inputs_337, definitions, findings, values, /
):
    rows = resource_rows(
        values,
        _state_check_model_inputs_337.identity,
        _state_check_model_inputs_337.resource["resourceType"],
        definitions,
    )
    for error in naming_errors(
        definitions,
        _state_check_model_inputs_337.resource["resourceType"],
        rows,
        _dependency_design_layout.resource_mode(_state_check_model_inputs_337.resource),
    ):
        findings.check(False, error)


def _callback_check_model_inputs_literal_check(
    _state_check_model_inputs_337, catalog, definitions, findings, root, /
):
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
    if (
        "document" not in _state_check_model_inputs_337.row
        and _dependency_model_identity.resource_link(
            _state_check_model_inputs_337.row["value"]
        )
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
    for error in catalog.literal_errors(kind, field, value):
        findings.check(False, f"provider schema violation: {prop}: {error}")


def check_model_inputs(path, values, root, *, definitions_root=None):
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
            # JSON/reference/presentation diagnostics also depend on producer observations.
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


def _check_model_inputs(
    path, values, root, *, definitions_root=None, observations=True
):
    """Validate authoritative inputs even when their View cannot be rendered."""
    _state_check_model_inputs_337 = _CallbackState()
    validate_mappings = _imports_aws_mapping_display.validate_mappings
    check_observed_values = _imports_validation_design.check_observed_values
    Findings = _imports_validation_findings.Findings

    validate_model_keys = _imports_model_core.validate_runtime_keys
    resource_row_index = _imports_model_files.resource_row_index
    owner = _imports_model_format.owner
    resource_details = _imports_model_render.resource_details
    runtime_values = _imports_model_sources.runtime_values
    values = runtime_values(values)

    findings = Findings(root)
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
    structure = _bind_framework_callback(
        _callback_check_model_inputs_structure,
        resource_row_index,
        validate_model_keys,
        values,
    )
    if findings.evaluate("model.structure", None, structure).errors:
        return findings
    prohibited = codebuild_reference_errors(model_path, values, findings=findings)
    findings.evaluate(
        "model.json-settings",
        None,
        _bind_framework_callback(
            _callback_check_model_inputs_json_settings,
            values,
            path,
            findings,
            prohibited,
        ),
    )
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
        findings.check(False, str(error))
        return findings
    resource_values = None
    for (
        _state_check_model_inputs_337.identity,
        _state_check_model_inputs_337.resource,
    ) in resources:
        if resource_values is None:
            resource_values = {}
            for key, value in values.items():
                kind, number = owner(key, values)
                if kind == "resource":
                    resource_values.setdefault(number, {})[key] = value
        selected = dict(resource_values.get(_state_check_model_inputs_337.identity, {}))
        findings.evaluate(
            "model.required." + _state_check_model_inputs_337.identity,
            None,
            lambda *, selected=selected: validate_required_properties(
                selected, definitions, warnings=findings.warnings
            ),
        )
        findings.evaluate(
            "model.mapping." + _state_check_model_inputs_337.identity,
            None,
            lambda *, selected=selected: validate_mappings(selected, definitions),
        )
        names = _bind_framework_callback(
            _callback_check_model_inputs_names,
            _state_check_model_inputs_337,
            definitions,
            findings,
            values,
        )
        findings.evaluate(
            "model.naming." + _state_check_model_inputs_337.identity, None, names
        )
        for row_id, _state_check_model_inputs_337.row in entries(
            selected, "desired.row."
        ):
            literal_check = _bind_framework_callback(
                _callback_check_model_inputs_literal_check,
                _state_check_model_inputs_337,
                catalog,
                definitions,
                findings,
                root,
            )
            findings.evaluate("model.literal." + row_id, None, literal_check)
    model = (
        (root / "model" / path.relative_to(root / "docs/designs")).with_suffix(
            ".properties"
        )
        if path.is_relative_to(root / "docs/designs")
        else path
    )
    _state_check_model_inputs_337.view = (
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
                design_sources={_state_check_model_inputs_337.view: values},
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
        _state_check_model_inputs_337.identity,
        _state_check_model_inputs_337.resource,
    ) in resources:
        findings.evaluate(
            "model.identity." + _state_check_model_inputs_337.identity,
            None,
            lambda *,
            identity=_state_check_model_inputs_337.identity,
            resource=_state_check_model_inputs_337.resource: validate_resource_identities(
                _state_check_model_inputs_337.view,
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
    return findings


_DEFAULT_ROOT = Path(__file__).resolve().parents[3]


def selected_rows(rows, root=_DEFAULT_ROOT):
    return _imports_aws_mapping_display.selected_rows(rows, root)


def resource_rows(values: dict[str, str], identity: str, kind: str, root: Path):
    return _dependency_model_projection.resource_rows(values, identity, kind, root)


def is_import_expression(prop: str, raw_value: str, design: Path):
    return _dependency_model_projection.is_import_expression(prop, raw_value, design)


def bound_resource_anchors(path):
    return _dependency_model_projection.bound_resource_anchors(path)


def design_target(path: Path, root: Path):
    return _dependency_model_projection.design_target(path, root)


def catalog_outputs(root: Path, kind: str):
    return _compat_utils_aws_catalogs.catalog_outputs(root, kind)
