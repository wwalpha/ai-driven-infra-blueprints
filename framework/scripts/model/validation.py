"""Explicit design validation over canonical metadata and runtime fields."""

from __future__ import annotations
from utils.json_format import policy_json

from model.core import ReferenceResolutionError

import re
from collections import Counter
from pathlib import Path
import iac_values
from array_display import indexed_rows
from model.projection import bound_resource_anchors, deployment_bucket, catalog_outputs, resource_rows, design_target, resource_display_rows, is_import_expression
from model.display import display_rows, catalog_display_rows, row_table, sg_tables
from aws_mapping_display import selected_rows
from validation_cache import input_is_file
from model.core import properties, entries, stack_model, deployment_settings, LINK, ARTIFACT_FIELDS

from design_layout import (
    GROUPED,
    HIDDEN_PROPERTIES,
    resource_display_name,
    resource_name_fields,
    resource_anchor,
    resource_has_name_property,
    resource_mode,
    is_import_pending_reference,
    GROUPED_RESOURCE_TYPES,
    IMPLICIT_GROUPED_PROPERTIES,
    ROTATION_SCHEDULE,
    LAMBDA_PERMISSION,
    SUBNET_LIST_SOURCE,
)
from policy_tables import literal, table
from design_catalog import DesignSchemaCatalog, property_paths_with_parents, selected_properties
from validation_cache import input_scope, memoized


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


@memoized
def naming_rule_files(root: Path, namespace: str | None = None) -> tuple[Path, ...]:
    """Read the common entry and only explicitly indexed service rules."""
    path = root / "framework/rules/aws-resource-naming.md"
    files = [path]
    for name, reference in re.findall(
        r"^\| `([A-Za-z0-9]+)` \| \[[^\]]+\]\((aws-resource-naming/[A-Za-z0-9]+\.md)\) \|$",
        path.read_text(encoding="utf-8"), re.MULTILINE,
    ):
        if namespace is None or name == namespace:
            files.append(path.parent / reference)
    return tuple(files)


def naming_target_matches(prop: str, targets: set[str], kind: str | None = None) -> bool:
    """Match a Naming Target at its declared root or exact nested property path."""
    normalized = {target.removeprefix(kind + ".") if kind else target for target in targets}
    return prop in normalized


@memoized
def naming_targets(root: Path, namespace: str | None = None) -> dict[str, set[str]]:
    targets: dict[str, set[str]] = {}
    for path in naming_rule_files(root, namespace):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) in {5, 6} and cells[2].startswith("`") and re.fullmatch(r"`[^`]+`", cells[4]):
                for kind in re.findall(r"`([^`]+)`", cells[2]):
                    targets.setdefault(kind, set()).add(cells[3].strip("`"))
    return targets


def naming_coverage_errors(root: Path, kind: str, selected: set[str], name_tag: bool = False,
                           mode: str = "CREATE") -> list[str]:
    """Check rule existence without requiring any design values."""
    if mode not in {"CREATE", "IMPORT"}:
        raise ValueError(f"resourceMode must be CREATE or IMPORT: {mode!r}")
    if mode == "IMPORT":
        return []
    targets = naming_targets(root, kind.partition(".")[0])
    expected = selected & set(resource_name_fields(kind))
    expected.update(field for field in selected if naming_target_matches(field, targets.get(kind, set()), kind))
    if name_tag:
        expected.add("Name tag")
    return [f"naming rule missing: {kind}: {field}" for field in sorted(expected)
            if kind + "." + field not in NAMING_EXEMPT_PROPERTIES
            and not naming_target_matches(field, targets.get(kind, set()), kind)]


def design_naming_errors(root: Path, kind: str, mode: str = "CREATE", name_tag: bool = False) -> list[str]:
    """Preflight a selected resource type before asking for design values."""
    # Deployment StackName is a model input, not a catalog resource property.
    selected = {"StackName"} if kind == "CloudFormation.Stack" else set(selected_properties(root, kind))
    if not selected:
        raise ValueError(f"catalog resource type missing: {kind}")
    selected -= {field.removeprefix(kind + ".") for field in catalog_outputs(root, kind)}
    if name_tag and not selected.intersection({"Tags", "Tags[].Key", "HostedZoneTags", "HostedZoneTags[].Key"}):
        raise ValueError(f"Name tag is not selectable: {kind}")
    if kind in {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}:
        selected.add("Name")
    if kind in {"EC2.VPCEndpoint", "EC2.Instance"}:
        name_tag = True
    return naming_coverage_errors(root, kind, selected, name_tag, mode)


