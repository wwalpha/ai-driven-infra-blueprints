"""Derived execution/display fields; never serialize these into Model authority."""

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial as _bind_framework_callback
from pathlib import Path

import design_catalog as _imports_design_catalog
import design_document as _dependency_design_document
import json_intrinsics as _imports_json_intrinsics
import policy_tables as _imports_policy_tables
import reference_contracts as _imports_reference_contracts
import utils.json_format as _imports_utils_json_format
from design_catalog import design_material_files
from reference_contracts import ARN_FORMS, ARN_SHAPES
from utils.aws_catalogs import catalog_outputs as catalog_outputs
from utils.aws_sdk import aws_runtime
from utils.input_cache import input_is_file, input_text, memoized
from utils.json_format import document_sha256, policy_json, validate_aws_document
from utils.layout_schema import HIDDEN_PROPERTIES, RESOURCE

import model.identity as _dependency_model_identity
import model.identity as _imports_model_identity
import model.importing.references as _imports_model_importing_references
import model.importing.sources as _imports_model_importing_sources
import model.references as _imports_model_references
import model.render as _imports_model_render
import model.sources as _imports_model_sources
from model.core import (
    LINK,
    ReferenceResolutionError,
    entries,
    literal,
    validate_bucket_reference,
)
from model.format import JSON_LINK as JSON_LINK
from model.format import REFERENCE_NAME_SUFFIXES as REFERENCE_NAME_SUFFIXES
from model.format import RESOURCE_LINK as RESOURCE_LINK

ANCHOR = re.compile(r'^<a\s+id="([^"]+)"\s*></a>$')

def json_sha256(path: Path) -> str:
    content = policy_json(input_text(path, encoding="utf-8"))
    validate_aws_document(content)
    return document_sha256(content)


@memoized
def identifier_outputs(root: Path) -> dict[str, set[str]]:
    outputs: dict[str, set[str]] = {}
    for path in design_material_files(root):
        resource_type = path.stem.replace("_", ".", 1)
        outputs[resource_type] = {
            line.partition("=")[0]
            for line in input_text(path, encoding="utf-8").splitlines()
            if line.endswith("=IDENTIFIER_OUTPUT") and line.partition("=")[0] not in HIDDEN_PROPERTIES
        }
    return outputs


def bound_stack_names(path):
    load_model = _imports_model_sources.load_model
    return {stack['placementName']: stack['name']
            for _, stack in entries(load_model(path).authoritative, 'desired.stack.')}


def bound_resource_anchors(path):
    display_anchor = _imports_model_identity.display_anchor
    load_model = _imports_model_sources.load_model
    path = Path(path).absolute()
    if len(path.parents) >= 5 and path.parents[2].name == 'designs' and path.parents[3].name == 'docs':
        path = path.parents[4] / 'model' / path.parents[1].name / path.parent.name / (path.stem + '.properties')
    if path.suffix != '.properties' or not input_is_file(path):
        return {}
    return {(resource['resourceType'], resource['logicalId']): display_anchor(resource)
            for _, resource in entries(load_model(path).authoritative, 'desired.resource.')}


def linked_resource(path: Path, value: str, *, design_index: _dependency_design_document.DesignIndex | None = None) -> tuple[str, str] | None:
    match = RESOURCE_LINK.fullmatch(value)
    if not match:
        return None
    _, target_text, fragment = match.groups()
    target = path if not target_text else path.parent / target_text
    if not input_is_file(target):
        return None
    pending_anchor = ""
    view = (design_index or _dependency_design_document.DesignIndex()).get(target).view(frozenset({fragment}))
    identities = view.logical_ids
    lines, _ = view.expanded
    for line in lines:
        if anchor := ANCHOR.fullmatch(line):
            pending_anchor = anchor.group(1)
        elif resource := RESOURCE.fullmatch(line):
            if pending_anchor == fragment:
                return resource.group(1), identities.get(pending_anchor, resource.group(2))
            pending_anchor = ""
    return None