def naming_errors(root: Path, kind: str, rows: list[list[str]], mode: str = "CREATE") -> list[str]:
    if kind in {"CodeBuild.Project", "IAM.Role"}:
        field = "RoleName" if kind == "IAM.Role" else "Name"
        names = [row[2].strip("`\"") for row in rows if row[1].removeprefix(kind + ".") == field]
        if len(names) != 1:
            return [f"{kind}.{field} must appear exactly once"]
        value = names[0]
        if not value.strip() or value.strip().lower() in {"unset", "pending", "pending_deploy", "tbd", "n/a", "none", "未確定"} or value.startswith("[") or "{{" in value:
            return [f"{kind}.{field} must be confirmed and non-empty"]
    if mode == "IMPORT":
        return []  # Confirmed actual names above and provider/schema checks remain mandatory.
    outputs = catalog_outputs(root, kind)
    selected = {row[1].removeprefix(kind + ".") for row in rows if kind + "." + row[1].removeprefix(kind + ".") not in outputs}
    tag_rows = [row for row in rows if row[1].removeprefix(kind + ".").startswith(("Tags", "HostedZoneTags"))]
    return naming_coverage_errors(root, kind, selected, resource_display_name(kind, tag_rows) is not None, mode)


def validate_required_properties(values: dict[str, str], root: Path, *, warnings=None) -> list[dict]:
    """Reject missing required model inputs before producing any view or artifact."""
    from model.core import validate_runtime_keys as validate_model_keys
    from model.files import resource_row_index
    validate_model_keys(values)
    resource_row_index(values)
    if entries(values, "desired.stack."):
        _, stacks = stack_model(values)
        for _, stack in stacks:
            if errors := naming_errors(root, 'CloudFormation.Stack', [['1', 'StackName', stack['name'], '名前']]):
                raise ValueError('; '.join(errors))
        return []
    catalog = DesignSchemaCatalog(root)
    errors = []
    warnings = [] if warnings is None else warnings
    for identity, resource in entries(values, "desired.resource."):
        resource_mode(resource)
        kind = resource["resourceType"]
        rows = resource_rows(values, identity, kind, root)
        from aws_mapping_display import rule
        from design_layout import RESOURCE_REFERENCE_PROPERTIES, is_service_role_reference, is_import_role_arn
        for _, prop, value, _ in rows:
            rule(prop, root)
            owner = '.'.join(prop.split('.')[:2])
            if owner not in {kind, *GROUPED_RESOURCE_TYPES.get(kind, set())}:
                raise ValueError(f"property does not belong to resource: {identity}: {prop}")
            if prop in RESOURCE_REFERENCE_PROPERTIES and not (
                LINK.fullmatch(value) or is_service_role_reference(prop, value) or
                resource_mode(resource) == 'IMPORT' and (prop != 'Config.ConfigurationRecorder.RoleARN' or is_import_pending_reference(prop, value)) or
                is_import_role_arn(prop, value, resource_mode(resource))
            ):
                warnings.append({'code': 'reference.expected_link', 'message': f'{prop} must be a resource link or an allowed IMPORT reference',
                                 'resource': identity, 'property': prop, 'reference': value})
        properties = {row[1] for row in rows
                      if (resource_mode(resource) == "IMPORT" and is_import_pending_reference(row[1], row[2]))
                      or literal(row[2]).strip().strip('"').strip().lower()
                      not in {"", "unset", "pending", "pending_deploy", "tbd", "未確定"}}
        if "parentProperty" in resource:
            properties.add(resource["parentProperty"])
        kinds = {kind} | {
            child for child in GROUPED_RESOURCE_TYPES.get(kind, set())
            if any(row[1].startswith(child + ".") for row in rows)
        }
        for schema_kind in sorted(kinds):
            present = property_paths_with_parents({prop.removeprefix(schema_kind + ".") for prop in properties
                                                  if prop.startswith(schema_kind + ".")})
            missing = catalog.required_design_properties(schema_kind) - present - IMPLICIT_GROUPED_PROPERTIES.get(schema_kind, set())
            errors.extend(f"{resource['logicalId']}: required provider schema property missing: {schema_kind}.{prop}"
                          for prop in sorted(missing))
    if errors:
        raise ValueError("\n- ".join(errors))
    return warnings


def validate_kms_policy_accounts(values: dict[str, str], target: dict) -> None:
    """Check local KMS account principals without rewriting explicit external grants."""
    if not target:
        return
    execution = target.get("awsExecutionAccountId", target["awsAccountId"])
    keys = {identity for identity, resource in entries(values, "desired.resource.")
            if resource["resourceType"] == "KMS.Key" and resource_mode(resource) == "CREATE"}
    for identity, row in entries(values, "desired.row."):
        if not any(identity.startswith(key + "-") for key in keys) or row.get("property") != "KMS.Key.KeyPolicy" or "document" not in row:
            continue
        external = set(re.findall(r"\bcross-account:(arn:[A-Za-z0-9_+=,.@:/-]+)(?=$|[\s`])", row.get("comment", "")))
        document = policy_json(row["document"])
        if not isinstance(document, dict):
            raise ValueError(f"KMS.Key.KeyPolicy {identity}: document must be an object")
        statements = document.get("Statement", [])
        for number, statement in enumerate(statements if isinstance(statements, list) else [statements], 1):
            if not isinstance(statement, dict):
                raise ValueError(f"KMS.Key.KeyPolicy {identity} Statement[{number}]: must be an object")
            if statement.get("Effect") != "Allow":
                continue
            principal = statement.get("Principal", {})
            principals = principal.get("AWS", []) if isinstance(principal, dict) else []
            for arn in principals if isinstance(principals, list) else [principals]:
                match = re.fullmatch(r"arn:[^:]+:iam::([0-9]{12}):(root|role/aws-service-role/macie(?:\.[a-z0-9-]+)?\.amazonaws\.com/AWSServiceRoleForAmazonMacie)", str(arn))
                if match and match[1] != execution and arn not in external:
                    raise ValueError(f"KMS.Key.KeyPolicy {identity} Statement[{number}] Principal.AWS: {arn}: "
                                     f"must use AWS execution account {execution}; explicit cross-account grant requires "
                                     f"cross-account:{arn} in the policy row comment")


def _kms_policy_account_check():
    """Reuse only the last successful ordered inputs within one service check."""
    successful = None

    def check(values, target):
        nonlocal successful
        inputs = (tuple(values.items()), tuple(target.items()))
        if inputs != successful:
            validate_kms_policy_accounts(values, target)
            successful = inputs

    return check


def validate_resource_identities(path, values, root, resources, *, definitions_root=None,
                                 _kms_policy_check=None):
    relative = path.parent.relative_to(root / "docs/designs") if path.is_relative_to(root / "docs/designs") else None
    target = design_target(path, root)
    (_kms_policy_check or validate_kms_policy_accounts)(values, target)
    stack_source = root / "model" / relative / "cloudformation-stacks.properties" if relative is not None else None
    stack_names = None
    identity_catalog = DesignSchemaCatalog(definitions_root or root)
    for identity, resource in resources:
        if "cfn-logicalId" not in resource:
            if target.get("iacEngine") == "cloudformation" and resource_mode(resource) == "CREATE" and f"desired.resource.{identity}.logicalId" not in values:
                try:
                    cfn_type = identity_catalog.cloudformation_type(resource["resourceType"])
                except ValueError:
                    cfn_type = None  # API-only design resources have no CFn identity.
                if cfn_type:
                    raise ValueError(f"{identity}: cfn-logicalId required for CloudFormation CREATE resource")
            continue
        if target.get("iacEngine") == "terraform":
            raise ValueError(f"{identity}: cfn-logicalId is forbidden for Terraform")
        if resource_mode(resource) != "CREATE":
            raise ValueError(f"{identity}: cfn-logicalId requires CREATE with a formal CFn type")
        identity_catalog.cloudformation_type(resource["resourceType"])
        from model.importing.scope import selected as import_selection, placement_names
        if import_selection(root) is not None and stack_source is not None:
            if stack_names is None:
                stack_names = placement_names(stack_source, {iac_values.cfn_resource_identity(spec['cfn-logicalId'])[0]
                    for _, spec in resources if spec.get('cfn-logicalId')})[0]
            if iac_values.cfn_resource_identity(resource['cfn-logicalId'])[0] not in stack_names:
                raise ReferenceResolutionError(f"{identity}: cfn-logicalId references an undeclared stack")
            continue
        if target.get("iacEngine") == "cloudformation" and (stack_source is None or not input_is_file(stack_source)):
            raise ValueError(f"{identity}: cfn-logicalId requires authoritative cloudformation-stacks.properties")
        if stack_source is not None and input_is_file(stack_source):
            if stack_names is None:
                from model.files import read_model
                _, stacks = stack_model(properties(read_model(stack_source)))
                from model.projection import bound_stack_names
                stack_names = set(bound_stack_names(stack_source)) or {stack["name"] for _, stack in stacks}
            if iac_values.cfn_resource_identity(resource["cfn-logicalId"])[0] not in stack_names:
                raise ReferenceResolutionError(f"{identity}: cfn-logicalId references an undeclared stack")