def is_import_expression(prop: str, raw_value: str, design: Path) -> bool:
    """Validate the narrow Model ImportValue notation, not arbitrary CFn/YAML."""
    value = literal(raw_value)
    link = re.fullmatch(r"\[([^\]]+)\]\(([^)]*)\)", value)
    expression = link[1] if link else value
    hosted_zone = prop == 'Route53.RecordSet.AliasTarget.HostedZoneId'
    if not (expression.startswith(('Fn::', 'Ref:')) or
            hosted_zone and ('Fn::' in value or '${' in value or expression.startswith('!')) or
            hosted_zone and value.startswith('[') and LINK.fullmatch(value) is None):
        return False
    if (not hosted_zone or
            re.fullmatch(r'Fn::ImportValue: [A-Z][A-Za-z0-9]*\$\{Suffix\}', expression) is None):
        raise ValueError('invalid or unsupported Model ImportValue expression: ' + prop)
    if link:
        if raw_value != value or re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*\.md', link[2]) is None:
            raise ValueError('ImportValue link requires a same-target service Markdown filename')
        target = (design.parent / link[2]).resolve()
        if target.parent != design.parent.resolve() or not input_is_file(target):
            raise ValueError('ImportValue link requires an existing same-target service design: ' + link[2])
    return True


def reference_attribute(kind: str, attribute: str) -> str:
    """Map proven Model attributes to provider attributes, never GetAtt aliases."""
    # Ref/GetAtt Id return the Secret ARN; ManagedPolicy uses PolicyArn, not Arn.
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-secretsmanager-secret.html
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-iam-managedpolicy.html
    return {"SecretsManager.Secret": "Id", "IAM.ManagedPolicy": "PolicyArn"}.get(kind, attribute) if attribute == "Arn" else attribute


def deployment_bucket(reference: str, path: Path, root: Path) -> str:
    """Resolve the confirmed name from the referenced authoritative S3 model."""
    scope_for = _imports_model_sources.scope_for
    validate_bucket_reference(reference)
    snapshot, identity, resource = _dependency_model_identity.Resolver(root).resolve(reference, scope_for((root / 'model' / path.relative_to(root / 'docs/designs')).with_suffix('.properties') if path.is_relative_to(root / 'docs/designs') else path))
    if resource['resourceType'] != 'S3.Bucket':
        raise ReferenceResolutionError('deployment bucket must identify one S3.Bucket')
    rows = entries(snapshot.authoritative, 'desired.row.')
    names = [literal(row.get('value', '')) for rid, row in rows
             if rid.rpartition('-')[0] == identity and row.get('property') == 'S3.Bucket.BucketName']
    if len(names) != 1 or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', names[0]):
        raise ReferenceResolutionError('deployment bucket requires one confirmed BucketName')
    return names[0]




def observed_value(row_id, row, observed, outputs):
    has_reference = _imports_model_importing_sources.has_reference
    LINKS = _imports_model_references.LINKS
    value = row['value']
    if observed is not None:
        if link := LINK.fullmatch(value):
            value = observed if row['property'] in outputs else f"[{literal(observed)}]({link.group(2)}#{link.group(3)})"
        elif has_reference(value) or LINKS.search(value):
            pass  # Structured link labels retain their native string/list shape.
        else:
            raise ValueError(f"observed value requires a desired logical reference: {row_id}")
    return value


_resource_row_cache = ContextVar("resource_row_cache", default=None)


@contextmanager
def resource_row_scope():
    """Reuse parsed rows only within one generation, including nested invocations."""
    token = _resource_row_cache.set({})
    try:
        yield
    finally:
        _resource_row_cache.reset(token)


def _resource_row_entries(values):
    cache = _resource_row_cache.get()
    if cache is None:
        return entries(values, "desired.row.")
    key = id(values)
    signature = tuple(values.items())
    previous = cache.get(key)
    if previous is None or previous[1] != signature:
        # Parse a fresh snapshot so the shared immutable-input memo cannot hide edits.
        parsed = entries(dict(signature), "desired.row.")
        cache[key] = (values, signature, parsed)
    return cache[key][2]


def resource_rows(values: dict[str, str], identity: str, kind: str, root: Path) -> list[list[str]]:
    outputs = catalog_outputs(root, kind)
    rows = []
    for row_id, row in _resource_row_entries(values):
        if not row_id.startswith(identity + "-"):
            continue
        if set(row) - {"property", "value", "comment", "artifactSha256", "document"} or not {"property", "value", "comment"} <= row.keys():
            raise ValueError(f"invalid resource row: {row_id}")
        observed = values.get(f"observed.row.{row_id}.value")
        value = observed_value(row_id, row, observed, outputs)
        rows.append([row_id, row["property"], value, row["comment"]])
    return rows


def design_target(path: Path, root: Path) -> dict:
    project = root / "project.json"
    if input_is_file(project) and path.is_relative_to(root / "docs/designs"):
        relative = path.parent.relative_to(root / "docs/designs")
        if len(relative.parts) == 2:
            environment, directory = relative.parts
            return next((item for item in json.loads(input_text(project, encoding="utf-8")).get("targets", [])
                         if item.get("environment") == environment and item.get("alias", item.get("awsAccountId")) == directory), {})
    return {}


def resource_display_rows(values: dict[str, str], identity: str, resource: dict[str, str], root: Path, *, scope=None) -> list[list[str]]:
    """Include a Key's own grouped aliases when resolving its display name."""
    rows = resource_rows(values, identity, resource["resourceType"], root)
    if resource["resourceType"] == "KMS.Key":
        for child_id, child in entries(values, "desired.resource."):
            parse_reference = _imports_model_identity.parse_reference
            parent = child.get('parentReference', '')
            link = LINK.fullmatch(parent)
            same = (link is not None and link[3] == resource['anchor'] and
                    (not link[2] or scope is not None and parse_reference(parent, scope)[:3] ==
                     (scope.environment, scope.target, scope.service)))
            if child['resourceType'] == 'KMS.Alias' and same:
                rows += resource_rows(values, child_id, child["resourceType"], root)
    return rows



def scalar_reference(row):
    """Decode the existing JSON scalar only at explicitly enabled properties."""
    SCALAR_REFERENCE_PROPERTIES = _imports_reference_contracts.SCALAR_REFERENCE_PROPERTIES

    resource_link = _imports_model_identity.resource_link
    _json = _imports_model_references._json

    prop = re.sub(r'\[\d+\]', '[]', row['property'])
    if prop not in SCALAR_REFERENCE_PROPERTIES or 'document' in row:
        return None
    value, structured = _json('desired.row.scalar.value', row['value'])
    if not structured:
        return None
    if (not isinstance(value, dict) or set(value) != {'$resource', '$attribute'} or
            not resource_link(value['$resource']) or value['$attribute'] != SCALAR_REFERENCE_PROPERTIES[prop][1]):
        raise ValueError('scalar Resource reference requires a Resource link and explicit Arn: ' + prop)
    return value


def scalar_reference_operand(row, root, scope, *, resolver=None):
    """Resolve scalar intent without acquiring or deriving any physical value."""
    SCALAR_REFERENCE_PROPERTIES = _imports_reference_contracts.SCALAR_REFERENCE_PROPERTIES

    Resolver = _imports_model_identity.Resolver

    selector = scalar_reference(row)
    if selector is None:
        return None
    operand = (resolver or Resolver(root)).operand(selector['$resource'], scope,
        attribute=selector['$attribute'], field=row['property'])
    snapshot, _, resource, attribute = operand
    expected = SCALAR_REFERENCE_PROPERTIES[re.sub(r'\[\d+\]', '[]', row['property'])]
    if ((resource['resourceType'], attribute) != expected or
            (snapshot.scope.environment, snapshot.scope.target) != (scope.environment, scope.target)):
        raise ReferenceResolutionError('scalar Arn reference requires a same-target KMS.Key', reference=selector['$resource'])
    return operand