def check_model_inputs(path, values, root, *, definitions_root=None):
    """Validate authoritative inputs even when their View cannot be rendered."""
    from validation.findings import Findings
    from model.render import resource_details
    from model.core import validate_authority
    from model.sources import runtime_values
    validate_authority(values)
    values = runtime_values(values)
    from model.core import validate_runtime_keys as validate_model_keys
    from model.files import resource_row_index
    from model.format import owner
    from aws_mapping_display import validate_mappings
    findings = Findings(root)
    definitions = definitions_root or root
    view = (root / 'docs/designs' / path.relative_to(root / 'model')).with_suffix('.md') if path.is_relative_to(root / 'model') else path
    def structure():
        validate_model_keys(values)
        resource_row_index(values)
    if findings.evaluate('model.structure', None, structure).errors:
        return findings
    if entries(values, 'desired.stack.'):
        findings.evaluate('model.stacks', None, lambda: validate_required_properties(values, definitions))
        return findings
    resources = entries(values, 'desired.resource.')
    try:
        catalog = DesignSchemaCatalog(definitions) if resources else None
    except (OSError, ValueError) as error:
        findings.check(False, str(error))
        return findings
    resource_values = None
    for identity, resource in resources:
        if resource_values is None:
            resource_values = {}
            for key, value in values.items():
                kind, number = owner(key, values)
                if kind == 'resource':
                    resource_values.setdefault(number, {})[key] = value
        selected = dict(resource_values.get(identity, {}))
        findings.evaluate('model.required.' + identity, None,
                          lambda: validate_required_properties(selected, definitions, warnings=findings.warnings))
        findings.evaluate('model.mapping.' + identity, None, lambda: validate_mappings(selected, definitions))
        def names():
            rows = resource_rows(values, identity, resource['resourceType'], definitions)
            for error in naming_errors(definitions, resource['resourceType'], rows, resource_mode(resource)):
                findings.check(False, error)
        findings.evaluate('model.naming.' + identity, None, names)
        for row_id, row in entries(selected, 'desired.row.'):
            def literal_check():
                prop, value = row['property'], row.get('document', literal(row['value']))
                if 'document' not in row and is_import_expression(prop, row['value'], view):
                    return
                if 'document' not in row and LINK.fullmatch(row['value']):
                    return
                kind = '.'.join(prop.split('.')[:2])
                from validation.design import DESIGN_ONLY_PROPERTIES
                from design_layout import config_role_arn, is_service_role_reference
                if (prop in catalog_outputs(definitions, kind) or prop in NAMING_EXEMPT_PROPERTIES
                        or prop in HIDDEN_PROPERTIES or prop in DESIGN_ONLY_PROPERTIES
                        or is_service_role_reference(prop, row.get('value', ''))
                        or resource_mode(resource) == 'IMPORT' and (is_import_pending_reference(prop, row.get('value', ''))
                                                                   or config_role_arn(prop, row.get('value', '')))):
                    return
                field = prop.removeprefix(kind + '.')
                if field == 'Name' and kind in {'EC2.VPC', 'EC2.Subnet', 'EC2.RouteTable', 'EC2.FlowLog'}:
                    return
                for error in catalog.literal_errors(kind, field, value):
                    findings.check(False, f'provider schema violation: {prop}: {error}')
            findings.evaluate('model.literal.' + row_id, None, literal_check)
    from validation.design import check_observed_values
    model = (root / 'model' / path.relative_to(root / 'docs/designs')).with_suffix('.properties') if path.is_relative_to(root / 'docs/designs') else path
    view = (root / 'docs/designs' / model.relative_to(root / 'model')).with_suffix('.md')
    findings.evaluate('model.observed', None, lambda: check_observed_values(
        [model], findings=findings, root=root, scope=None, design_sources={view: values}))
    service = path.stem
    owned = values.get(f'desired.service.{service}.ownedCatalogResourceTypes', '').split(',')
    def presentation():
        view = (root / 'docs/designs' / path.relative_to(root / 'model')).with_suffix('.md') if path.is_relative_to(root / 'model') else path
        resource_details(values, definitions, service, owned, resources, bound_resource_anchors(view), findings=findings)
    kms_policy_check = _kms_policy_account_check()
    for identity, resource in resources:
        findings.evaluate('model.identity.' + identity, None, lambda: validate_resource_identities(
            view, values, root, [(identity, resource)], definitions_root=definitions,
            _kms_policy_check=kms_policy_check))
    findings.evaluate('model.presentation', None, presentation)
    for warning in findings.warnings:
        warning.setdefault('scope', '/'.join((*model.relative_to(root / 'model').parts[:2], service)))
        warning.setdefault('source', str(model.relative_to(root)))
    return findings