def reference_display(values, path, root, *, definitions_root=None):
    """Preserve saved links/anchors and project only execution documents for display."""
    Resolver = _imports_model_identity.Resolver
    scope_for = _imports_model_sources.scope_for
    model_path = (root / 'model' / path.relative_to(root / 'docs/designs')).with_suffix('.properties') if path.is_relative_to(root / 'docs/designs') else path
    scope = scope_for(model_path)
    resolver = Resolver(root)
    result = dict(values)
    for key, value in values.items():
        if key.startswith('desired.row.') and key.endswith('.document'):
            projected = execution_document(policy_json(value), root,
                property_name=values[key.removesuffix('document') + 'property'], resolver=resolver, scope=scope,
                logical_id=values.get(f'desired.resource.{key.split(".")[2].rpartition("-")[0]}.logicalId'))
            result[key] = json.dumps(projected, ensure_ascii=False)
            result[key.removesuffix('document') + 'artifactSha256'] = document_sha256(projected)
    for row_id, row in entries(values, 'desired.row.'):
        operand = scalar_reference_operand(row, root, scope, resolver=resolver)
        if operand is not None:
            snapshot, number, resource, _ = operand
            address = _imports_model_identity.address
            resource_presentation = _imports_model_render.resource_presentation
            name, _, _ = resource_presentation(snapshot.values, number, resource,
                definitions_root or root, scope=snapshot.scope)
            result[f'desired.row.{row_id}.value'] = address(snapshot.scope, resource, consumer_scope=scope, label=name)
    return result


def _callback_document_references_reference(resolve, resolver, scope, /, uri, attribute, field, original):
    operand = resolver.operand(uri, scope, attribute=attribute, field=field)
    return resolve(*operand, uri) if resolve else original


def _recursive_document_references_visit(reference, /, value, field):
    if isinstance(value, str):
        if field and field.rsplit('.', 1)[-1] in {'Description', 'description'}:
            return value
        if value.startswith('resource://'):
            raise ReferenceResolutionError('unsupported saved Resource reference syntax')
        if _dependency_model_identity.resource_link(value):
            return reference(value, None, field, value)
        if any(_dependency_model_identity.reference_tokens(value)):
            raise ReferenceResolutionError('embedded Resource reference requires an explicit JSON operand')
        return value
    if isinstance(value, list):
        return [_recursive_document_references_visit(reference, item, field + '[]' if field else None) for item in value]
    if isinstance(value, dict):
        if '$resource' in value:
            if (set(value) - {'$resource', '$attribute'} or not _dependency_model_identity.resource_link(value['$resource']) or
                    '$attribute' in value and (not isinstance(value['$attribute'], str) or not value['$attribute'])):
                raise ValueError('invalid structured Resource reference')
            return reference(value['$resource'], value.get('$attribute'), field, value)
        if '$attribute' in value:
            raise ValueError('Resource attribute requires $resource')
        return {key: _recursive_document_references_visit(reference, child, field + '.' + key if field else key) for key, child in value.items()}
    return value


def document_references(document, root, *, property_name=None, resolver=None, scope=None, resolve=None):
    """One JSON reference walk for semantic validation and execution projection."""
    resolver = resolver or _dependency_model_identity.Resolver(root)

    reference = _bind_framework_callback(_callback_document_references_reference, resolve, resolver, scope)

    visit = _bind_framework_callback(_recursive_document_references_visit, reference)
    return visit(document, property_name)


def confirmed_property(snapshot, number, kind, attribute, uri, resolver):
    """Select one authoritative Row before evaluating its desired/observed value."""
    resource_link = _imports_model_identity.resource_link
    known = _imports_model_importing_references.known
    rows = [(rid, row) for rid, row in entries(snapshot.authoritative, 'desired.row.')
            if rid.rpartition('-')[0] == number and row['property'] == kind + '.' + attribute]
    if len(rows) == 1:
        rid, row = rows[0]
        observed = snapshot.authoritative.get(f'observed.row.{rid}.value')
        if observed is not None:
            if not resource_link(row['value']):
                raise ReferenceResolutionError('JSON observed output requires a logical Resource reference', reference=uri)
            resolver.resolve(row['value'], snapshot.scope)
        value = literal(observed if observed is not None else row.get('value', ''))
        if known(value):
            return value
    raise ReferenceResolutionError('JSON Resource reference requires one confirmed output: ' + kind + '.' + attribute, reference=uri)


def _callback_execution_document_reference(resolver, root, target_for, /, snapshot, number, resource, attribute, uri):
    kind = resource['resourceType']
    if attribute == 'Arn' or (kind, attribute) in ARN_FORMS:
        if attribute != 'Arn' or kind not in ARN_SHAPES:
            raise ReferenceResolutionError('JSON Resource ARN form cannot be derived: ' + kind + '.' + attribute, reference=uri)
        identity, template, patterns = ARN_SHAPES[kind]
        fields = identity if isinstance(identity, dict) else {identity: 'id'}
        parts = {group: confirmed_property(snapshot, number, kind, prop, uri, resolver) for prop, group in fields.items()}
        DesignSchemaCatalog = _imports_design_catalog.DesignSchemaCatalog
        catalog = DesignSchemaCatalog(root)
        if any(catalog.literal_errors(kind, prop, parts[group]) for prop, group in fields.items()):
            raise ReferenceResolutionError('invalid JSON Resource ARN identifier: ' + kind, reference=uri)
        if any(re.fullmatch(patterns[group], value) is None for group, value in parts.items()):
            raise ReferenceResolutionError('invalid JSON Resource ARN identifier: ' + kind, reference=uri)
        if kind == 'S3.Bucket':
            name = parts['id']
            if ('..' in name or re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', name) or
                    name.startswith(('xn--', 'sthree-', 'amzn-s3-demo-')) or
                    name.endswith(('-s3alias', '--ol-s3', '.mrap', '--x-s3', '--table-s3'))):
                raise ReferenceResolutionError('invalid JSON Resource BucketName', reference=uri)
            for rid, row in entries(snapshot.authoritative, 'desired.row.'):
                if rid.rpartition('-')[0] != number and row['property'] == 'S3.Bucket.BucketName':
                    value = snapshot.authoritative.get(f'observed.row.{rid}.value', row['value'])
                    if literal(value) == name:
                        raise ReferenceResolutionError('JSON Resource ARN requires a unique BucketName', reference=uri)
        target, _ = target_for(snapshot.scope, resolver.reads)
        UnknownRegionError = aws_runtime().UnknownRegionError
        get_session = aws_runtime().sdk_session
        session = get_session()
        try:
            partition = session.get_partition_for_region(target['awsRegion'])
        except UnknownRegionError as error:
            raise ReferenceResolutionError('unknown JSON Resource AWS partition', reference=uri) from error
        # SDK regex fallbacks also accept invented regions; require a recorded region.
        if not any(item['partition'] == partition and target['awsRegion'] in item['regions']
                   for item in session.get_data('endpoints')['partitions']):
            raise ReferenceResolutionError('JSON Resource ARN requires a confirmed Region', reference=uri)
        return template.format(partition=partition, region=target['awsRegion'],
                               account=target.get('awsExecutionAccountId', target['awsAccountId']), **parts)
    return confirmed_property(snapshot, number, kind, attribute, uri, resolver)


def execution_document(document, root, *, property_name=None, resolver=None, scope=None, logical_id=None, warnings=None):
    """Project design JSON; unresolved CFn expressions retain their authored structure."""
    POLICY_FORMATS = _imports_policy_tables.POLICY_FORMATS
    Policy = _imports_policy_tables.Policy
    validate_policy_document = _imports_policy_tables.validate_policy_document
    AwsDocumentError = _imports_utils_json_format.AwsDocumentError

    Resolver = _imports_model_identity.Resolver
    target_for = _imports_model_sources.target_for

    resolver = resolver or Resolver(root)

    reference = _bind_framework_callback(_callback_execution_document_reference, resolver, root, target_for)

    try:
        project_document = _imports_json_intrinsics.project_document
        document = project_document(document, warnings=warnings, property_name=property_name,
                                    model_path=scope.path if scope else root, logical_id=logical_id)
        projected = document_references(document, root, property_name=property_name, resolver=resolver, scope=scope, resolve=reference)
        if property_name in POLICY_FORMATS:
            validate_policy_document(projected, Policy('', '', '', '', property_name), design=True)
        else:
            project_document(projected, warnings=warnings, property_name=property_name,
                             model_path=scope.path if scope else root, logical_id=logical_id)
    except AwsDocumentError as error:
        raise ValueError(f'Model={scope.path if scope else root}, Resource logicalId={logical_id}, '
                         f'Property={property_name}; {error}') from error
    return projected
